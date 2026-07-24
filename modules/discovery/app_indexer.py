#!/usr/bin/env python3
"""
AppIndexer: Discovers installed applications on Windows by scanning Start Menu shortcuts,
AppsFolder (UWP), and the Windows Registry (uninstall keys).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import List, Dict, Optional

try:
    import win32com.client
except ImportError:
    win32com = None

try:
    import winreg
except ImportError:
    winreg = None

log = logging.getLogger("nova")


class AppIndexer:
    """Indexes installed applications by scanning Start Menu shortcuts and AppsFolder (UWP apps)."""

    def __init__(self):
        self._cache: List[Dict] = []
        self._built = False

    @staticmethod
    def _detect_install_type(record: Dict) -> Dict:
        """Detect installation type and launch method for a record."""
        path = record.get("path", "")
        shortcut_path = record.get("shortcut_path", "")

        # UWP / Store app: path contains '!' (PackageFamilyName!App)
        if "!" in (record.get("path") or ""):
            return {
                "install_type": "uwp",
                "launch_method": "appsfolder",
                "target": record.get("path", ""),
            }

        # Win32 executable
        path = record.get("path", "")
        if path and path.lower().endswith(".exe") and os.path.isfile(path):
            return {
                "install_type": "win32",
                "launch_method": "exe",
                "target": path,
            }

        # Shortcut-only (no direct exe target)
        shortcut_path = record.get("shortcut_path", "")
        if shortcut_path and os.path.exists(shortcut_path):
            return {
                "install_type": "shortcut",
                "launch_method": "shortcut",
                "target": shortcut_path,
            }

        # Unknown
        return {
            "install_type": "unknown",
            "launch_method": "unknown",
            "target": "",
        }

    def _resolve_shortcut(self, shortcut_path: Path) -> Optional[str]:
        """Resolve a .lnk file to its target executable path."""
        if win32com is None:
            log.debug("pywin32 not available, cannot resolve shortcut %s", shortcut_path)
            return None
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(shortcut_path))
            target = shortcut.Targetpath
            if target and os.path.exists(target):
                return target
            else:
                log.debug("Shortcut target does not exist: %s -> %s", shortcut_path, target)
                return None
        except Exception as e:
            log.debug("Failed to resolve shortcut %s: %s", shortcut_path, e)
            return None

    def _scan_apps_folder(self) -> List[Dict]:
        """Scan the Windows AppsFolder (shell:AppsFolder) for UWP and other modern apps."""
        records = []
        if win32com is None:
            log.debug("pywin32 not available, cannot scan AppsFolder")
            return []
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            namespace = shell.NameSpace("shell:AppsFolder")
            if namespace is None:
                log.warning("Could not open shell:AppsFolder")
                return []
            for item in namespace.Items():
                try:
                    name = item.Name
                    # The parsing name (path) for UWP apps is something like "shell:AppsFolder\<PackageFamilyName>!App"
                    path = item.Path
                    if not name or not path:
                        continue
                    record = {
                        "name": name,
                        "path": path,
                        "shortcut_path": "",  # no .lnk for UWP apps
                        "source": "apps_folder",
                    }
                    self._cache.append(record)
                except Exception as e:
                    log.debug("Error processing AppsFolder item: %s", e)
        except Exception as e:
            log.debug("Failed to scan AppsFolder: %s", e)
        return []

    def _scan_registry(self) -> List[Dict]:
        """Scan the Windows Registry for installed applications (Win32 apps)."""
        records = []
        if winreg is None:
            log.debug("winreg not available, cannot scan registry")
            return []
        
        # Registry paths to scan
        registry_paths = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]
        
        for reg_path in registry_paths:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, subkey_name) as subkey:
                                # Get display name
                                try:
                                    name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                except (OSError, FileNotFoundError):
                                    continue
                                
                                # Get install location or executable path
                                path = ""
                                try:
                                    path = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                                except (OSError, FileNotFoundError):
                                    pass
                                
                                if not path:
                                    try:
                                        path = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                    except (OSError, FileNotFoundError):
                                        pass
                                
                                # Clean up path - sometimes DisplayIcon has extra params
                                if path:
                                    path = path.strip('"')
                                    # If it's a .exe path with args, take just the exe part
                                    if path.lower().endswith('.exe"'):
                                        path = path[:-1]
                                    elif '.exe' in path:
                                        # Find the .exe part
                                        idx = path.lower().find('.exe')
                                        if idx >= 0:
                                            path = path[:idx+4]
                                
                                if not name:
                                    continue
                                    
                                # Skip system components, updates, etc.
                                try:
                                    system_component = winreg.QueryValueEx(subkey, "SystemComponent")[0]
                                    if system_component == 1:
                                        continue
                                except (OSError, FileNotFoundError):
                                    pass
                                
                                # Skip if no valid path
                                if not path or not os.path.exists(path):
                                    continue
                                
                                record = {
                                    "name": name,
                                    "path": path,
                                    "shortcut_path": "",
                                    "source": "registry",
                                }
                                self._cache.append(record)
                        except Exception as e:
                            log.debug("Error processing registry subkey %s: %s", subkey_name, e)
            except Exception as e:
                log.debug("Failed to scan registry path %s: %s", reg_path, e)
        
        return []

    def _scan_start_menu(self, root: Path) -> List[Dict]:
        """Scan a Start Menu directory for .lnk files and resolve them."""
        records = []
        if not root.is_dir():
            return records
        for lnk_path in root.rglob("*.lnk"):
            try:
                target = self._resolve_shortcut(lnk_path)
                if target is None:
                    continue
                name = lnk_path.stem  # filename without extension
                record = {
                    "name": name,
                    "path": target,
                    "shortcut_path": str(lnk_path),
                    "source": "start_menu",
                }
                self._cache.append(record)
            except Exception as e:
                log.debug("Error processing shortcut %s: %s", lnk_path, e)
        return records

    def build_index(self) -> None:
        """Full rescan of Start Menu shortcuts and AppsFolder, rebuilds the cache."""
        log.info("Building application index...")
        self._cache.clear()
        self._built = True

        # All-users Start Menu
        all_users = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        self._scan_start_menu(all_users)

        # Current user Start Menu
        current_user = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        self._scan_start_menu(current_user)

        # AppsFolder (UWP apps)
        self._scan_apps_folder()

        # Registry (Win32 apps from uninstall keys)
        self._scan_registry()

        # Enrich records with install_type / launch_method
        for rec in self._cache:
            det = self._detect_install_type(rec)
            rec.update(det)

        # Deduplicate by normalized name (case-insensitive), keeping first occurrence
        seen_names = set()
        deduped = []
        for rec in self._cache:
            name_key = rec.get("name", "").lower()
            if name_key and name_key not in seen_names:
                seen_names.add(name_key)
                deduped.append(rec)
        self._cache = deduped

        # Statistics
        start_menu = sum(1 for r in self._cache if r.get("source") == "start_menu")
        apps_folder = sum(1 for r in self._cache if r.get("source") == "apps_folder")
        registry = sum(1 for r in self._cache if r.get("source") == "registry")
        log.info("Index stats - Start Menu: %d, AppsFolder: %d, Registry: %d", start_menu, apps_folder, registry)
        log.info("After deduplication: Total Apps: %d", len(self._cache))

    def refresh(self) -> None:
        """Alias for build_index."""
        self.build_index()

    def get_all(self) -> List[Dict]:
        """Return all cached application records."""
        if not self._built:
            self.build_index()
        return self._cache

    def find(self, name: str) -> List[Dict]:
        """Simple case-insensitive substring lookup by app name."""
        if not self._built:
            self.build_index()
        name_lower = name.lower()
        return [app for app in self._cache if name_lower in app["name"].lower()]


# Singleton instance for easy import
_app_indexer: Optional[AppIndexer] = None
_app_indexer_lock = threading.Lock()


def get_app_indexer() -> AppIndexer:
    global _app_indexer
    if _app_indexer is None:
        with _app_indexer_lock:
            if _app_indexer is None:
                _app_indexer = AppIndexer()
    return _app_indexer


if __name__ == "__main__":
    # Quick test when run directly
    logging.basicConfig(level=logging.DEBUG)
    indexer = AppIndexer()
    indexer.build_index()
    apps = indexer.get_all()
    for app in apps[:20]:
        print(f"{app['name']} -> {app['path']} [{app.get('install_type')}]")
    print(f"Total apps indexed: {len(indexer.get_all())}")