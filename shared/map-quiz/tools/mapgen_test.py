#!/usr/bin/env python3
"""Checks of the shared map generator core (mapgen) on synthetic data:
python3 -I shared/map-quiz/tools/mapgen_test.py   (stdlib unittest; the
polyhedral tests take a few seconds)

The real-data check is each image's own `build_map.py --check` (its inputs
aren't committed)."""
import hashlib
import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mapgen  # noqa: E402

NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)")


def rings_of(d):
    """Path data written by path_d -> rings of absolute (x, y) points."""
    out, last = [], (0.0, 0.0)
    for part in re.findall(r"m([^z]*)z", d):
        v = [float(t) for t in NUM.findall(part)]
        x, y = last[0] + v[0], last[1] + v[1]
        ring = [(round(x, 3), round(y, 3))]
        for i in range(2, len(v), 2):
            x, y = x + v[i], y + v[i + 1]
            ring.append((round(x, 3), round(y, 3)))
        out.append(ring)
        last = ring[0]
    return out


def square(x0, y0, x1, y1):
    """A lon/lat polygon (GeoJSON order, closed)."""
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]


def planar(lon, lat):
    """A 'projection' for tests: 1 degree = 1 km."""
    return lon * 1000.0, lat * 1000.0


def synthetic(**kw):
    """Two regions A, B sharing an edge, context land beside B, water across
    both, a remote island of A far outside, a region C below the grid."""
    pts = [planar(x, y) for x, y in ((0, 0), (2, 1))]
    window = mapgen.Window(pts, 0.05, 1000.0, (0.25, 0.25))
    mb = mapgen.MapBuilder(planar, window, ["A", "B", "C"], **kw)
    mb.add_region("A", square(0, 0, 1, 1))
    mb.add_region("A", square(-30, 0, -29.5, 0.5), outside_ok=True, label="A island")
    mb.add_region("B", square(1, 0, 2, 1))
    mb.add_region("C", square(0.45, 0.44, 0.4501, 0.4401))
    mb.add_context(square(2, 0, 2.4, 1))
    mb.add_overlay("water", square(0.2, 0.45, 1.8, 0.55))
    return mb, window


class Projections(unittest.TestCase):
    def test_reference_points(self):
        mapgen.epsg3035().self_test()
        mapgen.osgb_example().self_test()

    def test_self_test_catches_errors(self):
        p = mapgen.LambertAzimuthalEqualArea(52, 10.001, 4321000.0, 3210000.0,
                                             reference=(5, 50, 3962799.45, 2999718.85))
        with self.assertRaises(ValueError):
            p.self_test()

    def test_tm_central_meridian(self):
        tm = mapgen.TransverseMercator(16.375, 0, 1, 0, 0)
        e, n = tm(16.375, 48.2)
        self.assertAlmostEqual(e, 0, places=6)
        self.assertGreater(tm(16.5, 48.2)[0], 0)  # east is +x
        self.assertGreater(tm(16.375, 48.3)[1], n)  # north is +y


class Wkt(unittest.TestCase):
    def test_polygon_and_multipolygon(self):
        self.assertEqual(mapgen.parse_wkt("POLYGON ((0 0, 1 0, 1 1, 0 0))"), [[[(0, 0), (1, 0), (1, 1), (0, 0)]]])
        mp = mapgen.parse_wkt("SRID=31256;MULTIPOLYGON Z (((0 0 5,2 0 5,2 2 5,0 0 5),(.5 .5 1,1 .5 1,1 1 1,.5 .5 1)),"
                              "((10 10 0,11 10 0,11 11 0,10 10 0)))")
        self.assertEqual(len(mp), 2)
        self.assertEqual(len(mp[0]), 2)  # exterior + hole
        self.assertEqual(mp[0][1][0], (0.5, 0.5))
        self.assertEqual(mapgen.parse_wkt("multipolygon empty"), [])

    def test_bad_input(self):
        for bad in ["POINT (1 2)", "POLYGON ((0 0, 1 0, 1 1)", "POLYGON ((0 0, 1))", "MULTIPOLYGON ((0 0, 1 0, 1 1, 0 0))",
                    "POLYGON ((0 0, 1 0, 1 1, 0 0)) x"]:
            with self.assertRaises(ValueError, msg=bad):
                mapgen.parse_wkt(bad)

    def test_projected_input(self):
        """Already projected data (e.g. EPSG:31256): Identity + Window, no extent."""
        polys = [mapgen.parse_wkt(f"POLYGON (({x} 340000, {x + 1000} 340000, {x + 1000} 341000, {x} 341000, {x} 340000))")[0]
                 for x in (0, 1000)]
        window = mapgen.Window([p for poly in polys for p in poly[0]], 0.0, 1000.0, (0, 0))
        self.assertEqual(window.viewbox(), "0 0 1000 500")
        mb = mapgen.MapBuilder(mapgen.Identity(), window, ["d01", "d02"])
        for rid, poly in zip(["d01", "d02"], polys):
            mb.add_region(rid, poly)
        res = mb.build()
        self.assertEqual(set(rings_of(res.paths["d01"])[0]), {(0, 0), (500, 0), (500, 500), (0, 500)})
        self.assertEqual(window.to_view(0, 341000), (0, 0))  # north edge at the top (y down)


class PathText(unittest.TestCase):
    def test_fmt_fixed(self):
        cases = {(0, 1): "0", (3, 1): ".3", (-3, 1): "-.3", (120, 1): "12", (405, 2): "4.05", (-1000, 2): "-10"}
        for (v, dec), want in cases.items():
            self.assertEqual(mapgen.fmt_fixed(v, dec), want)

    def test_path_d_round_trip(self):
        rings = [[(0, 0), (15, 0), (15, 5)], [(100, 100), (95, 103), (90, 100)]]
        d = mapgen.path_d(rings, 1)
        self.assertEqual(d, "m0 0 1.5 0 0 .5zm10 10-.5.3-.5-.3z")
        self.assertEqual(rings_of(d), [[(x / 10, y / 10) for x, y in r] for r in rings])


class Pipeline(unittest.TestCase):
    def test_build(self):
        mb, window = synthetic()
        self.assertEqual(window.width, 1000)
        self.assertEqual(window.height, 545.5)
        self.assertEqual(window.viewbox(), "-250 -136.4 1500 818.3")
        res = mb.build()
        svg = mapgen.map_svg(res, ["A", "B", "C"], "test head")
        ids = re.findall(r'id="([^"]+)"', svg)
        self.assertEqual(ids, ["land", "regions", "A", "B", "C", "overlays", "water"])
        self.assertIn("<!-- test head -->", svg)
        # A and B share their border vertex for vertex
        a = set(rings_of(res.paths["A"])[0])
        b = set(rings_of(res.paths["B"])[0])
        self.assertEqual(len(a & b), 2)
        # the remote island lies beyond the extent: clipped away, reported
        self.assertEqual(len(rings_of(res.paths["A"])), 1)
        self.assertEqual(res.stats["clipped"], ["A island"])
        # C fell below the grid: kept at 10x finer resolution
        self.assertTrue(any("C: below the grid" in n for n in res.report(["A", "B", "C"])["notes"]))
        self.assertLess(res.sizes["C"], 0.1)
        self.assertEqual(list(res.overlays), ["water"])

    def test_deterministic(self):
        one = mapgen.map_svg(synthetic()[0].build(), ["A", "B", "C"], "h")
        two = mapgen.map_svg(synthetic()[0].build(), ["A", "B", "C"], "h")
        self.assertEqual(one, two)

    def test_golden(self):
        """The synthetic map.svg, byte for byte, as of 37bd3a6 (captured before
        the boundary-line work): a change to the core that moves any output
        shows here, before the images' build_map.py --check (whose inputs
        aren't committed)."""
        svg = mapgen.map_svg(synthetic()[0].build(), ["A", "B", "C"], "h")
        self.assertEqual(hashlib.sha256(svg.encode("utf-8")).hexdigest(),
                         "3984fdd3bec9fc8926712f527511db02f06f4cbea8cd74bc45e668a0e2016a70")

    def test_region_outside_window_fails(self):
        mb, _ = synthetic()
        with self.assertRaises(mapgen.BuildError):
            mb.add_region("A", square(-30, 0, -29, 1))

    def test_unknown_region_and_points(self):
        mb, window = synthetic()
        with self.assertRaises(mapgen.BuildError):
            mb.add_region("Z", square(0, 0, 1, 1))
        x, y = mb.point(1, 0.5, "m")
        self.assertTrue(window.contains(x, y))
        with self.assertRaises(mapgen.BuildError):
            mb.point(5, 0.5, "far marker")

    def test_no_context_no_overlays(self):
        pts = [planar(0, 0), planar(1, 1)]
        window = mapgen.Window(pts, 0, 1000.0, (0.1, 0.1))
        mb = mapgen.MapBuilder(planar, window, ["d01"])
        mb.add_region("d01", square(0, 0, 1, 1))
        svg = mapgen.map_svg(mb.build(), ["d01"], "h", group_id="districts")
        self.assertEqual(re.findall(r'id="([^"]+)"', svg), ["districts", "d01"])
        self.assertEqual(window.map_js(), "export const MAP = { width: 1000, height: 1000, extent: [-100, -100, 1200, 1200] };")

    def test_region_tol(self):
        """A densified, wobbly shared border (as in city data): region_tol
        thins it on the shared arc, so both neighbours keep identical
        vertices; 0 (the default) keeps every vertex."""
        def build(**kw):
            window = mapgen.Window([(0, 0), (2000, 1000)], 0, 1000.0, (0, 0))
            wobble = [(1000 + (3 if i % 2 else -3), 1000 - i * 10) for i in range(101)]  # x = 1000 ± 3 m
            a = [(0, 0), (1000, 0)] + wobble[::-1][1:-1] + [(1000, 1000), (0, 1000)]
            b = [(1000, 0), (2000, 0), (2000, 1000), (1000, 1000)] + wobble[1:-1]
            mb = mapgen.MapBuilder(mapgen.Identity(), window, ["d01", "d02"], **kw)
            mb.add_region("d01", [a + [a[0]]])
            mb.add_region("d02", [b + [b[0]]])
            return mb.build()
        full, thin = build(), build(region_tol=2)  # 2 units = 4 m > the 1.5-unit wobble
        self.assertEqual(full.stats["points_after"], full.stats["points_before"])
        self.assertLess(thin.stats["points_after"], full.stats["points_after"] - 90)
        a, b = (set(rings_of(thin.paths[r])[0]) for r in ("d01", "d02"))
        self.assertEqual(a & b, {(500, 0), (500, 500)})  # the shared border is one straight arc now
        self.assertEqual(thin.stats["crossings"], 0)
        self.assertIn("all arcs simplified", thin.report(["d01", "d02"])["points"])

    def test_count_crossings(self):
        self.assertEqual(mapgen.count_crossings([[(0, 0), (10, 10)], [(0, 10), (10, 0)]]), 1)
        self.assertEqual(mapgen.count_crossings([[(0, 0), (10, 10), (20, 0)], [(10, 10), (10, 30)]]), 0)  # shared vertex
        self.assertEqual(mapgen.count_crossings([[(0, 0), (10, 0)], [(5, 0), (5, 9)]]), 0)  # touching, not crossing
        self.assertEqual(mapgen.count_crossings([[(0, 0), (100, 0), (100, 10), (50, -5), (0, 10)]]), 2)  # itself, twice
        self.assertEqual(mapgen.count_crossings([]), 0)

    def test_pinned_read(self):
        path = os.path.abspath(__file__)
        with open(path, "rb") as fh:
            raw = fh.read()
        self.assertEqual(mapgen.read_pinned(path, hashlib.sha256(raw).hexdigest(), len(raw)), raw)
        with self.assertRaises(mapgen.BuildError):
            mapgen.read_pinned(path, "0" * 64, len(raw), "https://example.org/x")


def lines_of(d, grid):
    """Path data written by lines_d -> polylines of integer points."""
    out, last = [], (0, 0)
    for part in re.findall(r"m([^m]*)", d):
        v = [round(float(t) * grid) for t in NUM.findall(part)]
        x, y = last
        line = []
        for i in range(0, len(v), 2):
            x, y = x + v[i], y + v[i + 1]
            line.append((x, y))
        out.append(line)
        last = line[-1]
    return out


def segments(lines):
    return [(min(a, b), max(a, b)) for ln in lines for a, b in zip(ln, ln[1:])]


def region_edges(res, rids):
    """Every edge of the regions' drawn rings, as integer points."""
    g = res.grid
    out = set()
    for rid in rids:
        for ring in rings_of(res.paths[rid]):
            ring = [(round(x * g), round(y * g)) for x, y in ring]
            for k in range(len(ring)):
                a, b = ring[k - 1], ring[k]
                out.add((min(a, b), max(a, b)))
    return out


def block():
    """A 2x2 block of regions (nw ne / sw se, 250 units square each, y down)
    and an island to the right; 1 degree = 250 units, grid 10."""
    window = mapgen.Window([planar(0, 0), planar(4, 2)], 0, 1000.0, (0, 0))
    ids = ["nw", "ne", "sw", "se", "isl"]
    mb = mapgen.MapBuilder(planar, window, ids)
    mb.add_region("nw", square(0, 1, 1, 2))
    mb.add_region("ne", square(1, 1, 2, 2))
    mb.add_region("sw", square(0, 0, 1, 1))
    mb.add_region("se", square(1, 0, 2, 1))
    mb.add_region("isl", square(3, 0.5, 3.5, 1.5))
    return mb.build(), ids


class Lines(unittest.TestCase):
    """Result.arcs / topo, boundary_lines, lines_d."""

    def test_arcs_and_topo_rebuild_the_paths(self):
        for res in (synthetic()[0].build(), block()[0]):
            self.assertEqual((res.grid, res.dec), (10, 1))
            self.assertTrue(res.topo)
            for fid, refs in res.topo.items():
                rings = [mapgen.ring_from_arcs(r, res.arcs) for r in refs]
                self.assertEqual(mapgen.path_d(rings, res.dec), res.paths[fid], fid)
        res = synthetic()[0].build()
        self.assertEqual(set(res.topo), {"A", "B", "land"}, "C fell below the grid: not in topo")
        self.assertIn("C", res.paths)

    def test_identity_grouping_gives_every_edge_once(self):
        res, ids = block()
        lines = mapgen.boundary_lines(res, {rid: rid for rid in ids})
        segs = segments(lines)
        self.assertEqual(len(segs), len(set(segs)), "no edge twice")
        self.assertEqual(set(segs), region_edges(res, ids))
        res = synthetic()[0].build()  # with context land beside B
        segs = segments(mapgen.boundary_lines(res, {"A": "A", "B": "B"}))
        self.assertEqual(len(segs), len(set(segs)))
        self.assertEqual(set(segs), region_edges(res, ["A", "B"]))

    def test_groups_inner_and_outer(self):
        res, _ = block()
        top_bottom = {"nw": "top", "ne": "top", "sw": "bottom", "se": "bottom"}
        inner = mapgen.boundary_lines(res, top_bottom, outer=False)
        self.assertEqual(inner, [[(0, 2500), (2500, 2500), (5000, 2500)]], "one line on through the centre")
        outer = mapgen.boundary_lines(res, top_bottom, inner=False)
        self.assertEqual(len(outer), 1)
        self.assertEqual(outer[0][0], (0, 0))
        self.assertEqual(outer[0][-1], (0, 0), "a closed loop from its smallest point")
        self.assertEqual(len(outer[0]), 9)
        self.assertTrue(all(0 <= x <= 5000 and 0 <= y <= 5000 for x, y in outer[0]), "the island is ungrouped")
        both = mapgen.boundary_lines(res, top_bottom)
        self.assertEqual(set(segments(both)), set(segments(inner)) | set(segments(outer)))
        self.assertEqual(mapgen.boundary_lines(res, top_bottom, inner=False, outer=False), [])
        # the island as a group of its own: its coast joins the outer lines
        with_isl = mapgen.boundary_lines(res, {**top_bottom, "isl": "isl"}, inner=False)
        self.assertEqual(set(segments(with_isl)) - set(segments(outer)), region_edges(res, ["isl"]))
        # an ungrouped region (inert) is outside: the edges against it are outer
        no_ne = {"nw": "top", "sw": "bottom", "se": "bottom"}
        segs = set(segments(mapgen.boundary_lines(res, no_ne, inner=False)))
        self.assertIn(((2500, 0), (2500, 2500)), segs, "nw | ne")
        self.assertIn(((2500, 2500), (5000, 2500)), segs, "se | ne")
        self.assertNotIn(((2500, 0), (5000, 0)), segs, "ne's own coast")
        self.assertNotIn(((5000, 0), (5000, 2500)), segs, "ne's own coast")
        self.assertEqual(set(segments(mapgen.boundary_lines(res, no_ne, outer=False))),
                         {((0, 2500), (2500, 2500))}, "inner: top | bottom only")

    def test_context_land_is_outside(self):
        res = synthetic()[0].build()
        one = mapgen.boundary_lines(res, {"A": "g", "B": "g"}, outer=False)
        self.assertEqual(one, [], "one group: no inner edges")
        coast = set(segments(mapgen.boundary_lines(res, {"A": "g", "B": "g"}, inner=False)))
        self.assertEqual(coast, region_edges(res, ["A", "B"]) - set(segments(
            mapgen.boundary_lines(res, {"A": "a", "B": "b"}, outer=False))))
        land = region_edges(res, ["land"])
        self.assertTrue(coast & land, "the edge against context land is outer")
        ab = mapgen.boundary_lines(res, {"A": "a", "B": "b"}, outer=False)
        self.assertEqual(len(ab), 1)
        self.assertEqual(len(ab[0]), 2, "the shared A | B edge")

    def test_order_independent(self):
        res, ids = block()
        groups = {"nw": 1, "ne": 2, "sw": 1, "se": 3, "isl": 2}
        rev = dict(reversed(list(groups.items())))
        for kw in ({}, {"inner": False}, {"outer": False}):
            self.assertEqual(mapgen.boundary_lines(res, groups, **kw), mapgen.boundary_lines(res, rev, **kw))

    def test_bad_groups(self):
        res = synthetic()[0].build()
        for bad in ({"C": "g"}, {"A": "g", "Z": "g"}, {"land": "g"}):
            with self.assertRaises(mapgen.BuildError, msg=str(bad)):
                mapgen.boundary_lines(res, bad)

    def test_lines_d_round_trip(self):
        lines = [[(0, 0), (15, 0), (15, 5)], [(100, 100), (95, 103)]]
        d = mapgen.lines_d(lines, 1)
        self.assertEqual(d, "m0 0 1.5 0 0 .5m8.5 9.5-.5.3")
        self.assertEqual(lines_of(d, 10), lines)
        res, ids = block()
        lines = mapgen.boundary_lines(res, {rid: rid for rid in ids})
        self.assertEqual(lines_of(mapgen.lines_d(lines, res.dec), res.grid), lines)
        self.assertEqual(mapgen.lines_d([], 1), "")


# ------------------------------------------------------------------ polyhedral (Fuller's net)
ph = mapgen.polyhedral
NET_AREA = 20 * math.sqrt(3) / 4  # the net's area (unit edges) for the sphere's 4 pi

# Gray's exact procedure ("Source Code For Coordinate Transformation",
# rwgrayprojects.com), evaluated offline: (lon, lat, x, y) on his net (edge 1).
GRAY_POINTS = [
    (16.37, 48.21, 2.273917287308, 1.883897518315),  # triangle 1
    (0.0, 0.0, 1.918655421635, 2.548259070204),  # triangle 6
    (-74.0, 40.7, 3.269559485469, 1.556215130818),  # triangle 4
    (139.7, 35.7, 2.166506585628, 0.706847815335),  # triangle 10
    (151.2, -33.9, 1.003080695687, 0.324252527347),  # triangle 17
    (-58.4, -34.6, 4.428062498662, 1.734679911039),  # triangle 14
    (0.0, -90.0, 5.101912575285, 1.254685727080),  # triangle 20
    (121.0, 14.6, 1.613467830591, 0.828248349544),  # triangle 9, the part with face 8 (9a)
    (144.8, 13.4, 2.129450600800, 0.373476111512),  # triangle 9, the third with face 10 (9b)
    (69.5, -49.3, 0.334626113358, 0.842583233992),  # triangle 16, the half with face 17 (16a)
    (-157.86, 21.3, 3.359884817939, 0.538808248848),  # triangle 11
    (144.32, -79.81, 5.171267879185, 1.124873943350),  # triangle 16, the half with face 20 (16b)
]


def d3_airocean_vertices():
    """d3-geo-polygon's geoAirocean (ISC): a pole-up icosahedron, rotated by
    [-83.65929, 25.44458, -87.45184] (d3-geo's rotation, inverted here)."""
    dl, dp, dg = (math.radians(a) for a in (-83.65929, 25.44458, -87.45184))
    th = math.degrees(math.atan(0.5))
    std = [(0, 90), (0, -90)] + [((i * 36 + 180) % 360 - 180, th if i & 1 else -th) for i in range(10)]
    out = []
    for lon, lat in std:
        lam, phi = math.radians(lon), math.radians(lat)
        x, y, z = math.cos(lam) * math.cos(phi), math.sin(lam) * math.cos(phi), math.sin(phi)
        k = z * math.cos(dg) - y * math.sin(dg)
        lam2 = math.atan2(y * math.cos(dg) + z * math.sin(dg), x * math.cos(dp) + k * math.sin(dp)) - dl
        out.append(ph.unit_vector(math.degrees(lam2), math.degrees(math.asin(k * math.cos(dp) - x * math.sin(dp)))))
    return out


def local_poly(centre, axis, outline, step=0.05):
    """A lon/lat ring around the unit vector centre: outline points (a, b) in
    degrees along axis (a unit tangent) and its normal, densified to step
    degrees (so split's own densify can stay off), closed."""
    n = ph._unit(ph._cross(centre, axis))
    t = ph._cross(n, centre)
    pts = []
    for (a0, b0), (a1, b1) in zip(outline, outline[1:] + outline[:1]):
        k = max(1, int(math.ceil(max(abs(a1 - a0), abs(b1 - b0)) / step)))
        for j in range(k):
            a, b = math.radians(a0 + (a1 - a0) * j / k), math.radians(b0 + (b1 - b0) * j / k)
            pts.append(ph.lon_lat(ph._unit(tuple(centre[i] + a * t[i] + b * n[i] for i in range(3)))))
    return pts + pts[:1]


def sphere_area(ring):
    """Signed area of a lon/lat ring with great-circle edges (unit sphere)."""
    v = [ph.unit_vector(*c) for c in ring[:-1]]
    c = ph._unit(tuple(sum(p[i] for p in v) for i in range(3)))
    s = 0.0
    for a, b in zip(v, v[1:] + v[:1]):
        s += 2 * math.atan2(ph._dot(c, ph._cross(a, b)), 1 + ph._dot(c, a) + ph._dot(a, b) + ph._dot(b, c))
    return s


def plane_area(parts):
    return sum(sum(mapgen.area2(r) for r in part) for part in parts) / 2


def merged(parts_by_region, net, grid=10):
    """MapBuilder (Identity) over the net: {rid: [parts]} -> Result."""
    window = mapgen.Window([p for _, tri in net.outline() for p in tri], 0.01, 1000.0, (0, 0))
    mb = mapgen.MapBuilder(mapgen.Identity(), window, list(parts_by_region), grid=grid)
    for rid, parts in parts_by_region.items():
        for part in parts:
            mb.add_region(rid, part)
    return mb.build(keep_islands=set(parts_by_region))


def rings_in(res, rid):
    return [mapgen.ring_from_arcs(r, res.arcs) for r in res.topo[rid]]


def mid(u, v):
    return ph._unit(tuple(ph.VERTICES[u][i] + ph.VERTICES[v][i] for i in range(3)))


def along(u, v):
    return ph._unit(tuple(ph.VERTICES[v][i] - ph.VERTICES[u][i] for i in range(3)))


class Polyhedral(unittest.TestCase):
    def test_icosahedron(self):
        vs = ph.VERTICES
        for v in vs.values():
            self.assertAlmostEqual(ph._dot(v, v), 1.0, places=15)
        edges = {tuple(sorted((f[i], f[(i + 1) % 3]))) for f in ph.FACES.values() for i in range(3)}
        self.assertEqual(len(edges), 30)
        for u, v in edges:
            self.assertAlmostEqual(ph._angle(vs[u], vs[v]), ph.EDGE_ARC, places=13)
        # Gray's table: vertex 1 at 64.7N 10.5362E, vertex 4 at 39.1N 122.3E
        for v, (lon, lat) in ((1, (10.5362, 64.7)), (4, (122.3, 39.1))):
            got = ph.lon_lat(vs[v])
            self.assertAlmostEqual(got[0], lon, places=4)
            self.assertAlmostEqual(got[1], lat, places=5)
        # d3-geo-polygon's geoAirocean puts them within 0.25 arc seconds
        for w in d3_airocean_vertices():
            self.assertLess(min(ph._angle(w, v) for v in vs.values()), math.radians(0.25 / 3600))

    def test_face_transforms(self):
        sg, cg = math.sin(ph.G), ph.COS_G
        corners = [(0.0, sg, cg), (-sg * math.sqrt(3) / 2, -sg / 2, cg), (sg * math.sqrt(3) / 2, -sg / 2, cg)]
        template = [(0, 1 / math.sqrt(3)), (-0.5, -0.5 / math.sqrt(3)), (0.5, -0.5 / math.sqrt(3))]
        rot = lambda p, a: (p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a))
        for t in (ph.GNOMONIC, ph.FULLER, ph.SNYDER):
            for u, want in zip(corners, template):
                got = t.plane(*u)
                self.assertAlmostEqual(got[0], want[0], places=12, msg=t)
                self.assertAlmostEqual(got[1], want[1], places=12, msg=t)
            self.assertEqual(tuple(round(c, 12) + 0 for c in t.plane(0, 0, 1)), (0, 0))
            for x, y in ((0.1, 0.2), (-0.3, 0.05), (0.2, -0.35)):
                z = math.sqrt(1 - x * x - y * y)
                p = t.plane(x, y, z)
                for k in (1, 2):  # a third of a turn about the centre
                    q = t.plane(*rot((x, y), k * 2 * math.pi / 3), z)
                    r = rot(p, k * 2 * math.pi / 3)
                    self.assertAlmostEqual(q[0], r[0], places=12, msg=t)
                    self.assertAlmostEqual(q[1], r[1], places=12, msg=t)
                m = t.plane(-x, y, z)  # mirror
                self.assertAlmostEqual(m[0], -p[0], places=12, msg=t)
                self.assertAlmostEqual(m[1], p[1], places=12, msg=t)
        net = ph.Polyhedral("fuller")
        for k in range(11):  # Fuller keeps the edges' arc length
            self.assertAlmostEqual(net.edge_t(ph.EDGE_ARC * k / 10), k / 10, places=12)

    def test_snyder_is_equal_area_and_gnomonic_keeps_great_circles(self):
        net = ph.Polyhedral("snyder")
        k = NET_AREA / (4 * math.pi)
        for lon, lat in ((10, 50), (-70, -20), (140, 40), (60, -50), (-160, 10), (0, -89)):
            v = ph.unit_vector(lon, lat)
            pc, _ = net.locate(v)
            e = ph._unit(ph._cross((0.0, 0.0, 1.0) if abs(v[2]) < 0.9 else (1.0, 0.0, 0.0), v))  # tangent
            n = ph._cross(v, e)
            h = 1e-6

            def at(a, b):
                return net._in_face(pc, ph._unit(tuple(v[i] + a * e[i] + b * n[i] for i in range(3))))
            p0, pe, pn = at(0, 0), at(h, 0), at(0, h)
            det = ((pe[0] - p0[0]) * (pn[1] - p0[1]) - (pn[0] - p0[0]) * (pe[1] - p0[1])) / (h * h)
            self.assertAlmostEqual(det / k, 1.0, places=4, msg=(lon, lat))
        gn = ph.Polyhedral("gnomonic")
        a, b = ph.unit_vector(5, 45), ph.unit_vector(20, 52)  # both in face 1
        pts = [gn(*ph.lon_lat(ph._unit(tuple(a[i] + s * (b[i] - a[i]) for i in range(3))))) for s in (0, 0.3, 1)]
        (x0, y0), (x1, y1), (x2, y2) = pts
        self.assertAlmostEqual((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0), 0, places=12)

    def test_net(self):
        net = ph.Polyhedral()
        self.assertEqual(len(net.pieces), 22)
        self.assertAlmostEqual(sum(abs(mapgen.area2(t)) / 2 for _, t in net.outline()), NET_AREA, places=12)
        h = math.sqrt(3) / 2
        for pc in net.pieces.values():  # Gray's lattice: x in halves, y in steps of sqrt 3 / 2
            for x, y in pc.pos.values():
                self.assertAlmostEqual(x * 2, round(x * 2), places=12)
                self.assertAlmostEqual(y / h, round(y / h), places=12)
        xs = [p[0] for _, t in net.outline() for p in t]
        ys = [p[1] for _, t in net.outline() for p in t]
        self.assertEqual((round(min(xs), 9), round(max(xs), 9), round(min(ys), 9), round(max(ys), 9)),
                         (0, 5.5, 0, round(3 * h, 9)))
        kinds = [k for k, _, _ in net.edges()]
        self.assertEqual((kinds.count("fold"), kinds.count("split")), (21, 1))
        with self.assertRaises(ValueError):  # a mirrored root
            ph.Polyhedral(root={1: ph.AIROCEAN_ROOT[1], 2: ph.AIROCEAN_ROOT[3], 3: ph.AIROCEAN_ROOT[2]})

    def test_gray_reference_points(self):
        net = ph.Polyhedral("fuller")
        for lon, lat, x, y in GRAY_POINTS:
            got = net(lon, lat)
            self.assertAlmostEqual(got[0], x, places=10, msg=(lon, lat))
            self.assertAlmostEqual(got[1], y, places=10, msg=(lon, lat))
        scaled = ph.Polyhedral("fuller", scale=7.5)
        self.assertAlmostEqual(scaled(16.37, 48.21)[0], 7.5 * GRAY_POINTS[0][2], places=9)
        for t in ("gnomonic", "fuller", "snyder"):
            ph.Polyhedral(t, scale=3).self_test()

    def test_vertices_and_folds_from_both_sides(self):
        for t in ("gnomonic", "fuller", "snyder"):
            net = ph.Polyhedral(t)
            for pc in net.pieces.values():
                f = net.faces[pc.face]
                for v in f.verts:
                    got = net._in_face(pc, ph.VERTICES[v])
                    self.assertAlmostEqual(got[0], pc.pos[v][0], places=12)
                    self.assertAlmostEqual(got[1], pc.pos[v][1], places=12)
                c = net._in_face(pc, f.m)
                self.assertAlmostEqual(c[0], sum(pc.pos[v][0] for v in f.verts) / 3, places=12)
                if pc.parent is None:
                    continue
                pp = net.pieces[pc.parent]
                u, v = sorted(set(f.verts) & set(net.faces[pp.face].verts))
                for s in (0.1, 0.37, 0.5, 0.9):  # a fold point maps alike from both faces
                    x = ph._unit(tuple((1 - s) * ph.VERTICES[u][i] + s * ph.VERTICES[v][i] for i in range(3)))
                    a, b = net._in_face(pc, x), net._in_face(pp, x)
                    self.assertAlmostEqual(a[0], b[0], places=12, msg=(t, pc.name))
                    self.assertAlmostEqual(a[1], b[1], places=12, msg=(t, pc.name))

    def test_inside_one_face(self):
        net = ph.Polyhedral()
        poly = square(15, 47, 17, 49)  # Austria-ish, face 1 only
        parts = net.split(poly)
        self.assertEqual(len(parts), 1)
        want = [net(lon, lat) for lon, lat in mapgen.open_ring(poly[0])]
        self.assertEqual([tuple(round(c, 12) for c in p) for p in parts[0][0]][::2],
                         [tuple(round(c, 12) for c in p) for p in want])  # densified: every other point

    def test_fold_merges_exactly(self):
        net = ph.Polyhedral("snyder", densify=0)
        c, ax = mid(1, 3), along(1, 3)  # the fold between pieces 1 and 2
        ring = local_poly(c, ax, [(-2, -1), (2, -1), (2, 1.5), (-2, 1.5)])
        parts = net.split([ring])
        self.assertEqual(len(parts), 2)
        shared = set(parts[0][0]) & set(parts[1][0])
        self.assertEqual(len(shared), 2)  # the two crossings of the fold, bit-identical
        self.assertAlmostEqual(plane_area(parts) / (sphere_area(ring) * NET_AREA / (4 * math.pi)), 1, places=5)
        res = merged({"A": parts}, net, grid=100)
        self.assertEqual(len(rings_in(res, "A")), 1)

    def test_fold_with_nested_crossings_and_a_hole(self):
        net = ph.Polyhedral("snyder", densify=0)
        c, ax = mid(1, 3), along(1, 3)
        u = [(-3, -1), (3, -1), (3, 1), (1, 1), (1, -0.5), (-1, -0.5), (-1, 1), (-3, 1)]  # a U across the fold
        ring = local_poly(c, ax, u)
        hole = local_poly(c, ax, [(2.5, -0.8), (1.5, -0.8), (1.5, 0.5), (2.5, 0.5)])  # in a prong, across it too
        parts = net.split([ring, hole])
        want = (sphere_area(ring) + sphere_area(hole)) * NET_AREA / (4 * math.pi)
        self.assertAlmostEqual(plane_area(parts) / want, 1, places=5)
        res = merged({"U": parts}, net, grid=100)
        rings = rings_in(res, "U")
        self.assertEqual(sorted(mapgen.area2(r) > 0 for r in rings), [False, True])  # one exterior, one hole

    def test_cut_stays_apart(self):
        net = ph.Polyhedral()
        c, ax = mid(1, 6), along(1, 6)  # between pieces 4 and 5: not folded in the net
        parts = net.split([local_poly(c, ax, [(-2, -1), (2, -1), (2, 1), (-2, 1)])])
        self.assertEqual(len(parts), 2)
        self.assertFalse(set(parts[0][0]) & set(parts[1][0]))
        self.assertEqual({net.piece_of(*ph.lon_lat(ph._unit(tuple(c[i] + s * ph._cross(c, ax)[i] for i in range(3)))))
                          for s in (-0.01, 0.01)}, {"4", "5"})
        self.assertEqual(len(rings_in(merged({"A": parts}, net), "A")), 2)

    def test_around_a_vertex(self):
        net = ph.Polyhedral("snyder", densify=0)
        v = ph.VERTICES[2]  # faces 1, 5, 6, 14, 15 meet here; in the net 6-1-5 fold together, 14 hangs on 13, 15 on 20
        ring = local_poly(v, along(2, 3), [(-4, -4), (4, -4), (4, 4), (-4, 4)])
        parts = net.split([ring])
        self.assertEqual(len(parts), 5)
        self.assertAlmostEqual(plane_area(parts) / (sphere_area(ring) * NET_AREA / (4 * math.pi)), 1, places=5)
        self.assertEqual(len(rings_in(merged({"A": parts}, net, grid=100), "A")), 3)  # 6-1-5, 14, 15

    def test_antimeridian(self):
        net = ph.Polyhedral()
        # Chukotka's latitudes (piece 3 on both sides); the two halves have different vertices on the seam
        east = [[[175, 64], [180, 64], [180, 65.5], [180, 67], [175, 67], [175, 64]]]
        west = [[[-180, 64], [-176, 64], [-176, 67], [-180, 67], [-180, 65], [-180, 64]]]
        seam = [net(180, 65.5), net(-180, 65)]

        def ring_points(polys):
            res = merged({"F": [p for poly in polys for p in net.split(poly)]}, net, grid=100)
            rings = rings_in(res, "F")
            return rings, {p for r in rings for p in r}, res
        rings, pts, res = ring_points([east, west])
        self.assertGreater(len(pts), 12)  # unstitched, the seam's T-junctions stay
        rings, pts, res = ring_points(ph.stitch_antimeridian([east, west]))
        self.assertEqual(len(rings), 1)
        w = res.window
        for x, y in seam:  # the seam cancelled: no vertex left on it
            vx, vy = w.to_view(x, y)
            self.assertNotIn((round(vx * 100), round(vy * 100)), pts)
        self.assertEqual(ph.stitch_antimeridian([square(0, 0, 1, 1)]), [square(0, 0, 1, 1)])
        self.assertEqual(net(180, 10), net(-180, 10))

    def test_antarctica_like(self):
        net = ph.Polyhedral("snyder", densify=0.25)
        ring = [[-180, -90], [-180, -70]] + [[lon, -70] for lon in range(-170, 181, 10)] + [[180, -90], [-180, -90]]
        parts = net.split([ring])
        band = 2 * math.pi * (1 - math.sin(math.radians(70)))  # the cap's area
        # parallels drawn as chords between 0.25-degree vertices: a hair less than the cap
        self.assertAlmostEqual(-plane_area(parts) / (band * NET_AREA / (4 * math.pi)), 1, places=4)  # clockwise
        rings = rings_in(merged({"ATA": parts}, net, grid=100), "ATA")
        self.assertEqual(len(rings), 1)  # Fuller's net keeps it whole

    def test_rejects_rings_wider_than_a_hemisphere(self):
        net = ph.Polyhedral()
        band = [[lon, 0] for lon in range(-180, 180, 10)] + [[lon, 10] for lon in range(180, -180, -10)]
        with self.assertRaises(mapgen.BuildError):
            net.split([band + band[:1]])
        self.assertEqual(net.split([[[1, 1], [1, 1], [1, 1]]]), [])

    def test_deterministic(self):
        net = ph.Polyhedral()
        c, ax = mid(1, 3), along(1, 3)
        ring = local_poly(c, ax, [(-3, -1), (3, -1), (3, 1), (1, 1), (1, -0.5), (-1, -0.5), (-1, 1), (-3, 1)])
        self.assertEqual(net.split([ring]), ph.Polyhedral().split([ring]))
        self.assertEqual(net.split([ring]), net.split([ring]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
