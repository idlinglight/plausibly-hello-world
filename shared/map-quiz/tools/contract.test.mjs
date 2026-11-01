// Plain-node checks of the engine's contract.js (the config checks main.js
// runs at start) on synthetic configs.
// No packages: node shared/map-quiz/tools/contract.test.mjs
import assert from 'node:assert/strict';
import { checkConfig, checkTexts } from '../site/contract.js';

let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

// A minimal valid config: three districts, two rounds, German texts.
function good() {
  return {
    map: { width: 1000, height: 800, extent: [0, 0, 1000, 800] },
    items: [
      { id: 'd01', name: 'Innere Stadt', number: 1 },
      { id: 'd02', name: 'Leopoldstadt', number: 2 },
      { id: 'd03', name: 'Landstraße', number: 3, marker: [500, 400], size: 3.5 },
    ],
    rounds: [
      { key: 'names', label: 'Namen', prompt: 'Finde', ask: (d) => d.name, miss: (d) => d.name, done: ({ total }) => `Alle ${total} gefunden.` },
      { key: 'numbers', label: 'Nummern', prompt: 'Finde', ask: (d) => `${d.number}. Bezirk`, miss: (d) => `${d.name} · ${d.number}.`, done: () => 'Fertig.' },
    ],
    text: {
      intro: { mouse: 'Klick', touch: 'Tipp' },
      newGame: 'Neues Spiel',
      reset: 'Zurücksetzen',
      resetArmed: 'Wirklich?',
      mapError: 'Karte nicht geladen',
      theme: (other, override) => ({ label: other, title: override ? 'System' : other }),
    },
    attribution: 'Datenquelle: Stadt Wien – data.wien.gv.at',
    view: { maxScale: 6 },
  };
}

const throwsWith = (fn, re) => assert.throws(fn, (e) => e instanceof Error && re.test(e.message), re.toString());

check('a valid config passes both checks; optional fields may be left out', () => {
  checkConfig(good());
  checkTexts(good());
  const c = good();
  delete c.attribution;
  delete c.view;
  checkTexts(c);
});

check('structure: each broken field is named', () => {
  const cases = [
    [(c) => delete c.map, /map:/],
    [(c) => (c.map.extent = [0, 0]), /map:/],
    [(c) => (c.items = []), /items:/],
    [(c) => (c.items[1].id = 'd01'), /items: id "d01"/],
    [(c) => (c.items[1].id = '2nd'), /items: id "2nd"/],
    [(c) => (c.items[1].id = 'land'), /items: id "land"/],
    [(c) => (c.items[1].id = 'fade-t'), /items: id "fade-t"/],
    [(c) => delete c.items[2].size, /d03: marker/],
    [(c) => (c.rounds = []), /rounds:/],
    [(c) => delete c.rounds[1].label, /rounds\[1\]\.label/],
    [(c) => (c.rounds[0].ask = 'name'), /rounds\[0\]\.ask/],
    [(c) => (c.rounds[1].key = 'names'), /each key once/],
    [(c) => delete c.text.mapError, /text\.mapError/],
    [(c) => (c.text.intro = 'x'), /text\.intro/],
    [(c) => (c.text.theme = {}), /text\.theme/],
    [(c) => (c.attribution = ''), /attribution/],
    [(c) => (c.view = { maxScale: 0 }), /view:/],
  ];
  for (const [breakIt, re] of cases) {
    const c = good();
    breakIt(c);
    throwsWith(() => checkConfig(c), re);
  }
});

check('texts: empty or duplicate prompts, missing labels', () => {
  let c = good();
  c.items[2].name = 'Leopoldstadt';
  throwsWith(() => checkTexts(c), /d03 and d02 are both asked as "Leopoldstadt"/);
  c = good();
  c.rounds[1].miss = () => '';
  throwsWith(() => checkTexts(c), /miss\(d01\)/);
  c = good();
  c.rounds[0].ask = (d) => ` ${d.name}`;
  throwsWith(() => checkTexts(c), /ask\(d01\)/);
  c = good();
  c.text.theme = () => ({ label: 'x' });
  throwsWith(() => checkTexts(c), /text\.theme/);
});

console.log(`${checks} checks passed`);
