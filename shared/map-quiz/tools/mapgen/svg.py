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


class _PathText:
    """Compact path data: commands and number tokens, with a separator only
    where the next number would otherwise run into the previous one."""

    def __init__(self):
        self.out = []
        self.prev = None  # last number token since the last command

    def cmd(self, c):
        self.out.append(c)
        self.prev = None

    def num(self, s):
        if self.prev is not None and not (s[0] == "-" or (s[0] == "." and "." in self.prev)):
            self.out.append(" ")
        self.out.append(s)
        self.prev = s

    def text(self):
        return "".join(self.out)


def path_d(rings, dec):
    """Rings of integer points (10**-dec units) -> compact relative path data:
    'm' + implicit relative lineto per ring, closed with 'z'."""
    w = _PathText()
    last = (0, 0)
    for r in rings:
        w.cmd("m")
        x0, y0 = r[0]
        w.num(fmt_fixed(x0 - last[0], dec))
        w.num(fmt_fixed(y0 - last[1], dec))
        px, py = x0, y0
        for x, y in r[1:]:
            w.num(fmt_fixed(x - px, dec))
            w.num(fmt_fixed(y - py, dec))
            px, py = x, y
        w.cmd("z")
        last = (x0, y0)
    return w.text()


def lines_d(lines, dec):
    """Polylines of integer points (10**-dec units, e.g. from boundary_lines)
    -> compact relative path data of open subpaths (no 'z'): each 'm' is
    relative to the previous line's end. Stroke only (fill: none)."""
    w = _PathText()
    last = (0, 0)
    for line in lines:
        w.cmd("m")
        px, py = last
        for x, y in line:
            w.num(fmt_fixed(x - px, dec))
            w.num(fmt_fixed(y - py, dec))
            px, py = x, y
        last = (px, py)
    return w.text()


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
