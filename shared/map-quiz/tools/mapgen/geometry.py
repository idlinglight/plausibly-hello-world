"""Planar geometry for the map generators: point-in-polygon, clipping,
dissolving, Douglas-Peucker, shared-arc topology. Rings are lists of (x, y);
polygons are [exterior, hole, ...] as in GeoJSON."""


def polys_of(geom):
    """GeoJSON Polygon / MultiPolygon geometry -> list of polygons."""
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
