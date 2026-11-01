# vienna-districts tools

Offline generator for the map data. Not part of the image (the Dockerfile
copies `site/` only); its outputs are committed:

- `site/map.svg`: one `<path id="d01">` … `<path id="d23">` per district
  inside `<g id="districts">`, the water as `<path id="water">` in
  `<g id="overlays">` above them. Nothing around the city. No styling in
  the file: the engine's `style.css` and `site/vienna.css` do that.
- `site/districts.js`: numbers, official names and the map's window
  (`MAP`). `site/config.js` (hand-written) hands it and the German texts
  to the shared map-quiz engine.

Both carry a "generated, don't edit" header. Edit `districts.json`
(numbers, names, the water seed points: the single source of truth next to
the two data files) or `build_map.py`, then regenerate.

`build_map.py` is this image's adapter: the two Stadt Wien files, the water
selection and the checks. The geometry (shared borders, simplification,
SVG writing, `--check`) is the shared core in `shared/map-quiz/tools/mapgen`
(`shared/map-quiz/README.md`), which the script imports from there.

## Regenerate

```sh
mkdir -p /tmp/wien
curl -fsS -o /tmp/wien/districts.csv 'https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:BEZIRKSGRENZEOGD&srsName=EPSG:31256&propertyName=SHAPE,BEZNR,NAMEK&sortBy=BEZNR&outputFormat=csv'
curl -fsS -o /tmp/wien/water.csv 'https://data.wien.gv.at/daten/geo?service=WFS&request=GetFeature&version=1.1.0&typeName=ogdwien:REALNUT2024OGD&srsName=EPSG:31256&propertyName=SHAPE,OBJECTID&cql_filter=CODE=241&sortBy=OBJECTID&outputFormat=csv'
python3 -I images/vienna-districts/tools/build_map.py /tmp/wien/districts.csv /tmp/wien/water.csv
python3 -I images/vienna-districts/tools/build_map.py /tmp/wien/districts.csv /tmp/wien/water.csv --check  # files up to date?
node images/vienna-districts/tools/data.test.mjs   # this image's data and config (Node 22.12+)
```

The engine's own tests and the generator core's live in
`shared/map-quiz/tools/`; CI runs them and `data.test.mjs`
(`.github/workflows/shared-sync.yml`), not `build_map.py --check` (its
inputs aren't committed).

Python 3.9+, standard library only. Output is deterministic: re-running
gives byte-identical files (`--check` compares without writing). It prints
sizes (raw, gzip -1 as nginx serves it, gzip -9), what it drew and left out
of the water, and the gaps between drawn water.

## Data

Stadt Wien open data, [data.wien.gv.at](https://www.data.gv.at/), WFS
service `https://data.wien.gv.at/daten/geo`, both layers in EPSG:31256
(MGI / Austria GK East), as CSV with WKT geometry. Licence **CC BY 4.0**;
the required attribution, verbatim, is on the page (config
`attribution`, shown under the controls or in the bottom-left corner):

> Datenquelle: Stadt Wien – data.wien.gv.at

| File (argument) | Layer | Pin |
| --- | --- | --- |
| `districts.csv` | `ogdwien:BEZIRKSGRENZEOGD` (Bezirksgrenzen), fields `SHAPE,BEZNR,NAMEK`, sorted by `BEZNR` | sha256 `a739a7b22a4fd38b43e58c956ac3bdda7da1a0ebd142cc23dbfe2153ab9e63e2`, 3 819 258 bytes |
| `water.csv` | `ogdwien:REALNUT2024OGD` (Realnutzungskartierung 2024), `CODE=241` "Gewässer inkl. Bachbett", fields `SHAPE,OBJECTID`, sorted by `OBJECTID` | sha256 `04ef8cdae7d83bd1c2aea6b6be1323633cdf85839cc6e0c500cb5543c9b04335`, 645 061 bytes, **of the file with its first column removed** |

Snapshot: downloaded 2026-11-01 (and again later that day: identical). The
district file is byte-stable between requests. The water file is not: the
server numbers the features anew on every request (`FID`, the first
column, e.g. `REALNUT2024OGD.fid-73bffeb0_…`), so the script hashes it
with everything up to the first comma of each line cut off (the `FID`
holds no comma) and checks that. Both files stay outside the repository,
like europe-quiz's Natural Earth file; there is no archive of the raw
input.

### Re-pin (when Stadt Wien refreshes a layer)

A refreshed layer changes the bytes, and the script stops with the sha256
and size it found. Then:

1. Download both files again (commands above) into a fresh folder.
2. Put the printed sha256 and size into `DISTRICTS_SHA256` /
   `DISTRICTS_BYTES` or `WATER_SHA256` / `WATER_BYTES` in `build_map.py`,
   and the download date in its comment and here.
3. Regenerate. The script checks district numbers and names against
   `districts.json`; a seed point outside all water, or two seeds in one
   body, stops it (fix the seed in `districts.json`). Read the report: the
   water drawn (bodies, hectares), the largest water left out, the widest
   gaps between drawn water (`site/vienna.css`'s `--overlay-stroke`, 1.6
   map units ≈ 49 m, has to stay above them).
4. Review the map diff: `git diff --stat site/`, and look at the page
   (full view and zoomed into the Donaukanal), before committing the new
   pins together with the regenerated files.

## Districts

23 features, `BEZNR` 1–23, `NAMEK` the official names (asserted against
`districts.json`, e.g. "Landstraße", "Rudolfsheim-Fünfhaus"). Districts
3, 4, 10, 12 and 15 come as `CURVEPOLYGON` with straight segments only;
the script reads them as `POLYGON` and stops on a real arc
(`CIRCULARSTRING`, `COMPOUNDCURVE`). The boundaries share their vertices
exactly (clean topology) and include the water: the Danube's main channel
lies in districts 2 / 20 and 21 / 22, the Donauinsel and the Neue Donau in
21 / 22, the Donaukanal in 2 / 20. On the page a click on the water picks
the district beneath (the overlay is never hit).

## Water

What the page draws: Donau, Neue Donau, Donaukanal, Alte Donau and the
open stretches of the Wienfluss, with the harbour basins and small pieces
that touch them. Left out: the Lobau's backwaters, the Liesingbach and
the other creeks, ponds and gravel-pit lakes, the Donau-Oder-Kanal basins,
the Prater's Heustadelwasser.

How: the layer has 450 polygons, cut wherever a bridge crosses. Polygons
closer than 20 m form a body (`BODY_GAP`: footbridges, weirs); a body is
drawn if it holds one of the seed points in `districts.json` (EPSG:31256
metres, a point well inside the body's largest piece; 37 seeds, grouped by
river). Bridges wider than 20 m split a river into several bodies, each
with its own seed. A seed list rather than a size or width rule: such
rules kept fragments of creeks and ponds and lost short river pieces. To
draw more water, add a seed inside it (any point in its largest piece).

Gaps: the widest gap between drawn bodies is 40 m (bridges over the Danube
and the Donaukanal); the overlay's same-coloured outline (1.6 units)
closes them on the page at every zoom. Where the Wienfluss is covered, the
map shows it as it is: the long vault from the Naschmarkt to the
Stadtpark, the square at Hietzing (Kennedybrücke, 89 m) and a few wide
road crossings stay breaks.

## Map geometry

- No projection: EPSG:31256 is a transverse Mercator with its central
  meridian (16°20′ E) through Vienna, conformal and true to scale within
  a few parts in 10 000 here. The window is the districts' bounding box
  plus 2 % (`MARGIN`), scaled to 1000 units wide (1 unit ≈ 30.6 m; window
  `0 0 1000 782.2`), y down. No context around it (extent = window).
- Shared borders: vertices snap to a 0.1-unit grid (≈ 3 m), borders become
  shared arcs (neighbours use identical vertices, no slivers or gaps).
- Simplification: the source is densified to ~0.1 m steps (16 288 points
  after snapping); Douglas-Peucker 0.25 units (≈ 7.7 m) on the shared arcs
  (`REGION_TOL`, mapgen's `region_tol`) leaves 1 792. The script asserts 0
  arc crossings and one outline per district. Water: 0.2 units, outside
  the shared topology.
- Size: `map.svg` 31 KB, 13 KB as served (gzip -1). The smallest districts
  at a 390 px phone's full view: Josefstadt 16 px, Neubau 22 px across;
  zoom (up to 6 px per unit, `config.view.maxScale`) is enough, no rings.
