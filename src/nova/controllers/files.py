"""
Files controller – open folder, search, create/delete/move/copy.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.files")


class FilesController(BaseController):
    domain = "files"
    description = "File system operations (open folder, search, create/delete/move/copy)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        path = intent.get("path")
        dest = intent.get("destination")
        query = intent.get("query")
        try:
            if operation == "open_folder":
                if not path:
                    return {"status": "error", "detail": "Missing path"}
                p = Path(path).expanduser().resolve()
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
                results = self._search(query)
                return {"status": "ok", "detail": results[:20]}

            if operation == "create_folder":
                if not path:
                    return {"status": "error", "detail": "Missing path"}
                Path(path).expanduser().resolve().mkdir(parents=True, exist_ok=True)
                return {"status": "ok", "detail": f"Created folder {path}"}

            if operation == "delete":
                if not path:
                    return {"status": "error", "detail": "Missing path"}
                p = Path(path).expanduser().resolve()
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                return {"status": "ok", "detail": f"Deleted {p}"}

            if operation == "move":
                if not path or not dest:
                    return {"status": "error", "detail": "Missing source or destination"}
                shutil.move(str(Path(path).expanduser()), str(Path(dest).expanduser()))
                return {"status": "ok", "detail": f"Moved {path} to {dest}"}

            if operation == "copy":
                if not path or not dest:
                    return {"status": "error", "detail": "Missing source or destination"}
                src = Path(path).expanduser()
                dst = Path(dest).expanduser()
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                return {"status": "ok", "detail": f"Copied {path} to {dest}"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("FilesController failed")
            return {"status": "error", "detail": "File operation failed"}

    def _search(self, query: str) -> List[str]:
        results: List[str] = []
        if sys.platform == "win32":
            cmd = ["cmd", "/c", f"dir /s /b *{query}*"]
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            results = [line.strip() for line in out.splitlines() if line.strip()]
        else:
            try:
                out = subprocess.check_output(["locate", "-i", query], text=True)
                results = out.strip().splitlines()
            except FileNotFoundError:
                out = subprocess.check_output(["find", os.path.expanduser("~"), "-iname", f"*{query}*"], text=True, stderr=subprocess.DEVNULL)
                results = out.strip().splitlines()
        return results


registry.register(FilesController())