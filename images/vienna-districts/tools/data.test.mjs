// Plain-node checks of vienna-districts' own data and config (the engine's
// rules are tested in shared/map-quiz/tools/). No packages:
// node images/vienna-districts/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DISTRICTS, MAP } from '../site/districts.js';
import config from '../site/config.js';
import { checkTexts } from '../site/contract.js';

const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

// Stadt Wien's official district names (NAMEK), by number.
const OFFICIAL = [
  'Innere Stadt', 'Leopoldstadt', 'Landstraße', 'Wieden', 'Margareten', 'Mariahilf', 'Neubau', 'Josefstadt',
  'Alsergrund', 'Favoriten', 'Simmering', 'Meidling', 'Hietzing', 'Penzing', 'Rudolfsheim-Fünfhaus', 'Ottakring',
  'Hernals', 'Währing', 'Döbling', 'Brigittenau', 'Floridsdorf', 'Donaustadt', 'Liesing',
];

check('data: 23 districts, numbers 1-23, ids d01-d23, the official names', () => {
  assert.equal(DISTRICTS.length, 23);
  assert.deepEqual(DISTRICTS.map((d) => d.number), Array.from({ length: 23 }, (_, i) => i + 1));
  assert.deepEqual(DISTRICTS.map((d) => d.id), DISTRICTS.map((d) => `d${String(d.number).padStart(2, '0')}`));
  assert.deepEqual(DISTRICTS.map((d) => d.name), OFFICIAL);
  assert.equal(new Set(DISTRICTS.map((d) => d.name)).size, 23);
  assert.ok(DISTRICTS.every((d) => d.marker === undefined), 'no rings');
});

check('map: 1000 units wide, no context around the window', () => {
  assert.equal(MAP.width, 1000);
  assert.deepEqual(MAP.extent, [0, 0, MAP.width, MAP.height]);
});

check('config: fits the engine contract, every round text renders, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items, DISTRICTS);
  assert.equal(config.map, MAP);
  assert.equal(config.attribution, 'Datenquelle: Stadt Wien – data.wien.gv.at');
  assert.deepEqual(config.view, { maxScale: 6, besideHud: true });
});

check('config: rounds names, numbers (<html data-round>); German texts', () => {
  assert.deepEqual(config.rounds.map((r) => r.key), ['names', 'numbers']);
  assert.deepEqual(config.rounds.map((r) => r.label), ['Namen', 'Nummern']);
  const d = (n) => DISTRICTS[n - 1];
  assert.equal(config.rounds[0].ask(d(2)), 'Leopoldstadt');
  assert.equal(config.rounds[1].ask(d(2)), '2. Bezirk');
  assert.equal(config.rounds[1].ask(d(23)), '23. Bezirk');
  for (const r of config.rounds) {
    assert.equal(r.miss(d(2)), 'Leopoldstadt · 2.');
    assert.equal(r.miss(d(15)), 'Rudolfsheim-Fünfhaus · 15.');
  }
  assert.equal(`${config.rounds[1].prompt} ${config.rounds[1].ask(d(2))}`, 'Finde den 2. Bezirk');
  assert.equal(config.rounds[0].done({ total: 23, misses: 1 }), 'Alle 23 Bezirke gefunden · 1 Fehlklick. Jetzt die Nummern.');
  assert.equal(config.rounds[0].done({ total: 23, misses: 3 }), 'Alle 23 Bezirke gefunden · 3 Fehlklicks. Jetzt die Nummern.');
  assert.equal(config.rounds[1].done({ total: 23, misses: 0 }), 'Alle 23 Nummern gefunden · ohne Fehlklick. Wieder die Namen, neu gemischt.');
  assert.deepEqual(config.text.theme('dark', false), { label: 'In den dunklen Modus wechseln', title: 'In den dunklen Modus wechseln' });
  assert.deepEqual(config.text.theme('light', true), { label: 'In den hellen Modus wechseln', title: 'Zurück zur Systemeinstellung (hell)' });
});

check('index.html: German, data-quiz names this image, own stylesheet after the engine\'s', () => {
  const html = site('index.html');
  assert.match(html, /<html lang="de" data-quiz="vienna-districts">/);
  assert.match(html, /<title>Wiener Bezirke · phw<\/title>/);
  assert.ok(html.indexOf('href="style.css"') < html.indexOf('href="vienna.css"') && html.indexOf('href="vienna.css"') < html.indexOf('src="theme.js"'));
  assert.match(html, /<span id="progress" class="num">0 \/ 23<\/span>/);
});

check('map.svg: a shape per district in #districts, the water overlay above', () => {
  const svg = site('map.svg');
  assert.ok(svg.includes(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 ${MAP.height}">`));
  for (const d of DISTRICTS) assert.ok(svg.includes(`<path id="${d.id}" `), d.id);
  assert.ok(svg.indexOf('<g id="districts">') < svg.indexOf('<g id="overlays">\n<path id="water" d="m'));
  assert.equal((svg.match(/ id="/g) || []).length, 23 + 3);
});

check('vienna.css: background, water and outline tokens; colours in all three token blocks', () => {
  const css = site('vienna.css');
  assert.equal((css.match(/--sea:/g) || []).length, 3);
  assert.equal((css.match(/--water:/g) || []).length, 3);
  assert.match(css, /--overlay-stroke: 1\.6px;/);
});

console.log(`${checks} checks passed`);
