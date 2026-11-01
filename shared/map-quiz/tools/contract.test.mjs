// Plain-node checks of the engine's contract.js (the config checks main.js
// runs at start) on synthetic configs.
// No packages: node shared/map-quiz/tools/contract.test.mjs
import assert from 'node:assert/strict';
import { checkConfig, checkTexts, roundSpecs } from '../site/contract.js';

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
    view: { maxScale: 6, besideHud: true },
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
  checkConfig({ ...good(), blockingOverlays: ['water', 'lakes'] });
  checkConfig({ ...good(), blockingOverlays: [] });
  checkTexts({ ...good(), carryColours: false });
  checkConfig({ ...good(), carryColours: true });
});

check('structure: each broken field is named', () => {
  const cases = [
    [(c) => delete c.map, /map:/],
    [(c) => (c.map.extent = [0, 0]), /map:/],
    [(c) => (c.map.extent = [0, 0, NaN, 800]), /map: extent/],
    [(c) => (c.map.extent = [0, '0', 1000, 800]), /map: extent/],
    [(c) => (c.map.extent = [0, 0, 1000, 0]), /map: extent/],
    [(c) => (c.map.width = Infinity), /map: width/],
    [(c) => (c.map.height = '800'), /map: width/],
    [(c) => (c.items[1].id = 'regions'), /items: id "regions"/],
    [(c) => (c.items[2].size = NaN), /d03: marker/],
    [(c) => (c.view = { maxScale: Infinity }), /view:/],
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
    [(c) => (c.carryColours = 'no'), /carryColours: true or false/],
    [(c) => (c.carryColours = 0), /carryColours: true or false/],
    [(c) => (c.view = { maxScale: 0 }), /view:/],
    [(c) => (c.view = { besideHud: 'yes' }), /view:/],
    [(c) => (c.blockingOverlays = 'water'), /blockingOverlays: an array/],
    [(c) => (c.blockingOverlays = ['water', 'water']), /blockingOverlays: id "water"/],
    [(c) => (c.blockingOverlays = ['d02']), /blockingOverlays: id "d02"/],
    [(c) => (c.blockingOverlays = ['overlays']), /blockingOverlays: id "overlays"/],
    [(c) => (c.blockingOverlays = ['']), /blockingOverlays: id ""/],
    [(c) => (c.blockingOverlays = [7]), /blockingOverlays: id 7/],
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

// A grouped config, Japan-like: map pieces (items), answers per round (an
// island of two prefectures, prefectures of one or two pieces: answer id
// niigata = pieces niigata + niigata-isles), an inert piece in the islands
// round, a subset round, line overlays, a sub-line.
function grouped() {
  const PREFS = [
    { id: 'niigata', pieces: ['niigata', 'niigata-isles'], name: 'Niigata', kanji: '新潟', kana: 'にいがた', capital: 'Niigata' },
    { id: 'nagano', pieces: ['nagano'], name: 'Nagano', kanji: '長野', kana: 'ながの', capital: 'Nagano' },
    { id: 'kagawa', pieces: ['kagawa'], name: 'Kagawa', kanji: '香川', kana: 'かがわ', capital: 'Takamatsu', marker: [700, 600], size: 4 },
    { id: 'ehime', pieces: ['ehime'], name: 'Ehime', kanji: '愛媛', kana: 'えひめ', capital: 'Matsuyama' },
  ];
  const c = good();
  c.items = ['niigata', 'niigata-isles', 'nagano', 'kagawa', 'ehime'].map((id) => ({ id }));
  c.rounds = [
    { key: 'islands', label: 'Islands', prompt: 'Find', lines: ['coast-main'], ask: (a) => a.name, miss: (a) => a.name, done: ({ total }) => `All ${total}.`,
      answers: [{ id: 'isl-honshu', pieces: ['niigata', 'nagano'], name: 'Honshu' }, { id: 'isl-shikoku', pieces: ['kagawa', 'ehime'], name: 'Shikoku' }] },
    { key: 'prefectures', label: 'Prefectures', prompt: 'Find', answers: PREFS, lines: ['coast-main', 'coast-isles', 'borders-prefectures'],
      sub: (p) => `${p.kanji} · ${p.kana}`, subLang: 'ja', ask: (p) => p.name, miss: (p) => p.name, done: ({ total }) => `All ${total}.` },
    { key: 'capitals', label: 'Capitals', prompt: 'Find the prefecture whose capital is', answers: PREFS, asked: (p) => p.capital !== p.name,
      ask: (p) => p.capital, miss: (p) => `${p.name} · ${p.capital}`, missSub: (p) => p.kanji, subLang: 'ja', done: ({ total }) => `All ${total}.` },
  ];
  return c;
}

check('a grouped config passes; roundSpecs gives answers, the asked ones, the config objects', () => {
  checkTexts(grouped());
  const c = grouped();
  const specs = roundSpecs(c);
  assert.deepEqual(specs.map((s) => s.key), ['islands', 'prefectures', 'capitals']);
  assert.deepEqual(specs[0].answers, [{ id: 'isl-honshu', pieces: ['niigata', 'nagano'] }, { id: 'isl-shikoku', pieces: ['kagawa', 'ehime'] }]);
  assert.deepEqual(specs[1].answers[0], { id: 'niigata', pieces: ['niigata', 'niigata-isles'] });
  assert.deepEqual(specs[1].asked, ['niigata', 'nagano', 'kagawa', 'ehime']);
  assert.deepEqual(specs[2].asked, ['kagawa', 'ehime'], 'capital differs from the name');
  assert.equal(specs[2].byId.get('kagawa'), c.rounds[2].answers[2]);
  assert.notEqual(specs[1].answers[0].pieces, c.rounds[1].answers[0].pieces, 'a copy');
  checkConfig({ ...grouped(), blockingOverlays: ['water'] });
  const empty = grouped();
  empty.rounds[0].lines = [];
  checkConfig(empty);
});

check('roundSpecs without answers: every item its own answer, all asked, byId -> the item', () => {
  const c = good();
  const specs = roundSpecs(c);
  assert.equal(specs.length, 2);
  for (const s of specs) {
    assert.deepEqual(s.answers, c.items.map((it) => ({ id: it.id, pieces: [it.id] })));
    assert.deepEqual(s.asked, ['d01', 'd02', 'd03']);
    assert.equal(s.byId.get('d03'), c.items[2]);
  }
  c.rounds[1].asked = (d) => d.number !== 2;
  assert.deepEqual(roundSpecs(c)[1].asked, ['d01', 'd03']);
});

check('grouped structure: each broken field is named', () => {
  const cases = [
    [(c) => (c.rounds[0].answers = []), /rounds\[0\]\.answers: a non-empty array/],
    [(c) => (c.rounds[0].answers = 'isl-honshu'), /rounds\[0\]\.answers: a non-empty array/],
    [(c) => (c.rounds[0].answers[1].id = 'isl-honshu'), /rounds\[0\]\.answers: id "isl-honshu"/],
    [(c) => (c.rounds[0].answers[1].id = '1st'), /rounds\[0\]\.answers: id "1st"/],
    [(c) => (c.rounds[0].answers[0].pieces = []), /isl-honshu: pieces/],
    [(c) => (c.rounds[0].answers[0].pieces = 'niigata'), /isl-honshu: pieces/],
    [(c) => c.rounds[0].answers[0].pieces.push('zz'), /isl-honshu: piece "zz" is not an item's id/],
    [(c) => c.rounds[0].answers[1].pieces.push('nagano'), /piece nagano in isl-honshu and isl-shikoku/],
    [(c) => (c.rounds[0].answers[1].marker = [1, 2]), /rounds\[0\]\.answers: isl-shikoku: marker/],
    [(c) => (c.rounds[2].asked = ['kagawa']), /rounds\[2\]\.asked: a function/],
    [(c) => (c.rounds[1].sub = 'kanji'), /rounds\[1\]\.sub: a function/],
    [(c) => (c.rounds[2].missSub = 'kanji'), /rounds\[2\]\.missSub: a function/],
    [(c) => (c.rounds[1].subLang = 'japanese!'), /rounds\[1\]\.subLang/],
    [(c) => (c.rounds[1].subLang = 7), /rounds\[1\]\.subLang/],
    [(c) => (c.rounds[0].lines = 'coast-main'), /rounds\[0\]\.lines: an array/],
    [(c) => (c.rounds[1].lines = ['coast-main', 'coast-main']), /rounds\[1\]\.lines: id "coast-main"/],
    [(c) => (c.rounds[1].lines = ['nagano']), /rounds\[1\]\.lines: id "nagano"/],
    [(c) => (c.rounds[1].lines = ['overlays']), /rounds\[1\]\.lines: id "overlays"/],
    [(c) => (c.blockingOverlays = ['coast-isles']), /rounds\[1\]\.lines: id "coast-isles"/],
    [(c) => c.items.push({ id: 'tsushima' }), /items: tsushima is in no round's answers/],
    [(c) => (c.rounds[0].answers[1].id = 'nagano'), /rounds\[0\]\.answers: nagano is an item's id but not one of its pieces/],
  ];
  for (const [breakIt, re] of cases) {
    const c = grouped();
    breakIt(c);
    throwsWith(() => checkConfig(c), re);
  }
  const c = grouped();
  c.rounds[2].asked = () => false;
  throwsWith(() => roundSpecs(c), /rounds\[2\] \(capitals\): asks nothing/);
  c.rounds[2].asked = (p) => p.capital;
  throwsWith(() => roundSpecs(c), /asked\(niigata\) gives "Niigata", not true or false/);
});

check('grouped texts: ask and sub for the asked answers only, miss and missSub for every one, done gets the asked count', () => {
  const c = grouped();
  const calls = { ask: [], miss: [], missSub: [], sub: [], total: [] };
  const spy = (k, fn) => (a) => (calls[k].push(a.id), fn(a));
  const cap = c.rounds[2];
  cap.ask = spy('ask', cap.ask);
  cap.miss = spy('miss', cap.miss);
  cap.missSub = spy('missSub', cap.missSub);
  cap.done = ({ total }) => (calls.total.push(total), 'done');
  c.rounds[1].sub = spy('sub', c.rounds[1].sub);
  checkTexts(c);
  assert.deepEqual(calls.ask, ['kagawa', 'ehime']);
  assert.deepEqual(calls.miss, ['niigata', 'nagano', 'kagawa', 'ehime']);
  assert.deepEqual(calls.missSub, ['niigata', 'nagano', 'kagawa', 'ehime']);
  assert.deepEqual(calls.sub, ['niigata', 'nagano', 'kagawa', 'ehime']);
  assert.deepEqual(calls.total, [2, 2, 2]);
  // a not-asked answer's prompt is never shown, so it may repeat or be empty
  const d = grouped();
  d.rounds[2].ask = (p) => (p.capital === p.name ? '' : p.capital);
  checkTexts(d);
  const cases = [
    [(x) => (x.rounds[1].sub = (p) => (p.id === 'nagano' ? '' : p.kanji)), /prefectures: sub\(nagano\) gives ""/],
    [(x) => (x.rounds[2].missSub = (p) => (p.id === 'niigata' ? undefined : p.kanji)), /capitals: missSub\(niigata\) gives undefined/],
    [(x) => (x.rounds[2].miss = (p) => (p.id === 'nagano' ? '' : p.name)), /capitals: miss\(nagano\)/],
    [(x) => (x.rounds[0].answers[1].name = 'Honshu'), /isl-shikoku and isl-honshu are both asked as "Honshu"/],
  ];
  for (const [breakIt, re] of cases) {
    const x = grouped();
    breakIt(x);
    throwsWith(() => checkTexts(x), re);
  }
});

console.log(`${checks} checks passed`);
