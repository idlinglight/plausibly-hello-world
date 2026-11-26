#!/usr/bin/env python3
"""Checks the Wikipedia titles in tools/states.json against the live German
Wikipedia and Wikidata (wiki: each state's article; capital_wiki: the
capital city's article, for all 16), or proposes titles from Wikidata.

usage:
  python3 -I tools/wiki_titles.py <ne_10m_admin_1_states_provinces.geojson> [--verbose]
  python3 -I tools/wiki_titles.py <ne_10m_admin_1_states_provinces.geojson> --suggest

Run by hand, with network access; never by the build or CI (build_map.py
and tools/data.test.mjs check presence and shape, offline). The generic
part is shared/map-quiz/tools/wikicheck.py. Expected items: a state's
article belongs to Natural Earth's wikidataid of its admin-1 feature
(matched by iso, as build_map.py matches it; the pinned file); a capital's
article belongs to an item Wikidata records as a current capital of that
state (P36 or P1376), or, where it is the state's own article (Berlin,
Hamburg: one article for city and state), to the state's item. Exits 1 if any title fails. Details:
tools/README.md, "Wikipedia titles".
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
sys.path.insert(1, HERE)
import mapgen  # noqa: E402  (shared core; python3 -I keeps the script's folder off sys.path)
import wikicheck  # noqa: E402
import build_map  # noqa: E402  (this image's adapter: the pin, the data's path)


def ne_items(path):
    raw = mapgen.read_pinned(path, build_map.ADM1_SHA256, build_map.ADM1_BYTES,
                             build_map.NE_BASE + build_map.ADM1_FILE)
    items = {}
    for f in json.loads(raw.decode("utf-8"))["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "DEU":
            items.setdefault(p["iso_3166_2"], set()).add(p.get("wikidataid"))
    return items


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("adm1", help=f"path to {build_map.ADM1_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("--suggest", action="store_true", help="propose titles from Wikidata instead of checking")
    ap.add_argument("--verbose", action="store_true", help="list every title, not only failures")
    args = ap.parse_args()
    try:
        with open(build_map.STATES_JSON, encoding="utf-8") as fh:
            st = json.load(fh)["states"]  # not build_map's loader: --suggest works without titles
        items = ne_items(args.adm1)
    except (mapgen.BuildError, ValueError) as e:
        sys.exit(f"wiki_titles: {e}")
    rows = []
    for s in st:
        qs = items.get(s["iso"], set())
        if len(qs) != 1 or None in qs:
            sys.exit(f"wiki_titles: {s['iso']}: Natural Earth has {sorted(map(str, qs)) or 'no'} wikidataid")
        q = next(iter(qs))
        rows.append({"key": f"{s['id']} wiki", "item": q, "title": s.get("wiki"), "stored": s.get("wiki")})
        if s.get("capital_wiki") is not None and s["capital_wiki"] == s.get("wiki"):
            # the city state's own article: the same item as the state's
            rows.append({"key": f"{s['id']} capital_wiki", "item": q, "title": s["capital_wiki"],
                         "stored": s["capital_wiki"]})
        else:
            rows.append({"key": f"{s['id']} capital_wiki", "capital_of": q, "name": s["capital"],
                         "title": s.get("capital_wiki"), "stored": s.get("capital_wiki")})
    try:
        if args.suggest:
            wikicheck.suggest("de", rows)
            return
        failed = wikicheck.check("de", rows, verbose=args.verbose)
    except (OSError, RuntimeError, ValueError) as e:
        sys.exit(f"wiki_titles: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
