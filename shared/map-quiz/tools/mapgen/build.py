"""The map pipeline: window, then project -> clip -> snap -> dissolve -> drop
specks -> shared arcs -> simplify context -> path data.

An image's adapter (images/<name>/tools/build_map.py) loads its data,
applies its own fix-ups and decides what is a region (interactive, one
<path> per id), context land (merged into one non-interactive path) or an
overlay (non-interactive, drawn above the regions). It feeds polygons in
lon/lat to a MapBuilder, in a fixed order: the output depends on it, and
the same inputs in the same order give byte-identical output."""
import math

from .geometry import (area2, bbox, build_topology, clip_ring, dissolve, douglas_peucker, open_ring,
                       ring_from_arcs, simplify_arc)
from .output import BuildError
from .svg import path_d

CONTEXT = "land"  # feature id of the merged context land (and its element id in map.svg)


class Window:
    """The full view. points: projected (easting, northing) that must be in
    view; their bounding box plus margin (a fraction of its width) becomes
    0 0 width height in map units (x right, y down). extent: how much
    context is drawn around it, as a fraction of the window's width and
    height per side; that rectangle is map.svg's viewBox and clip box
    ((0, 0): nothing around the window, e.g. a map without context land)."""

    def __init__(self, points, margin, width, extent):
        x0, y0, x1, y1 = bbox(points)
        m = (x1 - x0) * margin
        self.x0, self.y0, self.x1, self.y1 = x0 - m, y0 - m, x1 + m, y1 + m
        self.k = width / (self.x1 - self.x0)
        self.width = width
        self.height = round((self.y1 - self.y0) * self.k, 1)
        # (0.0 - …: an extent of 0 gives 0, not -0)
        ex0, ey0 = 0.0 - round(width * extent[0], 1), 0.0 - round(self.height * extent[1], 1)
        self.extent = (ex0, ey0, width - ex0, self.height - ey0)  # x0, y0, x1, y1

    def to_view(self, e, n):
        return ((e - self.x0) * self.k, (self.y1 - n) * self.k)

    def contains(self, x, y):
        return 0 <= x <= self.width and 0 <= y <= self.height

    def viewbox(self):
        ex0, ey0, ex1, ey1 = self.extent
        return f"{ex0:g} {ey0:g} {ex1 - ex0:g} {ey1 - ey0:g}"

    def map_js(self):
        """The data module's MAP line (the engine's config.map)."""
        ex0, ey0, ex1, ey1 = self.extent
        return (f"export const MAP = {{ width: {self.width:g}, height: {self.height:g}, "
                f"extent: [{ex0:g}, {ey0:g}, {ex1 - ex0:g}, {ey1 - ey0:g}] }};")


class Result:
    def __init__(self, window, context, paths, sizes, overlays, stats):
        self.window = window
        self.context = context
        self.paths = paths        # {fid: path data}, regions + context land
        self.sizes = sizes        # {fid: larger side of the bounding box, map units}
        self.overlays = overlays  # {overlay id: path data}, in add order
        self.stats = stats

    def report(self, regions, notes=()):
        s = self.stats
        return {
            "window": f"0 0 {self.window.width:g} {self.window.height:g}",
            "viewBox (extent)": self.window.viewbox(),
            "arcs": s["arcs"],
            "points": f"{s['points_before']} -> {s['points_after']} (context-only arcs simplified)",
            "dropped islands": s["dropped"],
            "clipped parts": sorted(set(s["clipped"])) or "none",
            "overlays": ", ".join(self.overlays) or "none",
            "notes": list(notes) + s["notes"],
            "smallest": sorted((round(self.sizes[a], 1), a) for a in regions)[:9],
        }


class MapBuilder:
    """project: (lon, lat) -> (easting, northing), e.g. mapgen.epsg3035().
    regions: the interactive ids, in data order. Tuning (map units):
    grid: vertices snap to 1/grid (a power of 10); min_island: unshared
    islands below this area are dropped (regions in keep_islands never);
    context_tol / far_tol: Douglas-Peucker for arcs only context land uses,
    near / beyond far_gap around the window (far_min_island: context
    islands entirely out there are dropped below this area); overlay_tol:
    Douglas-Peucker for overlays. Region arcs are never simplified."""

    def __init__(self, project, window, regions, *, grid=10, min_island=0.3, context_tol=0.2, far_tol=1.5,
                 far_min_island=4, far_gap=20, overlay_tol=0.2):
        self.dec = round(math.log10(grid))
        if 10 ** self.dec != grid:
            raise ValueError("grid must be a power of 10")
        self.project, self.window, self.grid = project, window, grid
        self.regions = list(regions)
        self.min_island, self.context_tol, self.far_tol = min_island, context_tol, far_tol
        self.far_min_island, self.far_gap, self.overlay_tol = far_min_island, far_gap, overlay_tol
        self.features = {}  # fid -> snapped rings; insertion order = first add
        self.overlay_rings = {}
        self.source = {}    # region id -> lon/lat polygons (for the below-the-grid fallback)
        self.clipped = []

    def view(self, lon, lat):
        """lon/lat -> map units."""
        e, n = self.project(lon, lat)
        return self.window.to_view(e, n)

    def point(self, lon, lat, label):
        """A point (e.g. a marker) in map units; BuildError if outside the window."""
        x, y = self.view(lon, lat)
        if not self.window.contains(x, y):
            raise BuildError(f"{label}: outside the window")
        return x, y

    def _snap(self, poly, inside_window=False, fid=None, label=None):
        """Projected, clipped to the extent, snapped rings: exteriors clockwise on
        screen (positive area, y down), holes negative. Degenerate rings dropped."""
        ex0, ey0, ex1, ey1 = self.window.extent
        g = self.grid
        out = []
        for ri, ring in enumerate(poly):
            pr = [self.view(c[0], c[1]) for c in open_ring(ring)]
            if inside_window and not all(self.window.contains(x, y) for x, y in pr):
                raise BuildError(f"{fid}: geometry outside the window (ring bbox "
                                 f"{tuple(round(v, 1) for v in bbox(pr))}, window 0 0 {self.window.width:g} "
                                 f"{self.window.height:g}); a part that may be clipped needs outside_ok")
            if not all(ex0 <= x <= ex1 and ey0 <= y <= ey1 for x, y in pr):
                if ri == 0 and label:
                    self.clipped.append(label)
                pr = clip_ring(pr, ex0, ey0, ex1, ey1)
            q = []
            for x, y in pr:
                pt = (round(x * g), round(y * g))
                if not q or q[-1] != pt:
                    q.append(pt)
            while len(q) > 1 and q[0] == q[-1]:
                q.pop()
            if len(q) < 3 or area2(q) == 0:
                continue
            if (ri == 0) != (area2(q) > 0):
                q.reverse()
            out.append(q)
        return out

    def add_region(self, rid, poly, outside_ok=False, label=None):
        """A polygon of region rid. It must lie inside the window unless
        outside_ok (remote parts): then it may be clipped at the extent, and
        label names it in the report if it is."""
        if rid not in self.regions:
            raise BuildError(f"{rid}: not in regions")
        self.source.setdefault(rid, []).append(poly)
        for q in self._snap(poly, inside_window=not outside_ok, fid=rid, label=label if outside_ok else None):
            self.features.setdefault(rid, []).append(q)

    def add_context(self, poly):
        """A polygon of context land (merged with all other context land)."""
        for q in self._snap(poly):
            self.features.setdefault(CONTEXT, []).append(q)

    def add_overlay(self, oid, poly):
        """A polygon of overlay oid (e.g. water), drawn above the regions,
        outside the shared topology."""
        for q in self._snap(poly):
            self.overlay_rings.setdefault(oid, []).append(q)

    def build(self, keep_islands=()):
        g, w = self.grid, self.window
        features = self.features
        for fid in list(features):
            features[fid] = dissolve(features[fid])

        fg = self.far_gap
        near = (-fg * g, -fg * g, (w.width + fg) * g, (w.height + fg) * g)

        def far(points):
            bx0, by0, bx1, by1 = bbox(points)
            return bx1 < near[0] or bx0 > near[2] or by1 < near[1] or by0 > near[3]

        def simplify_context(a):
            """Runs of far points get far_tol, the rest context_tol; run ends stay put."""
            flags = [far([p]) for p in a]
            if all(f == flags[0] for f in flags):
                return simplify_arc(a, (self.far_tol if flags[0] else self.context_tol) * g)
            out, start = [a[0]], 0
            for i in range(1, len(a)):
                if i == len(a) - 1 or flags[i + 1] != flags[start]:
                    run = a[start:i + 1]
                    tol = self.far_tol if all(flags[start:i + 1]) else self.context_tol
                    out.extend(douglas_peucker(run, tol * g)[1:])
                    start = i
            return out

        # Drop tiny islands that share no vertex with another ring.
        _, _, uses = build_topology(features)
        dropped = 0
        for fid, rings in features.items():
            if fid in keep_islands or not rings:
                continue
            big = max(rings, key=lambda r: abs(area2(r)))

            def keep(r):
                if r is big or any(uses[p] > 1 for p in r):
                    return True
                limit = self.far_min_island if fid == CONTEXT and far(r) else self.min_island
                return abs(area2(r)) >= 2 * limit * g * g

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
        arcs = [simplify_context(a) if users == {CONTEXT} else a for a, users in zip(arcs, arc_users)]
        n_after = sum(len(a) for a in arcs)

        paths, sizes = {}, {}
        for fid, refs in topo.items():
            rings = [ring_from_arcs(r, arcs) for r in refs]
            rings = [r for r in rings if len(set(r)) >= 3]
            if not rings:
                continue
            paths[fid] = path_d(rings, self.dec)
            bx = bbox([p for r in rings for p in r])
            sizes[fid] = max(bx[2] - bx[0], bx[3] - bx[1]) / g

        # Regions lost to the grid entirely: their own outline, 10x finer,
        # outside the shared topology, drawn on top of the neighbour. (Region
        # geometry lies inside the window, so whatever is missing here was
        # snapped away.)
        notes = []
        for rid in self.regions:
            if rid in paths:
                continue
            fine = []
            for p in self.source.get(rid, []):
                ring = [self.view(c[0], c[1]) for c in open_ring(p[0])]
                q = [(round(x * g * 10), round(y * g * 10)) for x, y in ring]
                if len(set(q)) < 3 or area2(q) == 0:
                    continue
                if area2(q) < 0:
                    q.reverse()
                fine.append(q)
            if not fine:
                raise BuildError(f"{rid}: nothing left even at 1/{g * 10} unit")
            paths[rid] = path_d(fine, self.dec + 1)
            bx = bbox([p for r in fine for p in r])
            sizes[rid] = max(bx[2] - bx[0], bx[3] - bx[1]) / (g * 10)
            notes.append(f"{rid}: below the grid, outline kept at 1/{g * 10} unit")

        overlays = {}
        for oid, rings in self.overlay_rings.items():
            rings = [r for r in dissolve(rings) if abs(area2(r)) >= 2 * self.min_island * g * g]
            rings = [simplify_arc(r + [r[0]], self.overlay_tol * g)[:-1] for r in rings]
            rings = [r for r in rings if len(set(r)) >= 3]
            if rings:
                overlays[oid] = path_d(rings, self.dec)

        stats = {"arcs": len(arcs), "points_before": n_before, "points_after": n_after, "dropped": dropped,
                 "clipped": self.clipped, "notes": notes}
        return Result(w, CONTEXT, paths, sizes, overlays, stats)
