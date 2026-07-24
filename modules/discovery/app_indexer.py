#!/usr/bin/env python3
"""
AppIndexer: Discovers installed applications on Windows by scanning Start Menu shortcuts,
AppsFolder (UWP), and the Windows Registry (uninstall keys).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
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

try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except Exception:
    _HAS_RAPIDFUZZ = False
    import difflib

log = logging.getLogger("nova")


# Module-level cache for the merged index
_merged_cache: Optional[List[Dict]] = None


def normalize_name(name: str) -> str:
    """Return a normalized version of an application name for matching.

    Normalisation steps:
    * lower‑case
    * remove substrations like "(64-bit)", "(x64)", "(x86)" (case‑insensitive)
    * remove version numbers such as "1.2.3" or "1.85.0"
    * strip punctuation characters
    * collapse consecutive whitespace to a single space and strip ends
    """
    if not name:
        return ""
    s = name.lower()
    # remove architecture / bitness tags in parentheses
    s = re.sub(r'\(?(?:64[-\s]?bit|x64|x86)\)?', '', s, flags=re.IGNORECASE)
    # remove version numbers (e.g. 1.2.3, 1.85.0, 2024.1)
    s = re.sub(r'\b\d+(?:\.\d+)+\b', '', s)
    # remove punctuation (keep alphanumerics and spaces)
    s = re.sub(r'[^\w\s]', ' ', s)
    # collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def resolve_shortcut(shortcut_path: Path) -> Optional[str]:
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


def scan_start_menu() -> List[Dict]:
    """Scan both all‑users and current‑user Start Menu Program folders for *.lnk files.

    Returns a list of dicts with keys:
        name (normalized), path (resolved target), shortcut_path, source="start_menu"
    """
    records: List[Dict] = []
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for lnk_path in root.rglob("*.lnk"):
            target = resolve_shortcut(lnk_path)
            if not target:
                continue
            name = normalize_name(lnk_path.stem)
            records.append({
                "name": name,
                "path": target,
                "shortcut_path": str(lnk_path),
                "source": "start_menu",
            })
    return records


def scan_registry() -> List[Dict]:
    """Scan HKLM uninstall keys for installed Win32 applications.

    Returns a list of dicts with keys:
        name (normalized), path, shortcut_path="", source="registry"
    """
    records: List[Dict] = []
    if winreg is None:
        log.debug("winreg not available, cannot scan registry")
        return records

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

                            if path:
                                path = path.strip('"')
                                if path.lower().endswith('.exe"'):
                                    path = path[:-1]
                                elif '.exe' in path:
                                    idx = path.lower().find('.exe')
                                    if idx >= 0:
                                        path = path[:idx + 4]

                            if not name:
                                continue

                            # Skip system components
                            try:
                                system_component = winreg.QueryValueEx(subkey, "SystemComponent")[0]
                                if system_component == 1:
                                    continue
                            except (OSError, FileNotFoundError):
                                pass

                            if not path or not os.path.exists(path):
                                continue

                            records.append({
                                "name": normalize_name(name),
                                "path": path,
                                "shortcut_path": "",
                                "source": "registry",
                            })
                    except Exception as e:
                        log.debug("Error processing registry subkey %s: %s", subkey_name, e)
        except Exception as e:
            log.debug("Failed to scan registry path %s: %s", reg_path, e)

    return records


def scan_uwp() -> List[Dict]:
    """Return a list of installed UWP/Store packages via PowerShell Get-AppxPackage.

    Each entry is a dict with keys:
        name (normalized), path (PackageFamilyName), shortcut_path="", source="uwp"
    """
    records: List[Dict] = []
    # Try current user first (no admin), then all users if that fails.
    for cmd_args in (
        ["Get-AppxPackage | Select-Object Name, PackageFamilyName | ConvertTo-Json -Depth 2"],
        ["Get-AppxPackage -AllUsers | Select-Object Name, PackageFamilyName | ConvertTo-Json -Depth 2"],
    ):
        try:
            cmd = ["powershell", "-NoProfile", "-Command", cmd_args[0]]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    name = item.get("Name")
                    pfn = item.get("PackageFamilyName")
                    if not name or not pfn:
                        continue
                    records.append({
                        "name": normalize_name(name),
                        "path": pfn,
                        "shortcut_path": "",
                        "source": "uwp",
                    })
                break  # success
            else:
                log.debug("Get-AppxPackage attempt failed: %s", result.stderr)
        except Exception as e:
            log.debug("Get-AppxPackage exception: %s", e)
    return records


def fuzzy_find(query: str, threshold: int = 60, top_n: int = 10) -> List[Dict]:
    """Return top_n merged apps matching query with fuzzy score >= threshold.

    Uses rapidfuzz.WRatio if available, otherwise difflib.SequenceMatcher.
    Returns list of app dicts (as from merged index) sorted by score desc.
    """
    try:
        from rapidfuzz import fuzz
        scorer = lambda a, b: fuzz.WRatio(a, b)
    except Exception:
        import difflib
        scorer = lambda a, b: int(difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)

    merged = build_merged_index()
    results = []
    for app in merged:
        score = scorer(query, app["name"])
        if score >= threshold:
            results.append((score, app))
    results.sort(key=lambda x: x[0], reverse=True)
    return [app for _, app in results[:top_n]]


def build_merged_index() -> List[Dict]:
    """Build a merged application index from registry, start_menu, and uwp scanners.

    Preference order for duplicates (by normalized name):
        1. registry (highest)
        2. start_menu
        3. uwp (lowest)

    Returns a list of dicts with keys: name (normalized), path, shortcut_path, source.
    The result is cached in the module-level variable _merged_cache.
    """
    global _merged_cache
    if _merged_cache is not None:
        return _merged_cache

    # Gather records from each source
    registry_recs = scan_registry()
    start_menu_recs = scan_start_menu()
    uwp_recs = scan_uwp()

    # Priority mapping: higher number wins
    priority = {"registry": 3, "start_menu": 2, "uwp": 1}

    merged: Dict[str, Dict] = {}
    for src_records, src_name in ((registry_recs, "registry"),
                                  (start_menu_recs, "start_menu"),
                                  (uwp_recs, "uwp")):
        src_priority = priority[src_name]
        for rec in src_records:
            norm_name = rec["name"]  # already normalized by scanners
            existing = merged.get(norm_name)
            if existing is None or src_priority > priority[existing["source"]]:
                merged[norm_name] = rec

    _merged_cache = list(merged.values())
    return _merged_cache


def fuzzy_find(query: str, threshold: int = 55, top_n: int = 3) -> List[Dict]:
    """Fuzzy-search the merged index for *query*.

    Uses rapidfuzz WRatio when available, otherwise difflib.SequenceMatcher.
    Logs the top *top_n* candidates with their scores (even if below threshold).
    Returns all entries with score >= threshold, sorted descending.
    """
    index = build_merged_index()
    scored = []
    q = query.lower()
    for entry in index:
        name = entry["name"]
        if _HAS_RAPIDFUZZ:
            score = fuzz.WRatio(q, name)
        else:
            score = int(difflib.SequenceMatcher(None, q, name).ratio() * 100)
        scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)

    # Log top N regardless of threshold
    for rank, (score, entry) in enumerate(scored[:top_n], 1):
        log.info("fuzzy_find top%d: %s (score=%d) source=%s path=%s",
                 rank, entry["name"], score, entry["source"], entry["path"])

    # Return those meeting threshold
    return [entry for score, entry in scored if score >= threshold]


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

    # ---- normalize_name quick tests ----
    test_names = [
        "Visual Studio Code (User) 1.85.0",
        "Microsoft Word (64-bit)",
        "Notepad++ (x64) 8.5.4",
        "Google Chrome (x86)",
        "MyApp 2.0.1 (Beta)",
    ]
    for tn in test_names:
        print(f"normalize_name({tn!r}) => {normalize_name(tn)!r}")

    # ---- scan_start_menu quick test ----
    start_menu_apps = scan_start_menu()
    print(f"\nStart Menu apps found: {len(start_menu_apps)}")
    for app in start_menu_apps[:5]:
        print(f"  {app['name']} -> {app['path']} (shortcut: {app['shortcut_path']})")

    # ---- scan_registry quick test ----
    registry_apps = scan_registry()
    print(f"\nRegistry apps found: {len(registry_apps)}")
    for app in registry_apps[:5]:
        print(f"  {app['name']} -> {app['path']} (source: {app['source']})")

    # ---- scan_uwp quick test ----
    uwp_apps = scan_uwp()
    print(f"\nUWP apps found: {len(uwp_apps)}")
    for app in uwp_apps[:5]:
        print(f"  {app['name']} -> {app['path']} (source: {app['source']})")

    # ---- merged index test ----
    merged = build_merged_index()
    print(f"\nMerged index apps: {len(merged)}")
    # check for duplicate normalized names
    seen = {}
    for app in merged:
        n = app["name"]
        if n in seen:
            print(f"  DUPLICATE: {n} from {seen[n]} and {app['source']}")
        else:
            seen[n] = app["source"]
    for app in merged[:5]:
        print(f"  {app['name']} -> {app['path']} (source: {app['source']})")

    # ---- fuzzy_find quick tests ----
    for q in ("excel", "word"):
        print(f"\n--- fuzzy_find for '{q}' ---")
        matches = fuzzy_find(q, threshold=55, top_n=3)
        if matches:
            for m in matches[:5]:
                print(f"  {m['name']} (score not shown) source={m['source']} path={m['path']}")
        else:
            print("  no matches above threshold")

    indexer = AppIndexer()
    indexer.build_index()
    apps = indexer.get_all()
    for app in apps[:20]:
        print(f"{app['name']} -> {app['path']} [{app.get('install_type')}]")
    print(f"Total apps indexed: {len(indexer.get_all())}")