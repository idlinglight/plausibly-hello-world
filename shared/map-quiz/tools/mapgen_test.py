#!/usr/bin/env python3
"""Checks of the shared map generator core (mapgen) on synthetic data:
python3 -I shared/map-quiz/tools/mapgen_test.py   (stdlib unittest)

The real-data check is each image's own `build_map.py --check` (its inputs
aren't committed)."""
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
        import hashlib
        self.assertEqual(mapgen.read_pinned(path, hashlib.sha256(raw).hexdigest(), len(raw)), raw)
        with self.assertRaises(mapgen.BuildError):
            mapgen.read_pinned(path, "0" * 64, len(raw), "https://example.org/x")


if __name__ == "__main__":
    unittest.main(verbosity=1)
