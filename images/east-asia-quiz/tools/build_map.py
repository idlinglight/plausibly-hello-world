#!/usr/bin/env python3
"""Builds site/map.svg and site/countries.js for images/east-asia-quiz.

usage:
  python3 -I tools/build_map.py <ne_50m_admin_0_countries.geojson> [--out DIR] [--check]

Offline, stdlib only (Python 3.9+), deterministic: the same inputs give
byte-identical outputs. --check builds in memory and exits 1 if the files in
the output folder differ (nothing is written). Details: tools/README.md.

This file is east-asia-quiz's adapter: Natural Earth, the fix-ups, the
window and the quiz set. The geometry (projection, clipping, shared
borders, simplification, SVG) is the shared map-quiz core,
shared/map-quiz/tools/mapgen.

Pipeline:
  1. Natural Earth admin-0 countries, 50m, v5.1.2 (sha256-verified; the
     file europe-quiz pins).
  2. Fix-ups: Hong Kong and Macao merge into China (MERGES, shared borders
     dissolved); Palau's Tobi is dropped (DROPS: a speck 500 km from the
     main islands that would hide Palau's ring). Everything else as
     Natural Earth's default layer draws it. Point checks (VIEW_CHECKS)
     assert the result, EMPTY that the South China Sea's reefs and islets
     aren't in the file at this scale (no polygon meets those boxes; a
     source that has them must decide about them here, not by accident).
     Natural Earth cuts land at 180° (Chukotka, Wrangel Island): every
     edge along the cut gets the other side's vertices, so the parts merge
     like any shared border (SEAMS checks no line is left there).
  3. Quiz countries (tools/countries.json) stay separate; every other
     polygon whose projected bounding box reaches the extent becomes
     context land, one merged path (polygons reaching towards the
     antipode, FAR_SIDE, are checked to stay outside it). CONTEXT_CHECKS
     assert that land is drawn all around the extent, from Sweden to
     Alaska and New Zealand.
  4. Window (the full view): the bounding box of all quiz geometry plus a
     margin (no remote parts: at 1:50m nothing lies far enough out to need
     one); after the build, each of its sides must still be set by drawn
     quiz geometry or a marker, not by an island mapgen dropped. Around
     it, EXTENT more context is drawn (so wide or tall screens show map,
     not blank) and clipped.
  5. Projection: Lambert azimuthal equal-area centred on 20°N 110°E
     (GRS80), the middle of the set, scaled to a WIDTH-unit-wide viewBox,
     y down.
  6. (mapgen) Clip to the extent, snap to a 1/GRID grid, merge parts (cancel
     shared segments), drop tiny unshared islands, then build shared arcs so
     neighbours use identical border vertices (no gaps or overlaps).
     Context-only arcs get a light Douglas-Peucker (a stronger one outside
     the window, where context is only seen small); quiz arcs keep every
     vertex.
  7. Write map.svg (one <path> per country, relative commands, no styling)
     and countries.js (names, capitals, projected marker points).
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
import mapgen  # noqa: E402  (shared core; python3 -I keeps the script's folder off sys.path)

# ------------------------------------------------------------------ input
NE_FILE = "ne_50m_admin_0_countries.geojson"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/" + NE_FILE
NE_SHA256 = "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"
NE_BYTES = 3083490

COUNTRIES_JSON = os.path.join(HERE, "countries.json")

# ------------------------------------------------------------------ output
WIDTH = 1000.0      # viewBox width in map units (1 unit ≈ 7 km)
GRID = 10           # vertices snap to 1/GRID unit (0.1)
MARGIN = 0.03       # window margin around the quiz geometry, fraction of its width
EXTENT = (0.45, 0.45)  # context drawn around the window: fraction of its width / height per side
MIN_ISLAND = 0.3    # drop islands below this area (units^2) unless they touch another ring
CONTEXT_TOL = 0.2   # Douglas-Peucker tolerance (units) for arcs only context land uses …
FAR_TOL = 1.5       # … and for their runs of points outside the window (+ FAR_GAP): only seen small
FAR_MIN_ISLAND = 4  # context islands entirely outside the window: dropped below this (units^2)
FAR_GAP = 20        # units around the window that still count as near
FAR_SIDE = 150.0    # degrees from the projection centre: polygons reaching farther (towards the antipode,
                    # where the azimuthal projection wraps) are skipped; their nearer vertices must lie
                    # outside the extent (the extent's corners are about 100 degrees out)
EDGE_TOL = 0.5      # units: how far inside its expected place a window side may be drawn
SEAM_EPS = 1e-4     # degrees: vertices this close to ±180 lie on Natural Earth's antimeridian cut

LAT0, LON0 = 20.0, 110.0  # projection centre

HEAD = ("Generated by tools/build_map.py from tools/countries.json and Natural Earth v5.1.2 (public domain). "
        "Don't edit: change the inputs and regenerate.")

# ------------------------------------------------------------------ fix-ups
# Features that merge into a quiz country: (target, source, label).
MERGES = [("CHN", "HKG", "Hong Kong"), ("CHN", "MAC", "Macao")]
# Parts that are dropped: (country, label, lon/lat box (lon0, lat0, lon1,
# lat1): every part whose bounding box lies inside, expected count).
DROPS = [
    ("PLW", "Tobi (Southwest Islands)", (130.5, 2.5, 132.5, 4.0), 1),
]
# (lon, lat, expected owner after the fix-ups or None for no land, label).
# Context land keeps its Natural Earth code here (owner_of looks at the
# features before they are merged into one path).
VIEW_CHECKS = [
    (114.16, 22.45, "CHN", "New Territories (Hong Kong)"),
    (114.19, 22.25, "CHN", "Hong Kong Island"),
    (113.94, 22.25, "CHN", "Lantau (Hong Kong)"),
    (113.52, 22.22, "CHN", "Macao"),
    (114.06, 22.55, "CHN", "Shenzhen"),
    (118.10, 24.49, "CHN", "Xiamen"),
    (121.56, 25.04, "TWN", "Taipei"),
    (118.38, 24.46, "TWN", "Kinmen"),
    (79.50, 35.00, "CHN", "Aksai Chin"),
    (91.86, 27.59, "IND", "Tawang (Arunachal Pradesh, context land)"),
    (93.62, 27.08, "IND", "Itanagar (Arunachal Pradesh, context land)"),
    (140.72, -2.60, "IDN", "Jayapura (Western New Guinea)"),
    (125.57, -8.60, "TLS", "Dili"),
    (124.25, -9.30, "TLS", "Oecusse"),
    (124.00, -10.00, "IDN", "Kupang (West Timor)"),
    (103.82, 1.36, "SGP", "Singapore"),
    (103.70, 1.55, "MYS", "Johor Bahru"),
    (114.70, 4.55, "BRN", "Brunei (west)"),
    (115.15, 4.65, "BRN", "Temburong (Brunei, east)"),
    (134.58, 7.52, "PLW", "Babeldaob (Palau)"),
    (131.15, 3.04, None, "Tobi (dropped)"),
    (142.16, 26.67, "JPN", "Hahajima (Ogasawara)"),
    (145.85, 44.05, "RUS", "Kunashiri (Kuril islands, context land)"),
    (147.90, 45.00, "RUS", "Iturup (Kuril islands, context land)"),
    (142.80, 47.00, "RUS", "Sakhalin (context land)"),
    (123.47, 25.74, None, "Uotsuri-jima (Senkaku: not in the file)"),
]
# Context land all around the extent, (lon, lat, label): each point must
# lie in the extent and be drawn as land (in the merged context path), so a
# selection that loses land inside the extent fails the build.
CONTEXT_CHECKS = [
    (15.0, 62.0, "Sweden"),
    (25.5, 58.7, "Estonia"),
    (25.5, 56.9, "Latvia"),
    (24.0, 55.3, "Lithuania"),
    (37.6, 55.75, "Moscow"),
    (35.0, 39.0, "Türkiye"),
    (45.0, 24.0, "Saudi Arabia"),
    (77.2, 28.6, "Delhi"),
    (159.0, 55.0, "Kamchatka"),
    (172.0, 66.0, "Chukotka, west of 180°"),
    (-176.58, 66.79, "Chukotka, east of 180°"),
    (-169.65, 63.21, "St. Lawrence Island (Alaska)"),
    (-150.0, 64.0, "Alaska"),
    (145.0, -6.0, "Papua New Guinea"),
    (133.0, -20.0, "Northern Territory (Australia)"),
    (146.5, -42.0, "Tasmania"),
    (172.0, -42.0, "New Zealand (South Island)"),
]
# Land Natural Earth cuts at 180°: (lat0, lat1, label), stretches of the
# meridian inside the land; after the build no drawn edge may run within
# 1 unit of it there (the cut merged away, no line through the land).
SEAMS = [
    (65.3, 68.7, "Chukotka"),
    (71.1, 71.4, "Wrangel Island"),
]
# Boxes (lon0, lat0, lon1, lat1) with no land at all in the file, checked
# on every run (no polygon may meet them): the South China Sea's reefs and
# islets are not in Natural Earth's 1:50m admin-0 file. Should a source
# ever have them, the build stops until they are handled on purpose (as
# context land, not assigned to a quiz country).
EMPTY = [
    ("Paracel Islands", (111.0, 15.5, 113.0, 17.5)),
    ("Spratly Islands", (111.5, 7.5, 116.0, 11.6)),
    ("Scarborough Shoal", (117.5, 14.9, 118.0, 15.4)),
    ("Pratas Island", (116.5, 20.5, 117.0, 21.0)),
]


def fail(msg):
    raise mapgen.BuildError(msg)


# ------------------------------------------------------------------ steps
def load_ne(path):
    raw = mapgen.read_pinned(path, NE_SHA256, NE_BYTES, NE_URL)
    geo = {}
    for f in json.loads(raw.decode("utf-8"))["features"]:
        geo.setdefault(f["properties"]["ADM0_A3"], []).extend(mapgen.polys_of(f["geometry"]))
    return geo


def load_countries():
    with open(COUNTRIES_JSON, encoding="utf-8") as fh:
        cl = json.load(fh)["countries"]
    ids = [c["id"] for c in cl]
    if len(set(ids)) != len(ids):
        fail("countries.json: duplicate ids")
    for key in ("name", "capital"):
        vals = [c[key] for c in cl]
        if any(not v or v != v.strip() for v in vals):
            fail(f"countries.json: empty or padded {key}")
        if len(set(vals)) != len(vals):
            fail(f"countries.json: duplicate {key}")
    for c in cl:
        m = c.get("marker")
        if m is not None and not (len(m) == 2 and -180 <= m[0] <= 180 and -90 <= m[1] <= 90):
            fail(f"countries.json: bad marker for {c['id']}")
    return cl


# Boxes are (x0, y0, x1, y1) throughout: lon/lat for the rules above.
def in_box(poly, box):
    """The polygon's bounding box lies inside box."""
    x0, y0, x1, y1 = mapgen.bbox(poly[0])
    b0, c0, b1, c1 = box
    return b0 <= x0 and x1 <= b1 and c0 <= y0 and y1 <= c1


def boxes_overlap(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def segment_meets_box(p, q, box):
    """Liang-Barsky: does the segment p-q touch the box?"""
    x0, y0, x1, y1 = box
    t0, t1 = 0.0, 1.0
    dx, dy = q[0] - p[0], q[1] - p[1]
    for pk, qk in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if pk == 0:
            if qk < 0:
                return False
        else:
            t = qk / pk
            if pk < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def poly_meets_box(poly, box):
    """The polygon's outer ring and the box share a point: an edge crosses or
    touches the box, or the box lies inside the ring."""
    ring = poly[0]
    if not boxes_overlap(mapgen.bbox(ring), box):
        return False
    if any(segment_meets_box(ring[i - 1], ring[i], box) for i in range(len(ring))):
        return True
    return mapgen.in_ring(box[0], box[1], ring)


def self_test():
    """poly_meets_box on cases the EMPTY guard relies on."""
    box = (0, 0, 1, 1)
    cases = [
        ([[-1, 0.5], [2, 0.4], [2, 0.6], [-1, 0.6]], True),    # a sliver across the box, no vertex inside
        ([[-2, -2], [3, -2], [3, 3], [-2, 3]], True),           # the box inside the polygon
        ([[0.4, 0.4], [0.6, 0.4], [0.5, 0.6]], True),           # the polygon inside the box
        ([[2, 2], [3, 2], [3, 3]], False),                      # apart
        ([[1.5, -1], [3, 1], [1.5, 3]], False),                 # bounding boxes overlap, shapes don't
    ]
    for ring, want in cases:
        if poly_meets_box([ring + [ring[0]]], box) != want:
            raise ValueError(f"poly_meets_box self-test failed for {ring}")


def stitch_antimeridian(geo, notes):
    """Natural Earth cuts land at 180°: Chukotka's eastern end is its own
    polygon with a vertex every 0.24° along -180, the main Russian polygon
    has one long edge along +180 there (Wrangel Island likewise, its
    eastern part at -179.99995). mapgen.dissolve cancels only identical
    segments, so the cut would stay a drawn line through the context land.
    Vertices within SEAM_EPS of the cut move onto it, and every edge along
    it gets the cut's other vertices in between: both sides then share
    their segments (after projection +180 and -180 coincide)."""
    def on_cut(c):
        return abs(abs(c[0]) - 180) < SEAM_EPS

    lats = sorted({c[1] for polys in geo.values() for p in polys for ring in p for c in ring if on_cut(c)})
    added = 0
    for polys in geo.values():
        for p in polys:
            for k, ring in enumerate(p):
                if not any(on_cut(c) for c in ring):
                    continue
                ring = [[180.0 if c[0] > 0 else -180.0, c[1]] if on_cut(c) else c for c in ring]
                out = [ring[0]]
                for a, b in zip(ring, ring[1:]):  # GeoJSON rings are closed
                    if on_cut(a) and on_cut(b) and a[0] == b[0]:
                        lo, hi = sorted((a[1], b[1]))
                        mids = [la for la in lats if lo < la < hi]
                        out.extend([a[0], la] for la in (mids if a[1] < b[1] else mids[::-1]))
                        added += len(mids)
                    out.append(b)
                p[k] = out
    notes.append(f"antimeridian cut: {added} vertices added along 180°")


def apply_fixups(geo, notes):
    stitch_antimeridian(geo, notes)
    for label, box in EMPTY:
        for a3, polys in geo.items():
            for p in polys:
                if poly_meets_box(p, box):
                    fail(f"{label}: {a3} has land in {box}; decide how to draw it (EMPTY)")
    notes.append(f"no land in {', '.join(label for label, _ in EMPTY)} (EMPTY)")
    for tgt, src, label in MERGES:
        if src not in geo or tgt not in geo:
            fail(f"merge {src} -> {tgt}: feature missing")
        geo[tgt].extend(geo.pop(src))
        notes.append(f"{label}: {src} -> {tgt}")
    for a3, label, box, want in DROPS:
        hit = [p for p in geo[a3] if in_box(p, box)]
        if len(hit) != want:
            fail(f"drop {a3} {label}: {len(hit)} parts in {box}, expected {want}")
        geo[a3] = [p for p in geo[a3] if not any(p is h for h in hit)]
        notes.append(f"{label}: {len(hit)} part(s) of {a3} dropped")
    for lon, lat, want, label in VIEW_CHECKS:
        got = mapgen.owner_of(geo, lon, lat)
        if got != want:
            fail(f"point check: {label} ({lon}, {lat}) is in {got}, expected {want}")
    notes.append(f"{len(VIEW_CHECKS)} point checks passed")


def angle_from_centre(lon, lat):
    """Great-circle distance (degrees, on the sphere) from the projection centre."""
    p0, p1 = math.radians(LAT0), math.radians(lat)
    c = math.sin(p0) * math.sin(p1) + math.cos(p0) * math.cos(p1) * math.cos(math.radians(lon - LON0))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def reaches_extent(mb, a3, poly):
    """Whether a context polygon can show in the extent: its projected
    bounding box overlaps it. None for a polygon reaching past FAR_SIDE
    (towards the antipode, where the projection wraps and a bounding box
    means nothing): skipped, after checking that its nearer vertices lie
    outside the extent."""
    ring = poly[0]
    ex0, ey0, ex1, ey1 = mb.window.extent
    if any(angle_from_centre(c[0], c[1]) > FAR_SIDE for c in ring):
        for c in ring:
            if angle_from_centre(c[0], c[1]) <= FAR_SIDE:
                x, y = mb.view(c[0], c[1])
                if ex0 <= x <= ex1 and ey0 <= y <= ey1:
                    fail(f"{a3}: a polygon reaches past FAR_SIDE and into the extent at {c[:2]}")
        return None
    return boxes_overlap(mapgen.bbox([mb.view(c[0], c[1]) for c in ring]), mb.window.extent)


def check_context(res, mb, notes):
    """CONTEXT_CHECKS: each point inside the extent and on drawn context land."""
    g = res.grid
    rings = [mapgen.ring_from_arcs(r, res.arcs) for r in res.topo.get(mapgen.CONTEXT, [])]
    ex0, ey0, ex1, ey1 = mb.window.extent
    for lon, lat, label in CONTEXT_CHECKS:
        x, y = mb.view(lon, lat)
        if not (ex0 <= x <= ex1 and ey0 <= y <= ey1):
            fail(f"context check {label} ({lon}, {lat}): outside the extent")
        if sum(mapgen.in_ring(x * g, y * g, r) for r in rings) % 2 != 1:
            fail(f"context check {label} ({lon}, {lat}): no context land drawn there")
    notes.append(f"{len(CONTEXT_CHECKS)} context-land checks passed")
    segs = [(r[i - 1], r[i]) for r in rings for i in range(len(r))]
    for lat0, lat1, label in SEAMS:
        n = int(round((lat1 - lat0) / 0.1))
        for i in range(n + 1):
            lat = lat0 + (lat1 - lat0) * i / n
            x, y = mb.view(180.0, lat)
            if not (ex0 <= x <= ex1 and ey0 <= y <= ey1):
                fail(f"seam check {label} at {lat:.2f}°N: outside the extent")
            if min(seg_distance(x * g, y * g, a, b) for a, b in segs) < g:
                fail(f"seam check {label}: a drawn edge runs along 180° at {lat:.2f}°N (the cut wasn't merged)")
    notes.append(f"{len(SEAMS)} antimeridian seams merged")


def seg_distance(px, py, a, b):
    """Distance from (px, py) to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / ll))
    return math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))


def check_window_edges(res, window, quiz, markers, notes):
    """Each side of the window must be set by drawn quiz geometry (or a
    marker), not by a part mapgen dropped: the drawn extremes sit where the
    margin puts them, within EDGE_TOL."""
    lost = [fid for fid in quiz if fid not in res.topo]
    if lost:
        fail(f"{lost}: drawn below the grid, outside the shared topology; check the window by hand")
    g = res.grid
    pts = [(x / g, y / g) for fid in quiz for r in res.topo[fid] for x, y in mapgen.ring_from_arcs(r, res.arcs)]
    x0, y0, x1, y1 = mapgen.bbox(pts + list(markers.values()))
    m = window.width * MARGIN / (1 + 2 * MARGIN)
    for side, got, want in zip(("west", "north", "east", "south"), (x0, y0, x1, y1),
                               (m, m, window.width - m, window.height - m)):
        if abs(got - want) > EDGE_TOL:
            fail(f"window {side} side: drawn quiz geometry reaches {got:.1f}, the window expects {want:.1f} "
                 "(a part that set it was dropped)")
    notes.append("window sides set by drawn geometry")


def build(ne_path):
    notes = []
    self_test()
    project = mapgen.LambertAzimuthalEqualArea(LAT0, LON0, ellipsoid=mapgen.GRS80, name=f"LAEA {LAT0:g}N {LON0:g}E")
    countries = load_countries()
    quiz = [c["id"] for c in countries]
    geo = load_ne(ne_path)
    for a3 in quiz:
        if a3 not in geo:
            fail(f"{a3} not in {NE_FILE}")
    apply_fixups(geo, notes)

    # Window: all quiz geometry plus a margin.
    core_pts = [project(c[0], c[1]) for a3 in quiz for p in geo[a3] for c in p[0]]
    window = mapgen.Window(core_pts, MARGIN, WIDTH, EXTENT)

    # Quiz countries are regions (all inside the window: add_region checks),
    # every other polygon that reaches the extent context land; in Natural
    # Earth's order (the output depends on it).
    mb = mapgen.MapBuilder(project, window, quiz, grid=GRID, min_island=MIN_ISLAND, context_tol=CONTEXT_TOL,
                           far_tol=FAR_TOL, far_min_island=FAR_MIN_ISLAND, far_gap=FAR_GAP)
    counts = {True: 0, False: 0, None: 0}
    for a3, polys in geo.items():
        for p in polys:
            if a3 in quiz:
                mb.add_region(a3, p)
                continue
            r = reaches_extent(mb, a3, p)
            counts[r] += 1
            if r:
                mb.add_context(p)
    notes.append(f"context polygons: {counts[True]} reach the extent, {counts[False]} outside, "
                 f"{counts[None]} past FAR_SIDE (towards the antipode)")
    # Markered countries keep every island.
    res = mb.build(keep_islands={c["id"] for c in countries if c.get("marker")})
    markers = {c["id"]: mb.point(*c["marker"], f"{c['id']}: marker") for c in countries if c.get("marker")}
    check_context(res, mb, notes)
    check_window_edges(res, window, quiz, markers, notes)

    def r1(v):
        return round(v, 1)

    svg_text = mapgen.map_svg(res, quiz, HEAD, group_id="countries")
    js = [
        f"// {HEAD}",
        "//",
        "// MAP: the window (full view) is 0 0 width height in map units; extent",
        "// [x, y, w, h] is map.svg's viewBox, the context drawn around it.",
        "// COUNTRIES: the quiz set in countries.json order; marker: [x, y] in map",
        "// units, size: the larger side of the country's bounding box (map units),",
        "// for markered countries only.",
        "",
        window.map_js(),
        "",
        "export const COUNTRIES = [",
    ]
    for c in countries:
        parts = [f"id: {mapgen.js_string(c['id'])}", f"name: {mapgen.js_string(c['name'])}",
                 f"capital: {mapgen.js_string(c['capital'])}"]
        if c["id"] in markers:
            mx, my = markers[c["id"]]
            parts.append(f"marker: [{r1(mx):g}, {r1(my):g}]")
            parts.append(f"size: {r1(res.sizes[c['id']]):g}")
        js.append("  { " + ", ".join(parts) + " },")
    js += ["];", ""]
    return {"map.svg": svg_text, "countries.js": "\n".join(js)}, res.report(quiz, notes)


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("ne", help=f"path to {NE_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site"), help="output folder (default: ../site)")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out instead of writing")
    args = ap.parse_args()
    try:
        files, report = build(args.ne)
    except (mapgen.BuildError, ValueError) as e:
        sys.exit(f"build_map: {e}")
    sys.exit(mapgen.emit(files, args.out, args.check, report))


if __name__ == "__main__":
    main()
