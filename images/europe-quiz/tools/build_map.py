#!/usr/bin/env python3
"""Builds site/map.svg and site/countries.js for images/europe-quiz.

usage:
  python3 -I tools/build_map.py <ne_50m_admin_0_countries.geojson> [--out DIR] [--check]

Offline, stdlib only (Python 3.9+), deterministic: the same inputs give
byte-identical outputs. --check builds in memory and exits 1 if the files in
the output folder differ (nothing is written). Details: tools/README.md.

Pipeline:
  1. Natural Earth admin-0 countries, 50m, v5.1.2 (sha256-verified).
  2. Border view (EU/Austrian): Crimea moves from Russia to Ukraine,
     Northern Cyprus merges into Cyprus, Åland into Finland; Kosovo and
     Transnistria are already as wanted. Point checks assert the result.
  3. Quiz countries (tools/countries.json) stay separate; every other
     feature becomes one merged context-land path.
  4. Window (the full view): the bounding box of all quiz geometry except
     a few remote parts (REMOTE below), plus a margin; asserts that all
     other quiz geometry lies inside it. Around it, EXTENT more context is
     drawn (so wide or tall screens show map, not blank) and clipped; only
     remote parts may be clipped there.
  5. Projection: Lambert azimuthal equal-area, EPSG:3035 parameters (GRS80),
     scaled to a WIDTH-unit-wide viewBox, y down.
  6. Clip to the extent, snap to a 1/GRID grid, merge parts (cancel shared
     segments), drop tiny unshared islands, then build shared arcs so
     neighbours use identical border vertices (no gaps or overlaps).
     Context-only arcs get a light Douglas-Peucker (a stronger one outside
     the window, where context is only seen small); quiz arcs keep every
     vertex.
  7. Write map.svg (one <path> per country, relative commands, no styling)
     and countries.js (names, capitals, projected marker points).
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import sys

# ------------------------------------------------------------------ input
NE_FILE = "ne_50m_admin_0_countries.geojson"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/" + NE_FILE
NE_SHA256 = "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"
NE_BYTES = 3083490

HERE = os.path.dirname(os.path.abspath(__file__))
COUNTRIES_JSON = os.path.join(HERE, "countries.json")

# ------------------------------------------------------------------ output
WIDTH = 1000.0      # viewBox width in map units
GRID = 10           # vertices snap to 1/GRID unit (0.1)
MARGIN = 0.03       # window margin around the quiz geometry, fraction of its width
EXTENT = (0.30, 0.45)  # context drawn around the window: fraction of its width / height per side
MIN_ISLAND = 0.3    # drop islands below this area (units^2) unless they touch another ring
CONTEXT_TOL = 0.2   # Douglas-Peucker tolerance (units) for arcs only context land uses …
FAR_TOL = 1.5       # … and for their runs of points outside the window (+ FAR_GAP): only seen small
FAR_MIN_ISLAND = 4  # context islands entirely outside the window: dropped below this (units^2)
FAR_GAP = 20        # units around the window that still count as near

# ------------------------------------------------------------------ border view
CRIMEA_POINT = (34.10, 44.95)            # Simferopol: picks the Crimea polygon out of RUS
MERGES = [("CYP", "CYN", "Northern Cyprus"), ("FIN", "ALD", "Åland")]
# (lon, lat, expected owner after the fix-ups, label)
VIEW_CHECKS = [
    (34.10, 44.95, "UKR", "Simferopol (Crimea)"),
    (33.52, 44.60, "UKR", "Sevastopol (Crimea)"),
    (37.80, 48.00, "UKR", "Donetsk"),
    (39.30, 48.57, "UKR", "Luhansk"),
    (29.63, 46.84, "MDA", "Tiraspol (Transnistria)"),
    (21.17, 42.66, "KOS", "Pristina (Kosovo)"),
    (20.47, 44.82, "SRB", "Belgrade"),
    (33.32, 35.33, "CYP", "Kyrenia (northern Cyprus)"),
    (33.94, 35.12, "CYP", "Famagusta (northern Cyprus)"),
    (19.94, 60.10, "FIN", "Mariehamn (Åland)"),
    (20.51, 54.71, "RUS", "Kaliningrad (context land)"),
]

# Remote parts of quiz countries: polygons whose bounding box lies entirely
# inside one of these lon/lat boxes don't count for the window and may be
# clipped. Every rule must match at least one polygon.
REMOTE = [
    ("PRT", "Azores, Madeira", (-180, -14), (-90, 90)),
    ("ESP", "Canary Islands", (-180, 180), (-90, 30)),
    ("FRA", "overseas departments", (-180, 180), (-90, 30)),
    ("NLD", "Caribbean Netherlands", (-180, 180), (-90, 30)),
    ("NOR", "Svalbard, Bear Island", (-180, 180), (73.5, 90)),
    ("NOR", "Jan Mayen", (-180, -5), (-90, 90)),
]
PREFILTER = ((-120, 120), (0, 90))  # lon/lat box: polygons entirely outside are skipped early

# ------------------------------------------------------------------ projection (EPSG:3035)
A = 6378137.0
F = 1 / 298.257222101
E2 = F * (2 - F)
E = math.sqrt(E2)
LAT0, LON0, FE, FN = math.radians(52), math.radians(10), 4321000.0, 3210000.0


def _q(phi):
    s = math.sin(phi)
    return (1 - E2) * (s / (1 - E2 * s * s) - (1 / (2 * E)) * math.log((1 - E * s) / (1 + E * s)))


QP = _q(math.pi / 2)
RQ = A * math.sqrt(QP / 2)
B1 = math.asin(_q(LAT0) / QP)
M1 = math.cos(LAT0) / math.sqrt(1 - E2 * math.sin(LAT0) ** 2)
D = A * M1 / (RQ * math.cos(B1))


def laea(lon, lat):
    """Snyder (1987) ellipsoidal LAEA, oblique aspect: (easting, northing) in metres."""
    lam, phi = math.radians(lon), math.radians(lat)
    beta = math.asin(_q(phi) / QP)
    dl = lam - LON0
    b = RQ * math.sqrt(2 / (1 + math.sin(B1) * math.sin(beta) + math.cos(B1) * math.cos(beta) * math.cos(dl)))
    x = b * D * math.cos(beta) * math.sin(dl)
    y = (b / D) * (math.cos(B1) * math.sin(beta) - math.sin(B1) * math.cos(beta) * math.cos(dl))
    return FE + x, FN + y


# ------------------------------------------------------------------ geometry helpers
def fail(msg):
    sys.exit("build_map: " + msg)


def polys_of(geom):
    if geom is None:
        return []
    return [geom["coordinates"]] if geom["type"] == "Polygon" else list(geom["coordinates"])


def open_ring(r):
    return r[:-1] if len(r) > 1 and r[0] == r[-1] else r


def in_ring(x, y, ring):
    inside, j = False, len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_polygon(x, y, poly):
    return in_ring(x, y, poly[0]) and not any(in_ring(x, y, h) for h in poly[1:])


def owner_of(geo, lon, lat):
    owners = [a3 for a3, polys in geo.items() if any(in_polygon(lon, lat, p) for p in polys)]
    return owners[0] if len(owners) == 1 else (None if not owners else "+".join(owners))


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def area2(ring):
    """Twice the signed area (shoelace)."""
    s = 0
    for i in range(len(ring)):
        x1, y1 = ring[i - 1]
        x2, y2 = ring[i]
        s += x1 * y2 - x2 * y1
    return s


def clip_ring(ring, xmin, ymin, xmax, ymax):
    """Sutherland-Hodgman against a rectangle. Intersections are computed in a
    canonical segment order so both neighbours of a shared edge get the same point."""
    def isect(p, q, axis, v):
        a, b = (p, q) if p <= q else (q, p)
        t = (v - a[axis]) / (b[axis] - a[axis])
        if axis == 0:
            return (v, a[1] + t * (b[1] - a[1]))
        return (a[0] + t * (b[0] - a[0]), v)

    pts = ring
    for axis, v, keep_ge in ((0, xmin, True), (0, xmax, False), (1, ymin, True), (1, ymax, False)):
        if not pts:
            break
        out = []
        for i in range(len(pts)):
            cur, prev = pts[i], pts[i - 1]
            cin = cur[axis] >= v if keep_ge else cur[axis] <= v
            pin = prev[axis] >= v if keep_ge else prev[axis] <= v
            if cin:
                if not pin:
                    out.append(isect(prev, cur, axis, v))
                out.append(cur)
            elif pin:
                out.append(isect(prev, cur, axis, v))
        pts = out
    return pts


def dissolve(rings):
    """Cancel directed segments that occur in both directions (internal borders of
    merged parts, zero-width clip bridges), then stitch the rest back into rings."""
    segs = {}
    for r in rings:
        n = len(r)
        for i in range(n):
            a, b = r[i], r[(i + 1) % n]
            if a == b:
                continue
            if segs.get((b, a), 0) > 0:
                segs[(b, a)] -= 1
            else:
                segs[(a, b)] = segs.get((a, b), 0) + 1
    nxt = {}
    for (a, b), c in segs.items():
        for _ in range(c):
            nxt.setdefault(a, []).append(b)
    out = []
    while nxt:
        start = next(iter(nxt))
        ring, cur = [start], start
        while True:
            lst = nxt.get(cur)
            if not lst:
                break
            b = lst.pop()
            if not lst:
                del nxt[cur]
            if b == start:
                break
            ring.append(b)
            cur = b
        if len(ring) >= 3 and area2(ring) != 0:
            out.append(ring)
    return out


def douglas_peucker(points, tol):
    """Douglas-Peucker on an open polyline; endpoints kept."""
    if len(points) <= 2 or tol <= 0:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    t2 = tol * tol
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = points[i], points[j]
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            px, py = points[k]
            if l2 == 0:
                d2 = (px - x1) ** 2 + (py - y1) ** 2
            else:
                c = (px - x1) * dy - (py - y1) * dx
                d2 = c * c / l2
            if d2 > best:
                best, bi = d2, k
        if best > t2:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    return [p for p, k in zip(points, keep) if k]


def build_topology(features):
    """features: {fid: [ring of int points]} -> (arcs, {fid: [[arc refs] per ring]}, uses).
    An arc runs between junctions (points whose neighbours differ between visits);
    ~i refers to arc i reversed, as in TopoJSON."""
    seen, junction, uses = {}, set(), {}
    for rings in features.values():
        for r in rings:
            n = len(r)
            for i, p in enumerate(r):
                nb = frozenset((r[i - 1], r[(i + 1) % n]))
                uses[p] = uses.get(p, 0) + 1
                if p in seen:
                    if seen[p] != nb:
                        junction.add(p)
                else:
                    seen[p] = nb
    arcs, index = [], {}

    def add_arc(pts):
        key = tuple(pts)
        if key in index:
            return index[key]
        if key[::-1] in index:
            return ~index[key[::-1]]
        arcs.append(list(pts))
        index[key] = len(arcs) - 1
        return len(arcs) - 1

    topo = {}
    for fid, rings in features.items():
        out = []
        for r in rings:
            js = [i for i, p in enumerate(r) if p in junction]
            if not js:
                # closed arc: canonical start = smallest point, so a shared ring dedupes
                m = r.index(min(r))
                rr = r[m:] + r[:m]
                fwd = tuple(rr + [rr[0]])
                rev = [rr[0]] + rr[1:][::-1]
                bwd = tuple(rev + [rev[0]])
                if bwd in index:
                    out.append([~index[bwd]])
                elif fwd in index:
                    out.append([index[fwd]])
                else:
                    arcs.append(list(fwd))
                    index[fwd] = len(arcs) - 1
                    out.append([len(arcs) - 1])
                continue
            s = js[0]
            rr = r[s:] + r[:s] + [r[s]]
            refs, start = [], 0
            for i in range(1, len(rr)):
                if rr[i] in junction:
                    refs.append(add_arc(rr[start:i + 1]))
                    start = i
            out.append(refs)
        topo[fid] = out
    return arcs, topo, uses


def simplify_arc(a, tol):
    if tol <= 0 or len(a) <= 3:
        return a
    if a[0] == a[-1]:  # closed: split at the point farthest from the start
        x0, y0 = a[0]
        k = max(range(len(a)), key=lambda i: (a[i][0] - x0) ** 2 + (a[i][1] - y0) ** 2)
        s = douglas_peucker(a[:k + 1], tol)[:-1] + douglas_peucker(a[k:], tol)
        return s if len(s) >= 4 else a
    return douglas_peucker(a, tol)


def ring_from_arcs(refs, arcs):
    pts = []
    for ref in refs:
        a = arcs[ref] if ref >= 0 else arcs[~ref][::-1]
        pts.extend(a if not pts else a[1:])
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


# ------------------------------------------------------------------ SVG path text
def fmt_fixed(v, dec):
    """Integer v in units of 10**-dec -> shortest decimal text ('-.3', '12', '4.05')."""
    neg, v = v < 0, abs(v)
    ip, fp = divmod(v, 10 ** dec)
    s = str(ip) if ip else ""
    if fp:
        s += "." + str(fp).rjust(dec, "0").rstrip("0")
    if not s:
        return "0"
    return "-" + s if neg else s


def path_d(rings, dec):
    """Rings of integer points (10**-dec units) -> compact relative path data:
    'm' + implicit relative lineto per ring, closed with 'z'."""
    out = []
    prev_num = None  # last number token, to decide whether a separator is needed

    def num(s):
        nonlocal prev_num
        if prev_num is not None and not (s[0] == "-" or (s[0] == "." and "." in prev_num)):
            out.append(" ")
        out.append(s)
        prev_num = s

    last = (0, 0)
    for r in rings:
        out.append("m")
        prev_num = None
        x0, y0 = r[0]
        num(fmt_fixed(x0 - last[0], dec))
        num(fmt_fixed(y0 - last[1], dec))
        px, py = x0, y0
        for x, y in r[1:]:
            num(fmt_fixed(x - px, dec))
            num(fmt_fixed(y - py, dec))
            px, py = x, y
        out.append("z")
        prev_num = None
        last = (x0, y0)
    return "".join(out)


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


# ------------------------------------------------------------------ steps
def load_ne(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != NE_BYTES or digest != NE_SHA256:
        fail(f"{path}: sha256 {digest} / {len(raw)} bytes, expected {NE_SHA256} / {NE_BYTES}\n"
             f"  (download: {NE_URL})")
    geo = {}
    for f in json.loads(raw.decode("utf-8"))["features"]:
        geo.setdefault(f["properties"]["ADM0_A3"], []).extend(polys_of(f["geometry"]))
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


def apply_border_view(geo, notes):
    crimea = [p for p in geo["RUS"] if in_polygon(*CRIMEA_POINT, p)]
    if len(crimea) != 1:
        fail(f"expected one Crimea polygon in RUS, found {len(crimea)}")
    geo["RUS"] = [p for p in geo["RUS"] if p is not crimea[0]]
    geo["UKR"].append(crimea[0])
    notes.append("Crimea: RUS -> UKR")
    for tgt, src, label in MERGES:
        if src not in geo or tgt not in geo:
            fail(f"merge {src} -> {tgt}: feature missing")
        geo[tgt].extend(geo.pop(src))
        notes.append(f"{label}: {src} -> {tgt}")
    for lon, lat, want, label in VIEW_CHECKS:
        got = owner_of(geo, lon, lat)
        if got != want:
            fail(f"border view check: {label} ({lon}, {lat}) is in {got}, expected {want}")
    notes.append(f"{len(VIEW_CHECKS)} border-view point checks passed")


def is_remote(a3, poly):
    x0, y0, x1, y1 = bbox(poly[0])
    for i, (rid, _, (lo0, lo1), (la0, la1)) in enumerate(REMOTE):
        if rid == a3 and lo0 <= x0 and x1 <= lo1 and la0 <= y0 and y1 <= la1:
            return i
    return None


def prefiltered(poly):
    x0, y0, x1, y1 = bbox(poly[0])
    (lo0, lo1), (la0, la1) = PREFILTER
    return x1 >= lo0 and x0 <= lo1 and y1 >= la0 and y0 <= la1


def build(ne_path):
    notes = []
    countries = load_countries()
    quiz = [c["id"] for c in countries]
    geo = load_ne(ne_path)
    for a3 in quiz:
        if a3 not in geo:
            fail(f"{a3} not in {NE_FILE}")
    apply_border_view(geo, notes)

    # Window: quiz geometry minus remote parts, plus a margin.
    remote_hits = [0] * len(REMOTE)
    core_pts = []
    for a3 in quiz:
        main = max(geo[a3], key=lambda p: abs(area2(p[0])))
        if is_remote(a3, main) is not None:
            fail(f"{a3}: its largest polygon matches a REMOTE rule")
        for p in geo[a3]:
            r = is_remote(a3, p)
            if r is None:
                core_pts.extend(laea(c[0], c[1]) for c in p[0])
            else:
                remote_hits[r] += 1
    for (rid, label, _, _), n in zip(REMOTE, remote_hits):
        if not n:
            fail(f"REMOTE rule {rid} '{label}' matches nothing")
    x0, y0, x1, y1 = bbox(core_pts)
    m = (x1 - x0) * MARGIN
    x0, y0, x1, y1 = x0 - m, y0 - m, x1 + m, y1 + m
    k = WIDTH / (x1 - x0)
    height = round((y1 - y0) * k, 1)
    W, H = WIDTH, height
    # extent: the clip rectangle and viewBox, the window at 0 0 W H inside it
    ex0, ey0 = -round(W * EXTENT[0], 1), -round(H * EXTENT[1], 1)
    ex1, ey1 = W - ex0, H - ey0

    def to_view(lon, lat):
        e, n = laea(lon, lat)
        return ((e - x0) * k, (y1 - n) * k)

    # Project, clip, snap. Features: quiz ids + 'land' (all context merged).
    features = {}
    clipped_remote = []
    for a3, polys in geo.items():
        is_quiz = a3 in quiz
        fid = a3 if is_quiz else "land"
        for p in polys:
            if not prefiltered(p):
                continue
            remote = is_remote(a3, p) if is_quiz else None
            for ri, ring in enumerate(p):
                pr = [to_view(c[0], c[1]) for c in open_ring(ring)]
                if is_quiz and remote is None and not all(0 <= x <= W and 0 <= y <= H for x, y in pr):
                    fail(f"{a3}: non-remote geometry outside the window "
                         f"(ring bbox {tuple(round(v, 1) for v in bbox(pr))}, window 0 0 {W} {H})")
                inside = all(ex0 <= x <= ex1 and ey0 <= y <= ey1 for x, y in pr)
                if not inside:
                    if is_quiz and ri == 0:
                        clipped_remote.append(f"{a3} {REMOTE[remote][1]}")
                    pr = clip_ring(pr, ex0, ey0, ex1, ey1)
                q = []
                for x, y in pr:
                    pt = (round(x * GRID), round(y * GRID))
                    if not q or q[-1] != pt:
                        q.append(pt)
                while len(q) > 1 and q[0] == q[-1]:
                    q.pop()
                if len(q) < 3 or area2(q) == 0:
                    continue
                # exterior rings clockwise on screen (positive area, y down), holes negative
                if (ri == 0) != (area2(q) > 0):
                    q.reverse()
                features.setdefault(fid, []).append(q)
    for a3 in quiz:
        if a3 not in features and a3 != "VAT":
            fail(f"{a3}: nothing left inside the window")
    for fid in list(features):
        features[fid] = dissolve(features[fid])

    near = (-FAR_GAP * GRID, -FAR_GAP * GRID, (W + FAR_GAP) * GRID, (H + FAR_GAP) * GRID)

    def far(points):
        bx0, by0, bx1, by1 = bbox(points)
        return bx1 < near[0] or bx0 > near[2] or by1 < near[1] or by0 > near[3]

    def simplify_context(a):
        """Runs of far points get FAR_TOL, the rest CONTEXT_TOL; run ends stay put."""
        flags = [far([p]) for p in a]
        if all(f == flags[0] for f in flags):
            return simplify_arc(a, (FAR_TOL if flags[0] else CONTEXT_TOL) * GRID)
        out, start = [a[0]], 0
        for i in range(1, len(a)):
            if i == len(a) - 1 or flags[i + 1] != flags[start]:
                run = a[start:i + 1]
                tol = FAR_TOL if all(flags[start:i + 1]) else CONTEXT_TOL
                out.extend(douglas_peucker(run, tol * GRID)[1:])
                start = i
        return out

    # Drop tiny islands that share no vertex with another ring (markers: keep all).
    marker_ids = {c["id"] for c in countries if c.get("marker")}
    _, _, uses = build_topology(features)
    dropped = 0
    for fid, rings in features.items():
        if fid in marker_ids or not rings:
            continue
        big = max(rings, key=lambda r: abs(area2(r)))

        def keep(r):
            if r is big or any(uses[p] > 1 for p in r):
                return True
            limit = FAR_MIN_ISLAND if fid == "land" and far(r) else MIN_ISLAND
            return abs(area2(r)) >= 2 * limit * GRID * GRID

        kept = [r for r in rings if keep(r)]
        dropped += len(rings) - len(kept)
        features[fid] = kept

    arcs, topo, _ = build_topology(features)
    arc_users = [set() for _ in arcs]
    for fid, refs in topo.items():
        for ring in refs:
            for ref in ring:
                arc_users[ref if ref >= 0 else ~ref].add(fid)
    n_before = sum(len(a) for a in arcs)
    arcs = [simplify_context(a) if users == {"land"} else a for a, users in zip(arcs, arc_users)]
    n_after = sum(len(a) for a in arcs)

    paths, sizes = {}, {}
    for fid, refs in topo.items():
        rings = [ring_from_arcs(r, arcs) for r in refs]
        rings = [r for r in rings if len(set(r)) >= 3]
        if not rings:
            continue
        paths[fid] = path_d(rings, 1)
        bx = bbox([p for r in rings for p in r])
        sizes[fid] = max(bx[2] - bx[0], bx[3] - bx[1]) / GRID

    # Countries lost to the grid (the Vatican): their own outline, 10x finer,
    # outside the shared topology. Drawn on top of the neighbour.
    for a3 in quiz:
        if a3 in paths:
            continue
        fine = []
        for p in geo[a3]:
            ring = [to_view(c[0], c[1]) for c in open_ring(p[0])]
            q = [(round(x * GRID * 10), round(y * GRID * 10)) for x, y in ring]
            if area2(q) < 0:
                q.reverse()
            fine.append(q)
        if not fine:
            fail(f"{a3}: no geometry")
        paths[a3] = path_d(fine, 2)
        bx = bbox([p for r in fine for p in r])
        sizes[a3] = max(bx[2] - bx[0], bx[3] - bx[1]) / (GRID * 10)
        notes.append(f"{a3}: below the grid, outline kept at 1/{GRID * 10} unit")

    for c in countries:
        if c.get("marker"):
            mx, my = to_view(*c["marker"])
            if not (0 <= mx <= W and 0 <= my <= H):
                fail(f"{c['id']}: marker outside the window")
    vb = f"{ex0:g} {ey0:g} {ex1 - ex0:g} {ey1 - ey0:g}"

    def r1(v):
        return round(v, 1)

    head = "Generated by tools/build_map.py from tools/countries.json and Natural Earth v5.1.2 (public domain). Don't edit: change the inputs and regenerate."
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">',
        f"<!-- {head} -->",
        f'<path id="land" d="{paths["land"]}"/>',
        '<g id="countries">',
    ]
    # Small countries last, so they sit on top of a neighbour's leftover sliver.
    for a3 in sorted(quiz, key=lambda a: (-sizes[a], a)):
        svg.append(f'<path id="{a3}" d="{paths[a3]}"/>')
    svg += ["</g>", "</svg>", ""]
    svg_text = "\n".join(svg)

    js = [
        f"// {head}",
        "//",
        "// MAP: the window (full view) is 0 0 width height in map units; extent",
        "// [x, y, w, h] is map.svg's viewBox, the context drawn around it.",
        "// COUNTRIES: the quiz set in countries.json order; marker: [x, y] in map",
        "// units, size: the larger side of the country's bounding box (map units),",
        "// for markered countries only.",
        "",
        f"export const MAP = {{ width: {W:g}, height: {H:g}, extent: [{ex0:g}, {ey0:g}, {ex1 - ex0:g}, {ey1 - ey0:g}] }};",
        "",
        "export const COUNTRIES = [",
    ]
    for c in countries:
        parts = [f"id: {js_string(c['id'])}", f"name: {js_string(c['name'])}", f"capital: {js_string(c['capital'])}"]
        if c.get("marker"):
            mx, my = to_view(*c["marker"])
            parts.append(f"marker: [{r1(mx):g}, {r1(my):g}]")
            parts.append(f"size: {r1(sizes[c['id']]):g}")
        js.append("  { " + ", ".join(parts) + " },")
    js += ["];", ""]
    js_text = "\n".join(js)

    report = {
        "window": f"0 0 {W:g} {H:g}",
        "viewBox (extent)": vb,
        "arcs": len(arcs),
        "points": f"{n_before} -> {n_after} (context-only arcs simplified)",
        "dropped islands": dropped,
        "clipped remote parts": sorted(set(clipped_remote)) or "none",
        "notes": notes,
        "smallest": sorted(((r1(sizes[a]), a) for a in quiz))[:9],
    }
    return {"map.svg": svg_text, "countries.js": js_text}, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ne", help=f"path to {NE_FILE} (Natural Earth v5.1.2)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "site"), help="output folder (default: ../site)")
    ap.add_argument("--check", action="store_true", help="compare with the files in --out instead of writing")
    args = ap.parse_args()

    e, n = laea(5, 50)  # EPSG:3035 reference point
    if abs(e - 3962799.45) > 0.01 or abs(n - 2999718.85) > 0.01:
        fail(f"projection self-test failed: {e:.2f} {n:.2f}")

    files, report = build(args.ne)
    stale = []
    for name, text in files.items():
        data = text.encode("utf-8")
        dest = os.path.join(args.out, name)
        if args.check:
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
    for key, val in report.items():
        print(f"  {key}: {val}")
    if args.check:
        if stale:
            print("out of date: " + ", ".join(stale))
            sys.exit(1)
        print("up to date")


if __name__ == "__main__":
    main()
