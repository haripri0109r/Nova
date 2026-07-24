#!/usr/bin/env python3
"""
AppLauncher: High-level application launcher using AppIndexer + fuzzy matching.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

from modules.discovery.app_indexer import get_app_indexer

log = logging.getLogger("nova")

# -------------------------------------------------------------------------
# Configuration constants
# -------------------------------------------------------------------------
DEFAULT_LAUNCH_THRESHOLD = 75   # Minimum rapidfuzz score to consider a match
DISAMBIGUATION_DELTA = 5        # Points within which multiple matches are ambiguous
ALIASES = {
    "vs code": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "vs": "Visual Studio Code",
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "teams": "Microsoft Teams",
    "notepad++": "Notepad++",
    "notepadpp": "Notepad++",
    "cmd": "Command Prompt",
    "powershell": "Windows PowerShell",
    "terminal": "Windows Terminal",
}

# -------------------------------------------------------------------------
# Result dataclass
# -------------------------------------------------------------------------
@dataclass
class LaunchResult:
    status: str                     # "launched" | "ambiguous" | "not_found" | "error"
    matched_app: Optional[Dict]     # The matched app record (if any)
    confidence: int                 # rapidfuzz score 0-100
    path: Optional[str]             # Resolved executable path
    candidates: List[Dict]          # List of candidate apps if ambiguous
    error_message: Optional[str]    # Error message if status == "error"

    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "matched_app": self.matched_app,
            "confidence": self.confidence,
            "path": self.path,
            "candidates": self.candidates,
            "error_message": self.error_message,
        }


# -------------------------------------------------------------------------
# AppLauncher
# -------------------------------------------------------------------------
class AppLauncher:
    """
    High-level app launcher using AppIndexer + rapidfuzz fuzzy matching.
    """

    def __init__(
        self,
        launch_threshold: int = DEFAULT_LAUNCH_THRESHOLD,
        disambiguation_delta: int = DISAMBIGUATION_DELTA,
    ):
        self.indexer = get_app_indexer()
        self.launch_threshold = launch_threshold
        self.disambiguation_delta = disambiguation_delta

    # ------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------
    def launch(self, spoken_name: str) -> LaunchResult:
        """
        Main entry point: resolve spoken app name and launch it.

        Returns a LaunchResult describing the outcome.
        """
        if not spoken_name or not spoken_name.strip():
            return LaunchResult(
                status="error",
                matched_app=None,
                confidence=0,
                path=None,
                candidates=[],
                error_message="Empty app name",
            )

        # 1. Ensure index is built
        self.indexer.refresh()

        # 2. Resolve aliases first
        normalized = spoken_name.strip().lower()
        canonical = ALIASES.get(normalized, normalized)

        # 2. Try exact match first (fast path)
        exact_matches = self._exact_match(canonical)
        if exact_matches:
            return self._launch_first(exact_matches[0])

        # 3. Fuzzy match against all indexed apps
        apps = self.indexer.get_all()
        if not apps:
            return LaunchResult(
                status="not_found",
                matched_app=None,
                confidence=0,
                path=None,
                candidates=[],
                error_message="App index is empty",
            )

        # Fuzzy match using rapidfuzz token_sort_ratio (good for word order variance)
        if fuzz is None:
            log.error("rapidfuzz not installed; cannot fuzzy match")
            return LaunchResult(
                status="error",
                matched_app=None,
                confidence=0,
                path=None,
                candidates=[],
                error_message="rapidfuzz not installed",
            )

        scored = []
        for app in self.indexer.get_all():
            score = fuzz.token_sort_ratio(canonical, app["name"].lower())
            if score >= 0:  # keep all for now
                scored.append((score, app))

        if not scored:
            return LaunchResult(
                status="not_found",
                matched_app=None,
                confidence=0,
                path=None,
                candidates=[],
                error_message="No apps indexed",
            )

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)

        top_score, top_app = scored[0]

        # Below threshold -> try cache refresh once
        if top_score < self.launch_threshold:
            log.info("Top score %d below threshold %d; refreshing index and retrying", top_score, self.launch_threshold)
            self.indexer.refresh()
            # Retry once
            apps = self.indexer.get_all()
            scored = []
            for app in apps:
                score = fuzz.token_sort_ratio(canonical, app["name"].lower())
                scored.append((score, app))
            scored.sort(key=lambda x: x[0], reverse=True)
            top_score, top_app = scored[0]
            if top_score < self.launch_threshold:
                return LaunchResult(
                    status="not_found",
                    matched_app=None,
                    confidence=top_score,
                    path=None,
                    candidates=[],
                    error_message=f"No match above threshold ({top_score}/{self.launch_threshold})",
                )

        # Disambiguation: collect all within DELTA of top score
        candidates = [app for score, app in scored if score >= top_score - self.disambiguation_delta]

        if len(candidates) > 1:
            # Ambiguous
            return LaunchResult(
                status="ambiguous",
                matched_app=None,
                confidence=top_score,
                path=None,
                candidates=[{"name": a["name"], "path": a["path"], "score": score} for score, a in scored if score >= top_score - self.disambiguation_delta],
                error_message=f"Ambiguous: {len(candidates)} apps within {self.disambiguation_delta} points",
            )

        # Single best match
        return self._launch(candidates[0])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _exact_match(self, name: str) -> List[Dict]:
        """Case-insensitive exact name match."""
        name_lower = name.lower()
        apps = self.indexer.get_all()
        return [app for app in apps if app["name"].lower() == name_lower]

    def _launch_first(self, app: Dict) -> LaunchResult:
        return self._launch(app)

    def _launch(self, app: Dict) -> LaunchResult:
        """Launch the given app record."""
        path = app.get("path")
        if not path:
            return LaunchResult(
                status="error",
                matched_app=app,
                confidence=0,
                path=None,
                candidates=[],
                error_message="App record has no executable path",
            )
        try:
            # Detect UWP app (path contains '!' indicating package family name)
            if '!' in path:
                # UWP app: launch via explorer shell:AppsFolder
                cmd = f'explorer.exe shell:AppsFolder\\{path}'
                subprocess.Popen(cmd, shell=True)
                log.info("Launched UWP %s via %s", app["name"], path)
                return LaunchResult(
                    status="launched",
                    matched_app=app,
                    confidence=100,
                    path=path,
                    candidates=[],
                    error_message=None,
                )
            else:
                # Regular executable
                if os.path.exists(path):
                    os.startfile(path)  # Windows
                    log.info("Launched %s via %s", app["name"], path)
                    return LaunchResult(
                        status="launched",
                        matched_app=app,
                        confidence=100,
                        path=path,
                        candidates=[],
                        error_message=None,
                    )
                else:
                    log.error("Executable not found: %s", path)
                    return LaunchResult(
                        status="error",
                        matched_app=app,
                        confidence=0,
                        path=path,
                        candidates=[],
                        error_message=f"Executable not found: {path}",
                    )
        except Exception as exc:
            log.error("Failed to launch %s: %s", app["name"], exc)
            return LaunchResult(
                status="error",
                matched_app=app,
                confidence=0,
                path=path,
                candidates=[],
                error_message=str(exc),
            )

# -------------------------------------------------------------------------
# Module-level singleton
# -------------------------------------------------------------------------
_launcher: Optional["AppLauncher"] = None
_launcher_lock = threading.Lock()


def get_app_launcher() -> AppLauncher:
    global _launcher
    if _launcher is None:
        with _launcher_lock:
            if _launcher is None:
                _launcher = AppLauncher()
    return _launcher


if __name__ == "__main__":
    # Quick manual test
    logging.basicConfig(level=logging.DEBUG)
    launcher = get_app_launcher()
    # Example: launcher.launch("visual studio code")
    print("AppLauncher module loaded. Import and use get_app_launcher().")