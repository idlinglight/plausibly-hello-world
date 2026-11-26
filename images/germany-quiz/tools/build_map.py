#!/usr/bin/env python3
"""Builds site/map.svg, site/states.js, site/relief.png and site/relief-context.png
for images/germany-quiz.

usage:
  python3 -I tools/build_map.py <ne_10m_admin_1_states_provinces.geojson> \\
      <ne_10m_lakes.geojson> <etopo_2022_15s_germany.asc> [--out DIR] [--check]

Offline, stdlib only (Python 3.9+), deterministic: the same inputs give
byte-identical outputs. --check builds in memory and exits 1 if the files in
the output folder differ (nothing is written). Details: tools/README.md.

This file is germany-quiz's adapter: Natural Earth, the checks, the window,
the context land, the lakes and the quiz data. The geometry (projection,
clipping, shared borders, simplification, SVG) and the relief shading are
the shared map-quiz core, shared/map-quiz/tools/mapgen.

Pipeline:
  1. tools/states.json (16 Länder; names, capitals, Wikipedia titles, a
     point inside each): checked, the titles present where the rounds link
     them (their articles are checked online, by hand: tools/wiki_titles.py).
  2. Natural Earth admin-1 states/provinces, 10m, v5.1.2 (sha256-verified):
     the 16 DEU features, matched by ISO 3166-2 code, NE's name checked;
     every other feature near Germany is context land, from the same file,
     so the national border is one line on both sides. No vertex of one
     feature lies on another's edge (mapgen.t_junctions, asserted).
  3. Point checks: each state's point (states.json) in that state, and
     VIEW_CHECKS (Bremerhaven in Bremen, Helgoland in Schleswig-Holstein,
     Büsingen on Swiss context land, …). No fix-ups: Natural Earth's
     Länder are drawn as they are (tools/README.md, "Choices").
  4. Projection: Lambert azimuthal equal-area centred on 51°N 10.5°E
     (GRS80), the middle of Germany; equal-area keeps the Länder's sizes
     comparable. The window is the bounding box of the Länder plus MARGIN;
     EXTENT more is drawn around it (context land, faded by the page).
  5. Context land: every non-DEU polygon whose projected bounding box
     reaches the extent (polygons far away or across the antimeridian are
     skipped before projecting: PREFILTER, MAX_SPAN).
  6. (mapgen) Clip to the extent, snap to a 1/GRID grid, merge, build
     shared arcs (neighbours use identical vertices); context-only arcs are
     simplified, the Länder's arcs keep every vertex; every Land keeps all
     its islands (Helgoland, the East Frisian islands, …).
  7. Lakes (LAKES): Natural Earth's 10m lakes in Germany, each checked to
     lie on the Länder it names (the Bodensee: on drawn land, its shores
     are German, Austrian and Swiss). An overlay above the Länder,
     see-through: a click on a lake picks the Land beneath.
  8. Ring (RING): Bremen's city part is a few pixels across at the full
     view on a phone, so Bremen gets a marker at the centre of that part's
     bounding box; its size is that part's larger side, not the whole
     state's (Bremerhaven, 50 km north, would hide the ring early).
  9. Shaded relief (RELIEF_*, mapgen.shaded_relief): NOAA ETOPO 2022 at
     its full 15" (an ERDDAP subset, sha256-verified), hill-shaded on all
     drawn land, ending at the coast, as two palette PNGs: relief.png on
     the Länder (RELIEF_PPU, over the window), relief-context.png on the
     context land (RELIEF_CONTEXT_PPU, coarser, over the whole extent: it
     fades out with the land at the page's fade). Drawn as
     <image id="relief"> and <image id="relief-context">, first in
     <g id="overlays">.
 10. Write map.svg (one <path> per Land in <g id="states">, the relief and
     the lakes in <g id="overlays">), states.js (MAP, STATES: the answers
     with their texts, Wikipedia titles and Bremen's ring) and the two PNGs.
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
LAKES_FILE = "ne_10m_lakes.geojson"
LAKES_SHA256 = "2d036f53dedec578001c5c30c2959ee7d4eebc1306900fa4367c49929ec8f2d9"
LAKES_BYTES = 5043554
# NOAA NCEI ETOPO 2022 (15" global relief), every cell of 44.75-57.25°N,
# 1.0°W-22.0°E as ESRI ASCII from CoastWatch's ERDDAP (tools/README.md).
ETOPO_FILE = "etopo_2022_15s_germany.asc"
ETOPO_URL = ("https://coastwatch.pfeg.noaa.gov/erddap/griddap/ETOPO_2022_v1_15s.esriAscii?"
             "z%5B(44.75):1:(57.25)%5D%5B(-1.0):1:(22.0)%5D")
ETOPO_SHA256 = "cbda9149d8e8900fa7c283ce3cb5be824053d15701b9892a3dbe278572e124f8"
ETOPO_BYTES = 157837395
ETOPO_GRID = (5521, 3001)  # columns, rows

STATES_JSON = os.path.join(HERE, "states.json")

# ------------------------------------------------------------------ output
WIDTH = 1000.0      # viewBox width in map units (1 unit ≈ 0.68 km)
GRID = 10           # vertices snap to 1/GRID unit (0.1)
MARGIN = 0.03       # window margin around the Länder, fraction of their width
EXTENT = (0.5, 0.2)  # context drawn around the window: fraction of its width / height per side
MIN_ISLAND = 0.3    # context land: drop islands below this area (units^2) unless they touch another ring
CONTEXT_TOL = 0.2   # Douglas-Peucker tolerance (units) for arcs only context land uses …
FAR_TOL = 1.5       # … and for their runs of points outside the window (+ FAR_GAP): only seen small
FAR_MIN_ISLAND = 4  # context islands entirely outside the window: dropped below this (units^2)
FAR_GAP = 20        # units around the window that still count as near
CROSSINGS = 2       # arc crossings the 0.1 grid's snapping makes (sub-grid, unseen; tools/README.md): expected exactly

LAT0, LON0 = 51.0, 10.5  # projection centre

# Shaded relief: site/relief.png on the Länder (over the window),
# site/relief-context.png on the context land (over the extent), coarser.
# The densities: tools/README.md, "Relief" (size against sharpness).
RELIEF_PPU = 1.0           # pixels per map unit, the Länder (0.68 km per pixel)
RELIEF_CONTEXT_PPU = 0.5   # pixels per map unit, the context land
RELIEF_SUB = 4             # coverage samples per pixel row (columns: exact)
RELIEF_AZ, RELIEF_ALT = 315.0, 45.0  # light: from the top left (azimuth from up, clockwise), 45° high
RELIEF_Z = 5.0             # vertical exaggeration
RELIEF_W_SHADOW = 0.8      # darkness: weight of facing away from the light …
RELIEF_W_STEEP = 0.9       # … and of steepness (so sunlit slopes still read)
RELIEF_DARK = 0.55         # strongest shadow: black at this alpha (multiplies by 0.45)
RELIEF_LIGHT = 0.3         # strongest highlight: white at this alpha
RELIEF_LEVELS = 32         # alpha steps from 0 to RELIEF_DARK (palette size, PNG size)

HEAD = ("Generated by tools/build_map.py from tools/states.json, Natural Earth v5.1.2 (public domain) "
        "and NOAA ETOPO 2022 (relief). Don't edit: change the inputs and regenerate.")

# ------------------------------------------------------------------ checks
# Owner after loading: (lon, lat, state id or None for "not in any Land",
# label). None points must lie on context land (checked after the build).
VIEW_CHECKS = [
    (8.58, 53.55, "bremen", "Bremerhaven"),
    (8.80, 53.08, "bremen", "Bremen (city)"),
    (7.895, 54.19, "schleswig-holstein", "Helgoland"),
    (7.922, 54.191, "schleswig-holstein", "Helgoland, Düne"),
    (8.30, 54.90, "schleswig-holstein", "Sylt"),
    (11.15, 54.47, "schleswig-holstein", "Fehmarn"),
    (6.70, 53.59, "niedersachsen", "Borkum"),
    (13.40, 54.45, "mecklenburg-vorpommern", "Rügen"),
    (14.00, 53.95, "mecklenburg-vorpommern", "Usedom (German part)"),
    (13.15, 52.43, "berlin", "Wannsee (Berlin, beside Brandenburg)"),
    (9.35, 47.62, "baden-wuerttemberg", "Bodensee, middle (Natural Earth's split)"),
    (9.66, 47.56, "bayern", "Bodensee off Lindau"),
    (6.21, 50.565, "nordrhein-westfalen", "Mützenich (beyond the Vennbahn, not drawn)"),
    (8.69, 47.697, None, "Büsingen am Hochrhein (Natural Earth: Schaffhausen)"),
    (10.45, 47.575, None, "Jungholz (Tirol)"),
    (10.15, 47.33, None, "Kleinwalsertal (Vorarlberg)"),
    (9.30, 47.585, None, "Bodensee off Romanshorn (Thurgau)"),
    (9.68, 47.50, None, "Bodensee off Bregenz (Vorarlberg)"),
    (14.30, 53.90, None, "Usedom (Polish part)"),
]
# Points inside no feature at all (sea, or land Natural Earth doesn't draw).
EMPTY_CHECKS = [
    (8.50, 53.92, "Neuwerk (Hamburg; not in Natural Earth)"),
    (8.20, 53.45, "Jadebusen"),
]
# Lakes drawn as the "lakes" overlay: (Natural Earth ne_id, its name or
# None, label, the Länder its outline must lie on, or None: on drawn land).
LAKES = [
    (1159114259, "Bodensee", "Bodensee (Obersee, Überlinger See)", None),
    (1159115487, None, "Untersee (Bodensee)", ("baden-wuerttemberg",)),
    (1159117823, "Müritz", "Müritz", ("mecklenburg-vorpommern",)),
    (1159117837, "Schweriner See", "Schweriner See", ("mecklenburg-vorpommern",)),
    (1159118311, None, "a lake south of the Müritz, near Mirow", ("mecklenburg-vorpommern",)),
    (1159122453, None, "Großer Plöner See", ("schleswig-holstein",)),
    (1159118291, None, "Havel and Wannsee", ("berlin", "brandenburg")),
    (1159118383, None, "Müggelsee", ("berlin",)),
    (1159118331, None, "Havel lakes at Brandenburg an der Havel", ("brandenburg",)),
    (1159118349, None, "Havel lakes at Werder", ("brandenburg",)),
    (1159118367, None, "Schwielowsee", ("brandenburg",)),
    (1159118401, None, "Schwielochsee", ("brandenburg",)),
    (1159118219, None, "Talsperre Spremberg", ("brandenburg",)),
]
# Every Natural Earth lake whose bounding box lies in this lon/lat box must
# be in LAKES (so a new or moved one isn't silently left out).
LAKE_BOX = (5.8, 47.2, 15.1, 55.1)
LAKE_IGNORE = {1159114143: "Lake Geneva", 1159118273: "Lauwersmeer", 1159118421: "Jezioro Dąbie",
               1159126631: "IJsselmeer"}
# Bremen's ring: the state, and a point inside the part the ring sits on.
RING = ("bremen", (8.80, 53.08))
PREFILTER = ((-5.0, 27.0), (40.0, 62.0))  # lon/lat box: context polygons entirely outside are skipped early
MAX_SPAN = 90.0     # … and polygons wider than this (degrees of longitude: across the antimeridian)

ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
# Overlay ids map.svg gets (build() checks it writes no other), and the
# ids of map.svg's own elements and the engine's layers: no state id may be
# one of them. RELIEF_ID and RELIEF_CONTEXT_ID are the <image>s this script
# inserts first in <g id="overlays">; "lakes" is mapgen's path.
RELIEF_ID, RELIEF_CONTEXT_ID = "relief", "relief-context"
OVERLAY_IDS = (RELIEF_ID, RELIEF_CONTEXT_ID, "lakes")
GROUP_ID = "states"
RESERVED = {"land", "overlays", "regions", "markers", GROUP_ID, *OVERLAY_IDS}


def fail(msg):
    raise mapgen.BuildError(msg)


# ------------------------------------------------------------------ steps
def load_data():
    with open(STATES_JSON, encoding="utf-8") as fh:
        st = json.load(fh)["states"]
    if len(st) != 16:
        fail(f"states.json: expected 16 states, got {len(st)}")
    for s in st:
        for key in ("id", "iso", "name", "capital", "ne_name"):
            v = s.get(key)
            if not isinstance(v, str) or not v or v != v.strip() or unicodedata.normalize("NFC", v) != v:
                fail(f"states.json: {s.get('id')}: empty, padded or not NFC: {key}")
        if not ID.match(s["id"]) or s["id"] in RESERVED or s["id"].startswith("fade"):
            fail(f"states.json: bad id {s['id']!r}")
        if not re.match(r"^DE-[A-Z]{2}$", s["iso"]):
            fail(f"states.json: {s['id']}: bad iso {s['iso']!r}")
        if not isinstance(s["capital_differs"], bool) or s["capital_differs"] != (s["capital"] != s["name"]):
            fail(f"states.json: {s['id']}: capital_differs must say whether capital and name differ")
        pt = s.get("point")
        if not (isinstance(pt, list) and len(pt) == 2 and 5 < pt[0] < 16 and 47 < pt[1] < 56):
            fail(f"states.json: {s['id']}: bad point")
    for key in ("id", "iso", "name", "capital"):
        vals = [s[key] for s in st]
        if len(set(vals)) != len(vals):
            fail(f"states.json: duplicate {key}")
    names = [s["name"] for s in st]
    if names != sorted(names, key=lambda n: n.replace("ü", "u")):
        fail("states.json: not in alphabetical order")
    # Wikipedia titles (tools/README.md, "Wikipedia titles"): wiki on every
    # state (each is asked by name), capital_wiki exactly on the states the
    # capitals round asks (capital_differs).
    for s in st:
        bad = mapgen.wiki_title_error(s.get("wiki"))
        if bad:
            fail(f"states.json: {s['id']}: wiki (a German Wikipedia article title) "
                 f"{'missing' if 'wiki' not in s else bad}")
        if not s["capital_differs"]:
            if "capital_wiki" in s:
                fail(f"states.json: {s['id']}: capital_wiki, but the capitals round doesn't ask its capital")
            continue
        bad = mapgen.wiki_title_error(s.get("capital_wiki"))
        if bad:
            fail(f"states.json: {s['id']}: capital_wiki (a German Wikipedia article title) "
                 f"{'missing' if 'capital_wiki' not in s else bad}")
    for key in ("wiki", "capital_wiki"):
        vals = [s[key] for s in st if key in s]
        if len(set(vals)) != len(vals):
            fail(f"states.json: duplicate {key}")
    return st


def load_adm1(path, st, notes):
    """{state id: polygons} for the 16 DEU features, and the context
    polygons in file order [(adm0_a3, polygon)]."""
    raw = mapgen.read_pinned(path, ADM1_SHA256, ADM1_BYTES, NE_BASE + ADM1_FILE)
    by_iso = {s["iso"]: s for s in st}
    geo, ctx, seen = {}, [], set()
    (lo0, lo1), (la0, la1) = PREFILTER
    skipped = 0
    for f in json.loads(raw.decode("utf-8"))["features"]:
        pr = f["properties"]
        polys = mapgen.polys_of(f["geometry"])
        if pr.get("adm0_a3") == "DEU":
            iso = pr["iso_3166_2"]
            if iso not in by_iso or iso in seen:
                fail(f"{ADM1_FILE}: unexpected or repeated DEU feature {iso}")
            seen.add(iso)
            s = by_iso[iso]
            if pr["name"] != s["ne_name"]:
                fail(f"{iso}: Natural Earth name {pr['name']!r}, states.json ne_name {s['ne_name']!r}")
            geo[s["id"]] = polys
            continue
        for p in polys:
            x0, y0, x1, y1 = mapgen.bbox(p[0])
            if x1 - x0 > MAX_SPAN:
                skipped += 1
            elif x1 >= lo0 and x0 <= lo1 and y1 >= la0 and y0 <= la1:
                ctx.append((pr["adm0_a3"], p))
    if seen != set(by_iso):
        fail(f"{ADM1_FILE}: DEU features {sorted(seen)} don't match states.json")
    geo = {s["id"]: geo[s["id"]] for s in st}
    notes.append(f"16 DEU features; {len(ctx)} context polygons near Germany "
                 f"({skipped} spanning more than {MAX_SPAN:g}° of longitude skipped)")
    return geo, ctx


def check_topology(geo, ctx, notes):
    """No vertex of a Land or a nearby context feature lies inside another's
    edge: the Länder share their borders with each other and with the
    neighbouring countries exactly (else the arcs come out one-sided)."""
    feats = dict(geo)
    for k, (a3, p) in enumerate(ctx):
        feats.setdefault(f"{a3}#{k}", []).append(p)
    tj = mapgen.t_junctions(feats)
    if tj:
        fail(f"{len(tj)} T-junctions, e.g. {tj[:3]}")
    notes.append(f"no T-junctions among the Länder and {len(ctx)} context polygons")


def check_points(st, geo, ctx, notes):
    for s in st:
        got = mapgen.owner_of(geo, *s["point"])
        if got != s["id"]:
            fail(f"point check {s['name']} {s['point']}: in {got}")
    ctx_polys = [p for _, p in ctx]
    for lon, lat, want, label in VIEW_CHECKS:
        got = mapgen.owner_of(geo, lon, lat)
        on_ctx = any(mapgen.in_polygon(lon, lat, p) for p in ctx_polys)
        if got != want or (want is None and not on_ctx):
            fail(f"view check {label} ({lon}, {lat}): in {got}, context land {on_ctx}, expected {want}")
    for lon, lat, label in EMPTY_CHECKS:
        if mapgen.owner_of(geo, lon, lat) or any(mapgen.in_polygon(lon, lat, p) for p in ctx_polys):
            fail(f"empty check {label} ({lon}, {lat}): land there")
    notes.append(f"{len(st) + len(VIEW_CHECKS) + len(EMPTY_CHECKS)} point checks passed")


def load_lakes(path, geo, ctx, notes):
    raw = mapgen.read_pinned(path, LAKES_SHA256, LAKES_BYTES, NE_BASE + LAKES_FILE)
    feats = json.loads(raw.decode("utf-8"))["features"]
    by_id = {f["properties"]["ne_id"]: f for f in feats}
    listed = {ne_id for ne_id, _, _, _ in LAKES}
    bx0, by0, bx1, by1 = LAKE_BOX
    for f in feats:
        ne_id = f["properties"]["ne_id"]
        x0, y0, x1, y1 = mapgen.bbox([c for p in mapgen.polys_of(f["geometry"]) for c in p[0]])
        inside = bx0 <= x0 and x1 <= bx1 and by0 <= y0 and y1 <= by1
        if inside and ne_id not in listed and ne_id not in LAKE_IGNORE:
            fail(f"{LAKES_FILE}: lake {ne_id} ({f['properties']['name']}) in LAKE_BOX but not in LAKES")
    all_land = [p for polys in geo.values() for p in polys] + [p for _, p in ctx]
    out = []
    for ne_id, name, label, states in LAKES:
        f = by_id.get(ne_id)
        if f is None or f["properties"]["name"] != name:
            fail(f"{LAKES_FILE}: no lake {ne_id} named {name!r}")
        polys = mapgen.polys_of(f["geometry"])
        land = all_land if states is None else [p for sid in states for p in geo[sid]]
        for poly in polys:
            for ring in poly:
                for c in ring:
                    if not any(mapgen.in_polygon(c[0], c[1], p) for p in land):
                        fail(f"lake {label}: point {c[0]}, {c[1]} outside {states or 'the drawn land'}")
        out.extend(polys)
    notes.append(f"{len(LAKES)} lakes, each on the Länder it names")
    return out


def km2(poly, project):
    """Area in km² (the projection is equal-area); holes subtracted."""
    rings = [[project(c[0], c[1]) for c in mapgen.open_ring(r)] for r in poly]
    return (abs(mapgen.area2(rings[0])) - sum(abs(mapgen.area2(h)) for h in rings[1:])) / 2e6


def check_context(res, mb, notes):
    """VIEW_CHECKS without a Land: each on drawn context land."""
    g = res.grid
    rings = [mapgen.ring_from_arcs(r, res.arcs) for r in res.topo.get(mapgen.CONTEXT, [])]
    n = 0
    for lon, lat, want, label in VIEW_CHECKS:
        if want is not None:
            continue
        x, y = mb.view(lon, lat)
        if sum(mapgen.in_ring(x * g, y * g, r) for r in rings) % 2 != 1:
            fail(f"context check {label} ({lon}, {lat}): no context land drawn there")
        n += 1
    notes.append(f"{n} points on drawn context land")


def ring_marker(res, mb, notes):
    """Bremen's marker: the centre of the bounding box of its drawn ring
    containing RING's point, and that ring's larger side (map units)."""
    sid, (lon, lat) = RING
    g = res.grid
    x, y = mb.view(lon, lat)
    hit = []
    for refs in res.topo[sid]:
        ring = mapgen.ring_from_arcs(refs, res.arcs)
        if mapgen.area2(ring) > 0 and mapgen.in_ring(x * g, y * g, ring):
            hit.append(ring)
    if len(hit) != 1:
        fail(f"ring {sid}: {len(hit)} drawn outer rings contain {lon}, {lat}")
    x0, y0, x1, y1 = mapgen.bbox(hit[0])
    marker = (round((x0 + x1) / 2 / g, 1), round((y0 + y1) / 2 / g, 1))
    size = round(max(x1 - x0, y1 - y0) / g, 1)
    notes.append(f"ring {sid}: marker {marker[0]:g}, {marker[1]:g}, size {size:g} "
                 f"(whole state {res.sizes[sid]:.1f})")
    return marker, size


def relief(res, window, project, dem, state_ids, notes):
    """The relief (mapgen.shaded_relief) as two images, so the Länder stay
    sharp at a size a phone loads quickly: relief.png on the Länder over
    the window (their land never reaches its edge), relief-context.png on
    the context land over the whole extent (clipped there: land on its
    edge), at RELIEF_CONTEXT_PPU. Returns {file: png} and the <image>s."""
    inv = mapgen.laea_inverse(project)
    worst = mapgen.inverse_error(project, inv, ((5.87, 47.27), (15.04, 55.06), (-0.7, 45.1), (21.5, 56.9),
                                                (LON0, LAT0)))
    if worst > 1e-6:  # ~0.1 m (the latitude series is good to ~1e-8°)
        fail(f"relief: inverse projection off by {worst:g}°")
    pngs, els = {}, []
    for rid, ppu, fids, box, edge_ok in ((RELIEF_ID, RELIEF_PPU, list(state_ids), None, False),
                                         (RELIEF_CONTEXT_ID, RELIEF_CONTEXT_PPU, [mapgen.CONTEXT], window.extent,
                                          True)):
        style = mapgen.ReliefStyle(ppu, sub=RELIEF_SUB, az=RELIEF_AZ, alt=RELIEF_ALT, z=RELIEF_Z,
                                   w_shadow=RELIEF_W_SHADOW, w_steep=RELIEF_W_STEEP, dark=RELIEF_DARK,
                                   light=RELIEF_LIGHT, levels=RELIEF_LEVELS)
        png, el, s = mapgen.shaded_relief(res, window, inv, dem, fids, style, box=box, edge_ok=edge_ok,
                                          element_id=rid, href=f"{rid}.png")
        pngs[f"{rid}.png"] = png
        els.append(el)
        notes.append(f"{rid}: {s['width']} x {s['height']} px ({ppu:g} px/unit), {s['land']} land px "
                     f"({s['shaded']} shaded)")
    notes.append(f"relief: inverse projection within {worst:.0e}°")
    return pngs, els


def build(adm1_path, lakes_path, etopo_path):
    notes = []
    project = mapgen.LambertAzimuthalEqualArea(LAT0, LON0, ellipsoid=mapgen.GRS80, name=f"LAEA {LAT0:g}N {LON0:g}E")
    x, y = project(LON0, LAT0)
    if abs(x) > 1e-6 or abs(y) > 1e-6:
        fail("projection: centre doesn't map to 0, 0")
    st = load_data()
    ids = [s["id"] for s in st]
    geo, ctx = load_adm1(adm1_path, st, notes)
    check_topology(geo, ctx, notes)
    check_points(st, geo, ctx, notes)
    areas = {sid: sum(km2(p, project) for p in geo[sid]) for sid in ids}
    notes.append("areas (km²): " + ", ".join(f"{sid} {a:.0f}" for sid, a in sorted(areas.items(), key=lambda t: t[1])[:4])
                 + ", …")
    lakes = load_lakes(lakes_path, geo, ctx, notes)
    raw = mapgen.read_pinned(etopo_path, ETOPO_SHA256, ETOPO_BYTES, ETOPO_URL)
    dem = mapgen.read_esri_ascii(raw, ETOPO_GRID, ETOPO_FILE)
    del raw
    notes.append(f"relief: ETOPO 2022 {dem['nc']} x {dem['nr']} cells of {dem['cs'] * 3600:g}\", "
                 f"max {dem['max']:.0f} m")

    pts = [project(c[0], c[1]) for sid in ids for p in geo[sid] for c in p[0]]
    window = mapgen.Window(pts, MARGIN, WIDTH, EXTENT)
    mb = mapgen.MapBuilder(project, window, ids, grid=GRID, min_island=MIN_ISLAND, context_tol=CONTEXT_TOL,
                           far_tol=FAR_TOL, far_min_island=FAR_MIN_ISLAND, far_gap=FAR_GAP)
    for sid in ids:
        for p in geo[sid]:
            mb.add_region(sid, p)
    ex0, ey0, ex1, ey1 = window.extent
    n_ctx = 0
    for _, p in ctx:
        bx0, by0, bx1, by1 = mapgen.bbox([mb.view(c[0], c[1]) for c in p[0]])
        if bx1 >= ex0 and bx0 <= ex1 and by1 >= ey0 and by0 <= ey1:
            mb.add_context(p)
            n_ctx += 1
    notes.append(f"context land: {n_ctx} polygons reach the extent")
    for p in lakes:
        mb.add_overlay("lakes", p)
    res = mb.build(keep_islands=set(ids))
    if res.stats["notes"]:
        fail("states below the grid: " + "; ".join(res.stats["notes"]))
    if res.stats["crossings"] != CROSSINGS:
        fail(f"{res.stats['crossings']} arc crossings, expected {CROSSINGS} (mapgen.crossing_pairs lists them)")
    check_context(res, mb, notes)
    marker, size = ring_marker(res, mb, notes)

    unknown = [oid for oid in res.overlays if oid not in OVERLAY_IDS]
    if unknown:
        fail(f"overlay ids not in OVERLAY_IDS: {unknown}")
    svg_text = mapgen.map_svg(res, ids, HEAD, group_id=GROUP_ID)
    # the relief: two <image>s, first in <g id="overlays"> (above the Länder
    # and the context land, below the lakes); mapgen writes path overlays only
    pngs, relief_els = relief(res, window, project, dem, ids, notes)
    tag = '<g id="overlays">\n'
    if svg_text.count(tag) != 1:
        fail("map.svg: no single <g id=\"overlays\">")
    svg_text = svg_text.replace(tag, tag + "".join(el + "\n" for el in relief_els))

    js = [
        f"// {HEAD}",
        "//",
        "// MAP: the window (full view) is 0 0 width height in map units; extent",
        "// [x, y, w, h] is map.svg's viewBox, the context drawn around it.",
        "// STATES: the 16 Länder in states.json order, one <path id> each in",
        "// map.svg; wiki: the German Wikipedia article's title; capitalWiki: the",
        "// capital's, only where the capitals round asks it (capitalDiffers).",
        "// marker: [x, y] in map units and size (map units) for the ring, on",
        "// Bremen only: size is the larger side of its city part's bounding box.",
        "",
        window.map_js(),
        "",
        "export const STATES = [",
    ]
    for s in st:
        fields = [
            f"id: {mapgen.js_string(s['id'])}",
            f"iso: {mapgen.js_string(s['iso'])}",
            f"name: {mapgen.js_string(s['name'])}",
            f"capital: {mapgen.js_string(s['capital'])}",
            f"capitalDiffers: {'true' if s['capital_differs'] else 'false'}",
            f"wiki: {mapgen.js_string(s['wiki'])}",
        ] + ([f"capitalWiki: {mapgen.js_string(s['capital_wiki'])}"] if s["capital_differs"] else [])
        if s["id"] == RING[0]:
            fields += [f"marker: [{marker[0]:g}, {marker[1]:g}]", f"size: {size:g}"]
        js.append("  { " + ", ".join(fields) + " },")
    js += ["];", ""]
    return {"map.svg": svg_text, "states.js": "\n".join(js)}, pngs, res.report(ids, notes)


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("adm1", help=f"path to {ADM1_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("lakes", help=f"path to {LAKES_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("etopo", help=f"path to {ETOPO_FILE} (NOAA ETOPO 2022 15\" subset, tools/README.md)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site"), help="output folder (default: ../site)")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out instead of writing")
    args = ap.parse_args()
    try:
        files, binaries, report = build(args.adm1, args.lakes, args.etopo)
    except (mapgen.BuildError, ValueError, OSError) as e:
        sys.exit(f"build_map: {e}")
    status = mapgen.emit(files, args.out, args.check, report)
    sys.exit(max(status, mapgen.emit_binary(binaries, args.out, args.check)))


if __name__ == "__main__":
    main()
