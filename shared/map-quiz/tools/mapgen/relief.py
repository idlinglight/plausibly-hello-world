"""Shaded relief for a map: an elevation grid (ESRI ASCII, e.g. a NOAA
ETOPO subset from ERDDAP) hill-shaded on a pixel grid over a box of the
map, masked to some features' land, written as a deterministic 8-bit
palette PNG (transparent, black or white with alpha) that the adapter
puts into map.svg as an <image> (shared/map-quiz/README.md, map.svg).

    dem = mapgen.read_esri_ascii(raw, (ncols, nrows), name)
    style = mapgen.ReliefStyle(ppu=2.5, ...)
    png, element, stats = mapgen.shaded_relief(res, window, inverse, dem, fids, style)

Each pixel centre goes back to lon/lat through the inverse of the map's
projection (mapgen.laea_inverse for a LambertAzimuthalEqualArea), its
elevation is bilinear between the grid's cell centres (sea and nodata
count as 0 m, so a coast doesn't shade against the sea floor); Horn's
gradient, light from RELIEF az/alt, shadow and steepness darken, slopes
facing the light lighten. The mask is the features' rings as drawn (the
result's shared arcs, even-odd over all of them), with exact coverage
along `sub` scanlines per pixel row, so the shading fades out across the
coast pixel."""
import array
import math
import os
import struct
import zlib

from .geometry import ring_from_arcs
from .output import BuildError


def read_esri_ascii(raw, grid, name="grid"):
    """An ESRI ASCII grid's bytes -> {"z": array of float32 elevations in
    metres, rows from north to south (values <= 0, sea and nodata, as 0),
    "nc", "nr", "cs" (cell size, degrees), "lat_top", "lon_left" (the
    north-west cell's centre), "max"}. grid: the expected (ncols, nrows);
    BuildError on another size or value count. The six header lines need
    xllcenter / yllcenter (cell centres, as ERDDAP writes them)."""
    parts = raw.split(b"\n", 6)
    if len(parts) < 7:
        raise BuildError(f"{name}: no ESRI ASCII header")
    hdr = {}
    for ln in parts[:6]:
        k, v = ln.split()
        hdr[k.decode("ascii").lower()] = float(v)
    if "xllcenter" not in hdr or "yllcenter" not in hdr:
        raise BuildError(f"{name}: header without xllcenter / yllcenter")
    nc, nr, cs = int(hdr["ncols"]), int(hdr["nrows"]), hdr["cellsize"]
    if (nc, nr) != tuple(grid):
        raise BuildError(f"{name}: {nc} x {nr} cells, expected {tuple(grid)}")
    z = array.array("f")
    for line in parts[6].split(b"\n"):  # row by row: a large grid needn't be one list of floats
        z.extend([v if v > 0 else 0.0 for v in map(float, line.split())])
    if len(z) != nc * nr:
        raise BuildError(f"{name}: {len(z)} values, expected {nc * nr}")
    return {"z": z, "nc": nc, "nr": nr, "cs": cs, "lat_top": hdr["yllcenter"] + (nr - 1) * cs,
            "lon_left": hdr["xllcenter"], "max": max(z)}


def inverse_error(project, inverse, points):
    """The largest error in degrees of inverse(project(lon, lat)) over points."""
    worst = 0.0
    for lon, lat in points:
        lo, la = inverse(*project(lon, lat))
        worst = max(worst, abs(lo - lon), abs(la - lat))
    return worst


class ReliefStyle:
    """The relief's look and resolution. ppu: pixels per map unit; sub:
    coverage samples per pixel row (columns: exact); az, alt: the light
    (azimuth from up, clockwise; height, degrees); z: vertical
    exaggeration; w_shadow, w_steep: darkness from facing away from the
    light and from steepness; dark: the strongest shadow (black at this
    alpha); light: the strongest highlight (white at this alpha); levels:
    alpha steps from 0 to dark (the palette, and the PNG's size)."""

    def __init__(self, ppu, sub=4, az=315.0, alt=45.0, z=5.0, w_shadow=0.8, w_steep=0.9, dark=0.55, light=0.3,
                 levels=32):
        self.ppu, self.sub, self.az, self.alt, self.z = ppu, sub, az, alt, z
        self.w_shadow, self.w_steep, self.dark, self.light, self.levels = w_shadow, w_steep, dark, light, levels


def coverage(res, fids, ppu, sub, box):
    """(cov, pw, ph): the fraction of each pixel of box (x0, y0, x1, y1, map
    units; pw x ph pixels at ppu, rows from the top) covered by the rings
    of fids as drawn in res (even-odd over all of them: their union, since
    neighbours share arcs)."""
    bx0, by0, bx1, by1 = box
    pw, ph = int(round((bx1 - bx0) * ppu)), int(math.ceil((by1 - by0) * ppu))
    g = res.grid
    edges = []
    for fid in fids:
        if fid not in res.topo:
            raise BuildError(f"relief: no outline for {fid}")
        for refs in res.topo[fid]:
            ring = ring_from_arcs(refs, res.arcs)
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if y1 == y2:
                    continue
                if y1 > y2:  # the same edge gives the same numbers from both sides
                    x1, y1, x2, y2 = x2, y2, x1, y1
                edges.append((y1 / g - by0, y2 / g - by0, x1 / g - bx0, (x2 - x1) / (y2 - y1)))
    # coverage: sub scanlines per pixel row, exact along them
    nrows = ph * sub
    dy = 1.0 / (sub * ppu)
    rows = [[] for _ in range(nrows)]
    for ylo, yhi, xlo, slope in edges:
        for s in range(max(0, int((ylo - dy / 2) / dy)), min(nrows, int((yhi - dy / 2) / dy) + 2)):
            y = dy / 2 + s * dy
            if ylo <= y < yhi:
                rows[s].append(xlo + (y - ylo) * slope)
    cov = array.array("f", bytes(4 * pw * ph))
    part = 1.0 / sub
    for s, xs in enumerate(rows):
        if len(xs) % 2:
            raise BuildError(f"relief: odd coast crossings on scanline {s}")
        xs.sort()
        base = (s // sub) * pw
        for a, b in zip(xs[0::2], xs[1::2]):
            xa, xb = max(0.0, a * ppu), min(float(pw), b * ppu)
            if xb <= xa:
                continue
            ia, ib = int(xa), int(xb)
            if ia == ib:
                cov[base + ia] += (xb - xa) * part
                continue
            cov[base + ia] += (ia + 1 - xa) * part
            for i in range(ia + 1, ib):
                cov[base + i] += part
            if ib < pw:
                cov[base + ib] += (xb - ib) * part
    return cov, pw, ph


def shaded_relief(res, window, inverse, dem, fids, style, box=None, edge_ok=False, element_id="relief",
                  href="relief.png"):
    """The relief over box (x0, y0, x1, y1 in map units; default the window,
    0 0 width height) on the land of fids (ids in res.topo; mapgen.CONTEXT
    for the context land): (png bytes, the <image> element for map.svg,
    stats). inverse: (easting, northing) -> (lon, lat), the inverse of the
    map's projection; dem: read_esri_ascii's dict, covering every pixel
    centre of the box and one pixel around it. Land on the box's edge is a
    BuildError unless edge_ok (e.g. a box that is the drawn extent, where
    the context land is clipped)."""
    if box is None:
        box = (0.0, 0.0, window.width, window.height)
    bx0, by0 = box[0], box[1]
    ppu = style.ppu
    cov, pw, ph = coverage(res, fids, ppu, style.sub, box)
    land = [i for i in range(pw * ph) if cov[i] > 0]
    if not edge_ok and any(i < pw or i >= pw * (ph - 1) or i % pw in (0, pw - 1) for i in land):
        raise BuildError("relief: land on the image's edge")

    # elevation at the land pixels and their neighbours (bilinear, cell
    # centres), on the pixel grid with a one-pixel border all round
    z, nc, cs, lat_top, lon_left = dem["z"], dem["nc"], dem["cs"], dem["lat_top"], dem["lon_left"]
    qw = pw + 2
    need = bytearray(qw * (ph + 2))
    for i in land:
        py, px = divmod(i, pw)
        j = (py + 1) * qw + px + 1
        for n in (j - qw - 1, j - qw, j - qw + 1, j - 1, j, j + 1, j + qw - 1, j + qw, j + qw + 1):
            need[n] = 1
    elev = array.array("f", bytes(4 * qw * (ph + 2)))
    k, x0, y1 = window.k, window.x0, window.y1
    for j in (j for j in range(qw * (ph + 2)) if need[j]):
        py, px = divmod(j, qw)
        py, px = py - 1, px - 1
        lon, lat = inverse((bx0 + (px + 0.5) / ppu) / k + x0, y1 - (by0 + (py + 0.5) / ppu) / k)
        fi, fj = (lat_top - lat) / cs, (lon - lon_left) / cs
        r0, c0 = int(fi), int(fj)
        if not (0 <= fi and 0 <= fj and r0 < dem["nr"] - 1 and c0 < nc - 1):
            raise BuildError(f"relief: {lon:.3f}, {lat:.3f} outside the elevation grid")
        ti, tj = fi - r0, fj - c0
        o = r0 * nc + c0
        elev[j] = (z[o] * (1 - tj) + z[o + 1] * tj) * (1 - ti) + (z[o + nc] * (1 - tj) + z[o + nc + 1] * tj) * ti

    # hillshade (Horn's gradient), screen coordinates: x right, y down, z up
    pix_m = 1.0 / ppu / k
    alt, az = math.radians(style.alt), math.radians(style.az)
    lx, ly, lz = math.cos(alt) * math.sin(az), -math.cos(alt) * math.cos(az), math.sin(alt)
    levels = style.levels
    step = style.dark / levels
    n_light = int(math.ceil(style.light / step - 1e-9))
    pal = bytearray(pw * ph)  # 0 transparent, 1..levels black, levels+1.. white
    for i in land:
        py, px = divmod(i, pw)
        j = (py + 1) * qw + px + 1
        a, b, c = elev[j - qw - 1], elev[j - qw], elev[j - qw + 1]
        d, f = elev[j - 1], elev[j + 1]
        gg, h, ii = elev[j + qw - 1], elev[j + qw], elev[j + qw + 1]
        zx = ((c + 2 * f + ii) - (a + 2 * d + gg)) / (8 * pix_m) * style.z
        zy = ((gg + 2 * h + ii) - (a + 2 * b + c)) / (8 * pix_m) * style.z
        nrm = math.sqrt(zx * zx + zy * zy + 1)
        shade = (-zx * lx - zy * ly + lz) / nrm
        dark = min(1.0, style.w_shadow * min(1.0, max(0.0, (lz - shade) / lz)) + style.w_steep * (1 - 1 / nrm))
        light = min(1.0, max(0.0, (shade - lz) / (1 - lz)))
        q = int(round((style.light * light - style.dark * dark) * min(1.0, cov[i]) / step))
        if q < 0:
            pal[i] = min(levels, -q)
        elif q > 0:
            pal[i] = levels + min(n_light, q)
    plte = bytes(3 * (1 + levels)) + b"\xff" * (3 * n_light)
    trns = bytes([0] + [int(round(255 * step * j)) for j in range(1, levels + 1)]
                 + [int(round(255 * step * j)) for j in range(1, n_light + 1)])
    png = png_palette(pw, ph, pal, plte, trns)
    el = (f'<image id="{element_id}" href="{href}" x="{bx0:g}" y="{by0:g}" width="{pw / ppu:g}" '
          f'height="{ph / ppu:g}" preserveAspectRatio="none"/>')
    stats = {"width": pw, "height": ph, "land": len(land), "shaded": sum(1 for i in land if pal[i])}
    return png, el, stats


def png_palette(w, h, pix, plte, trns):
    """An 8-bit palette PNG, deterministic (no time or text chunks). Row
    filters by the usual heuristic (least sum of absolute values; none,
    sub, up, Paeth), computed only where the row or the one above has a
    non-zero pixel (the rest filters to zeros either way)."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    def cost(seg):
        return sum(v if v < 128 else 256 - v for v in seg)

    raw = bytearray()
    prev = bytes(w)
    zero = bytes(w)
    for y in range(h):
        row = bytes(pix[y * w:(y + 1) * w])
        if row == zero and prev == zero:
            raw += b"\0" + row
            prev = row
            continue
        lo = min(w - len(row.lstrip(b"\0")), w - len(prev.lstrip(b"\0")))
        hi = min(w, max(len(row.rstrip(b"\0")), len(prev.rstrip(b"\0"))) + 1)
        seg0 = row[lo:hi]
        sub = bytes((row[i] - (row[i - 1] if i else 0)) & 255 for i in range(lo, hi))
        up = bytes((row[i] - prev[i]) & 255 for i in range(lo, hi))
        pa = bytearray(hi - lo)
        for i in range(lo, hi):
            a = row[i - 1] if i else 0
            b = prev[i]
            c = prev[i - 1] if i else 0
            pp = a + b - c
            da, db, dc = abs(pp - a), abs(pp - b), abs(pp - c)
            pa[i - lo] = (row[i] - (a if da <= db and da <= dc else (b if db <= dc else c))) & 255
        best = min(((cost(seg0), 0, seg0), (cost(sub), 1, sub), (cost(up), 2, up), (cost(pa), 4, bytes(pa))),
                   key=lambda t: (t[0], t[1]))
        raw.append(best[1])
        raw += row if best[1] == 0 else bytes(lo) + best[2] + bytes(w - hi)
        prev = row
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", plte) + chunk(b"tRNS", trns) + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def png_parts(data):
    """(IHDR, PLTE, tRNS, decompressed IDAT) of a PNG: what its pixels are,
    whatever zlib compressed them (emit_binary compares these when the
    bytes differ, e.g. under another zlib build)."""
    parts, pos, idat = {}, 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b"IDAT":
            idat += body
        else:
            parts[tag] = body
        pos += 12 + n
    return parts.get(b"IHDR"), parts.get(b"PLTE"), parts.get(b"tRNS"), zlib.decompress(idat)


def emit_binary(files, out_dir, check):
    """mapgen.emit for bytes (e.g. relief.png): writes, or with check
    compares. A PNG whose bytes differ but whose pixels don't (another zlib
    build compressed them) counts as up to date. Returns 1 if a file is out
    of date."""
    stale = []
    for name, data in files.items():
        dest = os.path.join(out_dir, name)
        print(f"{name}: {len(data)} B")
        if not check:
            with open(dest, "wb") as fh:
                fh.write(data)
            continue
        try:
            with open(dest, "rb") as fh:
                old = fh.read()
        except FileNotFoundError:
            old = None
        if old == data:
            continue
        try:
            same = old is not None and png_parts(old) == png_parts(data)
        except (zlib.error, struct.error):
            same = False
        if same:
            print(f"  {name}: same pixels, other compressed bytes (zlib {zlib.ZLIB_RUNTIME_VERSION})")
        else:
            stale.append(name)
    if check:
        print("out of date: " + ", ".join(stale) if stale else ", ".join(files) + " up to date")
    return 1 if stale else 0
