// Plain-node checks of east-asia-quiz's own data and config (the engine's
// rules are tested in shared/map-quiz/tools/). No packages:
// node images/east-asia-quiz/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { COUNTRIES, MAP } from '../site/countries.js';
import config from '../site/config.js';
import { checkTexts } from '../site/contract.js';

const ids = COUNTRIES.map((c) => c.id);
const byId = Object.fromEntries(COUNTRIES.map((c) => [c.id, c]));
const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

check('data: the 18 countries, unique names and capitals', () => {
  // UN geoscheme Eastern Asia (minus Hong Kong, Macao: part of China) +
  // South-eastern Asia, plus Palau; Taiwan its own country
  const want = ['BRN', 'KHM', 'CHN', 'IDN', 'JPN', 'LAO', 'MYS', 'MNG', 'MMR', 'PRK', 'PLW', 'PHL', 'SGP', 'KOR', 'TWN', 'THA', 'TLS', 'VNM'];
  assert.deepEqual([...ids].sort(), [...want].sort());
  assert.equal(new Set(COUNTRIES.map((c) => c.name)).size, 18);
  assert.equal(new Set(COUNTRIES.map((c) => c.capital)).size, 18);
  for (const id of ['HKG', 'MAC', 'RUS', 'IND']) assert.ok(!ids.includes(id), id);
});

check('data: names and capitals as chosen (tools/README.md)', () => {
  assert.equal(byId.MMR.name, 'Myanmar');
  assert.equal(byId.MMR.capital, 'Naypyidaw');
  assert.equal(byId.IDN.capital, 'Jakarta');
  assert.equal(byId.MYS.capital, 'Kuala Lumpur');
  assert.equal(byId.PLW.capital, 'Ngerulmud');
  assert.equal(byId.JPN.capital, 'Tokyo');
  assert.equal(byId.TWN.capital, 'Taipei');
  assert.equal(byId.SGP.capital, 'Singapore');
  for (const c of COUNTRIES) assert.match(c.name + c.capital, /^[\x20-\x7e]+$/, `${c.id}: plain ASCII`);
});

check('rings: Brunei, Palau, Singapore, Timor-Leste, inside the window', () => {
  const ringed = COUNTRIES.filter((c) => c.marker).map((c) => c.id).sort();
  assert.deepEqual(ringed, ['BRN', 'PLW', 'SGP', 'TLS']);
  for (const c of COUNTRIES.filter((c) => c.marker)) {
    const [x, y] = c.marker;
    assert.ok(x >= 0 && x <= MAP.width && y >= 0 && y <= MAP.height, c.id);
    assert.ok(c.size > 0 && c.size < 60, `${c.id}: size ${c.size}`);
  }
  // Palau's ring must not be sized by the dropped Tobi (500 km away)
  assert.ok(byId.PLW.size < 10, `PLW size ${byId.PLW.size}`);
});

check('config: fits the engine contract, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items, COUNTRIES);
  assert.equal(config.map, MAP);
  assert.deepEqual(config.view, { besideHud: true });
});

check('config: rounds countries, capitals (<html data-round>; misclick labels)', () => {
  assert.deepEqual(config.rounds.map((r) => r.key), ['countries', 'capitals']);
  const vnm = byId.VNM;
  assert.equal(config.rounds[0].ask(vnm), 'Vietnam');
  assert.equal(config.rounds[1].ask(vnm), 'Hanoi');
  assert.equal(config.rounds[1].miss(vnm), 'Vietnam · Hanoi');
  assert.equal(config.rounds[1].ask(byId.SGP), 'Singapore');
  assert.equal(config.rounds[0].done({ total: 18, misses: 1 }), 'All 18 countries found · 1 misclick. Now the capitals: find each one\'s country.');
  assert.equal(config.rounds[1].done({ total: 18, misses: 0 }), 'All 18 capitals found · no misclicks. Countries again, in a new order.');
});

check('index.html: data-quiz names this image; map.svg has a shape per country', () => {
  const html = site('index.html');
  assert.match(html, /<html lang="en" data-quiz="east-asia-quiz">/);
  assert.match(html, /<title>East Asia Quiz · phw<\/title>/);
  assert.match(html, /<span id="progress" class="num">0 \/ 18<\/span>/);
  const svg = site('map.svg');
  for (const id of ids) assert.ok(svg.includes(`<path id="${id}" `), id);
  for (const id of ['HKG', 'MAC']) assert.ok(!svg.includes(`id="${id}"`), `${id} merged into China`);
  assert.ok(svg.includes('<g id="countries">'));
  assert.ok(svg.includes('<path id="land" '));
});

console.log(`${checks} checks passed`);
