#!/usr/bin/env python3
"""
Entry point: wires NovaApplication lifecycle.
"""
from __future__ import annotations

import logging
import sys

from .application import run_application

log = logging.getLogger("nova")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    log = logging.getLogger("nova")
    log.info("Starting Nova...")
    return run_application()


if __name__ == "__main__":
    sys.exit(main())