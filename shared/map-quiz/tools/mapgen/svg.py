"""SVG text: compact path data, and the map.svg layout the map-quiz engine
reads (shared/map-quiz/README.md, "map.svg")."""
import json


def fmt_fixed(v, dec):
    """Integer v in units of 10**-dec -> shortest decimal text ('-.3', '12', '4.05')."""
    neg, v = v < 0, abs(v)
    ip, fp = divmod(v, 10 ** dec)
    s = str(ip) if ip else ""
    if fp:
        s += "." + str(fp).rjust(dec, "0").rstrip("0")
    if not s:
        return "0"
    return "-" + s if neg else s


def path_d(rings, dec):
    """Rings of integer points (10**-dec units) -> compact relative path data:
    'm' + implicit relative lineto per ring, closed with 'z'."""
    out = []
    prev_num = None  # last number token, to decide whether a separator is needed

    def num(s):
        nonlocal prev_num
        if prev_num is not None and not (s[0] == "-" or (s[0] == "." and "." in prev_num)):
            out.append(" ")
        out.append(s)
        prev_num = s

    last = (0, 0)
    for r in rings:
        out.append("m")
        prev_num = None
        x0, y0 = r[0]
        num(fmt_fixed(x0 - last[0], dec))
        num(fmt_fixed(y0 - last[1], dec))
        px, py = x0, y0
        for x, y in r[1:]:
            num(fmt_fixed(x - px, dec))
            num(fmt_fixed(y - py, dec))
            px, py = x, y
        out.append("z")
        prev_num = None
        last = (x0, y0)
    return "".join(out)


def lines_d(lines, dec):
    """Polylines of integer points (10**-dec units, e.g. from boundary_lines)
    -> compact relative path data of open subpaths (no 'z'): each 'm' is
    relative to the previous line's end. Stroke only (fill: none)."""
    out = []
    prev_num = None

    def num(s):
        nonlocal prev_num
        if prev_num is not None and not (s[0] == "-" or (s[0] == "." and "." in prev_num)):
            out.append(" ")
        out.append(s)
        prev_num = s

    last = (0, 0)
    for line in lines:
        out.append("m")
        prev_num = None
        px, py = last
        for x, y in line:
            num(fmt_fixed(x - px, dec))
            num(fmt_fixed(y - py, dec))
            px, py = x, y
        last = (px, py)
    return "".join(out)


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


def map_svg(result, regions, head, group_id="regions"):
    """map.svg text from a MapBuilder result: context land (<path id="land">,
    if any), the regions in <g id=group_id> (larger first, so small ones sit
    on top of a neighbour's leftover sliver), overlays in <g id="overlays">
    (if any). No styling: the engine's style.css does that."""
    if "--" in head:
        raise ValueError("head: '--' is not allowed inside an XML comment")
    paths, sizes = result.paths, result.sizes
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{result.window.viewbox()}">',
        f"<!-- {head} -->",
    ]
    if result.context in paths:
        svg.append(f'<path id="land" d="{paths[result.context]}"/>')
    svg.append(f'<g id="{group_id}">')
    for rid in sorted(regions, key=lambda a: (-sizes[a], a)):
        svg.append(f'<path id="{rid}" d="{paths[rid]}"/>')
    svg.append("</g>")
    if result.overlays:
        svg.append('<g id="overlays">')
        for oid, d in result.overlays.items():
            svg.append(f'<path id="{oid}" d="{d}"/>')
        svg.append("</g>")
    svg += ["</svg>", ""]
    return "\n".join(svg)
