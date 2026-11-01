// Plain-node checks of japan-quiz's own data and config (the engine's
// rules are tested in shared/map-quiz/tools/). No packages:
// node images/japan-quiz/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MAP, PIECES, ISLANDS, REGIONS, PREFECTURES } from '../site/japan.js';
import config from '../site/config.js';
import { checkTexts, roundSpecs } from '../site/contract.js';

const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
// tools/prefectures.json: the source of names and readings (build_map.py
// writes japan.js from it); the generated module must match it.
const SOURCE = JSON.parse(readFileSync(new URL('./prefectures.json', import.meta.url), 'utf8'));
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

const HIRAGANA = /^[ぁ-ゟ]+$/;
const KANJI = /^[一-鿿]+$/;
const pref = new Map(PREFECTURES.map((p) => [p.id, p]));
const pieceIds = PIECES.map((p) => p.id);

check('data: 47 prefectures in JIS order, japan.js matches prefectures.json', () => {
  assert.equal(PREFECTURES.length, 47);
  assert.deepEqual(PREFECTURES.map((p) => p.iso), Array.from({ length: 47 }, (_, i) => `JP-${String(i + 1).padStart(2, '0')}`));
  const camel = (p) => ({ id: p.id, iso: p.iso, name: p.name, kanji: p.kanji, kana: p.kana, capital: p.capital,
    capitalKanji: p.capital_kanji, capitalKana: p.capital_kana, capitalDiffers: p.capital_differs, region: p.region, island: p.island });
  assert.deepEqual(PREFECTURES.map(({ pieces, ...rest }) => rest), SOURCE.prefectures.map(camel));
  for (const [list, src] of [[ISLANDS, SOURCE.islands], [REGIONS, SOURCE.regions]])
    assert.deepEqual(list.map(({ pieces, ...rest }) => rest), src);
  assert.equal(ISLANDS.length, 4);
  assert.equal(REGIONS.length, 8);
  for (const key of ['id', 'name', 'kanji', 'capital']) assert.equal(new Set(PREFECTURES.map((p) => p[key])).size, 47, key);
});

check('data: Hepburn with macrons, kanji and hiragana for every asked name', () => {
  for (const e of [...ISLANDS, ...REGIONS, ...PREFECTURES]) {
    assert.match(e.kanji, KANJI, `${e.id} kanji`);
    assert.match(e.kana, HIRAGANA, `${e.id} kana`);
  }
  for (const p of PREFECTURES) {
    assert.match(p.capitalKana, HIRAGANA, `${p.id} capitalKana`);
    // Saitama's capital is written in hiragana (さいたま市); it isn't asked
    assert.match(p.capitalKanji, p.id === 'saitama' ? HIRAGANA : KANJI, `${p.id} capitalKanji`);
  }
  const by = (list, id) => list.find((e) => e.id === id);
  assert.deepEqual(['tokyo', 'kyoto', 'osaka', 'hyogo', 'kochi', 'oita', 'hokkaido'].map((id) => pref.get(id).name),
    ['Tōkyō', 'Kyōto', 'Ōsaka', 'Hyōgo', 'Kōchi', 'Ōita', 'Hokkaidō']);
  assert.deepEqual(['hyogo', 'yamanashi', 'shiga'].map((id) => pref.get(id).capital), ['Kōbe', 'Kōfu', 'Ōtsu']);
  assert.deepEqual(ISLANDS.map((i) => i.name), ['Honshū', 'Hokkaidō', 'Kyūshū', 'Shikoku']);
  assert.deepEqual(REGIONS.map((r) => r.name), ['Hokkaidō', 'Tōhoku', 'Kantō', 'Chūbu', 'Kansai', 'Chūgoku', 'Shikoku', 'Kyūshū']);
  // the card's second line, as the owner specified it
  assert.equal(`${pref.get('aomori').kanji} · ${pref.get('aomori').kana}`, '青森 · あおもり');
  assert.equal(`${pref.get('tokyo').kanji} · ${pref.get('tokyo').kana}`, '東京 · とうきょう');
  assert.equal(`${pref.get('hokkaido').kanji} · ${pref.get('hokkaido').kana}`, '北海道 · ほっかいどう');
  assert.equal(`${pref.get('hokkaido').capitalKanji} · ${pref.get('hokkaido').capitalKana}`, '札幌 · さっぽろ');
  assert.equal(`${by(ISLANDS, 'isl-honshu').kanji} · ${by(ISLANDS, 'isl-honshu').kana}`, '本州 · ほんしゅう');
  assert.equal(`${by(REGIONS, 'reg-kansai').kanji} · ${by(REGIONS, 'reg-kansai').kana}`, '関西 · かんさい');
});

check('data: 18 capitals differ from their prefecture\'s name (a flag), Tōkyō → Shinjuku among them', () => {
  const asked = PREFECTURES.filter((p) => p.capitalDiffers).map((p) => p.id);
  assert.deepEqual(asked, ['hokkaido', 'iwate', 'miyagi', 'ibaraki', 'tochigi', 'gunma', 'tokyo', 'kanagawa', 'ishikawa',
    'yamanashi', 'aichi', 'mie', 'shiga', 'hyogo', 'shimane', 'kagawa', 'ehime', 'okinawa']);
  assert.equal(pref.get('tokyo').capital, 'Shinjuku');
  assert.equal(`${pref.get('tokyo').capitalKanji} · ${pref.get('tokyo').capitalKana}`, '新宿 · しんじゅく');
  for (const p of PREFECTURES) if (p.id !== 'tokyo') assert.equal(p.capitalDiffers, p.capital !== p.name, p.id);
});

check('pieces: each in exactly one prefecture and one region; main piece id = prefecture id, islands as <id>-isles', () => {
  assert.equal(new Set(pieceIds).size, PIECES.length);
  assert.equal(PIECES.length, 64);
  for (const list of [PREFECTURES, REGIONS]) {
    const seen = list.flatMap((e) => e.pieces);
    assert.deepEqual([...seen].sort(), [...pieceIds].sort(), 'every piece once');
  }
  for (const p of PREFECTURES) {
    assert.equal(p.pieces[0], p.id);
    assert.ok(p.pieces.length === 1 || (p.pieces.length === 2 && p.pieces[1] === `${p.id}-isles`), p.id);
    for (const id of p.pieces) assert.equal(PIECES.find((x) => x.id === id).prefecture, p.id);
    assert.ok(REGIONS.find((r) => r.id === p.region).pieces.every((id) => pref.get(PIECES.find((x) => x.id === id).prefecture).region === p.region));
  }
  assert.deepEqual(pref.get('okinawa').pieces, ['okinawa']);
  assert.equal(PIECES.filter((p) => p.id.endsWith('-isles')).length, 17);
});

check('pieces: islands hold exactly the main pieces of their prefectures; -isles pieces and Okinawa are in none', () => {
  const onIsland = ISLANDS.flatMap((i) => i.pieces);
  assert.equal(new Set(onIsland).size, onIsland.length);
  for (const i of ISLANDS) assert.deepEqual(i.pieces, PREFECTURES.filter((p) => p.island === i.id).map((p) => p.id), i.id);
  assert.deepEqual(ISLANDS.map((i) => i.pieces.length), [34, 1, 7, 4]);
  const off = pieceIds.filter((id) => !onIsland.includes(id));
  assert.deepEqual(off, [...PIECES.filter((p) => p.id.endsWith('-isles')).map((p) => p.id), 'okinawa'].sort((a, b) => pieceIds.indexOf(a) - pieceIds.indexOf(b)));
  assert.equal(pref.get('okinawa').island, null);
  assert.equal(pref.get('okinawa').region, 'reg-kyushu');
  assert.equal(pref.get('mie').region, 'reg-kansai');
});

check('config: fits the engine contract, every round text renders, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items, PIECES);
  assert.equal(config.map, MAP);
  assert.deepEqual(config.view, { maxScale: 6, besideHud: true });
  assert.equal(config.blockingOverlays, undefined, 'Lake Biwa is see-through: a tap picks Shiga');
  assert.ok(PIECES.every((p) => p.marker === undefined), 'no rings');
});

check('config: rounds islands → regions → prefectures → capitals, answers, asked, lines', () => {
  assert.deepEqual(config.rounds.map((r) => r.key), ['islands', 'regions', 'prefectures', 'capitals']);
  assert.deepEqual(config.rounds.map((r) => r.label), ['Islands', 'Regions', 'Prefectures', 'Capitals']);
  assert.deepEqual(config.rounds.map((r) => r.answers), [ISLANDS, REGIONS, PREFECTURES, PREFECTURES]);
  const specs = roundSpecs(config);
  assert.deepEqual(specs.map((s) => s.asked.length), [4, 8, 47, 18]);
  assert.ok(specs[3].asked.includes('tokyo'));
  assert.deepEqual(config.rounds.map((r) => r.lines), [
    ['coast-main'],
    ['coast-main', 'coast-isles', 'borders-regions'],
    ['coast-main', 'coast-isles', 'borders-prefectures', 'borders-regions'],
    ['coast-main', 'coast-isles', 'borders-prefectures', 'borders-regions'],
  ]);
  assert.ok(config.rounds.every((r) => r.subLang === 'ja' && typeof r.sub === 'function' && typeof r.missSub === 'function'));
  // map.svg's borders-prefectures leaves out the region borders (each edge in one overlay)
  for (const r of config.rounds) if (r.lines.includes('borders-prefectures')) assert.ok(r.lines.includes('borders-regions'), r.key);
});

check('config: English texts, sub-lines, misclick labels', () => {
  const [isl, reg, pre, cap] = config.rounds;
  const i = ISLANDS[0], r = REGIONS.find((x) => x.id === 'reg-tohoku');
  const aomori = pref.get('aomori'), iwate = pref.get('iwate'), tokyo = pref.get('tokyo');
  assert.deepEqual([isl.ask(i), isl.sub(i), isl.miss(i), isl.missSub(i)], ['Honshū', '本州 · ほんしゅう', 'Honshū', '本州']);
  assert.deepEqual([reg.ask(r), reg.sub(r), reg.miss(r), reg.missSub(r)], ['Tōhoku', '東北 · とうほく', 'Tōhoku', '東北']);
  assert.deepEqual([pre.ask(aomori), pre.sub(aomori), pre.miss(aomori), pre.missSub(aomori)], ['Aomori', '青森 · あおもり', 'Aomori', '青森']);
  assert.deepEqual([cap.ask(tokyo), cap.sub(tokyo), cap.miss(tokyo), cap.missSub(tokyo)], ['Shinjuku', '新宿 · しんじゅく', 'Tōkyō · Shinjuku', '東京 · 新宿']);
  assert.equal(cap.miss(aomori), 'Aomori · Aomori');
  assert.equal(`${cap.prompt} ${cap.ask(iwate)}`, 'Find the prefecture whose capital is Morioka');
  assert.equal(isl.done({ total: 4, misses: 0 }), 'All 4 islands found · no misclicks. Now the 8 regions.');
  assert.equal(reg.done({ total: 8, misses: 1 }), 'All 8 regions found · 1 misclick. Now the 47 prefectures.');
  assert.equal(pre.done({ total: 47, misses: 3 }), "All 47 prefectures found · 3 misclicks. Now 18 capitals: find each one's prefecture.");
  assert.equal(cap.done({ total: 18, misses: 0 }), 'All 18 capitals found · no misclicks. Islands again, in a new order.');
  assert.deepEqual(config.text.theme('dark', false), { label: 'Switch to dark theme', title: 'Switch to the dark theme' });
});

check('index.html: English, data-quiz names this image, own stylesheet after the engine\'s, ids clear of the map\'s', () => {
  const html = site('index.html');
  assert.match(html, /<html lang="en" data-quiz="japan-quiz">/);
  assert.match(html, /<title>Japan Quiz · phw<\/title>/);
  assert.ok(html.indexOf('href="style.css"') < html.indexOf('href="japan.css"') && html.indexOf('href="japan.css"') < html.indexOf('src="theme.js"'));
  assert.match(html, /<span id="round">Islands<\/span> <span id="progress" class="num">0 \/ 4<\/span>/);
  const pageIds = [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  const mapIds = [...site('map.svg').matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  for (const id of mapIds) assert.ok(!pageIds.includes(id), id);
  for (const id of ['prompt-sub']) assert.ok(!mapIds.includes(id), id);
});

check('map.svg: a shape per piece in #pieces, context land, then lakes and the four line overlays', () => {
  const svg = site('map.svg');
  const [x, y, w, h] = MAP.extent;
  assert.ok(svg.startsWith(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${w} ${h}">`));
  assert.ok(x < 0 && y < 0, 'context land around the window');
  for (const id of pieceIds) assert.ok(svg.includes(`<path id="${id}" d="m`), id);
  const overlays = ['lakes', 'coast-main', 'coast-isles', 'borders-prefectures', 'borders-regions'];
  const at = overlays.map((id) => svg.indexOf(`<path id="${id}" d="m`));
  assert.ok(at.every((i, k) => i > svg.indexOf('<g id="overlays">') && (k === 0 || i > at[k - 1])), 'overlays in this order');
  assert.ok(svg.indexOf('<path id="land"') < svg.indexOf('<g id="pieces">') && svg.indexOf('<g id="pieces">') < svg.indexOf('<g id="overlays">'));
  for (const id of overlays.slice(1)) assert.ok(!/z/i.test(svg.match(new RegExp(`<path id="${id}" d="([^"]+)"`))[1]), `${id}: open lines`);
  assert.equal((svg.match(/ id="/g) || []).length, 1 + 1 + PIECES.length + 1 + overlays.length);
  for (const r of config.rounds) for (const id of r.lines) assert.ok(overlays.includes(id), id);
});

check('japan.css: region-border token in all three blocks, heavier region lines in the prefecture rounds, lake outline', () => {
  const css = site('japan.css');
  assert.equal((css.match(/--region-border:/g) || []).length, 3);
  assert.match(css, /:root\[data-round="prefectures"\] #overlays #borders-regions,\s*:root\[data-round="capitals"\] #overlays #borders-regions \{/);
  assert.match(css, /#overlays #lakes \{[^}]*vector-effect: non-scaling-stroke;/);
});

console.log(`${checks} checks passed`);
