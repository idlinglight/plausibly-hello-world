#!/usr/bin/env python3
"""Builds site/map.svg and site/districts.js for images/vienna-districts.

usage:
  python3 -I tools/build_map.py <districts.csv> <water.csv> [--out DIR] [--check]

Offline, stdlib only (Python 3.9+), deterministic: the same inputs give
byte-identical outputs. --check builds in memory and exits 1 if the files in
the output folder differ (nothing is written). Inputs, pins and how to
download them: tools/README.md.

This file is vienna-districts' adapter: Stadt Wien's district boundaries
and water, the seed-point water selection and the checks. The geometry
(shared borders, simplification, SVG) is the shared map-quiz core,
shared/map-quiz/tools/mapgen.

Pipeline:
  1. District boundaries (ogdwien:BEZIRKSGRENZEOGD, EPSG:31256, CSV with
     WKT; sha256-pinned): 23 features, numbers 1-23, names (NAMEK) equal
     to tools/districts.json. Five come as CURVEPOLYGON with straight
     segments only (read as POLYGON; a curved segment stops the build).
  2. Water (ogdwien:REALNUT2024OGD, CODE 241 "Gewässer inkl. Bachbett"):
     pinned without its first column (the server numbers features anew
     on every request). Pieces listed in water_cut (tools/districts.json:
     ponds, side arms, basins that only lie close to a river) are taken
     out first. Pieces closer than BODY_GAP (any ring, edge to edge, or
     overlapping) form a body; the bodies holding a seed point are drawn.
     Water within BRIDGE_GAP of drawn water must be drawn or listed in
     water_out: nothing near the rivers is dropped silently.
  3. No projection: EPSG:31256 (Gauss-Krüger, central meridian 16°20'
     through Vienna) is already conformal and true to scale here; the
     window (the districts' bounding box plus MARGIN) is scaled to WIDTH
     units, y down. No context land around it.
  4. (mapgen) Snap to a 1/GRID grid, shared arcs (neighbours use identical
     border vertices), Douglas-Peucker REGION_TOL on every arc (the source
     is densified to ~0.1 m steps), 0 arc crossings asserted. Water is an
     overlay above the districts, outside the shared topology.
  5. Calm water: drawn pieces below MIN_PIECE or MIN_WIDTH are dropped
     unless that splits the water; islands below HOLE_MIN are filled; wide
     water is simplified by WIDE_TOL first. A gap between two pieces whose
     facing banks are short (a bridge, BRIDGE_SPAN) gets a patch, the hull
     of both banks; side-by-side pieces (a dam, a mole) stay apart.
     Connected pieces (touching, bridged, or closer than 0.8 of the
     outline) must be closer than WATER_STROKE in the final map.svg, so
     the overlay's outline (site/vienna.css --overlay-stroke, checked to be
     WATER_STROKE) closes what the patches leave.
  6. Borders above the water: every district edge once, chained into
     open lines (mapgen.boundary_lines with each district its own group),
     as the last overlay (<path id="borders">, stroke only in
     site/vienna.css, never hit), so the borders run on unbroken across
     the rivers. Water edges within SNAP inside a border move onto it (no
     strips of district colour between water and line).
  7. Write map.svg (one <path> per district in <g id="districts">, the
     water and the borders in <g id="overlays">) and districts.js
     (numbers, names, MAP, WATER_STROKE).
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
import mapgen  # noqa: E402  (shared core; python3 -I keeps the script's folder off sys.path)

# ------------------------------------------------------------------ input
# Stadt Wien WFS (data.wien.gv.at), downloaded 2026-11-01; CC BY 4.0
WFS = "https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0"
DISTRICTS_URL = (WFS + "&typeName=ogdwien:BEZIRKSGRENZEOGD&srsName=EPSG:31256&propertyName=SHAPE,BEZNR,NAMEK"
                 "&sortBy=BEZNR&outputFormat=csv")
DISTRICTS_SHA256 = "a739a7b22a4fd38b43e58c956ac3bdda7da1a0ebd142cc23dbfe2153ab9e63e2"
DISTRICTS_BYTES = 3819258
WATER_URL = (WFS + "&typeName=ogdwien:REALNUT2024OGD&srsName=EPSG:31256&propertyName=SHAPE,OBJECTID"
             "&cql_filter=CODE=241&sortBy=OBJECTID&outputFormat=csv")
# sha256 and size of the water file with its first CSV column (FID) cut off every line
WATER_SHA256 = "04ef8cdae7d83bd1c2aea6b6be1323633cdf85839cc6e0c500cb5543c9b04335"
WATER_BYTES = 645061

DISTRICTS_JSON = os.path.join(HERE, "districts.json")
STYLESHEET = os.path.join(HERE, "..", "site", "vienna.css")

# ------------------------------------------------------------------ output
WIDTH = 1000.0      # viewBox width in map units (1 unit ≈ 30.6 m)
GRID = 10           # vertices snap to 1/GRID unit (0.1)
MARGIN = 0.02       # window margin around the city, fraction of its width
REGION_TOL = 0.25   # Douglas-Peucker on the district borders, map units (≈ 7.7 m)
OVERLAY_TOL = 0.35  # … and on the water outlines (≈ 11 m: calm, map-like banks)
BODY_GAP = 20.0     # metres: water pieces closer than this are one body
BRIDGE_GAP = 60.0   # metres: gaps up to this between drawn pieces are looked at as bridges
BRIDGE_SPAN = 3.0   # a gap is a bridge (end to end) if the facing banks span at most this many times the
                    # narrower piece's mean width; longer facing banks are a dam or mole (side by side): no patch
BRIDGE_PAD = 8.0    # metres: a bridge patch reaches this far onto both pieces
MIN_PIECE = 1000.0  # m²: smaller drawn pieces are dropped …
MIN_WIDTH = 12.0    # … and narrower ones (metres, mean width 2·area/perimeter: bank strips, slivers),
                    # unless that would split drawn water
HOLE_MIN = 10000.0  # m²: smaller islands inside drawn water are filled
WIDE = 70.0         # metres (mean width): wide water (Danube, Neue/Alte Donau, harbours; not the Donaukanal) …
WIDE_TOL = 30.0     # … is simplified this much first (metres): calm banks without groynes and jetties
SNAP = 1.0          # map units: a water edge this close inside a district border moves onto it (no strips
                    # of district colour between the water and the border line drawn above it)
WATER_STROKE = 0.9  # map units: the water outline (vienna.css --overlay-stroke); every bridge must end up
                    # closer than this in map.svg

HEAD = ("Generated by tools/build_map.py from tools/districts.json and Stadt Wien open data "
        "(Datenquelle: Stadt Wien – data.wien.gv.at, CC BY 4.0): Bezirksgrenzen, "
        "Realnutzungskartierung 2024 (Gewässer). Don't edit: change the inputs and regenerate.")


def fail(msg):
    raise mapgen.BuildError(msg)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ------------------------------------------------------------------ reading
def read_csv(text, label, fields):
    """Rows of a CSV text as dicts; every one of fields must be a column."""
    csv.field_size_limit(1 << 30)
    try:
        rows = list(csv.DictReader(io.StringIO(text, newline="")))
    except csv.Error as e:
        fail(f"{label}: {e}")
    if not rows:
        fail(f"{label}: no rows")
    missing = [f for f in fields if f not in rows[0]]
    if missing:
        fail(f"{label}: no column {', '.join(missing)} (has {', '.join(rows[0])})")
    return rows


def decode(raw, label):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        fail(f"{label}: not UTF-8 ({e})")


_HEAD = re.compile(r"^\s*(?:SRID=\d+\s*;)?\s*([A-Za-z]+)\s*(ZM|Z|M)?\s*(.*?)\s*$", re.S | re.I)
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_shape(text, label):
    """WKT (or EWKT) POLYGON / MULTIPOLYGON -> polygons. GeoServer writes some
    rings as CURVEPOLYGON; with straight segments only that is a POLYGON. A
    curved segment (CIRCULARSTRING, COMPOUNDCURVE …) or another geometry
    type stops the build with its name."""
    if not isinstance(text, str) or not text.strip():
        fail(f"{label}: empty SHAPE")
    m = _HEAD.match(text)
    kind = m.group(1).upper() if m else "?"
    if kind == "CURVEPOLYGON":
        body = m.group(3)
        words = sorted(set(re.findall(r"[A-Za-z]+", _NUMBER.sub(" ", body))))
        if words:
            fail(f"{label}: CURVEPOLYGON with curved segments ({', '.join(words)}): not supported")
        text = "POLYGON " + (m.group(2) or "") + " " + body
    elif kind not in ("POLYGON", "MULTIPOLYGON"):
        fail(f"{label}: geometry {kind} not supported (POLYGON, MULTIPOLYGON, CURVEPOLYGON with straight segments)")
    try:
        return mapgen.parse_wkt(text)
    except ValueError as e:
        fail(f"{label}: {e}")


_FID = re.compile(r"^[A-Za-z0-9_.:-]+$")


def read_without_first_column(path, sha256, size, url):
    """The water file: the server numbers its features anew on each request
    (FID, the first column), so the pin covers the file with everything up
    to the first comma of each line removed. That cut is checked to equal
    the CSV's first field on every line: one record per line (no quoted
    line breaks), header FID, each FID plain (no comma or quote). Returns
    the normalised text (what the pin covers)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    text = decode(raw, path)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    try:
        records = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as e:
        fail(f"{path}: {e}")
    if len(records) != len(lines):
        fail(f"{path}: {len(records)} CSV records on {len(lines)} lines (a quoted line break?)")
    if not records or records[0][:1] != ["FID"]:
        fail(f"{path}: the first column is not FID")
    for i, (rec, line) in enumerate(zip(records, lines), 1):
        if not rec or not _FID.match(rec[0]) or not line.startswith(rec[0] + ","):
            fail(f"{path} line {i}: first field {rec[:1]!r} is not a plain FID")
    norm = "\n".join(line[len(rec[0]) + 1:] for rec, line in zip(records, lines))
    norm += "\n" if text.endswith("\n") else ""
    data = norm.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != size or digest != sha256:
        fail(f"{path}: without its first column sha256 {digest} / {len(data)} bytes, expected {sha256} / {size}"
             f"\n  (download: {url})")
    return norm


def load_json():
    try:
        with open(DISTRICTS_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        fail(f"districts.json: {e}")

    def need(cond, msg):
        if not cond:
            fail(f"districts.json: {msg}")

    need(isinstance(data, dict), "an object with districts, water, water_out, water_cut")
    dl, water, out, cut = data.get("districts"), data.get("water"), data.get("water_out"), data.get("water_cut")
    need(isinstance(dl, list) and all(isinstance(d, dict) for d in dl), "districts: a list of { number, name }")
    need([d.get("number") for d in dl] == list(range(1, 24)), "districts: numbers 1 … 23 in order")
    names = [d.get("name") for d in dl]
    need(all(isinstance(n, str) and n and n == n.strip() for n in names) and len(set(names)) == 23,
         "districts: names non-empty, unpadded, unique")

    def point(p):
        return isinstance(p, list) and len(p) == 2 and all(is_num(v) for v in p)

    need(isinstance(water, list) and water, "water: a list of { name, seeds }")
    for w in water:
        need(isinstance(w, dict) and isinstance(w.get("name"), str) and w["name"], "water: each with a name")
        need(isinstance(w.get("seeds"), list) and w["seeds"] and all(point(p) for p in w["seeds"]),
             f"water {w['name']}: seeds are [x, y] number pairs (EPSG:31256 metres)")
    for key, lst in (("water_out", out), ("water_cut", cut)):
        need(isinstance(lst, list), f"{key}: a list of {{ name, point }}")
        for w in lst:
            need(isinstance(w, dict) and isinstance(w.get("name"), str) and w["name"] and point(w.get("point")),
                 f"{key}: each {{ name, point: [x, y] }}")
    return dl, water, out, cut


def load_districts(path, dl):
    raw = mapgen.read_pinned(path, DISTRICTS_SHA256, DISTRICTS_BYTES, DISTRICTS_URL)
    rows = read_csv(decode(raw, path), path, ("SHAPE", "BEZNR", "NAMEK"))
    if len(rows) != 23:
        fail(f"{path}: {len(rows)} features, expected 23")
    geo = {}
    for r in rows:
        if not re.fullmatch(r"[1-9]\d?", r["BEZNR"] or ""):
            fail(f"{path}: BEZNR {r['BEZNR']!r}")
        n = int(r["BEZNR"])
        if n in geo or not 1 <= n <= 23:
            fail(f"{path}: district number {n} twice or out of range")
        want = dl[n - 1]["name"]
        if r["NAMEK"] != want:
            fail(f"{path}: district {n} is {r['NAMEK']!r} in the source (NAMEK), {want!r} in districts.json")
        geo[n] = parse_shape(r["SHAPE"], f"district {n}")
        if not geo[n]:
            fail(f"district {n}: empty geometry")
    return geo


def load_water(path):
    rows = read_csv(read_without_first_column(path, WATER_SHA256, WATER_BYTES, WATER_URL), path, ("OBJECTID", "SHAPE"))
    polys = []
    for r in rows:
        polys.extend(parse_shape(r["SHAPE"], f"water OBJECTID {r['OBJECTID']}"))
    if not polys:
        fail(f"{path}: no water")
    return polys


# ------------------------------------------------------------------ distances
def _seg_d2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx or dy:
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        if t > 1:
            ax, ay = bx, by
        elif t > 0:
            ax, ay = ax + dx * t, ay + dy * t
    return (px - ax) ** 2 + (py - ay) ** 2


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def seg_seg_d2(p, q, r, s):
    """Squared distance between segments pq and rs (0 if they cross or touch)."""
    d1, d2, d3, d4 = _cross(p, q, r), _cross(p, q, s), _cross(r, s, p), _cross(r, s, q)
    if ((d1 > 0) != (d2 > 0) and d1 and d2) and ((d3 > 0) != (d4 > 0) and d3 and d4):
        return 0.0
    return min(_seg_d2(*p, *r, *s), _seg_d2(*q, *r, *s), _seg_d2(*r, *p, *q), _seg_d2(*s, *p, *q))


def _edges(rings, box, limit):
    """Edges of rings with a bounding box within limit of box."""
    x0, y0, x1, y1 = box[0] - limit, box[1] - limit, box[2] + limit, box[3] + limit
    out = []
    for r in rings:
        for i in range(len(r)):
            a, b = r[i - 1], r[i]
            if max(a[0], b[0]) >= x0 and min(a[0], b[0]) <= x1 and max(a[1], b[1]) >= y0 and min(a[1], b[1]) <= y1:
                out.append((a, b))
    return out


def poly_gap(a, b, limit):
    """Distance between polygons a and b (lists of rings: exterior, holes),
    edge to edge over all rings, 0 if they overlap; None if above limit."""
    ba, bb = mapgen.bbox(a[0]), mapgen.bbox(b[0])
    if ba[0] - limit > bb[2] or bb[0] - limit > ba[2] or ba[1] - limit > bb[3] or bb[1] - limit > ba[3]:
        return None
    ea, eb = _edges(a, bb, limit), _edges(b, ba, limit)
    best = limit * limit
    found = False
    for p, q in ea:
        px0, px1, py0, py1 = min(p[0], q[0]) - limit, max(p[0], q[0]) + limit, min(p[1], q[1]) - limit, max(p[1], q[1]) + limit
        for r, s in eb:
            if max(r[0], s[0]) < px0 or min(r[0], s[0]) > px1 or max(r[1], s[1]) < py0 or min(r[1], s[1]) > py1:
                continue
            d = seg_seg_d2(p, q, r, s)
            if d <= best:
                best, found = d, True
                if d == 0:
                    return 0.0
    if found:
        return math.sqrt(best)
    # no edges near each other: one may lie inside the other
    if mapgen.in_polygon(*a[0][0], b) or mapgen.in_polygon(*b[0][0], a):
        return 0.0
    return None


def near_pairs(polys, limit):
    """{(i, j): gap} for polygons closer than limit, i < j."""
    boxes = [mapgen.bbox(p[0]) for p in polys]
    order = sorted(range(len(polys)), key=lambda i: boxes[i][0])
    pairs = {}
    for k, i in enumerate(order):
        for j in order[k + 1:]:
            if boxes[j][0] - limit > boxes[i][2]:
                break
            d = poly_gap(polys[i], polys[j], limit)
            if d is not None:
                pairs[(min(i, j), max(i, j))] = d
    return pairs


# ------------------------------------------------------------------ water selection
def select_water(polys, groups, out, cut, notes):
    """Indices of the polygons of every body (pieces closer than BODY_GAP)
    that holds a seed point, in file order, and the near pairs ({(i, j): gap},
    metres) among all pieces not cut. water_cut pieces are taken out first:
    they never join a body or count as near water. A body within BRIDGE_GAP
    of drawn water must be drawn or in water_out."""
    polys = [[mapgen.open_ring(r) for r in p] for p in polys]

    def piece_at(x, y, label):
        hits = [i for i, p in enumerate(polys) if mapgen.in_polygon(x, y, p)]
        if len(hits) != 1:
            fail(f"{label}: in {len(hits)} water polygons, expected 1 (tools/README.md, re-pin)")
        return hits[0]

    cut_at = {}
    for w in cut:
        i = piece_at(*w["point"], f"districts.json water_cut {w['name']} ({w['point'][0]:g}, {w['point'][1]:g})")
        if i in cut_at:
            fail(f"districts.json water_cut {w['name']}: same piece as {cut_at[i]}")
        cut_at[i] = w["name"]
    pairs = {k: d for k, d in near_pairs(polys, BRIDGE_GAP).items() if k[0] not in cut_at and k[1] not in cut_at}
    parent = list(range(len(polys)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (i, j), d in sorted(pairs.items()):
        if d < BODY_GAP:
            a, b = find(i), find(j)
            parent[max(a, b)] = min(a, b)
    body = [find(i) for i in range(len(polys))]

    def body_at(x, y, label):
        i = piece_at(x, y, label)
        if i in cut_at:
            fail(f"{label}: in a water_cut piece ({cut_at[i]})")
        return body[i]

    picked = {}  # body -> label
    for g in groups:
        for k, (x, y) in enumerate(g["seeds"], 1):
            label = f"districts.json water {g['name']} seed {k} ({x:g}, {y:g})"
            b = body_at(x, y, label)
            if b in picked:
                fail(f"{label}: same body as {picked[b]}")
            picked[b] = f"{g['name']} seed {k}"
    left_out = {}
    for w in out:
        label = f"districts.json water_out {w['name']} ({w['point'][0]:g}, {w['point'][1]:g})"
        b = body_at(*w["point"], label)
        if b in picked:
            fail(f"{label}: that body is drawn ({picked[b]})")
        left_out[b] = w["name"]

    area, where = {}, {}
    for i, p in enumerate(polys):
        if i in cut_at:
            continue
        area[body[i]] = area.get(body[i], 0) + abs(mapgen.area2(p[0])) / 2
        where.setdefault(body[i], tuple(round(v) for v in p[0][0]))
    near = {}  # undrawn body -> closest gap to drawn water
    for (i, j), d in pairs.items():
        bi, bj = body[i], body[j]
        if (bi in picked) != (bj in picked):
            o = bj if bi in picked else bi
            near[o] = min(d, near.get(o, d))
    unlisted = sorted((round(d), b) for b, d in near.items() if b not in left_out)
    if unlisted:
        fail("water near drawn water but neither drawn nor in water_out (add a seed to draw it, or a "
             "water_out point to leave it out): " + "; ".join(
                 f"{area[b] / 1e4:.2f} ha at {where[b]}, {d} m from drawn water" for d, b in unlisted))
    stale = sorted(n for b, n in left_out.items() if b not in near)
    if stale:
        notes.append("water_out no longer near drawn water (could go): " + ", ".join(stale))

    keep = [i for i in range(len(polys)) if body[i] in picked and i not in cut_at]
    bridges = sorted(d for (i, j), d in pairs.items() if body[i] != body[j] and body[i] in picked and body[j] in picked)
    notes.append(f"water: {len(picked)} bodies ({len(keep)} of {len(polys)} polygons, "
                 f"{sum(area[b] for b in picked) / 1e4:.0f} ha) from {len(picked)} seeds; "
                 f"{len(left_out)} near bodies left out (water_out), {len(cut_at)} pieces cut (water_cut)")
    notes.append(f"water: {len(bridges)} gaps under {BRIDGE_GAP:g} m between drawn bodies" +
                 (f", widest {', '.join(f'{d:.0f}' for d in bridges[-4:])} m" if bridges else ""))
    largest = sorted(((a, b) for b, a in area.items() if b not in picked), reverse=True)[:5]
    if largest:
        notes.append("water left out, largest: " + ", ".join(f"{a / 1e4:.1f} ha at {where[b]}" for a, b in largest))
    return keep, pairs


# ------------------------------------------------------------------ calm water
def _hull(points):
    """Convex hull (Andrew's monotone chain), counter-clockwise, no repeats."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and _cross(h[-2], h[-1], p) <= 0:
                h.pop()
            h.append(p)
        return h[:-1]

    return half(pts) + half(pts[::-1])


def _facing(a, b, reach):
    """Vertices of ring a within reach (metres) of ring b."""
    bx = mapgen.bbox(b)
    edges = _edges([b], mapgen.bbox(a), reach)
    r2 = reach * reach
    return [p for p in a if bx[0] - reach <= p[0] <= bx[2] + reach and bx[1] - reach <= p[1] <= bx[3] + reach
            and any(_seg_d2(*p, *e[0], *e[1]) <= r2 for e in edges)]


def tidy_water(polys, keep, pairs, stroke_m, notes):
    """Calm, connected water from the drawn pieces (polys: open rings):
    bridges, patches and the pieces left after dropping small and narrow ones.
    A gap between two pieces is a bridge if their facing banks are short
    (BRIDGE_SPAN): a patch, the hull of both banks, closes it; side-by-side
    pieces (a dam, a mole, a lock beside a weir) stay apart. Pieces below
    MIN_PIECE or MIN_WIDTH are dropped, smallest first, unless that would split
    the water connected through touching, bridges or gaps the outline closes
    anyway (under 0.8 of its width, stroke_m metres). Returns (pieces,
    connections [(i, j)], patches [ring]): the connections must stay closed
    in map.svg."""
    area = {i: abs(mapgen.area2(polys[i][0])) / 2 for i in keep}
    width = {i: 2 * area[i] / sum(math.dist(polys[i][0][k - 1], polys[i][0][k]) for k in range(len(polys[i][0])))
             for i in keep}
    bridge_cache = {}

    def bridge(i, j, d):
        key = (min(i, j), max(i, j))
        if key not in bridge_cache:
            fi = _facing(polys[i][0], polys[j][0], d + BRIDGE_PAD)
            fj = _facing(polys[j][0], polys[i][0], d + BRIDGE_PAD)
            both = fi + fj
            span = max((math.dist(p, q) for k, p in enumerate(both) for q in both[k + 1:]), default=0.0)
            bridge_cache[key] = (span <= BRIDGE_SPAN * min(width[i], width[j]), both)
        return bridge_cache[key]

    def connections(alive):
        return [(i, j) for (i, j), d in pairs.items()
                if i in alive and j in alive and (d < 0.8 * stroke_m or bridge(i, j, d)[0])]

    def components(alive):
        parent = {i: i for i in alive}

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        for i, j in connections(alive):
            parent[find(i)] = find(j)
        return find

    alive = set(keep)
    kept_small = []
    for c in sorted((i for i in keep if area[i] < MIN_PIECE or width[i] < MIN_WIDTH), key=lambda i: (area[i], i)):
        before = components(alive)
        group = {i for i in alive if i != c and before(i) == before(c)}
        after = components(alive - {c})
        if len({after(i) for i in group}) > 1:
            kept_small.append(c)
            continue
        alive.discard(c)
    pieces = [i for i in keep if i in alive]
    conns = connections(alive)
    patches = []
    for i, j in conns:
        d = pairs[(i, j)]
        if d > 0 and bridge(i, j, d)[0]:
            hull = _hull(bridge(i, j, d)[1])
            if len(hull) >= 3:
                patches.append(hull)
    dropped = len(keep) - len(pieces)
    notes.append(f"water tidied: {dropped} small or narrow pieces dropped"
                 + (f" ({len(kept_small)} kept, they connect water)" if kept_small else "")
                 + f", {len(patches)} bridges patched, {len(conns)} connections the outline must keep closed, "
                 f"{sum(1 for (i, j) in pairs if i in alive and j in alive) - len(conns)} side-by-side gaps left open")
    return pieces, conns, patches


def calm_polygon(poly):
    """The polygon with its small islands (holes below HOLE_MIN) filled; wide
    water (mean width WIDE or more) simplified by WIDE_TOL."""
    rings = [poly[0]] + [h for h in poly[1:] if abs(mapgen.area2(h)) / 2 >= HOLE_MIN]
    a = abs(mapgen.area2(poly[0])) / 2
    per = sum(math.dist(poly[0][k - 1], poly[0][k]) for k in range(len(poly[0])))
    if 2 * a / per < WIDE:
        return rings
    out = []
    for r in rings:
        q = mapgen.simplify_arc(r + [r[0]], WIDE_TOL)[:-1]
        out.append(q if len(q) >= 3 and mapgen.area2(q) else r)
    return out


# ------------------------------------------------------------------ final water gaps
_PATH_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)")


def path_rings(d, grid):
    """mapgen path data (relative 'm…z' rings) -> rings of integer points."""
    out, last = [], (0, 0)
    for part in re.findall(r"m([^z]*)z", d):
        v = [round(float(t) * grid) for t in _PATH_NUM.findall(part)]
        x, y = last[0] + v[0], last[1] + v[1]
        ring = [(x, y)]
        for i in range(2, len(v), 2):
            x, y = x + v[i], y + v[i + 1]
            ring.append((x, y))
        out.append(ring)
        last = ring[0]
    return out


def final_gaps(polys, keep, links, water_d, window):
    """How wide the outline must be so that connected pieces (touching or
    bridged) read as one on the page: for each such pair, the widest gap
    on the best chain of map.svg rings between the rings they ended up in
    (a bottleneck; 0 for the same ring), in map units; the largest of
    these, where, and how many pieces weren't found. A piece's ring is the
    outer ring most of its (projected) vertices lie on, or the one around
    it if its outline dissolved into a neighbour."""
    g = GRID
    rings = [r for r in path_rings(water_d, g) if mapgen.area2(r) > 0]
    boxes = [mapgen.bbox(r) for r in rings]
    cell = 4 * g
    index = {}
    for k, r in enumerate(rings):
        for i in range(len(r)):
            a, b = r[i - 1], r[i]
            for cx in range(min(a[0], b[0]) // cell, max(a[0], b[0]) // cell + 1):
                for cy in range(min(a[1], b[1]) // cell, max(a[1], b[1]) // cell + 1):
                    index.setdefault((cx, cy), []).append((k, a, b))
    tol2 = (0.6 * g) ** 2  # simplification (OVERLAY_TOL) plus snapping, with room

    def ring_of(i):
        ext = polys[i][0]
        step = max(1, len(ext) // 24)
        votes = {}
        for x, y in ext[::step]:
            vx, vy = window.to_view(x, y)
            px, py = vx * g, vy * g
            best = None
            for k, a, b in index.get((int(px // cell), int(py // cell)), ()):
                d = _seg_d2(px, py, *a, *b)
                if d <= tol2 and (best is None or d < best[0]):
                    best = (d, k)
            if best:
                votes[best[1]] = votes.get(best[1], 0) + 1
        if votes:
            return max(sorted(votes), key=votes.get)
        # its outline dissolved (it filled another piece's hole): the ring around it
        vx, vy = window.to_view(*ext[0])
        inside = [k for k, (r, bx) in enumerate(zip(rings, boxes))
                  if bx[0] <= vx * g <= bx[2] and bx[1] <= vy * g <= bx[3] and mapgen.in_ring(vx * g, vy * g, r)]
        return inside[0] if len(inside) == 1 else None

    ring = {i: ring_of(i) for i in keep}
    lost = [i for i in keep if ring[i] is None]
    # Kruskal over the map.svg rings: a link is closed by the gap that
    # first joins its two rings.
    edges = sorted((d / g, a, b) for (a, b), d in near_pairs([[r] for r in rings], 3 * WATER_STROKE * g).items())
    parent = list(range(len(rings)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    pending = {(min(ring[i], ring[j]), max(ring[i], ring[j])) for i, j in links
               if ring[i] is not None and ring[j] is not None and ring[i] != ring[j]}
    worst = (0.0, None)
    for d, a, b in edges:
        if not pending:
            break
        if find(a) != find(b):
            parent[find(a)] = find(b)
            done = {p for p in pending if find(p[0]) == find(p[1])}
            if done:
                worst = (d, rings[a][0])
                pending -= done
    if pending:
        worst = (math.inf, rings[min(pending)[0]][0])
    return worst, len(lost)


def snap_to_borders(water_d, lines, dec):
    """Water path data with every vertex that lies within SNAP inside of a
    district border (the nearest border point outside its ring: water would
    stop short of the line) moved onto that border, and between two such
    neighbours on the same border line the water edge follows the line's
    own vertices. Only outward, so water never shrinks and a border inside
    the water (mid-river) is left alone. Returns (path data, vertices moved)."""
    g = 10 ** dec
    tol = SNAP * g
    cell = 2 * g
    index = {}
    for li, line in enumerate(lines):
        for si, (a, b) in enumerate(zip(line, line[1:])):
            for cx in range(min(a[0], b[0]) // cell, max(a[0], b[0]) // cell + 1):
                for cy in range(min(a[1], b[1]) // cell, max(a[1], b[1]) // cell + 1):
                    index.setdefault((cx, cy), []).append((li, si, a, b))

    def nearest(x, y):
        best = None
        for cx in range(int((x - tol) // cell), int((x + tol) // cell) + 1):
            for cy in range(int((y - tol) // cell), int((y + tol) // cell) + 1):
                for li, si, (ax, ay), (bx, by) in index.get((cx, cy), ()):
                    dx, dy = bx - ax, by - ay
                    t = 0.0 if not (dx or dy) else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
                    qx, qy = ax + t * dx, ay + t * dy
                    d2 = (qx - x) ** 2 + (qy - y) ** 2
                    if d2 <= tol * tol and (best is None or (d2, li, si) < best[:3]):
                        best = (d2, li, si, t, (round(qx), round(qy)))
        return best

    rings, moved = [], 0
    for ring in path_rings(water_d, g):
        outer = mapgen.area2(ring) > 0
        pts, where = [], []
        for x, y in ring:
            hit = nearest(x, y)
            if hit and hit[4] != (x, y) and mapgen.in_ring(hit[4][0], hit[4][1], ring) != outer:
                pts.append(hit[4])
                where.append((hit[1], hit[2] + hit[3]))  # line, position along it
                moved += 1
            else:
                pts.append((x, y))
                where.append(None)
        new = []
        n = len(pts)
        for k in range(n):
            new.append(pts[k])
            a, b = where[k], where[(k + 1) % n]
            if a and b and a[0] == b[0]:
                line = lines[a[0]]
                lo, hi = sorted((a[1], b[1]))
                between = line[int(lo) + 1:int(hi) + 1] if hi > int(lo) + 1 else []
                if a[1] > b[1]:
                    between = between[::-1]
                run = sum(math.dist(p, q) for p, q in zip([pts[k]] + between, between + [pts[(k + 1) % n]]))
                if between and run <= 3 * math.dist(pts[k], pts[(k + 1) % n]) + 2 * g and len(between) <= 60:
                    new.extend(between)
        new = [p for k, p in enumerate(new) if p != new[k - 1]]
        ok = len(set(new)) >= 3 and (mapgen.area2(new) > 0) == outer
        rings.append(new if ok else ring)
    return mapgen.path_d(rings, dec), moved


def check_stylesheet():
    with open(STYLESHEET, encoding="utf-8") as fh:
        css = fh.read()
    vals = re.findall(r"--overlay-stroke:\s*([\d.]+)px", css)
    if not vals or any(float(v) != WATER_STROKE for v in vals):
        fail(f"site/vienna.css: --overlay-stroke {vals or 'missing'}, expected {WATER_STROKE:g}px (WATER_STROKE)")


# ------------------------------------------------------------------ build
def build(districts_path, water_path):
    notes = []
    check_stylesheet()
    dl, groups, out, cut = load_json()
    geo = load_districts(districts_path, dl)
    polys = load_water(water_path)
    keep, pairs = select_water(polys, groups, out, cut, notes)
    ids = [f"d{d['number']:02d}" for d in dl]
    window = mapgen.Window([p for n in sorted(geo) for poly in geo[n] for p in poly[0]], MARGIN, WIDTH, (0, 0))
    opened = [[mapgen.open_ring(r) for r in p] for p in polys]
    pieces, links, patches = tidy_water(opened, keep, pairs, WATER_STROKE / window.k, notes)
    mb = mapgen.MapBuilder(mapgen.Identity(), window, ids, grid=GRID, region_tol=REGION_TOL,
                           overlay_tol=OVERLAY_TOL)
    for d, rid in zip(dl, ids):
        for poly in geo[d["number"]]:
            mb.add_region(rid, poly)
    for i in pieces:
        mb.add_overlay("water", calm_polygon(opened[i]))
    for ring in patches:
        mb.add_overlay("water", [ring])
    res = mb.build()

    if res.stats["crossings"]:
        fail(f"{res.stats['crossings']} arc crossings after simplification (REGION_TOL {REGION_TOL} too coarse?)")
    if res.stats["notes"]:
        fail("districts below the grid: " + "; ".join(res.stats["notes"]))
    for rid in ids:
        n = res.paths[rid].count("m")
        if n != 1:
            fail(f"{rid}: {n} rings, expected one outline")
    if "water" not in res.overlays:
        fail("no water left to draw")
    # The borders once more, above the water (an overlay: never hit), so they
    # run on unbroken where the river covers them; the water reaches them.
    lines = mapgen.boundary_lines(res, {rid: rid for rid in ids})
    res.overlays["water"], moved = snap_to_borders(res.overlays["water"], lines, res.dec)
    res.overlays["borders"] = mapgen.lines_d(lines, res.dec)
    notes.append(f"borders: {len(lines)} lines, {sum(len(ln) for ln in lines)} points, drawn above the water; "
                 f"{moved} water vertices moved onto a border")
    (gap, at), lost = final_gaps(opened, pieces, links, res.overlays["water"], window)
    if lost:
        fail(f"{lost} drawn water pieces not found in map.svg's water (dropped as specks?)")
    if gap >= WATER_STROKE:
        where = f" near {at[0] / GRID:g}, {at[1] / GRID:g}" if at else ""
        fail(f"water: a gap of {gap:.2f} units{where} in map.svg separates connected pieces (touching or bridged); "
             f"the {WATER_STROKE:g}-unit outline doesn't close it")
    notes.append(f"water: widest gap in map.svg the outline has to close: {gap:.2f} units (outline {WATER_STROKE:g})")
    svg_text = mapgen.map_svg(res, ids, HEAD, group_id="districts")
    js = [
        f"// {HEAD}",
        "//",
        "// MAP: the window (full view) is 0 0 width height in map units (1 unit is",
        f"// about {1 / window.k:.1f} m); nothing is drawn around it, so extent = window.",
        "// DISTRICTS: number and official name, in number order; id d01 … d23 is the",
        "// district's <path> in map.svg.",
        "// WATER_STROKE: the water outline in map units that closes every gap",
        "// between drawn water; site/vienna.css --overlay-stroke must be this.",
        "",
        window.map_js(),
        "",
        "export const DISTRICTS = [",
    ]
    for d, rid in zip(dl, ids):
        js.append(f"  {{ id: {mapgen.js_string(rid)}, number: {d['number']}, name: {mapgen.js_string(d['name'])} }},")
    js += ["];", "", f"export const WATER_STROKE = {WATER_STROKE:g};", ""]
    return {"map.svg": svg_text, "districts.js": "\n".join(js)}, res.report(ids, notes)


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("districts", help="ogdwien:BEZIRKSGRENZEOGD as CSV (tools/README.md)")
    ap.add_argument("water", help="ogdwien:REALNUT2024OGD, CODE=241, as CSV (tools/README.md)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site"), help="output folder (default: ../site)")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out instead of writing")
    args = ap.parse_args()
    try:
        files, report = build(args.districts, args.water)
    except (mapgen.BuildError, OSError) as e:
        sys.exit(f"build_map: {e}")
    sys.exit(mapgen.emit(files, args.out, args.check, report))


if __name__ == "__main__":
    main()
