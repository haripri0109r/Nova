"""
Files controller – open folder, search files, create folder, delete/move/copy files.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.files")


class FilesController(BaseController):
    intent = "files"
    description = "File system operations (open folder, search, create/delete/move/copy)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        path_str = intent_data.get("path")
        dest_str = intent_data.get("destination")
        query = intent_data.get("query")

        try:
            if operation == "open_folder":
                if not path_str:
                    return {"status": "error", "detail": "Missing path"}
                p = Path(path_str).expanduser().resolve()
                if not p.is_dir():
                    return {"status": "error", "detail": "Not a directory"}
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", str(p)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(p)])
                else:
                    subprocess.Popen(["xdg-open", str(p)])
                return {"status": "ok", "detail": f"Opened folder {p}"}

            if operation == "search":
                if not query:
                    return {"status": "error", "detail": "Missing query"}
                results = self._search_files(query)
                return {"status": "ok", "detail": results[:20]}

            if operation == "create_folder":
                if not path_str:
                    return {"status": "error", "detail": "Missing path"}
                Path(path_str).expanduser().resolve().mkdir(parents=True, exist_ok=True)
                return {"status": "ok", "detail": f"Created folder {path_str}"}

            if operation == "delete":
                if not path_str:
                    return {"status": "error", "detail": "Missing path"}
                p = Path(path_str).expanduser().resolve()
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                return {"status": "ok", "detail": f"Deleted {p}"}

            if operation == "move":
                if not path_str or not dest_str:
                    return {"status": "error", "detail": "Missing source or destination"}
                shutil.move(str(Path(path_str).expanduser()), str(Path(dest_str).expanduser()))
                return {"status": "ok", "detail": f"Moved {path_str} -> {dest_str}"}

            if operation == "copy":
                if not path_str or not dest_str:
                    return {"status": "error", "detail": "Missing source or destination"}
                src = Path(path_str).expanduser()
                dst = Path(dest_str).expanduser()
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                return {"status": "ok", "detail": f"Copied {path_str} -> {dest_str}"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("FilesController failed")
            return {"status": "error", "detail": "File operation failed"}

    def _search_files(self, query: str) -> List[str]:
        results: List[str] = []
        home = Path.home()
        if sys.platform == "win32":
            # simple dir /s /b
            cmd = ["cmd", "/c", f"dir /s /b *{query}*"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            results = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        else:
            cmd = ["find", str(home), "-iname", f"*{query}*"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            results = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        return results[:50]