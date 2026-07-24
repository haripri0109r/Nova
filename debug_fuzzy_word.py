#!/usr/bin/env python3
import sys
sys.path.insert(0, r"C:\Users\HARIPRIYAN\nova")
from modules.discovery.app_indexer import get_app_indexer

try:
    from rapidfuzz import fuzz
    def score(q, s):
        return fuzz.WRatio(q, s)
except Exception:
    import difflib
    def score(q, s):
        return int(difflib.SequenceMatcher(None, q.lower(), s.lower()).ratio() * 100)

def safe_print(s):
    sys.stdout.buffer.write((s + "\n").encode('utf-8', errors='replace'))

def main():
    indexer = get_app_indexer()
    apps = indexer.get_all()
    query = "word"
    results = []
    for app in apps:
        name = app.get("name", "")
        sc = score(query, name)
        results.append((sc, name, app.get("path", ""), app.get("install_type", "")))
    results.sort(key=lambda x: x[0], reverse=True)
    for sc, name, path, itype in results:
        safe_print(f"{sc:6.2f} | {name} -> {path} [{itype}]")

if __name__ == "__main__":
    main()