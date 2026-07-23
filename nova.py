#!/usr/bin/env python3
"""Shim: delegate to the packaged entry point."""
from src.nova.main import main

if __name__ == "__main__":
    raise SystemExit(main())