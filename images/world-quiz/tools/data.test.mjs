// Plain-node checks of world-quiz's own data and config (the engine's
// rules are tested in shared/map-quiz/tools/). No packages:
// node images/world-quiz/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MAP, COUNTRIES } from '../site/countries.js';
import config from '../site/config.js';
import { checkTexts, roundSpecs } from '../site/contract.js';

const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
// tools/countries.json: the source (build_map.py writes countries.js from it).
const SOURCE = JSON.parse(readFileSync(new URL('./countries.json', import.meta.url), 'utf8')).countries;
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

const byId = new Map(COUNTRIES.map((c) => [c.id, c]));
// The 36 (owner, 2026-11-02): land area under 1,000 km2, or an island state
// (no land border) under 30,000 km2; build_map.py checks the flags against
// that rule on the map as drawn (Cyprus, whole, has no land border).
const SMALL = ['AND', 'ATG', 'BHS', 'BHR', 'BRB', 'CPV', 'COM', 'CYP', 'DMA', 'FJI', 'GRD', 'JAM', 'KIR', 'LIE', 'MDV', 'MLT', 'MHL',
  'MUS', 'FSM', 'MCO', 'NRU', 'PLW', 'KNA', 'LCA', 'VCT', 'WSM', 'SMR', 'STP', 'SYC', 'SGP', 'SLB', 'TON', 'TTO', 'TUV',
  'VUT', 'VAT'];
// Not small, but the largest drawn shape under 4 map units: a ring in every round.
const RINGED_ALWAYS = ['BRN', 'KOS', 'LUX', 'MNE', 'QAT'];

check('data: 197 entries, countries.js matches countries.json, ids, names and capitals unique', () => {
  assert.equal(COUNTRIES.length, 197);
  assert.deepEqual(COUNTRIES.map(({ marker, size, ...rest }) => rest),
    SOURCE.map(({ marker, ...c }) => ({ id: c.id, name: c.name, capital: c.capital, ...(c.of ? { of: c.of } : {}),
      ...(c.small ? { small: true } : {}) })));
  for (const key of ['id', 'name']) assert.equal(new Set(COUNTRIES.map((c) => c[key])).size, 197, key);
  const caps = COUNTRIES.map((c) => c.capital).filter((v) => v !== null);
  assert.equal(new Set(caps).size, caps.length);
  for (const c of COUNTRIES) assert.ok(typeof c.capital === 'string' && c.capital, `${c.id} capital`);
  for (const c of COUNTRIES) assert.match(c.id, /^[A-Z]{3}$/);
});

check('data: the set (UN members, Vatican City, Kosovo, Taiwan, Greenland); no Palestine, Western Sahara, territories', () => {
  for (const id of ['VAT', 'KOS', 'TWN', 'GRL', 'RUS', 'SDS', 'CYP', 'SOM']) assert.ok(byId.has(id), id);
  for (const id of ['PSX', 'SAH', 'CYN', 'SOL', 'PRI', 'NCL', 'FLK', 'HKG', 'MAC', 'ALD', 'KAS', 'ATA', 'FRO', 'GUF']) assert.ok(!byId.has(id), id);
  assert.deepEqual(COUNTRIES.filter((c) => c.of).map((c) => [c.id, c.name, c.of]), [['GRL', 'Greenland', 'Denmark']]);
});

check('data: the 36 small states (flag) and the rings', () => {
  assert.deepEqual(COUNTRIES.filter((c) => c.small).map((c) => c.id).sort(), [...SMALL].sort());
  assert.deepEqual(COUNTRIES.filter((c) => c.marker).map((c) => c.id).sort(), [...SMALL, ...RINGED_ALWAYS].sort());
  for (const c of COUNTRIES.filter((c) => c.marker)) {
    const [x, y] = c.marker;
    assert.ok(x >= 0 && x <= MAP.width && y >= 0 && y <= MAP.height, `${c.id} marker in the window`);
    assert.ok(c.size > 0 && c.size < 30, `${c.id} size ${c.size}`);
  }
  assert.ok(byId.get('VAT').size < 0.2 && byId.get('LUX').size > 1, 'sizes are the ring\'s own polygon');
});

check('data: names and capitals as chosen (tools/README.md, Names and capitals)', () => {
  const cap = (id) => byId.get(id).capital;
  assert.deepEqual(['BOL', 'ZAF', 'NLD', 'CIV', 'BEN', 'LKA', 'SWZ', 'TZA', 'BDI', 'MYS', 'NRU', 'KIR', 'GNQ', 'MMR', 'PLW',
    'CHE', 'KAZ', 'IDN', 'YEM', 'TWN', 'KOS', 'GRL', 'ISR'].map(cap),
  ['Sucre / La Paz', 'Pretoria', 'Amsterdam', 'Yamoussoukro', 'Porto-Novo', 'Sri Jayewardenepura Kotte', 'Mbabane', 'Dodoma',
    'Gitega', 'Kuala Lumpur', 'Yaren', 'South Tarawa', 'Ciudad de la Paz', 'Naypyidaw', 'Ngerulmud', 'Bern', 'Astana',
    'Jakarta', 'Sanaa', 'Taipei', 'Pristina', 'Nuuk', 'Jerusalem']);
  assert.deepEqual(['TUR', 'CZE', 'CIV', 'CPV', 'SWZ', 'MKD', 'TLS', 'MMR', 'COD', 'COG', 'VAT', 'USA', 'STP'].map((id) => byId.get(id).name),
    ['Türkiye', 'Czechia', 'Côte d\'Ivoire', 'Cabo Verde', 'Eswatini', 'North Macedonia', 'Timor-Leste', 'Myanmar',
      'Democratic Republic of the Congo', 'Congo', 'Vatican City', 'United States', 'São Tomé and Príncipe']);
});

check('config: fits the engine contract, every round text renders, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items.length, 197);
  assert.equal(config.map, MAP);
  assert.equal(config.carryColours, false);
  assert.deepEqual(config.view, { maxScale: 60, besideHud: true, panToCentre: true });
  assert.equal(config.roundPicker, true);
  assert.equal(config.text.roundPicker, 'Pick a round (starts it fresh)');
});

check('config: rounds countries → capitals (without the small states) → all countries → all capitals', () => {
  const specs = roundSpecs(config);
  assert.deepEqual(config.rounds.map((r) => r.key), ['countries', 'capitals', 'all-countries', 'all-capitals']);
  const labels = config.rounds.map((r) => r.label);
  assert.deepEqual(labels, ['Countries', 'Capitals', 'All countries', 'All capitals']);
  assert.equal(new Set(labels).size, 4);
  for (const l of labels) assert.ok(l.length <= 14, l);
  const ids = (i) => specs[i].answers.map((a) => a.id);
  const main = COUNTRIES.filter((c) => !c.small).map((c) => c.id);
  assert.deepEqual(ids(0), main);
  assert.deepEqual(ids(1), main);
  assert.deepEqual(ids(2), COUNTRIES.map((c) => c.id));
  assert.deepEqual(ids(3), COUNTRIES.map((c) => c.id));
  assert.equal(main.length, 161);
  for (const s of SMALL) assert.ok(!ids(0).includes(s) && !ids(1).includes(s), `${s} inert in rounds 1 and 2`);
  assert.deepEqual(specs.map((s) => s.asked.length), [161, 161, 197, 197]);
  const rings = (i) => specs[i].answers.filter((a) => specs[i].byId.get(a.id).marker).map((a) => a.id).sort();
  assert.deepEqual(rings(0), [...RINGED_ALWAYS].sort());
  assert.deepEqual(rings(1), [...RINGED_ALWAYS].sort());
  assert.deepEqual(rings(2), [...SMALL, ...RINGED_ALWAYS].sort());
  assert.deepEqual(rings(3), [...SMALL, ...RINGED_ALWAYS].sort());
});

check('config: texts (prompts, misclick labels, Greenland with its state)', () => {
  const [countries, capitals, , allCapitals] = config.rounds;
  const grl = byId.get('GRL');
  assert.equal(countries.ask(grl), 'Greenland (Denmark)');
  assert.equal(capitals.ask(grl), 'Nuuk');
  assert.equal(capitals.miss(grl), 'Greenland (Denmark) · Nuuk');
  assert.equal(capitals.miss(byId.get('ISR')), 'Israel · Jerusalem');
  assert.equal(capitals.ask(byId.get('ISR')), 'Jerusalem');
  assert.equal(allCapitals.miss(byId.get('VAT')), 'Vatican City · Vatican City');
  assert.equal(capitals.prompt, 'Find the country or territory whose capital is');
  assert.match(capitals.done({ total: 161, misses: 0 }), /36 small states/);
  assert.match(countries.done({ total: 161, misses: 1 }), /^All 161 countries found · 1 misclick\./);
});

check('index.html: English, data-quiz names this image, own stylesheet after the engine\'s, ids clear of the map\'s', () => {
  const html = site('index.html');
  assert.match(html, /<html lang="en" data-quiz="world-quiz">/);
  assert.match(html, /<title>World Quiz · phw<\/title>/);
  assert.match(html, /Buckminster Fuller's Dymaxion \(Airocean\) projection/);
  assert.ok(html.indexOf('href="style.css"') < html.indexOf('href="world.css"') && html.indexOf('href="world.css"') < html.indexOf('src="theme.js"'));
  const pageIds = [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  const mapIds = [...site('map.svg').matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  for (const id of mapIds) assert.ok(!pageIds.includes(id), id);
  assert.match(html, /<span id="progress" class="num">0 \/ 161<\/span>/);
});

check('map.svg: the net (sea) and its folds first, context land, then the 197 states; nothing else', () => {
  const svg = site('map.svg');
  const [x, y, w, h] = MAP.extent;
  assert.ok(svg.startsWith(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${w} ${h}">`));
  const order = ['<path id="net" d="m', '<path id="folds" d="m', '<path id="land" d="m', '<g id="countries">'].map((s) => svg.indexOf(s));
  assert.ok(order.every((i, k) => i > 0 && (k === 0 || i > order[k - 1])), `order ${order}`);
  for (const c of COUNTRIES) assert.ok(svg.includes(`<path id="${c.id}" d="m`), c.id);
  assert.equal((svg.match(/ id="/g) || []).length, 3 + 1 + 197);
  const d = (id) => svg.match(new RegExp(`<path id="${id}" d="([^"]+)"`))[1];
  assert.equal((d('net').match(/m/g) || []).length, 1, 'the net is one ring');
  assert.ok(!/z/i.test(d('folds')), 'folds: open lines');
  assert.equal((d('folds').match(/m/g) || []).length, 21, 'the net\'s 21 folds');
  assert.ok(!svg.includes('<g id="overlays">'));
  assert.ok(Buffer.byteLength(svg) < 260_000, `${Buffer.byteLength(svg)} B`);
});

check('world.css: outside, sea and fold tokens in all three blocks; the net and folds never hit', () => {
  const css = site('world.css');
  for (const t of ['--sea', '--net-sea', '--fold']) assert.equal((css.match(new RegExp(`${t}:`, 'g')) || []).length, 3, t);
  assert.match(css, /#net \{\s*fill: var\(--net-sea\);\s*pointer-events: none;\s*\}/);
  assert.match(css, /#folds \{[^}]*fill: none;[^}]*stroke: var\(--fold\);[^}]*pointer-events: none;/);
  assert.match(site('index.html'), /<meta name="theme-color" content="#eef1f3">/);
});

console.log(`${checks} checks passed`);
