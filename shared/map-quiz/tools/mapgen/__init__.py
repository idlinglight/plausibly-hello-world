"""mapgen: the shared core of the map-quiz map generators (stdlib only,
Python 3.9+, deterministic). Per-image adapters (images/<name>/tools/
build_map.py) import it after putting shared/map-quiz/tools on sys.path
(python3 -I leaves the script's own folder off it anyway):

    sys.path.insert(0, os.path.join(REPO, "shared", "map-quiz", "tools"))
    import mapgen

Overview and the map.svg layout: shared/map-quiz/README.md. Tests:
python3 -I shared/map-quiz/tools/mapgen_test.py"""
from .build import CONTEXT, MapBuilder, Result, Window
from .geometry import (area2, bbox, build_topology, clip_ring, count_crossings, dissolve, douglas_peucker, in_polygon,
                       in_ring, open_ring, owner_of, parse_wkt, polys_of, ring_from_arcs, simplify_arc)
from .output import BuildError, emit, read_pinned
from .projection import (AIRY_1830, BESSEL_1841, GRS80, WGS84, Identity, LambertAzimuthalEqualArea, Projection,
                         TransverseMercator, epsg3035, osgb_example)
from .svg import fmt_fixed, js_string, map_svg, path_d

__all__ = [
    "CONTEXT", "MapBuilder", "Result", "Window",
    "area2", "bbox", "build_topology", "clip_ring", "count_crossings", "dissolve", "douglas_peucker", "in_polygon",
    "in_ring",
    "open_ring", "owner_of", "parse_wkt", "polys_of", "ring_from_arcs", "simplify_arc",
    "BuildError", "emit", "read_pinned",
    "AIRY_1830", "BESSEL_1841", "GRS80", "WGS84", "Identity", "LambertAzimuthalEqualArea", "Projection",
    "TransverseMercator", "epsg3035", "osgb_example",
    "fmt_fixed", "js_string", "map_svg", "path_d",
]
