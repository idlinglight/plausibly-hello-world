#!/usr/bin/env python3
"""Copies shared files into the image folders that use them.

usage:
  python3 shared/sync.py           write the copies (only files that differ),
                                   remove copies no rule produces any more,
                                   update shared/sync-manifest.json
  python3 shared/sync.py --check   change nothing; exit 1 on a missing,
                                   differing or stale copy or an outdated
                                   manifest (CI)

Every image folder is its own Docker build context, so a file several
images need can't be referenced from one place: it lives once under
shared/ and each image gets a byte-identical, committed copy. The rules
(which source goes where, for which images, and what else those images
must contain) are in shared/sync.json. shared/sync-manifest.json (written
here, committed) lists every copy with its source and sha256, so a copy
whose source was removed or renamed is found and removed; an unchanged one
only: a former copy edited by hand stops the sync until it is deleted or
its manifest entry is (keeping it as the image's own file).

Python 3.9+, standard library only. Paths in messages are relative to the
repository root. Exit status: 0 fine, 1 drift (--check), 2 a rule or a
required file is wrong, or a former copy was edited.
"""
import argparse
import hashlib
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")  # image folder names, as in _discover-images.yml
RULE_KEYS = {"from", "to", "images", "require"}
MANIFEST_ABOUT = ("Written by shared/sync.py, don't edit: every synced copy, its source and sha256. "
                  "Exception: to keep a former copy as an image's own file, delete its entry.")


class SyncError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


class Repo:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.shared = os.path.join(self.root, "shared")
        self.images = os.path.join(self.root, "images")
        self.rules_path = os.path.join(self.shared, "sync.json")
        self.manifest_path = os.path.join(self.shared, "sync-manifest.json")

    def rel(self, p):
        return os.path.relpath(p, self.root).replace(os.sep, "/")

    def abs(self, rel):
        return os.path.join(self.root, *rel.split("/"))

    def image_folders(self):
        """images/<name>/ with a Dockerfile, as in .github/workflows/_discover-images.yml."""
        return sorted(n for n in os.listdir(self.images) if os.path.isfile(os.path.join(self.images, n, "Dockerfile")))

    def source_files(self, src):
        """Every file below a folder (sorted; dotfiles such as .DS_Store skipped):
        [(path relative to src, absolute path)]."""
        out = []
        for d, dirs, files in os.walk(src):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            for f in sorted(files):
                if not f.startswith("."):
                    p = os.path.join(d, f)
                    out.append((os.path.relpath(p, src), p))
        if not out:
            raise SyncError(f"source folder {self.rel(src)} is empty")
        return out

    def rules(self):
        try:
            with open(self.rules_path, encoding="utf-8") as fh:
                rules = json.load(fh).get("rules")
        except (OSError, ValueError) as e:
            raise SyncError(f"shared/sync.json: {e}") from None
        if not isinstance(rules, list) or not rules:
            raise SyncError("shared/sync.json: 'rules' must be a non-empty list")
        for i, r in enumerate(rules):
            where = f"shared/sync.json rule {i + 1}"
            if not isinstance(r, dict):
                raise SyncError(f"{where}: must be an object")
            if set(r) - RULE_KEYS or not {"from", "to", "images"} <= set(r):
                raise SyncError(f"{where}: keys are from, to, images (and optionally require), got {sorted(r)}")
            for k in ("from", "to"):
                if not isinstance(r[k], str) or not r[k] or r[k].startswith("/") or "\\" in r[k]:
                    raise SyncError(f"{where}: '{k}' must be a relative path with / separators")
            imgs = r["images"]
            if imgs != "*" and not (isinstance(imgs, list) and imgs and all(isinstance(n, str) and NAME.match(n) for n in imgs)):
                raise SyncError(f"{where}: 'images' must be \"*\" or a non-empty list of image folder names")
            req = r.get("require", [])
            if not isinstance(req, list) or not all(
                    isinstance(q, dict) and set(q) == {"file", "pattern"} and all(isinstance(v, str) and v for v in q.values())
                    for q in req):
                raise SyncError(f"{where}: 'require' must be a list of {{\"file\", \"pattern\"}}")
            for q in req:
                try:
                    re.compile(q["pattern"].replace("{image}", "x"))
                except re.error as e:
                    raise SyncError(f"{where}: require pattern {q['pattern']!r}: {e}") from None
        return rules

    def plan(self):
        """{destination (repo-relative): source (repo-relative)} for every rule and
        image, after checking the rules, the paths and each rule's 'require'."""
        known = self.image_folders()
        copies = {}
        for i, r in enumerate(self.rules()):
            where = f"shared/sync.json rule {i + 1}"
            src = os.path.normpath(os.path.join(self.shared, r["from"]))
            if os.path.commonpath([src, self.shared]) != self.shared or src == self.shared:
                raise SyncError(f"{where}: 'from' must name a file or folder inside shared/")
            if src in (self.rules_path, self.manifest_path) or os.path.islink(src):
                raise SyncError(f"{where}: 'from' can't be sync.json, the manifest or a symlink")
            if os.path.isdir(src):
                if not r["to"].endswith("/"):
                    raise SyncError(f"{where}: 'from' is a folder, so 'to' must be one too (end it with /)")
                files = self.source_files(src)
            elif os.path.isfile(src):
                # a file: to "dir/" puts it in there under its own name
                files = [(os.path.basename(src) if r["to"].endswith("/") else "", src)]
            else:
                raise SyncError(f"{where}: source {self.rel(src)} not found")
            images = known if r["images"] == "*" else r["images"]
            for name in images:
                if name not in known:
                    raise SyncError(f"{where}: images/{name}/ is not an image folder (no Dockerfile)")
                base = os.path.join(self.images, name)
                for sub, path in files:
                    dest = os.path.normpath(os.path.join(base, r["to"], sub))
                    if os.path.commonpath([dest, base]) != base or dest == base:
                        raise SyncError(f"{where}: 'to' must stay inside images/{name}/")
                    if os.path.isdir(dest):
                        raise SyncError(f"{where}: {self.rel(dest)} is a folder; end 'to' with / to copy into it")
                    parent = os.path.dirname(dest)
                    while parent != base:
                        if os.path.exists(parent) and not os.path.isdir(parent):
                            raise SyncError(f"{where}: {self.rel(parent)} is a file, so {self.rel(dest)} can't be written")
                        parent = os.path.dirname(parent)
                    d, s = self.rel(dest), self.rel(path)
                    if copies.get(d, s) != s:
                        raise SyncError(f"{d} would get two sources: {copies[d]} and {s}")
                    copies[d] = s
                for q in r.get("require", []):
                    f = os.path.join(base, *q["file"].split("/"))
                    data = read(f) if os.path.isfile(f) else None
                    pattern = q["pattern"].replace("{image}", re.escape(name))
                    if data is None or not re.search(pattern, data.decode("utf-8", "replace")):
                        raise SyncError(f"{self.rel(f)}: must match {pattern!r} ({where}, 'require'; "
                                        f"{'missing' if data is None else 'no match'})")
        return dict(sorted(copies.items()))

    def load_manifest(self):
        data = read(self.manifest_path)
        if data is None:
            return None
        try:
            copies = json.loads(data.decode("utf-8"))["copies"]
            assert isinstance(copies, dict) and all(
                isinstance(v, dict) and isinstance(v.get("from"), str) and isinstance(v.get("sha256"), str)
                for v in copies.values())
            return copies
        except (ValueError, KeyError, AssertionError):
            raise SyncError("shared/sync-manifest.json is not a manifest: delete it and run python3 shared/sync.py") from None

    def manifest_text(self, plan):
        lines = ["{", f'  "about": {json.dumps(MANIFEST_ABOUT)},', '  "copies": {']
        items = list(plan.items())
        for k, (dest, src) in enumerate(items):
            entry = {"from": src, "sha256": sha256(read(self.abs(src)))}
            lines.append(f"    {json.dumps(dest)}: {json.dumps(entry)}" + ("," if k < len(items) - 1 else ""))
        lines += ["  }", "}", ""]
        return "\n".join(lines)


def run(argv, root=REPO):
    ap = argparse.ArgumentParser(prog="shared/sync.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any drift; write nothing")
    args = ap.parse_args(argv)
    repo = Repo(root)
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    try:
        plan = repo.plan()
        old = repo.load_manifest()
    except SyncError as e:
        print(f"shared/sync.py: {e}")
        if gha:
            print(f"::error::shared/sync.py: {e}")
        return 2

    problems = []  # (path, what, source or None)
    for dest, src in plan.items():
        have, want = read(repo.abs(dest)), read(repo.abs(src))
        if have != want:
            problems.append((dest, "missing" if have is None else "differs", src))
    stale, edited = [], []
    for dest, entry in (old or {}).items():
        if dest in plan:
            continue
        have = read(repo.abs(dest))
        if have is None:
            continue
        (stale if sha256(have) == entry["sha256"] else edited).append((dest, entry["from"]))
    manifest = repo.manifest_text(plan)
    manifest_ok = read(repo.manifest_path) == manifest.encode("utf-8")

    if edited:
        print("shared/sync.py: these were synced copies, their source is gone from the rules, and they have been edited since:")
        for dest, src in edited:
            print(f"  {dest}  (was a copy of {src})")
            if gha:
                print(f"::error file={dest}::Former copy of {src}, edited since. Delete it, or keep it as the image's own file by deleting its entry in shared/sync-manifest.json.")
        print("Delete each, or keep it as the image's own file by deleting its entry in shared/sync-manifest.json.")
        return 2

    if not args.check:
        for dest, what, src in problems:
            p = repo.abs(dest)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(read(repo.abs(src)))
            print(f"updated {dest}  (from {src})")
        for dest, src in stale:
            os.remove(repo.abs(dest))
            print(f"removed {dest}  (was a copy of {src}, which no rule syncs any more)")
        if not manifest_ok:
            with open(repo.manifest_path, "wb") as fh:
                fh.write(manifest.encode("utf-8"))
            print("updated shared/sync-manifest.json")
        print(f"{len(plan)} copies: {len(problems)} updated, {len(stale)} removed")
        return 0

    if not problems and not stale and manifest_ok:
        print(f"{len(plan)} copies up to date")
        return 0
    print(f"shared/sync.py --check: synced copies are out of date ({len(plan)} copies):")
    for dest, what, src in problems:
        print(f"  {dest}  ({what}; source: {src})")
        if gha:
            print(f"::error file={dest}::Synced copy of {src} ({what}). Edit {src}, then run: python3 shared/sync.py")
    for dest, src in stale:
        print(f"  {dest}  (stale: a copy of {src}, which no rule syncs any more)")
        if gha:
            print(f"::error file={dest}::Stale copy of {src} (no longer synced). Run: python3 shared/sync.py")
    if not manifest_ok:
        print("  shared/sync-manifest.json  (" + ("missing" if old is None else "out of date") + ")")
        if gha:
            print("::error file=shared/sync-manifest.json::Out of date. Run: python3 shared/sync.py")
    print(
        "\nThese files are copies: edit the source under shared/, then run\n"
        "  python3 shared/sync.py\n"
        "and commit the source, the copies and shared/sync-manifest.json together.\n"
        "If a change was made in a copy on purpose, move it into the source first\n"
        "(or it is lost). Rules: shared/sync.json."
    )
    return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
