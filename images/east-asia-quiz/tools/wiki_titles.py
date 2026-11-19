#!/usr/bin/env python3
"""Checks the Wikipedia titles in tools/countries.json against the live
English Wikipedia and Wikidata (capital_wiki: the capital city's article,
linked by the capitals round), or proposes titles from Wikidata.

usage:
  python3 -I tools/wiki_titles.py <ne_50m_admin_0_countries.geojson> [--verbose]
  python3 -I tools/wiki_titles.py <ne_50m_admin_0_countries.geojson> --suggest

Run by hand, with network access; never by the build or CI (build_map.py
and tools/data.test.mjs check presence and shape, offline). The generic
part is shared/map-quiz/tools/wikicheck.py. Expected items: a capital's
article belongs to an item Wikidata records as a current capital (P36 or
P1376) of the country, which is Natural Earth's WIKIDATAID of its ADM0_A3
feature (the pinned file build_map.py reads). Exits 1 if any title fails.
Details: tools/README.md, "Wikipedia titles".
"""
import sys

if sys.version_info < (3, 10):
    sys.exit("wiki_titles: needs Python 3.10 or newer")

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
sys.path.insert(1, HERE)
import mapgen  # noqa: E402  (shared core; python3 -I keeps the script's folder off sys.path)
import wikicheck  # noqa: E402
import build_map  # noqa: E402  (this image's adapter: the pin, the data's path)


def ne_items(path):
    raw = mapgen.read_pinned(path, build_map.NE_SHA256, build_map.NE_BYTES, build_map.NE_URL)
    items = {}
    for f in json.loads(raw.decode("utf-8"))["features"]:
        p = f["properties"]
        items.setdefault(p["ADM0_A3"], set()).add(p["WIKIDATAID"])
    return items


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("ne", help=f"path to {build_map.NE_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("--suggest", action="store_true", help="propose titles from Wikidata instead of checking")
    ap.add_argument("--verbose", action="store_true", help="list every title, not only failures")
    args = ap.parse_args()
    try:
        with open(build_map.COUNTRIES_JSON, encoding="utf-8") as fh:
            countries = json.load(fh)["countries"]  # not build_map's loader: --suggest works without titles
        items = ne_items(args.ne)
    except (mapgen.BuildError, ValueError) as e:
        sys.exit(f"wiki_titles: {e}")
    rows = []
    for c in countries:
        qs = items.get(c["id"], set())
        if len(qs) != 1:
            sys.exit(f"wiki_titles: {c['id']}: Natural Earth has {sorted(qs) or 'no'} WIKIDATAID")
        rows.append({"key": f"{c['id']} capital_wiki", "capital_of": qs.pop(), "name": c["capital"],
                     "title": c.get("capital_wiki"), "stored": c.get("capital_wiki")})
    try:
        if args.suggest:
            wikicheck.suggest("en", rows)
            return
        failed = wikicheck.check("en", rows, verbose=args.verbose)
    except (OSError, RuntimeError, ValueError) as e:
        sys.exit(f"wiki_titles: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
