#!/usr/bin/env python3
"""Builds site/map.svg, site/japan.js and site/relief.png for images/japan-quiz.

usage:
  python3 -I tools/build_map.py <ne_10m_admin_1_states_provinces.geojson> \\
      <ne_50m_admin_0_countries.geojson> <ne_10m_lakes.geojson> \\
      <etopo_2022_30s_japan.asc> [--out DIR] [--check]

Offline, stdlib only (Python 3.9+), deterministic: the same inputs give
byte-identical outputs. --check builds in memory and exits 1 if the files in
the output folder differ (nothing is written). Details: tools/README.md.

This file is japan-quiz's adapter: Natural Earth, the fix-ups, the split
into map pieces, the window and the quiz data. The geometry (projection,
clipping, shared borders, simplification, lines, SVG) is the shared
map-quiz core, shared/map-quiz/tools/mapgen.

Pipeline:
  1. tools/prefectures.json (47 prefectures, 4 islands, 8 regions; names,
     kanji, kana): checked, every kana reading against its Hepburn name.
  2. Natural Earth admin-1 states/provinces, 10m, v5.1.2 (sha256-verified):
     the 47 JPN features, matched by ISO 3166-2 code, NE's name checked.
  3. Fix-ups (MOVES, DROPS): the Amami islands (filed under Okinawa) and
     Nagashima + Shishijima (under Kumamoto) move to Kagoshima; Tōkyō's
     Ogasawara islands are dropped (the Bonin islands about 1,000 km south
     of Tokyo, the Iwo islands about 1,250 km, Minami-Torishima about
     1,850 km south-east); specks below SPECK_KM2 too. Point checks
     (VIEW_CHECKS) assert the result.
  4. Pieces: each prefecture's parts on its main island (the connected
     landmass of Honshū, Hokkaidō, Kyūshū or Shikoku; plus ATTACHED: spits
     Natural Earth draws apart) form its main piece, id = the prefecture's
     id; all other parts one <id>-isles piece. Okinawa is one piece.
  5. Context land: Natural Earth admin-0 countries, 50m, v5.1.2 (the file
     europe-quiz pins), without Japan (drawn from admin-1) and without the
     Kuril islands (KURILS: the Southern Kurils are neither clickable nor
     Japanese-administered, the rest of the chain would start mid-sea).
     Lakes: Lake Biwa from Natural Earth's 10m lakes (LAKES; the only
     Japanese lake in that file), checked to lie inside Shiga.
  6. Projection: Lambert azimuthal equal-area centred on 35°N 135°E (GRS80):
     135°E is Japan's standard meridian and runs through the middle of the
     window; equal-area keeps prefecture sizes comparable. The window is
     the bounding box of every piece plus MARGIN, so Okinawa sits at its
     real position; EXTENT more context is drawn around it and faded.
  7. (mapgen) Clip to the extent, snap to a 1/GRID grid, merge the parts
     of a piece, build shared arcs (neighbours use identical vertices);
     context-only arcs are simplified, piece arcs keep every vertex; every
     piece keeps all its islands (keep_islands).
  8. Overlays above the pieces, never hit: lakes (water, see-through: a
     click on Lake Biwa picks Shiga beneath), then lines along the piece
     edges (mapgen.boundary_lines), each edge in one overlay only:
     coast-main (the outline of the four main islands), coast-isles (the
     outline of every other piece), borders-prefectures (land borders
     between prefectures, without the region borders) and borders-regions
     (land borders between regions). The engine shows per round the ones
     it lists.
  9. Shaded relief (RELIEF_*): NOAA ETOPO 2022, a 30" ERDDAP subset
     (sha256-verified), hill-shaded on a RELIEF_PPU pixel grid over the
     window (each pixel centre back to lon/lat by the inverse projection,
     elevation bilinear), light from the top left, shadow + steepness
     darken, slopes facing the light lighten; only on the pieces (a
     coverage mask from their drawn rings, so it ends at the coast):
     site/relief.png, a palette PNG (transparent, black or white with
     alpha), drawn as <image id="relief"> first in <g id="overlays">.
 10. Write map.svg (one <path> per piece in <g id="pieces">, the relief,
     the lakes and the lines in <g id="overlays">), japan.js (MAP, PIECES,
     ISLANDS, REGIONS, PREFECTURES: the answers of the rounds with their
     pieces and texts) and relief.png.
"""
import argparse
import array
import json
import math
import os
import re
import struct
import sys
import unicodedata
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
import mapgen  # noqa: E402  (shared core; python3 -I keeps the script's folder off sys.path)

# ------------------------------------------------------------------ input
NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"
ADM1_FILE = "ne_10m_admin_1_states_provinces.geojson"
ADM1_SHA256 = "22d0e3ad85eb3e27f17cabf8ba2d50e554fbc27a87796ff891d958185da62fb5"
ADM1_BYTES = 40726851
ADM0_FILE = "ne_50m_admin_0_countries.geojson"
ADM0_SHA256 = "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"
ADM0_BYTES = 3083490
LAKES_FILE = "ne_10m_lakes.geojson"
LAKES_SHA256 = "2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9"
LAKES_BYTES = 5043554
# NOAA NCEI ETOPO 2022 (15" global relief), every 2nd cell (30") of
# 24.0-45.75°N, 122.75-146.0°E as ESRI ASCII from CoastWatch's ERDDAP
# (byte-identical on repeated downloads; tools/README.md).
ETOPO_FILE = "etopo_2022_30s_japan.asc"
ETOPO_URL = ("https://coastwatch.pfeg.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.esriAscii?"
             "z%5B(24.0):2:(45.75)%5D%5B(122.75):2:(146.0)%5D")
ETOPO_SHA256 = "f94b68ad855dce74e481030a2f73264534bfbfd89f82743964bf7b6c7735ff3c"
ETOPO_BYTES = 59353552
ETOPO_GRID = (2791, 2611)  # columns, rows

PREFECTURES_JSON = os.path.join(HERE, "prefectures.json")

# ------------------------------------------------------------------ output
WIDTH = 1000.0      # viewBox width in map units (1 unit ≈ 2.2 km)
GRID = 10           # vertices snap to 1/GRID unit (0.1)
MARGIN = 0.03       # window margin around all pieces, fraction of their width
EXTENT = (0.5, 0.35)  # context drawn around the window: fraction of its width / height per side
MIN_ISLAND = 0.3    # context land: drop islands below this area (units^2) unless they touch another ring
CONTEXT_TOL = 0.2   # Douglas-Peucker tolerance (units) for arcs only context land uses …
FAR_TOL = 1.5       # … and for their runs of points outside the window (+ FAR_GAP): only seen small
FAR_MIN_ISLAND = 4  # context islands entirely outside the window: dropped below this (units^2)
FAR_GAP = 20        # units around the window that still count as near
SPECK_KM2 = 0.5     # parts of a prefecture below this area are dropped (rocks and islets, a few px at the closest zoom)

LAT0, LON0 = 35.0, 135.0  # projection centre

# Shaded relief (site/relief.png). 2.5 px per unit (about 0.9 km, the 30"
# cells) keeps it sharp up to the closest zoom (6 px/unit) at ~330 KB.
RELIEF_PPU = 2.5           # pixels per map unit (2500 px across the window)
RELIEF_SUB = 4             # coverage samples per pixel row (columns: exact)
RELIEF_AZ, RELIEF_ALT = 315.0, 45.0  # light: from the top left (azimuth from up, clockwise), 45° high
RELIEF_Z = 5.0             # vertical exaggeration
RELIEF_W_SHADOW = 0.8      # darkness: weight of facing away from the light …
RELIEF_W_STEEP = 0.9       # … and of steepness (so sunlit slopes still read)
RELIEF_DARK = 0.55         # strongest shadow: black at this alpha (multiplies by 0.45)
RELIEF_LIGHT = 0.3         # strongest highlight: white at this alpha
RELIEF_LEVELS = 32         # alpha steps from 0 to RELIEF_DARK (palette size, PNG size)

HEAD = ("Generated by tools/build_map.py from tools/prefectures.json, Natural Earth v5.1.2 (public domain) "
        "and NOAA ETOPO 2022 (relief). Don't edit: change the inputs and regenerate.")

# ------------------------------------------------------------------ fix-ups
# Parts that move to another prefecture: (from, to, label, rule, expected
# count). A rule is ("point", lon, lat): the part containing it, or ("box",
# lon0, lat0, lon1, lat1): every part whose bounding box lies inside.
MOVES = [
    ("JP-47", "JP-46", "Amami islands", ("box", 128.3, 27.0, 131.0, 29.0), 6),  # Iheya, Iōtorishima stay
    ("JP-43", "JP-46", "Nagashima", ("point", 130.15, 32.17), 1),
    ("JP-43", "JP-46", "Shishijima", ("point", 130.23, 32.28), 1),
]
# Parts that are dropped: (prefecture, label, rule, expected count).
DROPS = [
    ("JP-13", "Ogasawara islands (incl. Iwo islands, Minami-Torishima)", ("box", 135.0, 20.0, 160.0, 29.0), 12),
]
# Parts that belong to the main piece though Natural Earth draws them apart
# from the main island (sandbar spits): (prefecture, label, point inside).
ATTACHED = [
    ("JP-01", "Notsuke spit", (145.336, 43.579)),
    ("JP-01", "Saroma lagoon spit", (143.89, 44.159)),
]
# Owner after the fix-ups: (lon, lat, prefecture id, piece id, label).
VIEW_CHECKS = [
    (129.49, 28.37, "kagoshima", "kagoshima-isles", "Amami Ōshima"),
    (129.97, 28.32, "kagoshima", "kagoshima-isles", "Kikaijima"),
    (128.95, 27.78, "kagoshima", "kagoshima-isles", "Tokunoshima"),
    (128.60, 27.38, "kagoshima", "kagoshima-isles", "Okinoerabujima"),
    (128.42, 27.04, "kagoshima", "kagoshima-isles", "Yoronjima"),
    (130.15, 32.17, "kagoshima", "kagoshima-isles", "Nagashima"),
    (130.23, 32.28, "kagoshima", "kagoshima-isles", "Shishijima"),
    (130.51, 30.35, "kagoshima", "kagoshima-isles", "Yakushima"),
    (127.97, 27.05, "okinawa", "okinawa", "Iheyajima"),
    (128.236, 27.861, "okinawa", "okinawa", "Iōtorishima"),
    (127.70, 26.21, "okinawa", "okinawa", "Naha (Okinawa Island)"),
    (122.98, 24.46, "okinawa", "okinawa", "Yonaguni"),
    (131.30, 25.94, "okinawa", "okinawa", "Kita-Daitōjima"),
    (130.06, 32.36, "kumamoto", "kumamoto-isles", "Amakusa-Shimoshima"),
    (130.43, 32.585, "kumamoto", "kumamoto-isles", "Ōyanojima"),
    (145.336, 43.579, "hokkaido", "hokkaido", "Notsuke spit"),
    (141.23, 45.18, "hokkaido", "hokkaido-isles", "Rishiri"),
    (139.40, 34.74, "tokyo", "tokyo-isles", "Izu Ōshima"),
    (140.31, 30.484, "tokyo", "tokyo-isles", "Torishima"),
    (139.70, 35.69, "tokyo", "tokyo", "Shinjuku"),
    (134.86, 34.39, "hyogo", "hyogo-isles", "Awajishima"),
    (138.38, 38.04, "niigata", "niigata-isles", "Sado"),
    (129.33, 34.42, "nagasaki", "nagasaki-isles", "Tsushima"),
]
# Context land: RUS parts whose bounding box lies inside this lon/lat box
# are the Kuril islands and are dropped (expected count at 50m).
KURILS = ((145.0, 43.0, 157.0, 51.0), 14)
KURIL_CHECKS = [  # (lon, lat, label, still context land afterwards?)
    (145.85, 44.05, "Kunashiri", False),
    (147.90, 45.00, "Iturup", False),
    (146.75, 43.82, "Shikotan", False),
    (155.70, 50.40, "Paramushir", False),
    (142.80, 47.00, "Sakhalin", True),
    (159.00, 55.00, "Kamchatka", True),
]
# Lakes drawn as the "lakes" overlay: (Natural Earth ne_id, name, the
# prefecture whose main piece must contain it entirely).
LAKES = [(1159115641, "Biwa Ko", "shiga")]
PREFILTER = ((95, 180), (0, 70))  # lon/lat box: context polygons entirely outside are skipped early

ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
# Overlay ids map.svg gets (build() checks it writes no other), and the
# ids of map.svg's own elements and the engine's layers: no prefecture,
# island or region id may be one of them. RELIEF_ID is the <image> this
# script inserts first in <g id="overlays">; the others are mapgen's paths.
RELIEF_ID = "relief"
OVERLAY_IDS = (RELIEF_ID, "lakes", "coast-main", "coast-isles", "borders-prefectures", "borders-regions",
               "borders-islands")
RESERVED = {"land", "overlays", "regions", "markers", "pieces", *OVERLAY_IDS}


def fail(msg):
    raise mapgen.BuildError(msg)


# ------------------------------------------------------------------ kana check
# Long vowels: a syllable ending in the key vowel, followed by the bare
# vowel kana, is written with a macron (ei and ii stay as they are).
_LONG = {"o": {"o": "ō", "u": "ō"}, "u": {"u": "ū"}, "a": {"a": "ā"}, "e": {"e": "ē"}}
# Readings where お + う meet across a morpheme boundary and stay "ou"
# (e.g. いのうえ, Inoue). None of today's names needs one.
OU_SPLIT = set()
_KANA = {}
for row in ("あa いi うu えe おo", "かka きki くku けke こko", "さsa しshi すsu せse そso", "たta ちchi つtsu てte とto",
            "なna にni ぬnu ねne のno", "はha ひhi ふfu へhe ほho", "まma みmi むmu めme もmo", "やya ゆyu よyo",
            "らra りri るru れre ろro", "わwa をo", "がga ぎgi ぐgu げge ごgo", "ざza じji ずzu ぜze ぞzo",
            "だda ぢji づzu でde どdo", "ばba びbi ぶbu べbe ぼbo", "ぱpa ぴpi ぷpu ぺpe ぽpo"):
    for cell in row.split():
        _KANA[cell[0]] = cell[1:]
for base, cons in (("き", "ky"), ("し", "sh"), ("ち", "ch"), ("に", "ny"), ("ひ", "hy"), ("み", "my"), ("り", "ry"),
                   ("ぎ", "gy"), ("じ", "j"), ("び", "by"), ("ぴ", "py")):
    for small, v in (("ゃ", "a"), ("ゅ", "u"), ("ょ", "o")):
        _KANA[base + small] = cons + v


def hepburn(kana):
    """Hiragana -> modified Hepburn with macrons (ō for おう/おお, ū for うう),
    as the names in prefectures.json are written. ValueError on other text."""
    syl = []
    i = 0
    while i < len(kana):
        if kana[i:i + 2] in _KANA:
            syl.append(_KANA[kana[i:i + 2]])
            i += 2
        elif kana[i] in _KANA or kana[i] in "っん":
            syl.append(_KANA.get(kana[i], kana[i]))
            i += 1
        else:
            raise ValueError(f"not hiragana: {kana[i]!r} in {kana!r}")
    out = []
    k = 0
    while k < len(syl):
        s = syl[k]
        nxt = syl[k + 1] if k + 1 < len(syl) else ""
        if s == "っ":
            if not nxt or nxt[0] in "aiueon":
                raise ValueError(f"っ before {nxt!r} in {kana!r}")
            out.append("t" if nxt.startswith("ch") else nxt[0])
        elif s == "ん":
            out.append("n'" if nxt and nxt[0] in "aiueoy" else "n")
        elif s[-1:] in _LONG and nxt in _LONG[s[-1]] and not (nxt == "u" and s[-1] == "o" and kana in OU_SPLIT):
            # a syllable's vowel and the bare vowel kana after it: one long
            # vowel (おお before おう: おおう is ō + u, not o + ō)
            out.append(s[:-1] + _LONG[s[-1]][nxt])
            k += 1
        else:
            out.append(s)
        k += 1
    return "".join(out)


# ------------------------------------------------------------------ steps
def load_data():
    with open(PREFECTURES_JSON, encoding="utf-8") as fh:
        d = json.load(fh)
    islands, regions, pl = d["islands"], d["regions"], d["prefectures"]
    if len(islands) != 4 or len(regions) != 8 or len(pl) != 47:
        fail(f"prefectures.json: expected 4 islands, 8 regions, 47 prefectures, "
             f"got {len(islands)}, {len(regions)}, {len(pl)}")
    texts = [(e, "name", "kana") for e in islands + regions + pl] + [(p, "capital", "capital_kana") for p in pl]
    for e, nk, kk in texts:
        for key in (nk, kk, "kanji" if nk == "name" else "capital_kanji"):
            v = e.get(key)
            if not isinstance(v, str) or not v or v != v.strip() or unicodedata.normalize("NFC", v) != v:
                fail(f"prefectures.json: {e.get('id')}: empty, padded or not NFC: {key}")
        try:
            got = hepburn(e[kk])
        except ValueError as err:
            fail(f"prefectures.json: {e['id']}: {kk}: {err}")
        if got != e[nk].lower():
            fail(f"prefectures.json: {e['id']}: {kk} {e[kk]} reads {got!r}, but {nk} is {e[nk]!r}")
    ids = [e["id"] for e in islands + regions + pl]
    for i in ids:
        if not ID.match(i) or i in RESERVED or i.startswith("fade") or i.endswith("-isles"):
            fail(f"prefectures.json: bad id {i!r}")
    if len(set(ids)) != len(ids):
        fail("prefectures.json: duplicate ids")
    for group in (islands, regions, pl):
        for key in ("name", "kanji"):
            vals = [e[key] for e in group]
            if len(set(vals)) != len(vals):
                fail(f"prefectures.json: duplicate {key}")
    caps = [p["capital"] for p in pl]
    if len(set(caps)) != len(caps):
        fail("prefectures.json: duplicate capital")
    isl_ids, reg_ids = {e["id"] for e in islands}, {e["id"] for e in regions}
    for k, p in enumerate(pl):
        if p["iso"] != f"JP-{k + 1:02d}":
            fail(f"prefectures.json: {p['id']}: iso {p['iso']}, expected JP-{k + 1:02d} (JIS order)")
        if not isinstance(p["capital_differs"], bool) or (p["capital"] != p["name"] and not p["capital_differs"]):
            fail(f"prefectures.json: {p['id']}: capital_differs must be true where capital and name differ")
        if p["region"] not in reg_ids or (p["island"] is not None and p["island"] not in isl_ids):
            fail(f"prefectures.json: {p['id']}: unknown region or island")
    if {p["region"] for p in pl} != reg_ids or {p["island"] for p in pl} - {None} != isl_ids:
        fail("prefectures.json: a region or island without prefectures")
    return islands, regions, pl


def load_adm1(path, pl):
    raw = mapgen.read_pinned(path, ADM1_SHA256, ADM1_BYTES, NE_BASE + ADM1_FILE)
    feats = {}
    for f in json.loads(raw.decode("utf-8"))["features"]:
        pr = f["properties"]
        if pr.get("adm0_a3") == "JPN":
            if pr["iso_3166_2"] in feats:
                fail(f"{ADM1_FILE}: two JPN features {pr['iso_3166_2']}")
            feats[pr["iso_3166_2"]] = f
    if sorted(feats) != [p["iso"] for p in pl]:
        fail(f"{ADM1_FILE}: JPN features {sorted(feats)} don't match prefectures.json")
    geo = {}
    for p in pl:
        f = feats[p["iso"]]
        if f["properties"]["name"] != p["ne_name"]:
            fail(f"{p['iso']}: Natural Earth name {f['properties']['name']!r}, prefectures.json ne_name {p['ne_name']!r}")
        geo[p["iso"]] = mapgen.polys_of(f["geometry"])
    return geo


def select(polys, rule):
    if rule[0] == "point":
        return [p for p in polys if mapgen.in_polygon(rule[1], rule[2], p)]
    lo0, la0, lo1, la1 = rule[1:]
    out = []
    for p in polys:
        x0, y0, x1, y1 = mapgen.bbox(p[0])
        if lo0 <= x0 and x1 <= lo1 and la0 <= y0 and y1 <= la1:
            out.append(p)
    return out


def apply_fixups(geo, project, notes):
    for src, dst, label, rule, n in MOVES:
        hit = select(geo[src], rule)
        if len(hit) != n:
            fail(f"move {label}: {len(hit)} parts of {src} match, expected {n}")
        geo[src] = [p for p in geo[src] if not any(p is h for h in hit)]
        geo[dst].extend(hit)
        notes.append(f"{label}: {n} part{'s' if n > 1 else ''} {src} -> {dst}")
    for iso, label, rule, n in DROPS:
        hit = select(geo[iso], rule)
        if len(hit) != n:
            fail(f"drop {label}: {len(hit)} parts of {iso} match, expected {n}")
        geo[iso] = [p for p in geo[iso] if not any(p is h for h in hit)]
        notes.append(f"{label}: {n} parts of {iso} dropped")
    specks = []
    for iso in geo:
        kept = []
        for p in geo[iso]:
            a = km2(p, project)
            if a >= SPECK_KM2:
                kept.append(p)
            else:
                specks.append((iso, a))
        geo[iso] = kept
    notes.append(f"{len(specks)} specks below {SPECK_KM2:g} km² dropped: " +
                 ", ".join(f"{iso} {a:.2f}" for iso, a in sorted(specks)))


def km2(poly, project):
    """Area in km² (the projection is equal-area); holes subtracted."""
    rings = [[project(c[0], c[1]) for c in mapgen.open_ring(r)] for r in poly]
    return (abs(mapgen.area2(rings[0])) - sum(abs(mapgen.area2(h)) for h in rings[1:])) / 2e6


def split_pieces(geo, islands, pl, notes):
    """{piece id: polygons} in JIS order (main piece, then -isles), and
    {piece id: prefecture id}. Main island = the connected landmass (parts
    sharing a border edge: two consecutive vertices, in either direction;
    a single shared vertex doesn't join) holding the island's prefectures'
    largest parts."""
    parts = [(p["iso"], poly) for p in pl for poly in geo[p["iso"]]]
    parent = list(range(len(parts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    seen = {}  # undirected edge -> first part using it
    for k, (_, poly) in enumerate(parts):
        ring = mapgen.open_ring(poly[0])
        for i in range(len(ring)):
            a, b = tuple(ring[i - 1][:2]), tuple(ring[i][:2])
            if a == b:
                continue
            j = seen.setdefault((min(a, b), max(a, b)), k)
            if find(j) != find(k):
                parent[find(k)] = find(j)
    main_comp = {}  # island id -> component root
    for isl in islands:
        members = [p for p in pl if p["island"] == isl["id"]]
        roots = set()
        for p in members:
            biggest = max((k for k, (iso, _) in enumerate(parts) if iso == p["iso"]),
                          key=lambda k: abs(mapgen.area2(parts[k][1][0])))
            roots.add(find(biggest))
        if len(roots) != 1:
            fail(f"{isl['name']}: its prefectures' largest parts aren't one landmass")
        root = roots.pop()
        on = {parts[k][0] for k in range(len(parts)) if find(k) == root}
        if on != {p["iso"] for p in members}:
            fail(f"{isl['name']}: landmass holds {sorted(on)}, expected {sorted(p['iso'] for p in members)}")
        main_comp[isl["id"]] = root
    attached = []
    for iso, label, (lon, lat) in ATTACHED:
        hit = [poly for i, poly in parts if i == iso and mapgen.in_polygon(lon, lat, poly)]
        if len(hit) != 1:
            fail(f"attached {label}: {len(hit)} parts of {iso} contain {lon}, {lat}, expected 1")
        attached.append(hit[0])
    pieces, owner = {}, {}
    for p in pl:
        mine = [(k, poly) for k, (iso, poly) in enumerate(parts) if iso == p["iso"]]
        if p["island"] is None:
            main, isles = [poly for _, poly in mine], []
        else:
            root = main_comp[p["island"]]
            main = [poly for k, poly in mine if find(k) == root or any(poly is a for a in attached)]
            isles = [poly for k, poly in mine if not (find(k) == root or any(poly is a for a in attached))]
        pieces[p["id"]] = main
        owner[p["id"]] = p["id"]
        if isles:
            pieces[p["id"] + "-isles"] = isles
            owner[p["id"] + "-isles"] = p["id"]
    notes.append(f"{len(pieces)} pieces; -isles: " +
                 ", ".join(f"{pid[:-6]} ({len(polys)})" for pid, polys in pieces.items() if pid.endswith("-isles")))
    for _, label, _ in ATTACHED:
        notes.append(f"{label}: part of the main piece")
    return pieces, owner


def load_context(path, notes):
    raw = mapgen.read_pinned(path, ADM0_SHA256, ADM0_BYTES, NE_BASE + ADM0_FILE)
    ctx = []
    (k0, k1, k2, k3), n_kurils = KURILS
    dropped = []
    rus_before, rus_after = [], []
    (lo0, lo1), (la0, la1) = PREFILTER
    for f in json.loads(raw.decode("utf-8"))["features"]:
        a3 = f["properties"]["ADM0_A3"]
        if a3 == "JPN":
            continue  # Japan comes from admin-1
        for p in mapgen.polys_of(f["geometry"]):
            x0, y0, x1, y1 = mapgen.bbox(p[0])
            if a3 == "RUS":
                rus_before.append(p)
                if k0 <= x0 and x1 <= k2 and k1 <= y0 and y1 <= k3:
                    dropped.append(p)
                    continue
                rus_after.append(p)
            if x1 >= lo0 and x0 <= lo1 and y1 >= la0 and y0 <= la1:
                ctx.append(p)
    if len(dropped) != n_kurils:
        fail(f"Kurils: {len(dropped)} RUS parts in the box, expected {n_kurils}")
    for lon, lat, label, stays in KURIL_CHECKS:
        before = any(mapgen.in_polygon(lon, lat, p) for p in rus_before)
        after = any(mapgen.in_polygon(lon, lat, p) for p in rus_after)
        if not before or after != stays:
            fail(f"Kuril check {label} ({lon}, {lat}): in RUS before {before}, after {after}, expected after {stays}")
    notes.append(f"Kuril islands: {len(dropped)} RUS parts left out of the context land "
                 f"({len(KURIL_CHECKS)} point checks passed)")
    return ctx


def load_lakes(path, pieces, notes):
    raw = mapgen.read_pinned(path, LAKES_SHA256, LAKES_BYTES, NE_BASE + LAKES_FILE)
    by_id = {f["properties"]["ne_id"]: f for f in json.loads(raw.decode("utf-8"))["features"]}
    out = []
    for ne_id, name, pref in LAKES:
        f = by_id.get(ne_id)
        if f is None or f["properties"]["name"] != name:
            fail(f"{LAKES_FILE}: no lake {ne_id} named {name!r}")
        polys = mapgen.polys_of(f["geometry"])
        for poly in polys:
            for ring in poly:
                for c in ring:
                    if not any(mapgen.in_polygon(c[0], c[1], p) for p in pieces[pref]):
                        fail(f"lake {name}: point {c[0]}, {c[1]} outside {pref}")
        out.extend(polys)
        notes.append(f"lake {name}: {sum(len(p[0]) for p in polys)} points, inside {pref}")
    return out


# ------------------------------------------------------------------ relief
def load_dem(path, notes):
    """The ETOPO subset: elevations in metres (sea and nodata as 0, so the
    coast doesn't shade against the sea floor), rows from north to south."""
    raw = mapgen.read_pinned(path, ETOPO_SHA256, ETOPO_BYTES, ETOPO_URL)
    parts = raw.split(b"\n", 6)
    hdr = {}
    for ln in parts[:6]:
        k, v = ln.split()
        hdr[k.decode("ascii").lower()] = float(v)
    nc, nr, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
    if (nc, nr) != ETOPO_GRID:
        fail(f"{ETOPO_FILE}: {nc} x {nr} cells, expected {ETOPO_GRID}")
    z = array.array("f", [v if v > 0 else 0.0 for v in map(float, parts[6].split())])
    if len(z) != nc * nr:
        fail(f"{ETOPO_FILE}: {len(z)} values, expected {nc * nr}")
    notes.append(f"relief: ETOPO 2022 {nc} x {nr} cells of {cs * 3600:g}\", max {max(z):.0f} m")
    return {"z": z, "nc": nc, "nr": nr, "cs": cs, "lat_top": hdr["yllcenter"] + (nr - 1) * cs,
            "lon_left": hdr["xllcenter"]}


def laea_inverse(p):
    """The inverse of a mapgen.LambertAzimuthalEqualArea p: (easting,
    northing) -> (lon, lat). Snyder (1987) eqs. 24-26 + 24-28, and 3-18 for
    the authalic -> geodetic latitude."""
    e2 = p.e2
    c2 = e2 / 3 + 31 * e2 ** 2 / 180 + 517 * e2 ** 3 / 5040
    c4 = 23 * e2 ** 2 / 360 + 251 * e2 ** 3 / 3780
    c6 = 761 * e2 ** 3 / 45360
    sb1, cb1 = math.sin(p.b1), math.cos(p.b1)

    def inv(e, n):
        x, y = e - p.fe, n - p.fn
        rho = math.hypot(x / p.d, p.d * y)
        if rho < 1e-9:
            return math.degrees(p.lon0), math.degrees(p.lat0)
        ce = 2 * math.asin(rho / (2 * p.rq))
        sce, cce = math.sin(ce), math.cos(ce)
        beta = math.asin(cce * sb1 + p.d * y * sce * cb1 / rho)
        lam = p.lon0 + math.atan2(x * sce, p.d * rho * cb1 * cce - p.d * p.d * y * sb1 * sce)
        phi = beta + c2 * math.sin(2 * beta) + c4 * math.sin(4 * beta) + c6 * math.sin(6 * beta)
        return math.degrees(lam), math.degrees(phi)

    return inv


def png_palette(w, h, pix, plte, trns):
    """An 8-bit palette PNG, deterministic (no time or text chunks). Row
    filters by the usual heuristic (least sum of absolute values; none,
    sub, up, Paeth), computed only where the row or the one above has a
    non-zero pixel (the rest filters to zeros either way)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    def cost(seg):
        return sum(v if v < 128 else 256 - v for v in seg)

    raw = bytearray()
    prev = bytes(w)
    zero = bytes(w)
    for y in range(h):
        row = bytes(pix[y * w:(y + 1) * w])
        if row == zero and prev == zero:
            raw += b"\0" + row
            prev = row
            continue
        lo = min(w - len(row.lstrip(b"\0")), w - len(prev.lstrip(b"\0")))
        hi = min(w, max(len(row.rstrip(b"\0")), len(prev.rstrip(b"\0"))) + 1)
        seg0 = row[lo:hi]
        sub = bytes((row[i] - (row[i - 1] if i else 0)) & 255 for i in range(lo, hi))
        up = bytes((row[i] - prev[i]) & 255 for i in range(lo, hi))
        pa = bytearray(hi - lo)
        for i in range(lo, hi):
            a = row[i - 1] if i else 0
            b = prev[i]
            c = prev[i - 1] if i else 0
            pp = a + b - c
            da, db, dc = abs(pp - a), abs(pp - b), abs(pp - c)
            pa[i - lo] = (row[i] - (a if da <= db and da <= dc else (b if db <= dc else c))) & 255
        best = min(((cost(seg0), 0, seg0), (cost(sub), 1, sub), (cost(up), 2, up), (cost(pa), 4, bytes(pa))),
                   key=lambda t: (t[0], t[1]))
        raw.append(best[1])
        raw += row if best[1] == 0 else bytes(lo) + best[2] + bytes(w - hi)
        prev = row
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", plte) + chunk(b"tRNS", trns) + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def png_parts(data):
    """(IHDR, PLTE, tRNS, decompressed IDAT) of a PNG: what its pixels are,
    whatever zlib compressed them (--check compares these when the bytes
    differ, e.g. under another zlib build)."""
    parts, pos, idat = {}, 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b"IDAT":
            idat += body
        else:
            parts[tag] = body
        pos += 12 + n
    return parts.get(b"IHDR"), parts.get(b"PLTE"), parts.get(b"tRNS"), zlib.decompress(idat)


def relief(res, window, project, dem, piece_ids, notes):
    """site/relief.png over the window (0 0 width height) and its <image>."""
    inv = laea_inverse(project)
    worst = 0.0
    for lon, lat in ((122.94, 24.26), (145.82, 45.52), (139.70, 35.69), (128.0, 33.0), (LON0, LAT0)):
        lo, la = inv(*project(lon, lat))
        worst = max(worst, abs(lo - lon), abs(la - lat))
    if worst > 1e-6:  # ~0.1 m (the latitude series is good to ~1e-8°)
        fail(f"relief: inverse projection off by {worst:g}°")
    ppu = RELIEF_PPU
    pw, ph = int(round(window.width * ppu)), int(math.ceil(window.height * ppu))

    # Japan's land: the pieces' rings as drawn (shared arcs, so neighbours
    # meet exactly), in map units; even-odd over all of them is their union.
    g = res.grid
    edges = []
    for pid in piece_ids:
        if pid not in res.topo:
            fail(f"relief: no outline for {pid}")
        for refs in res.topo[pid]:
            ring = mapgen.ring_from_arcs(refs, res.arcs)
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if y1 == y2:
                    continue
                if y1 > y2:  # the same edge gives the same numbers from both sides
                    x1, y1, x2, y2 = x2, y2, x1, y1
                edges.append((y1 / g, y2 / g, x1 / g, (x2 - x1) / (y2 - y1)))
    # coverage: RELIEF_SUB scanlines per pixel row, exact along them
    nrows = ph * RELIEF_SUB
    dy = 1.0 / (RELIEF_SUB * ppu)
    rows = [[] for _ in range(nrows)]
    for ylo, yhi, xlo, slope in edges:
        for s in range(max(0, int((ylo - dy / 2) / dy)), min(nrows, int((yhi - dy / 2) / dy) + 2)):
            y = dy / 2 + s * dy
            if ylo <= y < yhi:
                rows[s].append(xlo + (y - ylo) * slope)
    cov = array.array("f", bytes(4 * pw * ph))
    part = 1.0 / RELIEF_SUB
    for s, xs in enumerate(rows):
        if len(xs) % 2:
            fail(f"relief: odd coast crossings on scanline {s}")
        xs.sort()
        base = (s // RELIEF_SUB) * pw
        for a, b in zip(xs[0::2], xs[1::2]):
            xa, xb = max(0.0, a * ppu), min(float(pw), b * ppu)
            if xb <= xa:
                continue
            ia, ib = int(xa), int(xb)
            if ia == ib:
                cov[base + ia] += (xb - xa) * part
                continue
            cov[base + ia] += (ia + 1 - xa) * part
            for i in range(ia + 1, ib):
                cov[base + i] += part
            if ib < pw:
                cov[base + ib] += (xb - ib) * part
    land = [i for i in range(pw * ph) if cov[i] > 0]
    if any(i < pw or i >= pw * (ph - 1) or i % pw in (0, pw - 1) for i in land):
        fail("relief: land on the image's edge")

    # elevation at the land pixels and their neighbours (bilinear, ETOPO cell centres)
    z, nc, cs, lat_top, lon_left = dem["z"], dem["nc"], dem["cs"], dem["lat_top"], dem["lon_left"]
    need = bytearray(pw * ph)
    for i in land:
        for j in (i - pw - 1, i - pw, i - pw + 1, i - 1, i, i + 1, i + pw - 1, i + pw, i + pw + 1):
            need[j] = 1
    elev = array.array("f", bytes(4 * pw * ph))
    k, x0, y1 = window.k, window.x0, window.y1
    for i in (i for i in range(pw * ph) if need[i]):
        py, px = divmod(i, pw)
        lon, lat = inv((px + 0.5) / ppu / k + x0, y1 - (py + 0.5) / ppu / k)
        fi, fj = (lat_top - lat) / cs, (lon - lon_left) / cs
        r0, c0 = int(fi), int(fj)
        if not (0 <= r0 < dem["nr"] - 1 and 0 <= c0 < nc - 1):
            fail(f"relief: {lon:.3f}, {lat:.3f} outside the ETOPO subset")
        ti, tj = fi - r0, fj - c0
        o = r0 * nc + c0
        elev[i] = (z[o] * (1 - tj) + z[o + 1] * tj) * (1 - ti) + (z[o + nc] * (1 - tj) + z[o + nc + 1] * tj) * ti

    # hillshade (Horn's gradient), screen coordinates: x right, y down, z up
    pix_m = 1.0 / ppu / k
    alt, az = math.radians(RELIEF_ALT), math.radians(RELIEF_AZ)
    lx, ly, lz = math.cos(alt) * math.sin(az), -math.cos(alt) * math.cos(az), math.sin(alt)
    step = RELIEF_DARK / RELIEF_LEVELS
    n_light = int(math.ceil(RELIEF_LIGHT / step - 1e-9))
    pal = bytearray(pw * ph)  # 0 transparent, 1..LEVELS black, LEVELS+1.. white
    for i in land:
        a, b, c = elev[i - pw - 1], elev[i - pw], elev[i - pw + 1]
        d, f = elev[i - 1], elev[i + 1]
        gg, h, ii = elev[i + pw - 1], elev[i + pw], elev[i + pw + 1]
        zx = ((c + 2 * f + ii) - (a + 2 * d + gg)) / (8 * pix_m) * RELIEF_Z
        zy = ((gg + 2 * h + ii) - (a + 2 * b + c)) / (8 * pix_m) * RELIEF_Z
        nrm = math.sqrt(zx * zx + zy * zy + 1)
        shade = (-zx * lx - zy * ly + lz) / nrm
        dark = min(1.0, RELIEF_W_SHADOW * min(1.0, max(0.0, (lz - shade) / lz)) + RELIEF_W_STEEP * (1 - 1 / nrm))
        light = min(1.0, max(0.0, (shade - lz) / (1 - lz)))
        q = int(round((RELIEF_LIGHT * light - RELIEF_DARK * dark) * min(1.0, cov[i]) / step))
        if q < 0:
            pal[i] = min(RELIEF_LEVELS, -q)
        elif q > 0:
            pal[i] = RELIEF_LEVELS + min(n_light, q)
    plte = bytes(3 * (1 + RELIEF_LEVELS)) + b"\xff" * (3 * n_light)
    trns = bytes([0] + [int(round(255 * step * j)) for j in range(1, RELIEF_LEVELS + 1)]
                 + [int(round(255 * step * j)) for j in range(1, n_light + 1)])
    png = png_palette(pw, ph, pal, plte, trns)
    el = (f'<image id="{RELIEF_ID}" href="relief.png" x="0" y="0" width="{pw / ppu:g}" height="{ph / ppu:g}" '
          f'preserveAspectRatio="none"/>')
    shaded = sum(1 for i in land if pal[i])
    notes.append(f"relief: {pw} x {ph} px ({ppu:g} px/unit), {len(land)} land px ({shaded} shaded), "
                 f"inverse projection within {worst:.0e}°")
    return png, el


def edges_of(lines):
    """The undirected edges of polylines (mapgen.chain_edges' input)."""
    return {(min(a, b), max(a, b)) for ln in lines for a, b in zip(ln, ln[1:]) if a != b}


def build(adm1_path, adm0_path, lakes_path, etopo_path):
    notes = []
    project = mapgen.LambertAzimuthalEqualArea(LAT0, LON0, ellipsoid=mapgen.GRS80, name=f"LAEA {LAT0:g}N {LON0:g}E")
    x, y = project(LON0, LAT0)
    if abs(x) > 1e-6 or abs(y) > 1e-6:
        fail("projection: centre doesn't map to 0, 0")
    islands, regions, pl = load_data()
    geo = load_adm1(adm1_path, pl)
    apply_fixups(geo, project, notes)
    pieces, owner = split_pieces(geo, islands, pl, notes)
    piece_ids = list(pieces)
    by_id = {p["id"]: p for p in pl}
    for lon, lat, pref, piece, label in VIEW_CHECKS:
        got = [pid for pid, polys in pieces.items() if any(mapgen.in_polygon(lon, lat, p) for p in polys)]
        if got != [piece] or owner[piece] != pref:
            fail(f"view check {label} ({lon}, {lat}): in {got}, expected {piece} ({pref})")
    notes.append(f"{len(VIEW_CHECKS)} point checks passed")
    context = load_context(adm0_path, notes)
    lakes = load_lakes(lakes_path, pieces, notes)
    dem = load_dem(etopo_path, notes)

    pts = [project(c[0], c[1]) for polys in pieces.values() for p in polys for c in p[0]]
    window = mapgen.Window(pts, MARGIN, WIDTH, EXTENT)
    mb = mapgen.MapBuilder(project, window, piece_ids, grid=GRID, min_island=MIN_ISLAND, context_tol=CONTEXT_TOL,
                           far_tol=FAR_TOL, far_min_island=FAR_MIN_ISLAND, far_gap=FAR_GAP)
    for pid in piece_ids:
        for p in pieces[pid]:
            mb.add_region(pid, p)
    for p in context:
        mb.add_context(p)
    for p in lakes:
        mb.add_overlay("lakes", p)
    res = mb.build(keep_islands=set(piece_ids))
    if res.stats["notes"]:
        fail("pieces below the grid: " + "; ".join(res.stats["notes"]))

    # Line overlays along the piece edges, each edge in one overlay only:
    # borders-prefectures leaves out the region borders (the rounds that
    # show it show borders-regions too; tools/data.test.mjs checks that).
    main_ids = [p["id"] for p in pl if p["island"] is not None]
    other_ids = [pid for pid in piece_ids if pid not in main_ids]
    regions_of = {pid: by_id[owner[pid]]["region"] for pid in piece_ids}
    region_lines = mapgen.boundary_lines(res, regions_of, outer=False)
    lines = {
        "coast-main": mapgen.boundary_lines(res, {pid: "main" for pid in main_ids}, inner=False),
        "coast-isles": mapgen.boundary_lines(res, {pid: "isles" for pid in other_ids}, inner=False),
        "borders-prefectures": mapgen.chain_edges(edges_of(mapgen.boundary_lines(res, owner, outer=False))
                                                  - edges_of(region_lines)),
        "borders-regions": region_lines,
    }
    islands_of = {pid: by_id[pid]["island"] for pid in main_ids}
    if mapgen.boundary_lines(res, islands_of, outer=False):
        fail("islands share a land border: emit borders-islands too")
    for oid, ln in lines.items():
        if not ln:
            fail(f"{oid}: no lines")
        res.overlays[oid] = mapgen.lines_d(ln, res.dec)
        notes.append(f"{oid}: {len(ln)} lines, {sum(len(x) for x in ln)} points")

    unknown = [oid for oid in res.overlays if oid not in OVERLAY_IDS]
    if unknown:
        fail(f"overlay ids not in OVERLAY_IDS: {unknown}")
    svg_text = mapgen.map_svg(res, piece_ids, HEAD, group_id="pieces")
    # the relief: an <image>, first in <g id="overlays"> (above the pieces,
    # below the lake and the lines); mapgen writes path overlays only
    png, relief_el = relief(res, window, project, dem, piece_ids, notes)
    tag = '<g id="overlays">\n'
    if svg_text.count(tag) != 1:
        fail("map.svg: no single <g id=\"overlays\">")
    svg_text = svg_text.replace(tag, tag + relief_el + "\n")

    def pieces_of(pred):
        return [pid for pid in piece_ids if pred(by_id[owner[pid]], pid)]

    def js_list(items):
        return "[" + ", ".join(mapgen.js_string(i) for i in items) + "]"

    def texts(e):
        return [f"id: {mapgen.js_string(e['id'])}", f"name: {mapgen.js_string(e['name'])}",
                f"kanji: {mapgen.js_string(e['kanji'])}", f"kana: {mapgen.js_string(e['kana'])}"]

    js = [
        f"// {HEAD}",
        "//",
        "// MAP: the window (full view) is 0 0 width height in map units; extent",
        "// [x, y, w, h] is map.svg's viewBox, the context drawn around it.",
        "// PIECES: the map pieces, one <path id> each in map.svg: every prefecture's",
        "// main piece (id = the prefecture's id: its parts on Honshū, Hokkaidō,",
        "// Kyūshū or Shikoku) and, where it has parts off that island, <id>-isles;",
        "// Okinawa is one piece. prefecture: whose piece it is.",
        "// ISLANDS, REGIONS, PREFECTURES: the answers, each with the pieces it",
        "// covers; name in Hepburn, kanji and kana its Japanese name and reading",
        "// (prefectures.json). A piece in no island (the -isles pieces, Okinawa)",
        "// lies on none of the four main islands.",
        "",
        window.map_js(),
        "",
        "export const PIECES = [",
    ]
    js += [f"  {{ id: {mapgen.js_string(pid)}, prefecture: {mapgen.js_string(owner[pid])} }}," for pid in piece_ids]
    js += ["];", "", "export const ISLANDS = ["]
    for isl in islands:
        ps = pieces_of(lambda p, pid: p["island"] == isl["id"] and pid == p["id"])
        js.append("  { " + ", ".join(texts(isl) + [f"pieces: {js_list(ps)}"]) + " },")
    js += ["];", "", "export const REGIONS = ["]
    for reg in regions:
        ps = pieces_of(lambda p, pid: p["region"] == reg["id"])
        js.append("  { " + ", ".join(texts(reg) + [f"pieces: {js_list(ps)}"]) + " },")
    js += ["];", "", "export const PREFECTURES = ["]
    for p in pl:
        ps = pieces_of(lambda q, pid: q["id"] == p["id"])
        fields = texts(p) + [
            f"iso: {mapgen.js_string(p['iso'])}",
            f"capital: {mapgen.js_string(p['capital'])}",
            f"capitalKanji: {mapgen.js_string(p['capital_kanji'])}",
            f"capitalKana: {mapgen.js_string(p['capital_kana'])}",
            f"capitalDiffers: {'true' if p['capital_differs'] else 'false'}",
            f"region: {mapgen.js_string(p['region'])}",
            f"island: {'null' if p['island'] is None else mapgen.js_string(p['island'])}",
            f"pieces: {js_list(ps)}",
        ]
        js.append("  { " + ", ".join(fields) + " },")
    js += ["];", ""]
    return {"map.svg": svg_text, "japan.js": "\n".join(js)}, {"relief.png": png}, res.report(piece_ids, notes)


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("adm1", help=f"path to {ADM1_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("adm0", help=f"path to {ADM0_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("lakes", help=f"path to {LAKES_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("etopo", help=f"path to {ETOPO_FILE} (NOAA ETOPO 2022 30\" subset, tools/README.md)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site"), help="output folder (default: ../site)")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out instead of writing")
    args = ap.parse_args()
    try:
        files, binaries, report = build(args.adm1, args.adm0, args.lakes, args.etopo)
    except (mapgen.BuildError, ValueError, OSError) as e:
        sys.exit(f"build_map: {e}")
    status = mapgen.emit(files, args.out, args.check, report)
    sys.exit(max(status, emit_binary(binaries, args.out, args.check)))


def emit_binary(files, out_dir, check):
    """mapgen.emit for bytes (relief.png): writes, or with check compares.
    A PNG whose bytes differ but whose pixels don't (another zlib build
    compressed them) counts as up to date. Returns 1 if a file is out of date."""
    stale = []
    for name, data in files.items():
        dest = os.path.join(out_dir, name)
        print(f"{name}: {len(data)} B")
        if not check:
            with open(dest, "wb") as fh:
                fh.write(data)
            continue
        try:
            with open(dest, "rb") as fh:
                old = fh.read()
        except FileNotFoundError:
            old = None
        if old == data:
            continue
        try:
            same = old is not None and png_parts(old) == png_parts(data)
        except (zlib.error, struct.error):
            same = False
        if same:
            print(f"  {name}: same pixels, other compressed bytes (zlib {zlib.ZLIB_RUNTIME_VERSION})")
        else:
            stale.append(name)
    if check:
        print("out of date: " + ", ".join(stale) if stale else ", ".join(files) + " up to date")
    return 1 if stale else 0


if __name__ == "__main__":
    main()
