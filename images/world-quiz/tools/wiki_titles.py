#!/usr/bin/env python3
"""Checks the Wikipedia titles in tools/countries.json against the live
English Wikipedia and Wikidata (wiki: the country's article, capital_wiki:
its capital city's), or proposes titles from Wikidata.

usage:
  python3 -I tools/wiki_titles.py <ne_50m_admin_0_countries.geojson> [--verbose]
  python3 -I tools/wiki_titles.py <ne_50m_admin_0_countries.geojson> --suggest

Run by hand, with network access; never by the build or CI (build_map.py
and tools/data.test.mjs check presence and shape, offline). The generic
part is shared/map-quiz/tools/wikicheck.py. Expected items: a country's
article belongs to Natural Earth's WIKIDATAID of its ADM0_A3 feature (the
pinned file build_map.py reads); a capital's article belongs to an item
Wikidata records as a current capital of that country (P36 or P1376), or
to the item CAPITAL_ITEMS names. Exits 1 if any title fails. Details:
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

# Capitals Wikidata doesn't record as a current capital of the country
# (tools/README.md, "Wikipedia titles"): id -> the article's expected item.
CAPITAL_ITEMS = {
    # Managua: Wikidata's capital of Nicaragua (P36) is the city item
    # Q131546626, which has no English article; the article "Managua" belongs
    # to the municipality, Q3274 ("capital and largest city of Nicaragua").
    "NIC": "Q3274",
}


def first_city(capital):
    """The city a capital field names first ('Sucre / La Paz' -> 'Sucre')."""
    return capital.split(" / ")[0]


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
        q = qs.pop()
        rows.append({"key": f"{c['id']} wiki", "item": q, "title": c.get("wiki"), "stored": c.get("wiki")})
        rows.append({"key": f"{c['id']} capital_wiki", "capital_of": q, "name": first_city(c["capital"]),
                     "capital_item": CAPITAL_ITEMS.get(c["id"]), "title": c.get("capital_wiki"),
                     "stored": c.get("capital_wiki")})
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
