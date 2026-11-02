// Plain-node checks of south-america-quiz's own data and config (the
// engine's rules are tested in shared/map-quiz/tools/). No packages:
// node images/south-america-quiz/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { COUNTRIES, MAP } from '../site/countries.js';
import config from '../site/config.js';
import { checkTexts } from '../site/contract.js';

const ids = COUNTRIES.map((c) => c.id);
const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
const source = JSON.parse(readFileSync(new URL('./countries.json', import.meta.url), 'utf8')).countries;
const SOVEREIGN = ['ARG', 'BOL', 'BRA', 'CHL', 'COL', 'ECU', 'GUY', 'PER', 'PRY', 'SUR', 'URY', 'VEN'];
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

check('data: the quiz set is countries.json without quiz: false, in its order', () => {
  assert.deepEqual(ids, source.filter((c) => c.quiz !== false).map((c) => c.id));
  for (const c of COUNTRIES) {
    const s = source.find((e) => e.id === c.id);
    assert.equal(c.name, s.name, c.id);
    assert.equal(c.capital, s.capital, c.id);
    assert.equal(c.of, s.of, c.id);
  }
});

check('data: 12 sovereign states + French Guiana (France), Falklands context land; unique names and capitals', () => {
  assert.equal(ids.length, 13);
  for (const id of SOVEREIGN) assert.ok(ids.includes(id), id);
  assert.ok(!ids.includes('FLK') && !ids.includes('TTO'));
  assert.deepEqual(COUNTRIES.filter((c) => c.of).map((c) => [c.id, c.name, c.capital, c.of]), [['GUF', 'French Guiana', 'Cayenne', 'France']]);
  assert.equal(new Set(COUNTRIES.map((c) => c.name)).size, ids.length);
  assert.equal(new Set(COUNTRIES.map((c) => c.capital)).size, ids.length);
});

check('rings: none at this scale (French Guiana, the smallest, is ~23 px on a portrait phone)', () => {
  assert.deepEqual(COUNTRIES.filter((c) => c.marker).map((c) => c.id), []);
});

check('config: fits the engine contract, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items, COUNTRIES);
  assert.equal(config.map, MAP);
  assert.deepEqual(config.view, { maxScale: 6, besideHud: true });
});

check('config: rounds countries, capitals (<html data-round>; misclick labels; French Guiana and Bolivia)', () => {
  assert.deepEqual(config.rounds.map((r) => r.key), ['countries', 'capitals']);
  const [countries, capitals] = config.rounds;
  const by = (id) => COUNTRIES.find((c) => c.id === id);
  assert.equal(countries.ask(by('PER')), 'Peru');
  assert.equal(countries.ask(by('GUF')), 'French Guiana (France)');
  assert.equal(countries.miss(by('GUF')), 'French Guiana (France)');
  assert.equal(capitals.ask(by('BRA')), 'Brasília');
  assert.equal(capitals.ask(by('BOL')), 'Sucre / La Paz');
  assert.equal(capitals.ask(by('GUF')), 'Cayenne');
  assert.equal(capitals.miss(by('PRY')), 'Paraguay · Asunción');
  assert.equal(capitals.miss(by('GUF')), 'French Guiana (France) · Cayenne');
  assert.equal(capitals.prompt, 'Find the country or territory whose capital is');
  assert.equal(countries.done({ total: 13, misses: 1 }), 'All 13 found · 1 misclick. Now the capitals: find each one on the map.');
  assert.equal(capitals.done({ total: 13, misses: 0 }), 'All 13 capitals found · no misclicks. Countries again, in a new order.');
});

check('index.html: data-quiz names this image; map.svg has a shape per quiz entry', () => {
  const html = site('index.html');
  assert.match(html, /<html lang="en" data-quiz="south-america-quiz">/);
  assert.match(html, /<title>South America Quiz · phw<\/title>/);
  const svg = site('map.svg');
  for (const id of ids) assert.ok(svg.includes(`<path id="${id}" `), id);
  assert.ok(svg.includes('<g id="countries">'));
  assert.ok(!svg.includes('id="FLK"'));
});

console.log(`${checks} checks passed`);
