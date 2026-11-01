#!/usr/bin/env python3
"""Builds site/map.svg and site/japan.js for images/japan-quiz.

usage:
  python3 -I tools/build_map.py <ne_10m_admin_1_states_provinces.geojson> \\
      <ne_50m_admin_0_countries.geojson> <ne_10m_lakes.geojson> [--out DIR] [--check]

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
     Ogasawara islands (incl. the Iwo islands and Minami-Torishima, 1,000+
     km out in the Pacific) are dropped; specks below SPECK_KM2 too. Point
     checks (VIEW_CHECKS) assert the result.
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
  9. Write map.svg (one <path> per piece in <g id="pieces">, the lakes and
     the lines in <g id="overlays">) and japan.js (MAP, PIECES, ISLANDS,
     REGIONS, PREFECTURES: the answers of the rounds with their pieces and
     texts).
"""
import argparse
import json
import os
import re
import sys
import unicodedata

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

HEAD = ("Generated by tools/build_map.py from tools/prefectures.json and Natural Earth v5.1.2 (public domain). "
        "Don't edit: change the inputs and regenerate.")

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
RESERVED = {"land", "overlays", "regions", "markers", "pieces"}


def fail(msg):
    raise mapgen.BuildError(msg)


# ------------------------------------------------------------------ kana check
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
    for k, s in enumerate(syl):
        nxt = syl[k + 1] if k + 1 < len(syl) else ""
        if s == "っ":
            if not nxt or nxt[0] in "aiueon":
                raise ValueError(f"っ before {nxt!r} in {kana!r}")
            out.append("t" if nxt.startswith("ch") else nxt[0])
        elif s == "ん":
            out.append("n'" if nxt and nxt[0] in "aiueoy" else "n")
        else:
            out.append(s)
    text = "".join(out)
    for a, b in (("ou", "ō"), ("oo", "ō"), ("uu", "ū"), ("aa", "ā"), ("ee", "ē")):
        text = text.replace(a, b)
    return text


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
    sharing vertices) holding the island's prefectures' largest parts."""
    parts = [(p["iso"], poly) for p in pl for poly in geo[p["iso"]]]
    parent = list(range(len(parts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    seen = {}
    for k, (_, poly) in enumerate(parts):
        for c in poly[0]:
            j = seen.setdefault((c[0], c[1]), k)
            if find(j) != find(k):
                parent[find(k)] = find(j)
    by_iso = {p["iso"]: p for p in pl}
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
    return pieces, owner, by_iso


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


def edges_of(lines):
    """The undirected edges of polylines (mapgen.chain_edges' input)."""
    return {(min(a, b), max(a, b)) for ln in lines for a, b in zip(ln, ln[1:]) if a != b}


def build(adm1_path, adm0_path, lakes_path):
    notes = []
    project = mapgen.LambertAzimuthalEqualArea(LAT0, LON0, ellipsoid=mapgen.GRS80, name=f"LAEA {LAT0:g}N {LON0:g}E")
    x, y = project(LON0, LAT0)
    if abs(x) > 1e-6 or abs(y) > 1e-6:
        fail("projection: centre doesn't map to 0, 0")
    islands, regions, pl = load_data()
    geo = load_adm1(adm1_path, pl)
    apply_fixups(geo, project, notes)
    pieces, owner, _ = split_pieces(geo, islands, pl, notes)
    piece_ids = list(pieces)
    by_id = {p["id"]: p for p in pl}
    for lon, lat, pref, piece, label in VIEW_CHECKS:
        got = [pid for pid, polys in pieces.items() if any(mapgen.in_polygon(lon, lat, p) for p in polys)]
        if got != [piece] or owner[piece] != pref:
            fail(f"view check {label} ({lon}, {lat}): in {got}, expected {piece} ({pref})")
    notes.append(f"{len(VIEW_CHECKS)} point checks passed")
    context = load_context(adm0_path, notes)
    lakes = load_lakes(lakes_path, pieces, notes)

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

    svg_text = mapgen.map_svg(res, piece_ids, HEAD, group_id="pieces")

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
    return {"map.svg": svg_text, "japan.js": "\n".join(js)}, res.report(piece_ids, notes)


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("adm1", help=f"path to {ADM1_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("adm0", help=f"path to {ADM0_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("lakes", help=f"path to {LAKES_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site"), help="output folder (default: ../site)")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out instead of writing")
    args = ap.parse_args()
    try:
        files, report = build(args.adm1, args.adm0, args.lakes)
    except (mapgen.BuildError, ValueError, OSError) as e:
        sys.exit(f"build_map: {e}")
    sys.exit(mapgen.emit(files, args.out, args.check, report))


if __name__ == "__main__":
    main()
