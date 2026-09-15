"""
File search skill – find files by name using safe Python filesystem APIs.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.files.search")


def _get_search_roots() -> List[Path]:
    user_home = Path.home()
    roots = [
        user_home / "Desktop",
        user_home / "Documents",
        user_home / "Downloads",
        user_home / "Music",
        user_home / "Pictures",
        user_home / "Videos",
        Path(os.environ.get("TEMP", r"C:\Windows\Temp")),
        Path.cwd(),
    ]
    seen = set()
    valid_roots = []
    for r in roots:
        try:
            resolved = r.resolve()
            if resolved.is_dir() and resolved not in seen:
                seen.add(resolved)
                valid_roots.append(resolved)
        except Exception:
            continue
    return valid_roots


from .path_guard import PathGuard, OperationType, is_reparse_point

def _safe_search_files(
    pattern: str,
    max_results: int = 20,
    max_depth: int = 4,
    extension: Optional[str] = None,
    search_root: Optional[str] = None,
) -> List[str]:
    """
    Safely search for files matching pattern (case-insensitive substring) across standard user folders.
    Does not use shell or subprocess. Bounded by depth (max 4) and hard capped at 50 results.
    Never follows symlinks or reparse points.
    """
    clean_pattern = pattern.strip().lower()
    if not clean_pattern:
        return []

    # Hard cap at 50 results
    effective_max = min(max(1, max_results), 50)
    effective_depth = min(max(1, max_depth), 4)

    clean_ext = extension.strip().lower() if extension else None
    if clean_ext and not clean_ext.startswith("."):
        clean_ext = f".{clean_ext}"

    results: List[str] = []

    if search_root:
        try:
            validated_root = PathGuard.validate_safe_path(search_root, operation=OperationType.LIST)
            if validated_root.is_dir():
                search_roots = [validated_root]
            else:
                search_roots = []
        except Exception as exc:
            logger.warning("Invalid search_root provided (%s): %s", search_root, exc)
            return []
    else:
        search_roots = _get_search_roots()

    for root in search_roots:
        root_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
            curr_depth = len(Path(dirpath).parts) - root_depth
            if curr_depth >= effective_depth:
                dirnames.clear()

            # Skip hidden / system / large build directories and any reparse points
            safe_dirnames = []
            for d in dirnames:
                if d.startswith("."):
                    continue
                if d.lower() in (
                    "node_modules",
                    "site-packages",
                    "__pycache__",
                    "$recycle.bin",
                    "system volume information",
                    "appdata",
                ):
                    continue
                d_full = os.path.join(dirpath, d)
                try:
                    if is_reparse_point(d_full):
                        continue
                except Exception:
                    continue
                safe_dirnames.append(d)
            dirnames[:] = safe_dirnames

            for fname in filenames:
                if clean_ext and not fname.lower().endswith(clean_ext):
                    continue
                if clean_pattern in fname.lower():
                    full_path = os.path.join(dirpath, fname)
                    if full_path not in results:
                        results.append(full_path)
                        if len(results) >= effective_max:
                            return results

    return results


class FileSearchSkill(BaseSkill):
    intent = "find_file"
    description = "Search for files by name."

    parameters_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "File name pattern or substring to search for.",
            },
            "extension": {
                "type": "string",
                "description": "Optional file extension to filter by (e.g. '.pdf', '.txt').",
            },
            "search_root": {
                "type": "string",
                "description": "Optional root directory path to restrict search within.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 20, hard cap 50).",
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "find_file"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        pattern = intent_data.get("pattern")
        if not pattern:
            logger.warning("FileSearchSkill called without pattern")
            return {"status": "error", "message": "Missing search pattern"}

        ext = intent_data.get("extension")
        root = intent_data.get("search_root")
        max_res = intent_data.get("max_results", 20)
        try:
            max_res = int(max_res)
        except (ValueError, TypeError):
            max_res = 20

        try:
            results = _safe_search_files(
                pattern,
                max_results=max_res,
                max_depth=4,
                extension=ext,
                search_root=root,
            )
            logger.info("Found %d files for pattern %s", len(results), pattern)
            return {"status": "ok", "detail": results}
        except Exception:
            logger.exception("FileSearchSkill failed")
            return {"status": "error", "message": "File search failed"}


registry.register(FileSearchSkill())