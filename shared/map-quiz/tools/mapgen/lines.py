"""Lines along the region edges: outlines of groups of regions (a coast, the
borders between provinces of a country, …) taken from the shared arcs, so
they lie exactly on the edges of the region paths. For line overlays in
map.svg (path data: svg.lines_d), drawn above the regions."""
from .output import BuildError

_OUTSIDE = object()  # the other side of an arc: context land, an ungrouped region, nothing


def boundary_lines(res, group_of, inner=True, outer=True):
    """Polylines along the arcs whose two sides fall in different groups.
    res: a MapBuilder result. group_of: {region id: group key} (any hashable
    key); context land, regions not in group_of, and nothing (an arc with
    one user) are outside. inner: edges between two groups; outer: edges
    between a group and the outside (a coast, the edge against context land
    or an ungrouped region). Each edge once, chained into polylines between
    the points where three or more meet (closed loops start at their
    smallest point); deterministic, independent of group_of's order.
    Integer points (1/res.grid units), never simplified on their own (they
    are the region edges). BuildError for a grouped id that isn't in
    res.topo (a region lost to the grid has no shared edges)."""
    for rid in group_of:
        if rid == res.context:
            raise BuildError(f"boundary_lines: {rid} is context land, not a region")
        if rid not in res.topo:
            if rid in res.paths:
                raise BuildError(f"boundary_lines: {rid} fell below the grid (drawn from its own outline, outside "
                                 "the shared arcs): leave it ungrouped, or use a finer grid")
            raise BuildError(f"boundary_lines: {rid} is not a region of this map")
    users = [[] for _ in res.arcs]
    for fid, refs in res.topo.items():
        for ring in refs:
            for ref in ring:
                users[ref if ref >= 0 else ~ref].append(fid)
    edges = set()
    for arc, fids in zip(res.arcs, users):
        if not fids:
            continue
        sides = [_OUTSIDE if f == res.context else group_of.get(f, _OUTSIDE) for f in fids]
        if len(sides) == 1:
            sides.append(_OUTSIDE)
        groups = {k for k in sides if k is not _OUTSIDE}
        if (inner and len(groups) >= 2) or (outer and groups and _OUTSIDE in sides):
            for a, b in zip(arc, arc[1:]):
                if a != b:
                    edges.add((min(a, b), max(a, b)))
    return chain_edges(edges)


def chain_edges(edges):
    """Undirected edges {(a, b)} of integer points -> polylines: each edge
    once, a line runs on through every point where exactly two edges meet;
    lines start at the other points (ends, junctions) in sorted order, then
    closed loops at their smallest point. Deterministic."""
    nbrs = {}
    for a, b in edges:
        nbrs.setdefault(a, []).append(b)
        nbrs.setdefault(b, []).append(a)
    for v in nbrs.values():
        v.sort()
    used = set()

    def walk(a, b):
        line = [a, b]
        used.add((min(a, b), max(a, b)))
        while len(nbrs[b]) == 2:
            c = nbrs[b][0] if nbrs[b][1] == a else nbrs[b][1]
            e = (min(b, c), max(b, c))
            if e in used:
                break
            used.add(e)
            line.append(c)
            a, b = b, c
        return line

    lines = []
    for v in sorted(p for p, n in nbrs.items() if len(n) != 2):
        for w in nbrs[v]:
            if (min(v, w), max(v, w)) not in used:
                lines.append(walk(v, w))
    for v in sorted(nbrs):  # closed loops without a junction
        for w in nbrs[v]:
            if (min(v, w), max(v, w)) not in used:
                lines.append(walk(v, w))
    return lines
