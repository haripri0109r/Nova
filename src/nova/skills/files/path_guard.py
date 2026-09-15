"""
Path Guard — Lexical, canonical, and security policy validation for file operations.

Provides defense-in-depth protection against:
- Directory traversal attacks
- Alternate Data Streams (ADS)
- Device namespaces and reserved DOS device names
- UNC path injections
- Reparse points, symlinks, and junction escapes
- Operations in protected Windows system directories
- Dangerous executable file opening
"""

from __future__ import annotations

import ctypes
import enum
import logging
import os
import re
import stat
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger("nova.skills.files.path_guard")


class OperationType(enum.Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    LIST = "list"
    EXECUTE_OPEN = "execute_open"


class PathSecurityError(ValueError):
    """Raised when a path violates security constraints."""
    pass


# Reserved DOS device names on Windows
RESERVED_DEVICE_NAMES: Set[str] = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Win32 file attribute flag for reparse point (junctions, symlinks, mount points)
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400

# Conservative allowlist for open_file (documents, media, project files)
ALLOWED_OPEN_EXTENSIONS: Set[str] = {
    ".txt", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".md",
    ".py", ".c", ".cpp", ".h", ".java", ".html", ".css", ".log",
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp",
    ".mp3", ".wav", ".m4a", ".mp4", ".mkv", ".avi",
}

# Explicit blacklist of executable / script / launcher types
FORBIDDEN_OPEN_EXTENSIONS: Set[str] = {
    ".exe", ".com", ".msi", ".scr", ".pif", ".cpl",
    ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".hta", ".lnk", ".url", ".msc", ".reg",
}


def is_reparse_point(path: Path | str) -> bool:
    """
    Check if a path is a Windows reparse point (symlink, junction, mount point).
    Safe to call on any platform.
    """
    p_str = str(path)
    # Check Python's standard symlink detection
    try:
        st = os.lstat(p_str)
        if stat.S_ISLNK(st.st_mode):
            return True
    except (OSError, ValueError):
        pass

    # On Windows, check Win32 file attributes for reparse points
    if sys.platform == "win32":
        try:
            attrs = ctypes.windll.kernel32.GetFileAttributesW(p_str)
            if attrs != 0xFFFFFFFF and (attrs & FILE_ATTRIBUTE_REPARSE_POINT) != 0:
                return True
        except Exception:
            pass

    return False


def _is_subpath(target: Path, base: Path) -> bool:
    """
    Component-aware subpath check.
    Returns True if target == base or base is an ancestor of target.
    Does NOT use naive string prefix matching.
    """
    try:
        t_res = target.resolve()
        b_res = base.resolve()
        if t_res == b_res:
            return True
        return b_res in t_res.parents
    except Exception:
        return False


def _get_protected_system_paths() -> List[Path]:
    """Retrieve canonical Windows system roots that must never be modified."""
    protected: List[Path] = []
    
    # Standard Windows directories
    win_dir = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    try:
        protected.append(Path(win_dir).resolve())
    except Exception:
        pass

    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        val = os.environ.get(env_var)
        if val:
            try:
                protected.append(Path(val).resolve())
            except Exception:
                pass

    # Common defaults if env vars missing
    for default_path in (r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData"):
        p = Path(default_path)
        if p.exists():
            try:
                p_res = p.resolve()
                if p_res not in protected:
                    protected.append(p_res)
            except Exception:
                pass

    return protected


def _get_nova_repo_root() -> Optional[Path]:
    """
    Derive Nova repository root from this file's location.
    Traverses upward until .git, pyproject.toml, or src/nova marker is found.
    """
    try:
        current = Path(__file__).resolve()
        for p in current.parents:
            if (p / ".git").exists() or (p / "pyproject.toml").exists() or ((p / "src" / "nova").is_dir()):
                return p.resolve()
        if len(current.parents) >= 5:
            return current.parents[4].resolve()
    except Exception:
        pass
    return None


def _get_nova_protected_paths() -> List[Path]:
    """
    Retrieve canonical paths for the Nova project, runtime, config, tests, and .git.
    Mutation operations inside any of these are strictly prohibited.
    """
    protected: List[Path] = []
    root = _get_nova_repo_root()
    if root:
        protected.append(root)
        for sub in ("src", "tests", "config", ".git", ".cache"):
            sub_path = (root / sub).resolve()
            if sub_path not in protected:
                protected.append(sub_path)
    return protected


def _get_credential_protected_paths() -> List[Path]:
    """
    Retrieve sensitive user credential locations:
    - %USERPROFILE%\\.ssh
    - %USERPROFILE%\\.aws
    - %APPDATA%\\Microsoft\\Credentials
    - %APPDATA%\\Microsoft\\Vault
    """
    protected: List[Path] = []
    user_profile = os.environ.get("USERPROFILE") or str(Path.home())
    try:
        user_p = Path(user_profile).resolve()
        protected.append((user_p / ".ssh").resolve())
        protected.append((user_p / ".aws").resolve())
    except Exception:
        pass

    appdata = os.environ.get("APPDATA")
    if not appdata:
        try:
            appdata = str(Path(user_profile) / "AppData" / "Roaming")
        except Exception:
            appdata = None

    if appdata:
        try:
            appdata_p = Path(appdata).resolve()
            protected.append((appdata_p / "Microsoft" / "Credentials").resolve())
            protected.append((appdata_p / "Microsoft" / "Vault").resolve())
        except Exception:
            pass

    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        try:
            local_p = Path(localappdata).resolve()
            protected.append((local_p / "Microsoft" / "Credentials").resolve())
            protected.append((local_p / "Microsoft" / "Vault").resolve())
        except Exception:
            pass

    return protected


def is_protected_system_target(path: Path, operation: OperationType) -> bool:
    """Check if path itself is a protected root or directory (e.g. C:\\ or C:\\Users)."""
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path

    # Drive root (e.g. C:\)
    if len(resolved.parts) <= 1:
        return True

    # C:\Users directly
    if len(resolved.parts) == 2 and resolved.parts[1].lower() == "users":
        return True

    return False


def is_inside_protected_system_tree(path: Path, operation: OperationType) -> bool:
    """
    Check if path is inside Windows system roots, Nova project/runtime tree,
    or sensitive user credential stores.
    """
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path

    # 1. Standard Windows system roots (Windows, Program Files, ProgramData)
    for sys_root in _get_protected_system_paths():
        try:
            if _is_subpath(resolved, sys_root):
                # System folders are protected from WRITE, DELETE, and EXECUTE_OPEN
                if operation in (OperationType.WRITE, OperationType.DELETE, OperationType.EXECUTE_OPEN):
                    return True
                # Sensitive files in system folder are protected even from READ / LIST
                if operation in (OperationType.READ, OperationType.LIST):
                    rel_parts = resolved.relative_to(sys_root).parts
                    if rel_parts and rel_parts[0].lower() in ("system32", "syswow64"):
                        if len(rel_parts) > 1 and rel_parts[1].lower() == "config":
                            return True  # Block SAM, SYSTEM hive reading
        except Exception:
            continue

    # 2. Nova project / runtime / config / tests / .git tree
    # Mutation operations (WRITE, DELETE) are strictly prohibited
    if operation in (OperationType.WRITE, OperationType.DELETE):
        for nova_path in _get_nova_protected_paths():
            if _is_subpath(resolved, nova_path):
                return True

    # 3. Sensitive user credential locations (%USERPROFILE%\.ssh, .aws, Microsoft\Credentials, Vault)
    # Mutation operations (WRITE, DELETE) and EXECUTE_OPEN are strictly prohibited
    if operation in (OperationType.WRITE, OperationType.DELETE, OperationType.EXECUTE_OPEN):
        for cred_path in _get_credential_protected_paths():
            if _is_subpath(resolved, cred_path):
                return True

    return False


def is_protected_system_path(path: Path, operation: OperationType) -> bool:
    """
    Determine if the path lies inside a protected system location for the given operation.
    WRITE and DELETE are strictly forbidden inside system roots, drive roots, user roots,
    Nova project tree, and credential locations.
    """
    return is_protected_system_target(path, operation) or is_inside_protected_system_tree(path, operation)


class PathGuard:
    """
    Validator for filesystem paths according to Nova security invariants.
    """

    _get_nova_repo_root = staticmethod(_get_nova_repo_root)
    get_nova_repo_root = staticmethod(_get_nova_repo_root)

    @classmethod
    def validate_syntax(cls, raw_path: str) -> None:
        """
        Validate path syntax, rejecting null bytes, control characters,
        UNC paths, device namespaces, reserved names, and Alternate Data Streams (ADS).
        """
        if not raw_path or not isinstance(raw_path, str):
            raise PathSecurityError("Path must be a non-empty string.")

        # 1. Null bytes & control characters
        if "\0" in raw_path:
            raise PathSecurityError("Path contains forbidden null byte.")
        for char in raw_path:
            # Reject ASCII control chars (0x01 to 0x1F)
            if ord(char) < 32 and char not in ("\t", "\n", "\r"):
                raise PathSecurityError(f"Path contains forbidden control character (ASCII {ord(char)}).")

        stripped = raw_path.strip()
        if not stripped:
            raise PathSecurityError("Path cannot be blank.")

        # 2. Device namespaces (e.g. \\.\ or \\?\ or //./ or //?/)
        normalized_slashes = stripped.replace("/", "\\")
        if (
            normalized_slashes.startswith("\\\\.\\")
            or normalized_slashes.startswith("\\\\?\\")
            or normalized_slashes.startswith("\\??\\")
        ):
            raise PathSecurityError("Device namespaces are forbidden.")

        # 3. UNC paths (e.g. \\server\share or //server/share)
        if stripped.startswith(r"\\") or stripped.startswith("//"):
            raise PathSecurityError("UNC network paths are forbidden.")

        # 4. Windows drive letter vs Alternate Data Streams (ADS)
        # Valid Windows drive letter is: ^[A-Za-z]:[\\/] or relative drive ^[A-Za-z]:[^:]
        # Any colon other than at index 1 for a drive letter is an ADS stream!
        colon_indices = [i for i, c in enumerate(stripped) if c == ":"]
        if colon_indices:
            if len(colon_indices) > 1:
                raise PathSecurityError("Path contains multiple colons (forbidden ADS or invalid syntax).")
            if colon_indices[0] != 1 or not stripped[0].isalpha():
                raise PathSecurityError(f"Colon at index {colon_indices[0]} is not a valid drive letter prefix (potential ADS).")

        # 5. Reserved DOS device names
        # Check all components separated by / or \
        parts = re.split(r"[\\/]", stripped)
        for part in parts:
            if not part:
                continue
            # Strip extension for DOS device name check (e.g. "nul.txt" -> "nul")
            base_part = part.split(".")[0].upper()
            if base_part in RESERVED_DEVICE_NAMES:
                raise PathSecurityError(f"Path references reserved DOS device name: {base_part}")

    @classmethod
    def validate_ancestors(cls, path: Path, operation: OperationType) -> None:
        """
        Validate the complete existing ancestor chain of a path.
        Ensures no ancestor is a junction/symlink/reparse point escaping boundaries
        or located in a protected system directory.
        """
        curr = path
        # If the path does not exist yet, find the first existing ancestor
        while len(curr.parts) > 1:
            try:
                if curr.exists():
                    break
            except (OSError, PermissionError):
                pass
            curr = curr.parent

        try:
            if not curr.exists():
                return
        except (OSError, PermissionError):
            return

        # Check existing ancestors up to root
        for ancestor in [curr] + list(curr.parents):
            try:
                if not ancestor.exists():
                    continue
            except (OSError, PermissionError):
                continue

            # Check reparse point / junction on existing ancestor
            if is_reparse_point(ancestor):
                # Symlinks / junctions in user or system paths cannot be used to bypass boundaries
                raise PathSecurityError(
                    f"Path ancestor '{ancestor}' is a reparse point or junction (traversal forbidden)."
                )

            # Check protected system path on existing ancestor
            if is_inside_protected_system_tree(ancestor, operation):
                raise PathSecurityError(
                    f"Path ancestor '{ancestor}' is in a protected system location."
                )

    @classmethod
    def validate_safe_path(
        cls,
        raw_path: str | Path,
        operation: OperationType,
        allow_nonexistent: bool = False,
        base_dir: Optional[Path] = None,
    ) -> Path:
        """
        Execute full multi-stage path validation pipeline.
        
        raw path
         ↓
        syntax / lexical validation
         ↓
        Windows canonicalization
         ↓
        operation-specific policy
         ↓
        protected-boundary validation
         ↓
        symlink/junction/reparse-point validation
         ↓
        ancestor chain validation
         ↓
        validated Path object
        """
        path_str = str(raw_path).strip()
        cls.validate_syntax(path_str)

        # Expand environment variables and user (~)
        expanded_str = os.path.expandvars(path_str)
        if expanded_str != path_str:
            cls.validate_syntax(expanded_str)
        expanded = Path(expanded_str).expanduser()

        # If relative and base_dir provided, resolve against base_dir; else resolve against cwd
        if not expanded.is_absolute():
            if base_dir:
                expanded = (base_dir / expanded)
            else:
                expanded = (Path.cwd() / expanded)

        # Windows canonicalization
        try:
            resolved = expanded.resolve()
        except Exception as e:
            raise PathSecurityError(f"Failed to canonicalize path: {e}")

        # Non-existent path check
        if not allow_nonexistent and not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {resolved}")

        # Protected boundary check
        if is_protected_system_path(resolved, operation):
            raise PathSecurityError(
                f"Path '{resolved}' is inside a protected system directory for operation '{operation.value}'."
            )

        # Reparse point / symlink check on the target itself if it exists
        if resolved.exists() and is_reparse_point(resolved):
            if operation in (OperationType.DELETE, OperationType.WRITE):
                raise PathSecurityError(
                    f"Target '{resolved}' is a reparse point or symlink (mutations forbidden)."
                )

        # Validate complete ancestor chain
        cls.validate_ancestors(resolved, operation)

        return resolved

    @classmethod
    def validate_open_extension(cls, path: Path) -> None:
        """
        Validate that file extension is safe for open_file.
        Applies strict allowlist and explicit blacklist.
        """
        ext = path.suffix.lower()
        if not ext:
            raise PathSecurityError(f"Cannot open file without extension: {path.name}")

        if ext in FORBIDDEN_OPEN_EXTENSIONS:
            raise PathSecurityError(f"Forbidden file type for open: {ext}")

        if ext not in ALLOWED_OPEN_EXTENSIONS:
            raise PathSecurityError(f"Extension '{ext}' is not in the safe open allowlist.")

    @classmethod
    def pre_action_verify_file(cls, path: Path, operation: OperationType) -> None:
        """
        Pre-action race-resistant verification immediately before filesystem mutation.
        Re-verifies target existence, regular file status, reparse point, and parent.
        """
        if not path.is_absolute():
            raise PathSecurityError("Path must be absolute for pre-action verification.")

        # Re-check syntax of path string
        cls.validate_syntax(str(path))

        # Re-check protected boundary
        if is_protected_system_path(path, operation):
            raise PathSecurityError(f"Pre-action: Protected boundary violation for {path}")

        # Verify parent directory exists and is not a reparse point
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            raise PathSecurityError(f"Pre-action: Parent directory does not exist or is not a directory: {parent}")

        if is_reparse_point(parent):
            raise PathSecurityError(f"Pre-action: Parent directory is a reparse point: {parent}")

        # For DELETE, ensure target exists, is a regular file, and not a link/junction/directory
        if operation == OperationType.DELETE:
            if not path.exists():
                raise FileNotFoundError(f"File not found for deletion: {path}")
            if path.is_dir():
                raise PathSecurityError(f"Refusing to delete directory as file: {path}")
            if is_reparse_point(path):
                raise PathSecurityError(f"Refusing to delete reparse point/symlink: {path}")
            if not path.is_file():
                raise PathSecurityError(f"Target is not a regular file: {path}")
