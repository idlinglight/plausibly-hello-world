"""Planar geometry for the map generators: reading polygons (GeoJSON, WKT),
point-in-polygon, clipping, dissolving, Douglas-Peucker, shared-arc
topology. Rings are lists of (x, y); polygons are [exterior, hole, ...] as
in GeoJSON."""
import re

_WKT = re.compile(r"^\s*(?:SRID=\d+;)?\s*(MULTIPOLYGON|POLYGON)\s*(?:ZM|Z|M)?\s*(EMPTY|\(.*\))\s*$", re.I | re.S)
_WKT_TOKEN = re.compile(r"\(|\)|,|[^\s(),]+")


def polys_of(geom):
    """GeoJSON Polygon / MultiPolygon geometry -> list of polygons."""
    if geom is None:
        return []
    return [geom["coordinates"]] if geom["type"] == "Polygon" else list(geom["coordinates"])


def parse_wkt(text):
    """WKT (or EWKT, with an SRID=…; prefix) POLYGON or MULTIPOLYGON -> list of
    polygons, coordinates as (x, y) floats (a Z or M value is dropped).
    ValueError on anything else."""
    m = _WKT.match(text)
    if not m:
        raise ValueError(f"not a WKT (MULTI)POLYGON: {text[:60]!r}")
    kind, body = m.group(1).upper(), m.group(2)
    if body.upper() == "EMPTY":
        return []
    tokens = _WKT_TOKEN.findall(body)

    def nested(i):  # tokens[i] == "(" -> (list, index after the matching ")")
        i += 1
        items = []
        if tokens[i] == "(":
            while True:
                node, i = nested(i)
                items.append(node)
                if tokens[i] == ")":
                    return items, i + 1
                if tokens[i] != ",":
                    raise ValueError(f"WKT: unexpected {tokens[i]!r}")
                i += 1
        pt = []
        while True:
            t = tokens[i]
            if t in (",", ")"):
                if len(pt) < 2:
                    raise ValueError("WKT: a point needs x and y")
                items.append((pt[0], pt[1]))
                pt = []
                if t == ")":
                    return items, i + 1
            elif t == "(":
                raise ValueError("WKT: unexpected '('")
            else:
                pt.append(float(t))
            i += 1

    try:
        tree, end = nested(0)
    except IndexError:
        raise ValueError("WKT: unbalanced parentheses") from None
    if end != len(tokens):
        raise ValueError("WKT: trailing text")
    depth = 3 if kind == "MULTIPOLYGON" else 2
    node = tree
    for _ in range(depth - 1):
        if not node or not isinstance(node[0], list):
            raise ValueError(f"WKT: {kind} nesting")
        node = node[0]
    return tree if kind == "MULTIPOLYGON" else [tree]


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


def owner_of(geo, x, y):
    """geo: {id: [polygons]} -> the id containing (x, y), None, or 'A+B' if several do."""
    owners = [k for k, polys in geo.items() if any(in_polygon(x, y, p) for p in polys)]
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
    return _stitch(segs)


def _stitch(segs):
    """{(a, b): count} directed segments -> rings (closed walks), as dissolve
    stitches them; degenerate ones (under 3 points, no area) left out."""
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


def count_crossings(arcs):
    """Proper crossings between the segments of all arcs (integer points;
    segments that only touch, e.g. at a shared vertex, don't count). A
    shared-arc topology has none; simplification can make some, which
    would show as overlaps or slivers between neighbours."""
    return len(crossing_pairs(arcs))


def crossing_pairs(arcs):
    """The crossings count_crossings counts, as (arc index, arc index) per
    crossing (the lower index first; an arc crossing itself appears as
    (i, i)), sorted."""
    segs, owner = [], []
    for ai, a in enumerate(arcs):
        for p, q in zip(a, a[1:]):
            if p != q:
                segs.append((p, q))
                owner.append(ai)
    if not segs:
        return []
    # Grid buckets about four average segments wide; a pair is tested only in
    # the cell holding the low corner of their bounding boxes' overlap.
    cell = max(1, 4 * sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in segs) // len(segs))
    grid = {}
    for i, (p, q) in enumerate(segs):
        for cx in range(min(p[0], q[0]) // cell, max(p[0], q[0]) // cell + 1):
            for cy in range(min(p[1], q[1]) // cell, max(p[1], q[1]) // cell + 1):
                grid.setdefault((cx, cy), []).append(i)

    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return (v > 0) - (v < 0)

    found = []
    for (cx, cy), members in grid.items():
        for k, i in enumerate(members):
            p, q = segs[i]
            for j in members[k + 1:]:
                r, s = segs[j]
                ox, oy = max(min(p[0], q[0]), min(r[0], s[0])), max(min(p[1], q[1]), min(r[1], s[1]))
                if ox // cell != cx or oy // cell != cy:
                    continue
                if ox > min(max(p[0], q[0]), max(r[0], s[0])) or oy > min(max(p[1], q[1]), max(r[1], s[1])):
                    continue
                if p in (r, s) or q in (r, s):
                    continue
                if orient(p, q, r) * orient(p, q, s) < 0 and orient(r, s, p) * orient(r, s, q) < 0:
                    found.append(tuple(sorted((owner[i], owner[j]))))
    return sorted(found)


def cut_cells(poly, xs=(), ys=()):
    """A polygon (exterior, holes; any planar or lon/lat coordinates) cut
    along the vertical lines x = xs and horizontal lines y = ys: {(i, j):
    polygon} for the cells it reaches, i counting the xs below x, j the ys
    below y. Rectangle clipping per cell (clip_ring), so the parts of two
    neighbouring cells share their cut vertices exactly and merge again in
    a MapBuilder feature. Cells without a usable exterior are left out.
    Where a ring crosses a cut line several times, each cell's edges along
    the line are split at all the crossings there (as both neighbours have
    them), so the edges cancel pairwise when the cells merge again."""
    inf = float("inf")
    bx = [-inf] + sorted(xs) + [inf]
    by = [-inf] + sorted(ys) + [inf]
    raw = {}
    for i in range(len(bx) - 1):
        for j in range(len(by) - 1):
            rings = []
            for ri, ring in enumerate(poly):
                r = clip_ring([tuple(c[:2]) for c in open_ring(ring)], bx[i], by[j], bx[i + 1], by[j + 1])
                q = []
                for pt in r:
                    if not q or q[-1] != pt:
                        q.append(pt)
                while len(q) > 1 and q[0] == q[-1]:
                    q.pop()
                if len(set(q)) < 3 or area2(q) == 0:
                    if ri == 0:
                        break
                    continue
                rings.append(q)
            if rings and len(rings[0]) > 2:
                raw[(i, j)] = rings
    # every point on a cut line, per line: (axis, value) -> sorted coordinates along it
    on = {}
    for rings in raw.values():
        for r in rings:
            for x, y in r:
                if x in xs:
                    on.setdefault((0, x), set()).add(y)
                if y in ys:
                    on.setdefault((1, y), set()).add(x)
    on = {k: sorted(v) for k, v in on.items()}
    out = {}
    for cell, rings in raw.items():
        noded = []
        for r in rings:
            q = []
            for k, a in enumerate(r):
                b = r[(k + 1) % len(r)]
                q.append(a)
                for axis in (0, 1):
                    if a[axis] == b[axis] and (axis, a[axis]) in on:
                        lo, hi = sorted((a[1 - axis], b[1 - axis]))
                        mids = [t for t in on[(axis, a[axis])] if lo < t < hi]
                        if a[1 - axis] > b[1 - axis]:
                            mids.reverse()
                        q.extend((a[0], t) if axis == 0 else (t, a[1]) for t in mids)
            noded.append(q + q[:1])
        out[cell] = noded
    return out


def ring_from_arcs(refs, arcs):
    pts = []
    for ref in refs:
        a = arcs[ref] if ref >= 0 else arcs[~ref][::-1]
        pts.extend(a if not pts else a[1:])
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts


def clip_box(poly, box):
    """A polygon (exterior, holes; planar or lon/lat coordinates) and a
    rectangle box (x0, y0, x1, y1) -> (inside, outside): lists of polygons
    (closed rings, exterior first, counterclockwise with y up) for the part
    within the box and the rest. Only the box's own four edges cut, nothing
    beyond them; each crossing is computed once and is a vertex of both
    parts. ValueError if a vertex lies on the box's outline or an edge
    passes through its corner (move the box a little)."""
    x0, y0, x1, y1 = box
    rings = []
    for i, r in enumerate(poly):
        q = [tuple(c[:2]) for c in open_ring(r)]
        if len(q) < 3:
            continue
        if (area2(q) > 0) != (i == 0):
            q.reverse()
        rings.append(q)
    for r in rings:
        for x, y in r:
            if (x in (x0, x1) and y0 <= y <= y1) or (y in (y0, y1) and x0 <= x <= x1):
                raise ValueError(f"clip_box: vertex {(x, y)} on the box's outline")
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
    on_edge = [[] for _ in edges]
    noded = []
    for r in rings:
        out = []
        for k, a in enumerate(r):
            b = r[(k + 1) % len(r)]
            out.append(a)
            p, q = (a, b) if a <= b else (b, a)  # canonical: the same point from both directions
            hits = []
            for ei, ((ex0, ey0), (ex1, ey1)) in enumerate(edges):
                axis = 1 if ey0 == ey1 else 0  # the coordinate the edge fixes
                v = ey0 if axis else ex0
                lo, hi = sorted((ex0, ex1) if axis else (ey0, ey1))
                if (p[axis] - v) * (q[axis] - v) >= 0:
                    continue
                t = (v - p[axis]) / (q[axis] - p[axis])
                w = p[1 - axis] + t * (q[1 - axis] - p[1 - axis])
                if w in (lo, hi):
                    raise ValueError(f"clip_box: an edge through the box's corner near {(w, v)}")
                if lo < w < hi:
                    pt = (w, v) if axis else (v, w)
                    hits.append(pt)
                    on_edge[ei].append(pt)
            hits.sort(key=lambda h: (h[0] - a[0]) ** 2 + (h[1] - a[1]) ** 2)
            out.extend(hits)
        noded.append(out)
    outline = []
    for (start, _), pts in zip(edges, on_edge):
        outline.append(start)
        outline.extend(sorted(pts, key=lambda h: (h[0] - start[0]) ** 2 + (h[1] - start[1]) ** 2))
    inside, outside = {}, {}

    def add(segs, a, b):
        segs[(a, b)] = segs.get((a, b), 0) + 1
    for r in noded:
        for k, a in enumerate(r):
            b = r[(k + 1) % len(r)]
            if a == b:
                continue
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            add(inside if x0 < mx < x1 and y0 < my < y1 else outside, a, b)
    for k, a in enumerate(outline):
        b = outline[(k + 1) % len(outline)]
        if in_polygon((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, rings):
            add(inside, a, b)
            add(outside, b, a)
    return _polygons(_stitch(inside)), _polygons(_stitch(outside))


def _polygons(rings):
    """Rings (exteriors counterclockwise, holes clockwise, y up) -> polygons
    [exterior, holes...] with closed rings; each hole goes to the smallest
    exterior around it."""
    exts = sorted((r for r in rings if area2(r) > 0), key=area2)
    polys = [[r] for r in exts]
    for h in (r for r in rings if area2(r) < 0):
        mx, my = (h[0][0] + h[1][0]) / 2, (h[0][1] + h[1][1]) / 2
        owner = next((p for p in polys if in_ring(mx, my, p[0])), None)
        if owner is None:
            raise ValueError("clip_box: a hole outside every exterior")
        owner.append(h)
    return [[r + r[:1] for r in p] for p in polys]


def _seg_grid(segs, cell):
    grid = {}
    for i, (_, a, b) in enumerate(segs):
        for cx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
            for cy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                grid.setdefault((cx, cy), []).append(i)
    return grid


def _on_segment(p, a, b, eps):
    """p strictly inside segment a-b (within eps of the line, not an end)."""
    if p == a or p == b:
        return False
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    if not l2:
        return False
    px, py = p[0] - a[0], p[1] - a[1]
    along = px * dx + py * dy
    if along <= 0 or along >= l2:
        return False
    return abs(px * dy - py * dx) <= eps * l2 ** 0.5


def t_junctions(features, eps=1e-9, cell=0.5):
    """features {fid: [polygons]} (planar or lon/lat): every vertex of one
    feature lying inside an edge of another without being one of its
    vertices, as (point, vertex's fids, edge's fid), sorted. Neighbours must
    share their border vertices (else the arcs come out one-sided: slivers,
    gaps); an adapter that moves or cuts geometry asserts there are none."""
    segs, verts = [], {}
    for fid, polys in features.items():
        for p in polys:
            for r in p:
                q = open_ring([tuple(c[:2]) for c in r])
                for k, a in enumerate(q):
                    verts.setdefault(a, set()).add(fid)
                    b = q[(k + 1) % len(q)]
                    if a != b:
                        segs.append((fid, a, b))
    grid = _seg_grid(segs, cell)
    out = set()
    for pt, fids in verts.items():
        for i in grid.get((int(pt[0] // cell), int(pt[1] // cell)), ()):
            fid, a, b = segs[i]
            if fid not in fids and _on_segment(pt, a, b, eps):
                out.add((pt, tuple(sorted(fids)), fid))
    return sorted(out)


def node_points(polys, points, eps=1e-9, cell=0.5):
    """Polygons with every one of points that lies inside one of their edges
    inserted there (in order along the edge): neighbours of a cut get the
    cut's new border vertices."""
    pgrid = {}
    for pt in points:
        pgrid.setdefault((int(pt[0] // cell), int(pt[1] // cell)), []).append(pt)
    out = []
    for p in polys:
        rings = []
        for r in p:
            q = open_ring([tuple(c[:2]) for c in r])
            nr = []
            for k, a in enumerate(q):
                b = q[(k + 1) % len(q)]
                nr.append(a)
                cand = set()
                for cx in range(int(min(a[0], b[0]) // cell), int(max(a[0], b[0]) // cell) + 1):
                    for cy in range(int(min(a[1], b[1]) // cell), int(max(a[1], b[1]) // cell) + 1):
                        cand.update(pt for pt in pgrid.get((cx, cy), ()) if _on_segment(pt, a, b, eps))
                nr.extend(sorted(cand, key=lambda h: (h[0] - a[0]) ** 2 + (h[1] - a[1]) ** 2))
            rings.append(nr + nr[:1])
        out.append(rings)
    return out
