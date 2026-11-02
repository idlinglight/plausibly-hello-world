"""Inputs and outputs: sha256-pinned reads, writing or checking the generated
files, the size report, and the shape of Wikipedia titles in the data."""
import gzip
import hashlib
import os
import unicodedata


class BuildError(Exception):
    """A check failed; the message says which. Adapters print it and exit 1."""


def read_pinned(path, sha256, size, url=None):
    """The file's bytes, if it has exactly this sha256 and size (else BuildError)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != size or digest != sha256:
        hint = f"\n  (download: {url})" if url else ""
        raise BuildError(f"{path}: sha256 {digest} / {len(raw)} bytes, expected {sha256} / {size}{hint}")
    return raw


def wiki_title_error(title):
    """Why a Wikipedia article title in an image's data is malformed, or None.
    Titles are stored as the article is named: spaces (no underscores), no
    section (#), query (?) or link syntax (| [ ] { } < >), no leading,
    trailing or double space, NFC. Whether the article exists and is the
    right one is shared/map-quiz/tools/wikicheck.py's job (by hand, online)."""
    if not isinstance(title, str) or not title:
        return "empty or not a string"
    if title != title.strip() or "  " in title:
        return "leading, trailing or double space"
    bad = sorted({c for c in title if c in "_#?|[]{}<>"})
    if bad:
        return "contains " + " ".join(bad)
    if unicodedata.normalize("NFC", title) != title:
        return "not NFC"
    return None


def emit(files, out_dir, check, report=None):
    """files: {name: text}. Writes them to out_dir as UTF-8 (or, with check,
    compares instead and writes nothing), prints sizes (raw, gzip -1 as nginx
    serves it, gzip -9) and the report. Returns the exit status: 1 if check
    found a file out of date."""
    stale = []
    for name, text in files.items():
        data = text.encode("utf-8")
        dest = os.path.join(out_dir, name)
        if check:
            try:
                with open(dest, "rb") as fh:
                    same = fh.read() == data
            except FileNotFoundError:
                same = False
            if not same:
                stale.append(name)
        else:
            with open(dest, "wb") as fh:
                fh.write(data)
        print(f"{name}: {len(data)} B, gzip -1 {len(gzip.compress(data, 1, mtime=0))} B, "
              f"gzip -9 {len(gzip.compress(data, 9, mtime=0))} B")
    for key, val in (report or {}).items():
        print(f"  {key}: {val}")
    if check:
        if stale:
            print("out of date: " + ", ".join(stale))
            return 1
        print("up to date")
    return 0
