#!/usr/bin/env python3
"""Checks of the shared map generator core (mapgen) on synthetic data:
python3 -I shared/map-quiz/tools/mapgen_test.py   (stdlib unittest)

The real-data check is each image's own `build_map.py --check` (its inputs
aren't committed)."""
import hashlib
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
