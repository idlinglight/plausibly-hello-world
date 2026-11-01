// Plain-node checks of europe-quiz's own data and config (the engine's
// rules are tested in shared/map-quiz/tools/). No packages:
// node images/europe-quiz/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { COUNTRIES, MAP } from '../site/countries.js';
import config from '../site/config.js';
import { checkTexts } from '../site/contract.js';

const ids = COUNTRIES.map((c) => c.id);
const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

check('data: 46 countries, unique names and capitals', () => {
  assert.equal(ids.length, 46);
  assert.equal(new Set(COUNTRIES.map((c) => c.name)).size, 46);
  assert.equal(new Set(COUNTRIES.map((c) => c.capital)).size, 46);
  assert.ok(!ids.includes('RUS'));
  for (const id of ['KOS', 'CYP', 'TUR', 'VAT']) assert.ok(ids.includes(id), id);
});

check('rings: the seven microstates, inside the window', () => {
  const ringed = COUNTRIES.filter((c) => c.marker).map((c) => c.id).sort();
  assert.deepEqual(ringed, ['AND', 'LIE', 'LUX', 'MCO', 'MLT', 'SMR', 'VAT']);
  for (const c of COUNTRIES.filter((c) => c.marker)) {
    const [x, y] = c.marker;
    assert.ok(x >= 0 && x <= MAP.width && y >= 0 && y <= MAP.height, c.id);
  }
});

check('config: fits the engine contract, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items, COUNTRIES);
  assert.equal(config.map, MAP);
});

check('config: rounds countries, capitals (<html data-round>; misclick labels)', () => {
  assert.deepEqual(config.rounds.map((r) => r.key), ['countries', 'capitals']);
  const aut = COUNTRIES.find((c) => c.id === 'AUT');
  assert.equal(config.rounds[0].ask(aut), 'Austria');
  assert.equal(config.rounds[1].ask(aut), 'Vienna');
  assert.equal(config.rounds[1].miss(aut), 'Austria · Vienna');
  assert.equal(config.rounds[0].done({ total: 46, misses: 1 }), 'All 46 countries found · 1 misclick. Now the capitals: find each one\'s country.');
  assert.equal(config.rounds[1].done({ total: 46, misses: 0 }), 'All 46 capitals found · no misclicks. Countries again, in a new order.');
});

check('index.html: data-quiz names this image; map.svg has a shape per country', () => {
  assert.match(site('index.html'), /<html lang="en" data-quiz="europe-quiz">/);
  const svg = site('map.svg');
  for (const id of ids) assert.ok(svg.includes(`<path id="${id}" `), id);
  assert.ok(svg.includes('<g id="countries">'));
});

console.log(`${checks} checks passed`);
