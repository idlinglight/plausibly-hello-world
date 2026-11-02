"""Polyhedral projections: the sphere cut along the edges of an icosahedron,
each face mapped onto a plane equilateral triangle, the triangles laid out
as a net. AIROCEAN is Buckminster Fuller's net (the Dymaxion / "Airocean"
world map, 1954 icosahedral version): his icosahedron orientation puts all
12 vertices in the sea, and two faces are split so continents stay whole.

A net is discontinuous, so a polygon can't be projected vertex by vertex.
Polyhedral.split(poly) clips each ring on the sphere against every piece of
the net (convex spherical triangles, great-circle edges), places each part
by its piece's transform and returns planar polygons for a MapBuilder with
mapgen.Identity(). Points where a ring crosses a piece's edge are computed
once per (edge, ring segment) and placed through the edge's endpoints, so
the parts of one polygon on two pieces that meet in the net share their
fold vertices exactly and the builder's dissolve merges them; along a cut
they stay apart. Polyhedral(lon, lat) projects a single point (a marker).

Face transforms (template: face centre at the local z axis, vertex a up;
plane triangle with unit edges, centroid at the origin):
  GNOMONIC: central projection onto the face plane. Great circles become
    straight lines; areas grow towards the vertices (0.83 to 1.63 of the
    mean), shapes stay closest to true (axes at most 1.25 : 1).
  FULLER: Fuller's own transformation, in Robert W. Gray's exact equations
    ("Exact Transformation Equations for Fuller's World Map", Cartographica
    32(3): 17-25, 1995). Edges keep their arc lengths; areas within 0.95 to
    1.08 of the mean, axes at most 1.26 : 1.
  SNYDER: Snyder's equal-area polyhedral projection ("An Equal-Area Map
    Projection for Polyhedral Globes", Cartographica 29(1): 10-21, 1992),
    as in ISEA: equal area, shapes sheared most near the edges (axes at
    most 1.35 : 1), kinks where the face's thirds meet.

Sources: the vertex coordinates and the net (face numbering, which faces
fold together, the split faces 9 and 16) follow Gray's published
description of Fuller's map (rwgrayprojects.com, "Fuller's World Map:
Coordinates" and "Source Code For Coordinate Transformation"); they agree
with d3-geo-polygon's geoAirocean (ISC, Jason Davies, Enrico Spinielli,
Philippe Rivière) to 0.25 arc seconds. The FULLER face formulas follow
Philippe Rivière's public-domain port of Gray's equations in d3-geo-polygon
(src/grayfuller.js). The code here is written anew (Python, stdlib)."""
import math

from .output import BuildError

_S3 = math.sqrt(3.0)
_S5 = math.sqrt(5.0)

# ------------------------------------------------------------------ the icosahedron
# Fuller's orientation in Gray's coordinates (vertex numbers as Gray's; 7..12
# are the antipodes of 4, 5, 6, 2, 3, 1). Vertex 1 is 64.7N 10.5362E, vertex 4
# 39.1N 122.3E.
_V = {
    1: (0.420152426708710003, 0.078145249402782959, 0.904082550615019298),
    2: (0.995009439436241649, -0.091347795276427931, 0.040147175877166645),
    3: (0.518836730327364437, 0.835420380378235850, 0.181331837557262454),
    4: (-0.414682225320335218, 0.655962405434800777, 0.630675807891475371),
    5: (-0.515455959944041808, -0.381716898287133011, 0.767200992517747538),
    6: (0.355781402532944713, -0.843580002466178147, 0.402234226602925571),
}
for _v, _w in ((7, 4), (8, 5), (9, 6), (10, 2), (11, 3), (12, 1)):
    _V[_v] = tuple(-c for c in _V[_w])
VERTICES = dict(_V)

# Gray's face numbers and their vertices.
FACES = {
    1: (1, 3, 2), 2: (1, 4, 3), 3: (1, 5, 4), 4: (1, 6, 5), 5: (1, 2, 6), 6: (2, 3, 8), 7: (3, 9, 8),
    8: (3, 4, 9), 9: (4, 10, 9), 10: (4, 5, 10), 11: (5, 11, 10), 12: (5, 6, 11), 13: (6, 7, 11),
    14: (2, 7, 6), 15: (2, 8, 7), 16: (8, 9, 12), 17: (9, 10, 12), 18: (10, 11, 12), 19: (11, 7, 12),
    20: (8, 12, 7),
}

# Angles of the face triangles (unit sphere): centre to vertex (g), edge arc,
# the plane face's edge (chord) and the distance of an edge's midpoint from
# the sphere's centre.
COS_G = math.sqrt((5 + 2 * _S5) / 15)
G = math.acos(COS_G)
EDGE_ARC = math.atan(2.0)
CHORD = math.sqrt(8) / math.sqrt(5 + _S5)
DVE = math.sqrt(3 + _S5) / math.sqrt(5 + _S5)

# Fuller's net, as Gray draws it (x right, y up, edge 1): (piece, face,
# parent piece, parts). A piece folds onto its parent across their shared
# edge; parts (corners: vertex numbers, ("c", face) the face's centre,
# ("m", a, b) the midpoint of edge a-b) are convex spherical triangles,
# None = the whole face. Face 9 is split at its centre (a third, 9b, goes
# with face 10), face 16 along its median from vertex 8 (16a with face 17,
# 16b with 20). ROOT places face 1.
AIROCEAN = (
    ("1", 1, None, None),
    ("2", 2, "1", None),
    ("3", 3, "2", None),
    ("4", 4, "3", None),
    ("5", 5, "1", None),
    ("6", 6, "1", None),
    ("8", 8, "2", None),
    ("7", 7, "8", None),
    ("9a", 9, "8", ((("c", 9), 10, 9), (("c", 9), 9, 4))),
    ("17", 17, "9a", None),
    ("16a", 16, "17", ((8, 9, ("m", 9, 12)),)),
    ("10", 10, "3", None),
    ("9b", 9, "10", ((4, 10, ("c", 9)),)),
    ("12", 12, "4", None),
    ("11", 11, "12", None),
    ("18", 18, "11", None),
    ("13", 13, "12", None),
    ("14", 14, "13", None),
    ("19", 19, "13", None),
    ("20", 20, "19", None),
    ("15", 15, "20", None),
    ("16b", 16, "20", ((8, ("m", 9, 12), 12),)),
)
AIROCEAN_ROOT = {1: (2.5, _S3), 2: (2.0, 1.5 * _S3), 3: (1.5, _S3)}


# ------------------------------------------------------------------ vectors
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    m = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    return (a[0] / m, a[1] / m, a[2] / m)


def _angle(a, b):
    c = _cross(a, b)
    return math.atan2(math.sqrt(_dot(c, c)), _dot(a, b))


def unit_vector(lon, lat):
    """lon/lat (degrees) -> unit vector (x to 0E, y to 90E, z north).
    Canonical: the poles ignore lon, and lon 180 is -180, so one place always
    gives the same floats (Natural Earth's two sides of the antimeridian meet)."""
    if lat >= 90:
        return (0.0, 0.0, 1.0)
    if lat <= -90:
        return (0.0, 0.0, -1.0)
    while lon >= 180:
        lon -= 360
    while lon < -180:
        lon += 360
    lam, phi = math.radians(lon), math.radians(lat)
    c = math.cos(phi)
    return (c * math.cos(lam), c * math.sin(lam), math.sin(phi))


def _along(a, n, x):
    """Signed arc from a to x along the great circle with normal n (= unit(a x b))."""
    return math.atan2(_dot(_cross(a, x), n), _dot(a, x))


def lon_lat(v):
    """Unit vector -> (lon, lat) in degrees."""
    return math.degrees(math.atan2(v[1], v[0])), math.degrees(math.asin(max(-1.0, min(1.0, v[2]))))


# ------------------------------------------------------------------ face transforms
class FaceTransform:
    """Maps a point of the spherical face (local unit vector x, y, z: z the
    face centre, y towards vertex a, x right as seen from outside) to the
    plane template triangle: unit edges, centroid at the origin, a at
    (0, 1/sqrt 3), b at 210 degrees, c at 330. Must be symmetric under the
    triangle's rotations and mirrors (so a fold edge maps the same from both
    faces) and map edges onto edges."""

    name = None

    def plane(self, x, y, z):
        raise NotImplementedError

    def __repr__(self):
        return self.name


class Gnomonic(FaceTransform):
    name = "gnomonic"

    def plane(self, x, y, z):
        k = COS_G / (z * CHORD)
        return x * k, y * k


class Fuller(FaceTransform):
    """Gray's exact equations (1995) for Fuller's transformation: the
    gnomonic point's three distances to the face's edges, each turned into
    the angle it subtends at the sphere's centre."""

    name = "fuller"

    def plane(self, x, y, z):
        s = COS_G / z
        gx, gy = x * s, y * s
        e3, e2 = CHORD / 3, CHORD / 2
        a1 = math.atan((2 * gy / _S3 + e3 - e2) / DVE)
        a2 = math.atan((gx - gy / _S3 + e3 - e2) / DVE)
        a3 = math.atan((e3 - gx - gy / _S3 - e2) / DVE)
        return (a2 - a3) / (2 * EDGE_ARC), (2 * a1 - a2 - a3) / (2 * _S3 * EDGE_ARC)


class Snyder(FaceTransform):
    """Snyder's (1992) equal-area polyhedral projection, equations (8)-(14),
    on the icosahedron (G = 36, theta = 30 degrees), per third of the face
    (centre and one edge)."""

    name = "snyder"
    BIG_G = math.radians(36.0)
    COT_THETA = _S3  # theta = 30 degrees
    # R': the plane face (circumradius R' tan g) has the spherical face's area, 4 pi / 20
    R1 = math.sqrt(4 * math.pi / 20 * 4 / (3 * _S3)) / math.tan(G)

    def plane(self, x, y, z):
        tan_g, big_g, cot_t, r1 = math.tan(G), self.BIG_G, self.COT_THETA, self.R1
        az = math.atan2(x, y)  # clockwise from vertex a
        if az < 0:
            az += 2 * math.pi
        k = min(2, int(az // (2 * math.pi / 3)))
        az -= k * 2 * math.pi / 3
        dz = math.atan2(math.hypot(x, y), z)
        q = math.atan2(tan_g, math.cos(az) + math.sin(az) * cot_t)
        h = math.acos(max(-1.0, min(1.0, math.sin(az) * math.sin(big_g) * COS_G - math.cos(az) * math.cos(big_g))))
        ag = az + big_g + h - math.pi
        azp = math.atan2(2 * ag, r1 * r1 * tan_g * tan_g - 2 * ag * cot_t)
        dp = r1 * tan_g / (math.cos(azp) + math.sin(azp) * cot_t)
        rho = dp * math.sin(dz / 2) / math.sin(q / 2) if q else 0.0
        azp += k * 2 * math.pi / 3
        s = 1 / (_S3 * r1 * tan_g)
        return rho * math.sin(azp) * s, rho * math.cos(azp) * s


GNOMONIC, FULLER, SNYDER = Gnomonic(), Fuller(), Snyder()
TRANSFORMS = {t.name: t for t in (GNOMONIC, FULLER, SNYDER)}


# ------------------------------------------------------------------ helpers for adapters
def stitch_antimeridian(polys, tol=1e-4):
    """A feature's lon/lat polygons (GeoJSON order) with every segment that
    runs along lon +-180 split at all the feature's latitudes there, so the
    two sides of a polygon cut at the antimeridian (Natural Earth: Russia's
    Chukotka and Wrangel Island, Fiji, Antarctica) have the same vertices
    and merge. Longitudes within tol degrees of +-180 count as on it
    (Natural Earth has some at -179.999951, 5 m off)."""
    def on_seam(c):
        if 180 - abs(c[0]) <= tol:
            return (180.0 if c[0] > 0 else -180.0, c[1])
        return c
    polys = [[[on_seam(c) for c in r] for r in p] for p in polys]
    lats = sorted({c[1] for p in polys for r in p for c in r if abs(c[0]) == 180})
    if not lats:
        return polys
    out = []
    for p in polys:
        rings = []
        for r in p:
            nr = [r[0]]
            for a, b in zip(r, r[1:]):
                if abs(a[0]) == 180 and a[0] == b[0] and a[1] != b[1]:
                    lo, hi = sorted((a[1], b[1]))
                    mids = [y for y in lats if lo < y < hi]
                    if a[1] > b[1]:
                        mids.reverse()
                    nr.extend((a[0], y) for y in mids)
                nr.append(b)
            rings.append(nr)
        out.append(rings)
    return out


def _densify(ring, step):
    """Closed lon/lat ring -> open ring with segments longer than step degrees
    split linearly in lon/lat (canonically: the same points from both sides of
    a shared border)."""
    pts = [tuple(c[:2]) for c in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if not step:
        return pts
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        out.append(a)
        d = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        if d > step:
            k = int(math.ceil(d / step))
            p, q = (a, b) if a <= b else (b, a)
            mids = [(p[0] + (q[0] - p[0]) * j / k, p[1] + (q[1] - p[1]) * j / k) for j in range(1, k)]
            out.extend(mids if p == a else mids[::-1])
    return out


# ------------------------------------------------------------------ the net
class _Line:
    """A great-circle segment bounding pieces: a face edge (both ends
    vertices; points on it are placed through the edge function) or a line
    inside a face (centre, median)."""

    def __init__(self, lid, a, b, edge):
        self.id, self.a, self.b, self.edge = lid, a, b, edge  # edge: (u, v) vertex numbers or None
        self.n = _unit(_cross(a, b))


class _Part:
    def __init__(self, corners, lines, centre, cos_r):
        self.corners = corners    # corner keys, counterclockwise from outside
        self.lines = lines        # [(line, sign)] in corner order (corner i -> i + 1)
        self.centre, self.cos_r = centre, cos_r  # bounding cap
        self.corner_at = {}       # (line id, line id) -> corner key


class _Piece:
    def __init__(self, name, face, parent):
        self.name, self.face, self.parent = name, face, parent
        self.pos = {}    # vertex number -> net position (edge 1)
        self.parts = []


class _Face:
    def __init__(self, fid, verts):
        a, b, c = verts
        if _dot(_V[a], _cross(_V[b], _V[c])) < 0:
            b, c = c, b
        self.id, self.verts = fid, (a, b, c)  # counterclockwise from outside
        m = _unit(tuple(_V[a][k] + _V[b][k] + _V[c][k] for k in range(3)))
        va = _V[a]
        d = _dot(va, m)
        ey = _unit(tuple(va[k] - d * m[k] for k in range(3)))
        self.m, self.ey, self.ex = m, ey, _cross(ey, m)


def _corner_key(k):
    """Sort key and identity of a corner: vertex v, ("c", face), ("m", a, b)."""
    if isinstance(k, int):
        return (0, k, 0)
    if k[0] == "c":
        return (1, k[1], 0)
    a, b = sorted(k[1:])
    return (2, a, b)


class Polyhedral:
    """A polyhedral map: transform (GNOMONIC, FULLER, SNYDER) on the net
    (default Fuller's AIROCEAN). Coordinates: the net with unit edges times
    scale, x right, y up (a MapBuilder with mapgen.Identity() and a Window
    over outline() take it as easting, northing). densify: lon/lat segments
    longer than this many degrees get intermediate points first (linear in
    lon/lat, as the data was drawn; 0: none)."""

    def __init__(self, transform=FULLER, net=AIROCEAN, root=AIROCEAN_ROOT, scale=1.0, densify=1.0):
        self.transform = TRANSFORMS[transform] if isinstance(transform, str) else transform
        self.scale, self.densify = scale, densify
        self.faces = {f: _Face(f, vs) for f, vs in FACES.items()}
        self.lines = {}
        self.on_line = {}  # line id -> [(param, corner key)]: static corners strictly inside a line
        self.pieces = {}
        self._build(net, root)
        self._memo = {}

    def __repr__(self):
        return f"polyhedral({self.transform.name})"

    def self_test(self, tol=1e-9):
        """ValueError unless every face's vertices land on its net corners and,
        for FULLER on AIROCEAN, Vienna lands where Gray's procedure puts it."""
        for pc in self.pieces.values():
            for v in self.faces[pc.face].verts:
                x, y = self._in_face(pc, _V[v])
                k = self.scale
                if abs(x - pc.pos[v][0] * k) > tol * k or abs(y - pc.pos[v][1] * k) > tol * k:
                    raise ValueError(f"{self!r}: vertex {v} of piece {pc.name} misplaced")
        if self.transform is FULLER and self.pieces.get("1") and self.pieces["1"].pos == AIROCEAN_ROOT:
            x, y = self(16.37, 48.21)
            if abs(x / self.scale - 2.273917287308) > tol or abs(y / self.scale - 1.883897518315) > tol:
                raise ValueError(f"{self!r}: self-test failed: {x / self.scale:.12f} {y / self.scale:.12f}")

    # ---------------------------------------------------------- construction
    def corner_vec(self, k):
        if isinstance(k, int):
            return _V[k]
        if k[0] == "c":
            return self.faces[k[1]].m
        return _unit(tuple(_V[k[1]][i] + _V[k[2]][i] for i in range(3)))

    def _line(self, face, k1, k2):
        """The supporting line of a part's side from corner k1 to k2: a face
        edge when both lie on one (a half edge is its whole edge)."""
        def edges_of(k):
            vs = face.verts
            es = {tuple(sorted((vs[i], vs[(i + 1) % 3]))) for i in range(3)}
            if isinstance(k, int):
                return {e for e in es if k in e}
            if k[0] == "m":
                return {tuple(sorted(k[1:]))} & es
            return set()
        common = edges_of(k1) & edges_of(k2)
        if common:
            u, v = common.pop()
            lid = ("e", u, v)
            if lid not in self.lines:
                self.lines[lid] = _Line(lid, _V[u], _V[v], (u, v))
            return self.lines[lid]
        s1, s2 = sorted((k1, k2), key=_corner_key)
        lid = ("i", _corner_key(s1), _corner_key(s2))
        if lid not in self.lines:
            self.lines[lid] = _Line(lid, self.corner_vec(s1), self.corner_vec(s2), None)
        return self.lines[lid]

    def _build(self, net, root):
        specs = {name: (face, parent, parts) for name, face, parent, parts in net}
        order, placed = [], set()
        while len(order) < len(specs):
            n0 = len(order)
            for name, (face, parent, parts) in specs.items():
                if name not in placed and (parent is None or parent in placed):
                    order.append(name)
                    placed.add(name)
            if len(order) == n0:
                raise ValueError("net: a piece's parent is missing or the parents form a loop")
        for name in order:
            fid, parent, parts = specs[name]
            face = self.faces[fid]
            pc = _Piece(name, fid, parent)
            if parent is None:
                pc.pos = {v: tuple(map(float, root[v])) for v in face.verts}
            else:
                pp = self.pieces[parent]
                hinge = set(face.verts) & set(self.faces[pp.face].verts)
                if len(hinge) != 2:
                    raise ValueError(f"net: piece {name} shares no edge with its parent {parent}")
                (w_parent,) = set(self.faces[pp.face].verts) - hinge
                (w,) = set(face.verts) - hinge
                u, v = sorted(hinge)
                pc.pos = {u: pp.pos[u], v: pp.pos[v]}
                pc.pos[w] = tuple(pp.pos[u][i] + pp.pos[v][i] - pp.pos[w_parent][i] for i in range(2))
            # orientation: counterclockwise from outside must stay counterclockwise in the net
            (xa, ya), (xb, yb), (xc, yc) = (pc.pos[k] for k in face.verts)
            if (xb - xa) * (yc - ya) - (yb - ya) * (xc - xa) <= 0:
                raise ValueError(f"net: piece {name} is mirrored (root order or vertex numbering)")
            for corners in (parts or (face.verts,)):
                vecs = [self.corner_vec(k) for k in corners]
                if _dot(vecs[0], _cross(vecs[1], vecs[2])) < 0:
                    corners = (corners[0], corners[2], corners[1])
                    vecs = [vecs[0], vecs[2], vecs[1]]
                centre = _unit(tuple(sum(v[i] for v in vecs) for i in range(3)))
                lines = []
                for i in range(3):
                    ln = self._line(face, corners[i], corners[(i + 1) % 3])
                    sign = 1.0 if _dot(ln.n, centre) > 0 else -1.0
                    lines.append((ln, sign))
                part = _Part(tuple(corners), lines, centre, min(_dot(centre, v) for v in vecs))
                for i in range(3):  # line i ends at corner i + 1, where line i + 1 starts
                    l1, l2 = lines[i][0].id, lines[(i + 1) % 3][0].id
                    part.corner_at[(l1, l2)] = part.corner_at[(l2, l1)] = corners[(i + 1) % 3]
                pc.parts.append(part)
                for k in corners:  # a corner strictly inside a line of any part (a half edge's midpoint)
                    if isinstance(k, tuple) and k[0] == "m":
                        ln = self._line(face, k[1], k[2])
                        entry = (_along(ln.a, ln.n, self.corner_vec(k)), k)
                        if entry not in self.on_line.setdefault(ln.id, []):
                            self.on_line[ln.id].append(entry)
            self.pieces[name] = pc

    # ---------------------------------------------------------- points
    def edge_t(self, theta):
        """The face transform along an edge: fraction of the plane edge for a
        point theta radians (of arc) from the edge's first vertex. Evaluated
        on the template edge a -> b, so it is the same for every face."""
        s = math.sin(EDGE_ARC)
        w0, w1 = math.sin(EDGE_ARC - theta) / s, math.sin(theta) / s
        sg = math.sin(G)
        ax, ay, az = 0.0, sg, COS_G
        bx, by, bz = -sg * _S3 / 2, -sg / 2, COS_G
        x, y = self.transform.plane(w0 * ax + w1 * bx, w0 * ay + w1 * by, w0 * az + w1 * bz)
        return -0.5 * x - _S3 / 2 * (y - 1 / _S3)  # (X - Va) . (Vb - Va), |Vb - Va| = 1

    def _on_edge(self, pc, line, vec):
        u, v = line.edge
        t = self.edge_t(_angle(_V[u], vec))
        pu, pv = pc.pos[u], pc.pos[v]
        return ((pu[0] + t * (pv[0] - pu[0])) * self.scale, (pu[1] + t * (pv[1] - pu[1])) * self.scale)

    def _in_face(self, pc, vec):
        f = self.faces[pc.face]
        x, y = self.transform.plane(_dot(vec, f.ex), _dot(vec, f.ey), _dot(vec, f.m))
        la = 1 / 3 + 2 / _S3 * y
        lb = 1 / 3 - x - y / _S3
        lc = 1 / 3 + x - y / _S3
        pa, pb, pcc = (pc.pos[k] for k in f.verts)
        return ((la * pa[0] + lb * pb[0] + lc * pcc[0]) * self.scale,
                (la * pa[1] + lb * pb[1] + lc * pcc[1]) * self.scale)

    def _place(self, pc, rec):
        kind, vec, ref = rec
        if kind == "k":
            if isinstance(ref, int):
                p = pc.pos[ref]
                return (p[0] * self.scale, p[1] * self.scale)
            if ref[0] == "m":
                return self._on_edge(pc, self.lines[("e",) + tuple(sorted(ref[1:]))], vec)
            return self._in_face(pc, vec)
        if kind == "x" and ref.edge:
            return self._on_edge(pc, ref, vec)
        return self._in_face(pc, vec)

    def locate(self, vec):
        """(piece, part) containing the unit vector (first in net order)."""
        for pc in self.pieces.values():
            for part in pc.parts:
                if all(s * _dot(ln.n, vec) >= 0 for ln, s in part.lines):
                    return pc, part
        raise BuildError(f"polyhedral: no piece contains {vec}")  # pragma: no cover (the pieces cover the sphere)

    def __call__(self, lon, lat):
        v = unit_vector(lon, lat)
        pc, _ = self.locate(v)
        return self._in_face(pc, v)

    def piece_of(self, lon, lat):
        return self.locate(unit_vector(lon, lat))[0].name

    # ---------------------------------------------------------- polygons
    def _isect(self, sup, line):
        """Where the edge with support sup crosses line: a ring segment's
        crossing (once per segment and line, canonical), or two lines' corner."""
        if sup[0] == "l":
            return None
        key = (line.id, sup[1], sup[2])
        rec = self._memo.get(key)
        if rec is None:
            a, b = sup[1], sup[2]
            da, db = _dot(line.n, a), _dot(line.n, b)
            t = da / (da - db)
            x = _unit(tuple(a[i] + t * (b[i] - a[i]) for i in range(3)))
            rec = ("x", x, line)
            self._memo[key] = rec
        return rec

    def _clip(self, ring, part):
        """Sutherland-Hodgman on the sphere: ring [(rec, support of the edge to
        the next point)] against the part's three great circles. Correct for
        rings inside an open hemisphere (split checks that)."""
        for line, sign in part.lines:
            if not ring:
                break
            n = line.n
            out = []
            prev, psup = ring[-1]
            pin = sign * _dot(n, prev[1]) >= 0
            for cur, csup in ring:
                cin = sign * _dot(n, cur[1]) >= 0
                if cin != pin:
                    x = self._isect(psup, line)
                    if x is None:  # a part side crossing the next one: their corner
                        k = part.corner_at[(psup[1], line.id)]
                        x = ("k", self.corner_vec(k), k)
                    out.append((x, psup if cin else ("l", line.id)))
                if cin:
                    out.append((cur, csup))
                prev, psup, pin = cur, csup, cin
            ring = out
        return ring

    def split(self, poly):
        """A lon/lat polygon (GeoJSON order: exterior, holes) -> its parts on
        the net: [polygon], each [exterior, holes...] of (x, y) points, one per
        piece part it touches, in net order. Parts that meet across a fold share
        their vertices there (feed them all to one MapBuilder feature: its
        dissolve merges them). Each ring must lie within an open hemisphere."""
        self._memo = {}
        rings = []
        for ri, ring in enumerate(poly):
            pts = []
            for lon, lat in _densify(ring, self.densify):
                v = unit_vector(lon, lat)
                if not pts or pts[-1] != v:
                    pts.append(v)
            while len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(set(pts)) < 3:
                if ri == 0:
                    return []
                continue
            c = tuple(sum(p[i] for p in pts) for i in range(3))
            if _dot(c, c) < 1e-18:
                raise BuildError("polyhedral: a ring that doesn't fit in a hemisphere")
            c = _unit(c)
            cos_r = min(_dot(c, p) for p in pts)
            if cos_r <= 1e-6:
                raise BuildError(f"polyhedral: a ring wider than a hemisphere (near {lon_lat(c)})")
            recs = []
            for i, p in enumerate(pts):
                q = pts[(i + 1) % len(pts)]
                recs.append((("p", p, None), ("s", min(p, q), max(p, q))))
            rings.append((recs, c, cos_r))
        if not rings:
            return []
        clipped = []  # (piece, [part ring or None per ring])
        for pc in self.pieces.values():
            for part in pc.parts:
                cap = math.acos(max(-1.0, min(1.0, part.cos_r)))
                outs = []
                for ri, (recs, c, cos_r) in enumerate(rings):
                    if math.acos(max(-1.0, min(1.0, _dot(c, part.centre)))) > cap + math.acos(cos_r) + 1e-9:
                        outs.append(None)
                        continue
                    flags = [[s * _dot(ln.n, rec[1]) >= 0 for rec, _ in recs] for ln, s in part.lines]
                    if all(all(f) for f in flags):
                        outs.append(recs)
                    elif any(not any(f) for f in flags):
                        outs.append(None)
                    else:
                        outs.append(self._clip(recs, part) or None)
                if outs[0]:
                    clipped.append((pc, outs))
        # points on each line (crossings of this polygon, static corners), by position along it
        along = {}
        for rec in self._memo.values():
            along.setdefault(rec[2].id, []).append(rec)
        params = {}

        def param(line, rec):
            key = (line.id, rec[1])
            if key not in params:
                params[key] = _along(line.a, line.n, rec[1])
            return params[key]

        result = []
        for pc, outs in clipped:
            poly_out = []
            for out in outs:
                if not out:
                    continue
                pts = []
                for i, (rec, sup) in enumerate(out):
                    pts.append(self._place(pc, rec))
                    if sup[0] == "l":
                        line = self.lines[sup[1]]
                        nxt = out[(i + 1) % len(out)][0]
                        t0, t1 = param(line, rec), param(line, nxt)
                        lo, hi = min(t0, t1), max(t0, t1)
                        mids = [(param(line, r), r) for r in along.get(line.id, ())]
                        mids += [(t, ("k", self.corner_vec(k), k)) for t, k in self.on_line.get(line.id, ())]
                        mids = sorted(((t, r) for t, r in mids if lo < t < hi and r[1] != rec[1] and r[1] != nxt[1]),
                                      key=lambda e: e[0])
                        if t0 > t1:
                            mids.reverse()
                        pts.extend(self._place(pc, r) for _, r in mids)
                poly_out.append(pts)
            result.append(poly_out)
        self._memo = {}
        return result

    # ---------------------------------------------------------- the net's shape
    def outline(self):
        """The net's parts as planar triangles: [(piece name, [(x, y) * 3])]."""
        out = []
        for pc in self.pieces.values():
            for part in pc.parts:
                out.append((pc.name, [self._place(pc, ("k", self.corner_vec(k), k)) for k in part.corners]))
        return out

    def edges(self):
        """The parts' sides in the net: [(kind, (x, y), (x, y))], kind "fold"
        (two pieces meet there), "cut" (the net's outline) or "split" (inside
        one piece, between its parts). Rounded to 1e-9 to match ends."""
        segs = {}
        for pc in self.pieces.values():
            for part in pc.parts:
                for i, (line, _) in enumerate(part.lines):
                    k0, k1 = part.corners[i], part.corners[(i + 1) % 3]
                    v0, v1 = self.corner_vec(k0), self.corner_vec(k1)
                    t0, t1 = _along(line.a, line.n, v0), _along(line.a, line.n, v1)
                    ks = [k0] + [k for t, k in sorted(self.on_line.get(line.id, ()), reverse=t0 > t1)
                                 if min(t0, t1) < t < max(t0, t1)] + [k1]  # a half edge's midpoint
                    pts = [self._place(pc, ("k", self.corner_vec(k), k)) for k in ks]
                    for p, q in zip(pts, pts[1:]):
                        key = tuple(sorted((tuple(round(c, 9) for c in p), tuple(round(c, 9) for c in q))))
                        segs.setdefault(key, []).append(pc.name)
        out = []
        for (p, q), names in sorted(segs.items()):
            kind = "cut" if len(names) == 1 else ("split" if names[0] == names[1] else "fold")
            out.append((kind, p, q))
        return out
