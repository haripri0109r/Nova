"""
File Operations Skill — Safe file and folder management for Nova.

Provides strictly controlled filesystem operations:
- list_directory
- get_file_info
- open_file
- create_folder
- create_file
- rename_file
- copy_file
- move_file
- delete_file

Invariants enforced:
- Single capability ownership: find_file is owned by FileSearchSkill; open_folder is owned by ExplorerSkill.
- Overwrite is ALWAYS false in V1. Destination collisions fail safely.
- open_file enforces conservative document/media allowlist and executable blacklist.
- delete_file is restricted to regular files only (no directory, no symlink/junction, no recursive deletion).
- Pre-action race-resistant checks immediately before destructive mutation.
- Strict parameter matrix validation for each action.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry
from .path_guard import (
    OperationType,
    PathGuard,
    PathSecurityError,
    is_reparse_point,
)

logger = logging.getLogger("nova.skills.files.file_ops")

# Allowed actions for FileOpsSkill
ALLOWED_ACTIONS = {
    "list_directory",
    "get_file_info",
    "open_file",
    "create_folder",
    "create_file",
    "rename_file",
    "copy_file",
    "move_file",
    "delete_file",
}


class FileOpsSkill(BaseSkill):
    intent = "file_operation"
    description = "Perform safe file and folder management (list, info, open, create, copy, move, rename, delete)."

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(ALLOWED_ACTIONS),
                "description": "The file operation action to perform.",
            },
            "path": {
                "type": "string",
                "description": "Target file or folder path.",
            },
            "source": {
                "type": "string",
                "description": "Source path for copy, move, or rename.",
            },
            "destination": {
                "type": "string",
                "description": "Destination path for copy, move, or rename.",
            },
            "content": {
                "type": "string",
                "description": "Optional text content when creating a file.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        canonical_intent = intent_data.get("intent")
        if canonical_intent in ("file_operation", "file", "file_control"):
            action = intent_data.get("action")
            return action in ALLOWED_ACTIONS
        return False

    def _validate_parameter_matrix(self, action: str, data: Dict[str, Any]) -> None:
        """
        Enforce the strict parameter matrix for each action.
        Rejects unexpected parameters and ensures required parameters are present.
        """
        # Disallowed top-level payload keys
        allowed_keys = {"intent", "action", "session_id", "task_id", "step_index"}

        if action == "list_directory":
            allowed_keys.add("path")
            for forbidden in ("source", "destination", "content"):
                if forbidden in data and data[forbidden] is not None:
                    raise ValueError(f"Action '{action}' does not accept '{forbidden}'.")

        elif action in ("get_file_info", "open_file", "create_folder"):
            allowed_keys.add("path")
            if not data.get("path"):
                raise ValueError(f"Action '{action}' requires 'path'.")
            for forbidden in ("source", "destination", "content"):
                if forbidden in data and data[forbidden] is not None:
                    raise ValueError(f"Action '{action}' does not accept '{forbidden}'.")

        elif action == "create_file":
            allowed_keys.update({"path", "content"})
            if not data.get("path"):
                raise ValueError(f"Action '{action}' requires 'path'.")
            for forbidden in ("source", "destination"):
                if forbidden in data and data[forbidden] is not None:
                    raise ValueError(f"Action '{action}' does not accept '{forbidden}'.")

        elif action in ("rename_file", "copy_file", "move_file"):
            allowed_keys.update({"source", "destination"})
            if not data.get("source"):
                raise ValueError(f"Action '{action}' requires 'source'.")
            if not data.get("destination"):
                raise ValueError(f"Action '{action}' requires 'destination'.")
            for forbidden in ("path", "content"):
                if forbidden in data and data[forbidden] is not None:
                    raise ValueError(f"Action '{action}' does not accept '{forbidden}'.")

        elif action == "delete_file":
            allowed_keys.add("path")
            if not data.get("path"):
                raise ValueError(f"Action '{action}' requires 'path'.")
            for forbidden in ("source", "destination", "content"):
                if forbidden in data and data[forbidden] is not None:
                    raise ValueError(f"Action '{action}' does not accept '{forbidden}'.")

        else:
            raise ValueError(f"Unsupported action: '{action}'")

        # Check for unknown parameters
        for key in data.keys():
            if key not in allowed_keys and data[key] is not None:
                raise ValueError(f"Unexpected parameter '{key}' for action '{action}'.")

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action")
        if not action or action not in ALLOWED_ACTIONS:
            return {"status": "error", "message": f"Invalid or missing action: '{action}'"}

        try:
            self._validate_parameter_matrix(action, intent_data)
        except ValueError as exc:
            logger.warning("Parameter validation failed for %s: %s", action, exc)
            return {"status": "error", "message": str(exc)}

        try:
            if action == "list_directory":
                return self._list_directory(intent_data.get("path"))
            elif action == "get_file_info":
                return self._get_file_info(intent_data["path"])
            elif action == "open_file":
                return self._open_file(intent_data["path"])
            elif action == "create_folder":
                return self._create_folder(intent_data["path"])
            elif action == "create_file":
                return self._create_file(intent_data["path"], intent_data.get("content"))
            elif action == "rename_file":
                return self._rename_file(intent_data["source"], intent_data["destination"])
            elif action == "copy_file":
                return self._copy_file(intent_data["source"], intent_data["destination"])
            elif action == "move_file":
                return self._move_file(intent_data["source"], intent_data["destination"])
            elif action == "delete_file":
                return self._delete_file(intent_data["path"])
        except PathSecurityError as exc:
            logger.warning("PathSecurityError in %s: %s", action, exc)
            return {"status": "error", "message": f"Security violation: {exc}"}
        except FileNotFoundError as exc:
            logger.warning("FileNotFoundError in %s: %s", action, exc)
            return {"status": "error", "message": str(exc)}
        except FileExistsError as exc:
            logger.warning("FileExistsError in %s: %s", action, exc)
            return {"status": "error", "message": str(exc)}
        except Exception as exc:
            logger.exception("Unexpected error in %s", action)
            return {"status": "error", "message": f"Failed to execute {action}: {exc}"}

        return {"status": "error", "message": "Unknown execution path"}

    # -----------------------------------------------------------------------
    # Action Implementations
    # -----------------------------------------------------------------------

    def _list_directory(self, raw_path: Optional[str]) -> Dict[str, Any]:
        target = raw_path if raw_path else str(Path.cwd())
        path = PathGuard.validate_safe_path(target, operation=OperationType.LIST)

        if not path.is_dir():
            return {"status": "error", "message": f"Path is not a directory: {path}"}

        entries: List[Dict[str, Any]] = []
        try:
            with os.scandir(str(path)) as it:
                for entry in it:
                    if len(entries) >= 100:
                        break
                    # Avoid reading reparse points or system-hidden entries
                    is_rep = False
                    try:
                        is_rep = is_reparse_point(entry.path)
                    except Exception:
                        pass
                    try:
                        st = entry.stat(follow_symlinks=False)
                        entries.append({
                            "name": entry.name,
                            "is_dir": entry.is_dir(follow_symlinks=False),
                            "size": st.st_size if not entry.is_dir(follow_symlinks=False) else 0,
                            "is_reparse_point": is_rep,
                        })
                    except (OSError, PermissionError):
                        continue
        except PermissionError:
            return {"status": "error", "message": f"Permission denied accessing directory: {path}"}

        return {
            "status": "ok",
            "path": str(path),
            "count": len(entries),
            "entries": entries,
        }

    def _get_file_info(self, raw_path: str) -> Dict[str, Any]:
        path = PathGuard.validate_safe_path(raw_path, operation=OperationType.READ)

        st = path.stat()
        mtime = datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc).isoformat()

        return {
            "status": "ok",
            "name": path.name,
            "path": str(path),
            "is_dir": path.is_dir(),
            "is_file": path.is_file(),
            "size": st.st_size,
            "modified_time": mtime,
            "extension": path.suffix.lower(),
            "is_reparse_point": is_reparse_point(path),
        }

    def _open_file(self, raw_path: str) -> Dict[str, Any]:
        path = PathGuard.validate_safe_path(raw_path, operation=OperationType.EXECUTE_OPEN)

        if not path.is_file():
            return {"status": "error", "message": f"File not found: {path}"}

        # Validate file extension against approved documents/media allowlist
        PathGuard.validate_open_extension(path)

        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
            return {"status": "ok", "message": f"Opened file {path.name}", "path": str(path)}
        except Exception as exc:
            logger.exception("Failed to open file: %s", path)
            return {"status": "error", "message": f"Failed to open file: {exc}"}

    def _create_folder(self, raw_path: str) -> Dict[str, Any]:
        path = PathGuard.validate_safe_path(raw_path, operation=OperationType.WRITE, allow_nonexistent=True)

        if path.exists():
            return {"status": "error", "message": f"Folder already exists: {path}"}

        # Ancestor validation has verified every existing parent directory
        # Validate that the immediate non-existing path can be created safely
        try:
            path.mkdir(parents=True, exist_ok=False)
            return {"status": "ok", "message": f"Created folder {path.name}", "path": str(path)}
        except FileExistsError:
            return {"status": "error", "message": f"Folder already exists: {path}"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied creating folder: {path}"}

    def _create_file(self, raw_path: str, content: Optional[str]) -> Dict[str, Any]:
        path = PathGuard.validate_safe_path(raw_path, operation=OperationType.WRITE, allow_nonexistent=True)

        if path.exists():
            # Invariant: V1 overwrite is ALWAYS false. No silent replacement.
            return {"status": "error", "message": f"Destination file already exists: {path}"}

        if not path.parent.exists():
            return {"status": "error", "message": f"Parent directory does not exist: {path.parent}"}

        # Pre-action check
        PathGuard.validate_syntax(str(path))

        text_content = content if content is not None else ""
        try:
            # Mode 'x' opens for exclusive creation, failing if the file already exists
            with open(str(path), mode="x", encoding="utf-8") as f:
                f.write(text_content)
            return {"status": "ok", "message": f"Created file {path.name}", "path": str(path)}
        except FileExistsError:
            return {"status": "error", "message": f"File already exists: {path}"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied creating file: {path}"}

    def _rename_file(self, raw_src: str, raw_dst: str) -> Dict[str, Any]:
        src = PathGuard.validate_safe_path(raw_src, operation=OperationType.WRITE)
        dst = PathGuard.validate_safe_path(raw_dst, operation=OperationType.WRITE, allow_nonexistent=True)

        if dst.exists():
            # Invariant: Overwrite is false
            return {"status": "error", "message": f"Destination already exists: {dst}"}

        if not dst.parent.exists():
            return {"status": "error", "message": f"Destination parent directory does not exist: {dst.parent}"}

        try:
            os.rename(str(src), str(dst))
            return {"status": "ok", "message": f"Renamed {src.name} to {dst.name}", "source": str(src), "destination": str(dst)}
        except FileExistsError:
            return {"status": "error", "message": f"Destination already exists: {dst}"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied renaming file: {src}"}

    def _copy_file(self, raw_src: str, raw_dst: str) -> Dict[str, Any]:
        src = PathGuard.validate_safe_path(raw_src, operation=OperationType.READ)
        dst = PathGuard.validate_safe_path(raw_dst, operation=OperationType.WRITE, allow_nonexistent=True)

        if not src.is_file():
            return {"status": "error", "message": f"Source is not a regular file: {src}"}

        if dst.exists():
            # Invariant: Overwrite is false
            return {"status": "error", "message": f"Destination already exists: {dst}"}

        if not dst.parent.exists():
            return {"status": "error", "message": f"Destination parent directory does not exist: {dst.parent}"}

        try:
            # Atomic exclusive copy
            shutil.copy2(str(src), str(dst))
            return {"status": "ok", "message": f"Copied {src.name} to {dst.name}", "source": str(src), "destination": str(dst)}
        except FileExistsError:
            return {"status": "error", "message": f"Destination already exists: {dst}"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied copying file: {src}"}

    def _move_file(self, raw_src: str, raw_dst: str) -> Dict[str, Any]:
        src = PathGuard.validate_safe_path(raw_src, operation=OperationType.WRITE)
        dst = PathGuard.validate_safe_path(raw_dst, operation=OperationType.WRITE, allow_nonexistent=True)

        if dst.exists():
            # Invariant: Overwrite is false
            return {"status": "error", "message": f"Destination already exists: {dst}"}

        if not dst.parent.exists():
            return {"status": "error", "message": f"Destination parent directory does not exist: {dst.parent}"}

        try:
            shutil.move(str(src), str(dst))
            return {"status": "ok", "message": f"Moved {src.name} to {dst.name}", "source": str(src), "destination": str(dst)}
        except FileExistsError:
            return {"status": "error", "message": f"Destination already exists: {dst}"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied moving file: {src}"}

    def _delete_file(self, raw_path: str) -> Dict[str, Any]:
        path = PathGuard.validate_safe_path(raw_path, operation=OperationType.DELETE)

        # Immediate pre-action race-resistant verification
        PathGuard.pre_action_verify_file(path, operation=OperationType.DELETE)

        try:
            os.unlink(str(path))
            return {"status": "ok", "message": f"Deleted file {path.name}", "path": str(path)}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied deleting file: {path}"}
        except FileNotFoundError:
            return {"status": "error", "message": f"File not found: {path}"}


# Register skill singleton
registry.register(FileOpsSkill())
