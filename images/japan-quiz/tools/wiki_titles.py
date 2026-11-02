#!/usr/bin/env python3
"""Checks the Wikipedia titles in tools/prefectures.json against the live
English Wikipedia and Wikidata (wiki: each island's, region's and
prefecture's article; capital_wiki: the capital city's article, for the 18
prefectures the capitals round asks), or proposes titles from Wikidata.

usage:
  python3 -I tools/wiki_titles.py <ne_10m_admin_1_states_provinces.geojson> [--verbose]
  python3 -I tools/wiki_titles.py <ne_10m_admin_1_states_provinces.geojson> --suggest

Run by hand, with network access; never by the build or CI (build_map.py
and tools/data.test.mjs check presence and shape, offline). The generic
part is shared/map-quiz/tools/wikicheck.py. Expected items: a prefecture's
article belongs to Natural Earth's wikidataid of its admin-1 feature
(matched by iso, as build_map.py matches it; the pinned file); a capital's
article belongs to an item Wikidata records as a current capital of that
prefecture (P36 or P1376); an island's or region's article belongs to the
hand-checked item in AREA_ITEMS. Exits 1 if any title fails. Details:
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

# The Wikidata items of the islands' and regions' articles, checked by hand
# (tools/README.md, "Wikipedia titles"). English Wikipedia has no articles
# of their own for the Hokkaidō, Shikoku and Kyūshū regions ("Kyushu
# region" etc. redirect to the island's article, no section): those link the
# island's article and item.
AREA_ITEMS = {
    "isl-honshu": "Q13989",     # Honshu
    "isl-hokkaido": "Q35581",   # Hokkaido (the island; the article covers the prefecture too)
    "isl-kyushu": "Q13987",     # Kyushu
    "isl-shikoku": "Q13991",    # Shikoku
    "reg-hokkaido": "Q35581",   # Hokkaido
    "reg-tohoku": "Q129465",    # Tōhoku region
    "reg-kanto": "Q132480",     # Kantō region
    "reg-chubu": "Q134638",     # Chūbu region
    "reg-kansai": "Q164256",    # Kansai region (Kinki region redirects there)
    "reg-chugoku": "Q127864",   # Chūgoku region
    "reg-shikoku": "Q13991",    # Shikoku
    "reg-kyushu": "Q13987",     # Kyushu
}

# The item whose capital a prefecture's capital is checked against, where it
# isn't Natural Earth's: for JP-01 Natural Earth gives Q35581, the island,
# whose English article "Hokkaido" covers island and prefecture (Wikidata's
# prefecture item Q1037393 sitelinks the redirect "Hokkaido Prefecture");
# Sapporo is the capital (P1376) of the prefecture item.
CAPITAL_OF = {"hokkaido": "Q1037393"}


def ne_items(path):
    raw = mapgen.read_pinned(path, build_map.ADM1_SHA256, build_map.ADM1_BYTES,
                             build_map.NE_BASE + build_map.ADM1_FILE)
    items = {}
    for f in json.loads(raw.decode("utf-8"))["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "JPN":
            items.setdefault(p["iso_3166_2"], set()).add(p.get("wikidataid"))
    return items


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("adm1", help=f"path to {build_map.ADM1_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("--suggest", action="store_true", help="propose titles from Wikidata instead of checking")
    ap.add_argument("--verbose", action="store_true", help="list every title, not only failures")
    args = ap.parse_args()
    try:
        with open(build_map.PREFECTURES_JSON, encoding="utf-8") as fh:
            data = json.load(fh)  # not build_map's loader: --suggest works without titles
        islands, regions, pl = data["islands"], data["regions"], data["prefectures"]
        items = ne_items(args.adm1)
    except (mapgen.BuildError, ValueError) as e:
        sys.exit(f"wiki_titles: {e}")
    rows = []
    for e in islands + regions:
        if e["id"] not in AREA_ITEMS:
            sys.exit(f"wiki_titles: {e['id']}: no item in AREA_ITEMS")
        rows.append({"key": f"{e['id']} wiki", "item": AREA_ITEMS[e["id"]], "title": e.get("wiki"),
                     "stored": e.get("wiki")})
    for p in pl:
        qs = items.get(p["iso"], set())
        if len(qs) != 1 or None in qs:
            sys.exit(f"wiki_titles: {p['iso']}: Natural Earth has {sorted(map(str, qs)) or 'no'} wikidataid")
        q = next(iter(qs))
        rows.append({"key": f"{p['id']} wiki", "item": q, "title": p.get("wiki"), "stored": p.get("wiki")})
        if p["capital_differs"]:
            rows.append({"key": f"{p['id']} capital_wiki", "capital_of": CAPITAL_OF.get(p["id"], q), "name": p["capital"],
                         "title": p.get("capital_wiki"), "stored": p.get("capital_wiki")})
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
