#!/usr/bin/env python3
"""Copies shared files into the image folders that use them.

usage:
  python3 shared/sync.py           write the copies (only files that differ)
  python3 shared/sync.py --check   change nothing; exit 1 if any copy is
                                   missing or differs from its source (CI)

Every image folder is its own Docker build context, so a file several
images need can't be referenced from one place: it lives once under
shared/ and each image gets a byte-identical, committed copy. The rules
(which source goes where, for which images) are in shared/sync.json.

Python 3.9+, standard library only. Paths in messages are relative to the
repository root.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
IMAGES = os.path.join(REPO, "images")
RULES = os.path.join(HERE, "sync.json")
SKIP = {".DS_Store"}


def rel(p):
    return os.path.relpath(p, REPO)


def fail(msg):
    sys.exit("shared/sync.py: " + msg)


def image_folders():
    """images/<name>/ with a Dockerfile, as in .github/workflows/_discover-images.yml."""
    return sorted(n for n in os.listdir(IMAGES) if os.path.isfile(os.path.join(IMAGES, n, "Dockerfile")))


def source_files(src):
    """A file, or every file below a folder (sorted, dotfiles like .DS_Store skipped):
    [(path relative to src, absolute path)]."""
    if os.path.isfile(src):
        return [("", src)]
    if not os.path.isdir(src):
        fail(f"source {rel(src)} not found (shared/sync.json)")
    out = []
    for d, dirs, files in os.walk(src):
        dirs[:] = sorted(x for x in dirs if not x.startswith("."))
        for f in sorted(files):
            if f in SKIP or f.startswith("."):
                continue
            p = os.path.join(d, f)
            out.append((os.path.relpath(p, src), p))
    if not out:
        fail(f"source folder {rel(src)} is empty")
    return out


def plan():
    """[(destination, source)] for every rule and image; checks the rules."""
    with open(RULES, encoding="utf-8") as fh:
        rules = json.load(fh)["rules"]
    known = image_folders()
    copies, seen = [], {}
    for i, r in enumerate(rules):
        where = f"shared/sync.json rule {i + 1}"
        src = os.path.normpath(os.path.join(HERE, r["from"]))
        if os.path.commonpath([src, HERE]) != HERE:
            fail(f"{where}: 'from' must stay inside shared/")
        images = known if r["images"] == "*" else r["images"]
        if not isinstance(images, list) or not images:
            fail(f"{where}: 'images' must be \"*\" or a non-empty list of image folder names")
        for name in images:
            if name not in known:
                fail(f"{where}: images/{name}/ is not an image folder (no Dockerfile)")
            base = os.path.join(IMAGES, name)
            for sub, path in source_files(src):
                dest = os.path.normpath(os.path.join(base, r["to"], sub))
                if os.path.commonpath([dest, base]) != base:
                    fail(f"{where}: 'to' must stay inside images/{name}/")
                if dest in seen and seen[dest] != path:
                    fail(f"{rel(dest)} would get two sources: {rel(seen[dest])} and {rel(path)}")
                seen[dest] = path
                copies.append((dest, path))
    return copies


def read(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any missing or differing copy; write nothing")
    args = ap.parse_args()

    copies = plan()
    stale = []
    for dest, src in copies:
        data = read(src)
        if read(dest) == data:
            continue
        stale.append((dest, src))
        if not args.check:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            print(f"updated {rel(dest)}  (from {rel(src)})")

    if not args.check:
        print(f"{len(copies)} copies, {len(stale)} updated")
        return
    if not stale:
        print(f"{len(copies)} copies up to date")
        return
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    print(f"{len(stale)} of {len(copies)} synced copies differ from their source in shared/:")
    for dest, src in stale:
        state = "missing" if read(dest) is None else "differs"
        print(f"  {rel(dest)}  ({state}; source: {rel(src)})")
        if gha:
            print(f"::error file={rel(dest)}::Synced copy of {rel(src)} ({state}). "
                  f"Edit {rel(src)}, then run: python3 shared/sync.py")
    print(
        "\nThese files are copies: edit the source under shared/, then run\n"
        "  python3 shared/sync.py\n"
        "and commit the source together with the updated copies. If the change was\n"
        "made in a copy on purpose, move it into the source first (or it is lost).\n"
        "Rules: shared/sync.json."
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
