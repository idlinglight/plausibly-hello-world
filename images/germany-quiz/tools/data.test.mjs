// Plain-node checks of germany-quiz's own data and config (the engine's
// rules are tested in shared/map-quiz/tools/). No packages:
// node images/germany-quiz/tools/data.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MAP, STATES } from '../site/states.js';
import config from '../site/config.js';
import { checkTexts, roundSpecs } from '../site/contract.js';

const site = (f) => readFileSync(new URL(`../site/${f}`, import.meta.url), 'utf8');
// tools/states.json: the source of names, capitals and titles (build_map.py
// writes states.js from it); the generated module must match it.
const SOURCE = JSON.parse(readFileSync(new URL('./states.json', import.meta.url), 'utf8'));
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

const st = new Map(STATES.map((s) => [s.id, s]));

check('data: 16 Länder in alphabetical order, states.js matches states.json', () => {
  assert.equal(STATES.length, 16);
  const camel = (s) => ({ id: s.id, iso: s.iso, name: s.name, capital: s.capital, capitalDiffers: s.capital_differs,
    wiki: s.wiki, ...(s.capital_wiki ? { capitalWiki: s.capital_wiki } : {}) });
  assert.deepEqual(STATES.map(({ marker, size, ...rest }) => rest), SOURCE.states.map(camel));
  assert.deepEqual(STATES.map((s) => s.name), ['Baden-Württemberg', 'Bayern', 'Berlin', 'Brandenburg', 'Bremen', 'Hamburg',
    'Hessen', 'Mecklenburg-Vorpommern', 'Niedersachsen', 'Nordrhein-Westfalen', 'Rheinland-Pfalz', 'Saarland', 'Sachsen',
    'Sachsen-Anhalt', 'Schleswig-Holstein', 'Thüringen']);
  assert.deepEqual(STATES.map((s) => s.iso).sort(), ['DE-BB', 'DE-BE', 'DE-BW', 'DE-BY', 'DE-HB', 'DE-HE', 'DE-HH', 'DE-MV',
    'DE-NI', 'DE-NW', 'DE-RP', 'DE-SH', 'DE-SL', 'DE-SN', 'DE-ST', 'DE-TH']);
  for (const key of ['id', 'name', 'capital']) assert.equal(new Set(STATES.map((s) => s[key])).size, 16, key);
  for (const s of STATES) assert.match(s.id, /^[a-z-]+$/, s.id);
});

check('data: 13 capitals differ from their state\'s name; the city states don\'t', () => {
  const asked = STATES.filter((s) => s.capitalDiffers).map((s) => s.id);
  assert.equal(asked.length, 13);
  assert.deepEqual(STATES.filter((s) => !s.capitalDiffers).map((s) => s.id), ['berlin', 'bremen', 'hamburg']);
  for (const s of STATES) assert.equal(s.capitalDiffers, s.capital !== s.name, s.id);
  assert.deepEqual(['bayern', 'niedersachsen', 'nordrhein-westfalen', 'saarland', 'hessen'].map((id) => st.get(id).capital),
    ['München', 'Hannover', 'Düsseldorf', 'Saarbrücken', 'Wiesbaden']);
});

// A Wikipedia article title as stored: the same rule as
// mapgen.wiki_title_error (shared/map-quiz/tools/mapgen/output.py; the
// class is checked against its WIKI_TITLE_BAD below): non-empty, no
// underscore, nothing Wikipedia forbids in titles (# | [ ] { } < >, control
// characters), no whitespace but the plain space, no leading, trailing or
// double space, NFC. '?' is fine. tools/wiki_titles.py checks the articles
// themselves, online, by hand.
const WIKI_TITLE_BAD = /[_#|\[\]{}<>\x00-\x1f\x7f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/;
const titleOk = (t) => typeof t === 'string' && t !== '' && !WIKI_TITLE_BAD.test(t)
  && !t.startsWith(' ') && !t.endsWith(' ') && !t.includes('  ') && t.normalize('NFC') === t;

check('data: the title rule is mapgen.wiki_title_error\'s (same class, same cases as mapgen_test.py)', () => {
  const py = readFileSync(new URL('../../../shared/map-quiz/tools/mapgen/output.py', import.meta.url), 'utf8');
  assert.equal(py.match(/^WIKI_TITLE_BAD = re\.compile\(r"(.*)"\)$/m)?.[1], WIKI_TITLE_BAD.source);
  for (const t of ['What? (film)', 'Georgia (country)', 'St. John\'s, Antigua and Barbuda', 'Kōchi Prefecture', 'Nukuʻalofa'])
    assert.ok(titleOk(t), t);
  for (const t of ['Kanto\u0304 region', 'a  b', 'a_b', 'a#b', ' a', 'a ', 'a|b', '[[a]]', 'a\u00a0b', 'a\tb', '', null])
    assert.ok(!titleOk(t), JSON.stringify(t));
});

check('data: German Wikipedia titles for every state, and for the 13 asked capitals only', () => {
  for (const s of STATES) assert.ok(titleOk(s.wiki), `${s.id} wiki: ${JSON.stringify(s.wiki)}`);
  for (const s of STATES) {
    if (s.capitalDiffers) assert.ok(titleOk(s.capitalWiki), `${s.id} capitalWiki: ${JSON.stringify(s.capitalWiki)}`);
    else assert.ok(!('capitalWiki' in s), `${s.id}: capital not asked, no capitalWiki`);
  }
  assert.equal(new Set(STATES.map((s) => s.wiki)).size, 16);
  assert.equal(new Set(STATES.filter((s) => s.capitalDiffers).map((s) => s.capitalWiki)).size, 13);
  // special cases (tools/README.md, Wikipedia titles)
  assert.equal(st.get('bremen').wiki, 'Freie Hansestadt Bremen', 'the state, not the city');
  assert.deepEqual(['berlin', 'hamburg'].map((id) => st.get(id).wiki), ['Berlin', 'Hamburg'], 'one article for city and state');
  for (const s of STATES) if (s.id !== 'bremen') assert.equal(s.wiki, s.name, `${s.id}: the article is titled by the short name`);
  for (const s of STATES) if (s.capitalDiffers) assert.equal(s.capitalWiki, s.capital, `${s.id}: the capital's article`);
});

check('config: fits the engine contract, every round text renders, prompts unique per round', () => {
  checkTexts(config);
  assert.equal(config.items, STATES);
  assert.equal(config.map, MAP);
  assert.deepEqual(config.view, { maxScale: 3, besideHud: true });
  assert.equal(config.blockingOverlays, undefined, 'lakes are see-through: a tap picks the Land beneath');
  assert.equal(config.carryColours, undefined);
  assert.equal(config.attribution, undefined);
});

check('config: rounds states → capitals, asked, the ring on Bremen only', () => {
  assert.deepEqual(config.rounds.map((r) => r.key), ['states', 'capitals']);
  assert.deepEqual(config.rounds.map((r) => r.label), ['Länder', 'Hauptstädte']);
  const specs = roundSpecs(config);
  assert.deepEqual(specs.map((s) => s.asked.length), [16, 13]);
  for (const id of ['berlin', 'hamburg', 'bremen']) assert.ok(!specs[1].asked.includes(id), id);
  assert.deepEqual(STATES.filter((s) => s.marker).map((s) => s.id), ['bremen']);
  const b = st.get('bremen');
  assert.ok(b.marker.every(Number.isFinite) && b.size > 0);
  assert.ok(b.marker[0] > 0 && b.marker[0] < MAP.width && b.marker[1] > 0 && b.marker[1] < MAP.height);
});

check('config: German texts, misclick labels', () => {
  const [sta, cap] = config.rounds;
  const by = st.get('bayern'), be = st.get('berlin'), hb = st.get('bremen');
  assert.deepEqual([sta.ask(by), sta.miss(by)], ['Bayern', 'Bayern']);
  assert.deepEqual([cap.ask(by), cap.miss(by)], ['München', 'Bayern · München']);
  // city states (not asked this round): the name alone, not "Berlin · Berlin"
  assert.deepEqual([cap.miss(be), cap.miss(hb)], ['Berlin', 'Bremen']);
  assert.equal(`${sta.prompt} ${sta.ask(by)}`, 'Finde das Land Bayern');
  assert.equal(`${cap.prompt} ${cap.ask(by)}`, 'Finde das Land mit der Hauptstadt München');
  assert.equal(sta.done({ total: 16, misses: 0 }), 'Alle 16 Länder gefunden · ohne Fehlklick. Jetzt 13 Landeshauptstädte: finde das Land dazu.');
  assert.equal(sta.done({ total: 16, misses: 1 }), 'Alle 16 Länder gefunden · 1 Fehlklick. Jetzt 13 Landeshauptstädte: finde das Land dazu.');
  assert.equal(cap.done({ total: 13, misses: 3 }), 'Alle 13 Hauptstädte gefunden · 3 Fehlklicks. Wieder die Länder, neu gemischt.');
  assert.deepEqual(config.text.theme('dark', false), { label: 'In den dunklen Modus wechseln', title: 'In den dunklen Modus wechseln' });
  assert.deepEqual(config.text.theme('light', true), { label: 'In den hellen Modus wechseln', title: 'Zurück zur Systemeinstellung (hell)' });
});

check('index.html: German, data-quiz names this image, own stylesheet after the engine\'s, ids clear of the map\'s', () => {
  const html = site('index.html');
  assert.match(html, /<html lang="de" data-quiz="germany-quiz">/);
  assert.match(html, /<title>Deutschland-Quiz · phw<\/title>/);
  assert.ok(html.indexOf('href="style.css"') < html.indexOf('href="germany.css"') && html.indexOf('href="germany.css"') < html.indexOf('src="theme.js"'));
  assert.match(html, /<span id="round">Länder<\/span> <span id="progress" class="num">0 \/ 16<\/span>/);
  const pageIds = [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  const mapIds = [...site('map.svg').matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  for (const id of mapIds) assert.ok(!pageIds.includes(id), id);
  for (const id of ['prompt-link', 'prompt-live']) assert.ok(!mapIds.includes(id), id);
});

check('map.svg: a shape per Land in #states, context land, then the two relief images and the lakes', () => {
  const svg = site('map.svg');
  const [x, y, w, h] = MAP.extent;
  assert.ok(svg.startsWith(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x} ${y} ${w} ${h}">`));
  assert.ok(x < 0 && y < 0, 'context land around the window');
  for (const s of STATES) assert.ok(svg.includes(`<path id="${s.id}" d="m`), s.id);
  assert.ok(svg.indexOf('<path id="land"') < svg.indexOf('<g id="states">') && svg.indexOf('<g id="states">') < svg.indexOf('<g id="overlays">'));
  assert.match(svg, /<g id="overlays">\n<image id="relief" [^>]*\/>\n<image id="relief-context" [^>]*\/>\n<path id="lakes" d="m/);
  assert.equal((svg.match(/ id="/g) || []).length, 1 + 1 + STATES.length + 1 + 2 + 1);
  assert.equal((svg.match(/<image /g) || []).length, 2);
});

// A relief <image>'s attributes and its PNG's size and format.
function relief(id) {
  const el = site('map.svg').match(new RegExp(`<image id="${id}" [^>]*/>`))[0];
  const attr = (name) => el.match(new RegExp(` ${name}="([^"]*)"`))?.[1];
  const png = readFileSync(new URL(`../site/${attr('href')}`, import.meta.url));
  assert.deepEqual([...png.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 'PNG signature');
  assert.equal(png.toString('latin1', 12, 16), 'IHDR');
  assert.deepEqual([png[24], png[25]], [8, 3], '8-bit palette');
  assert.equal(attr('preserveAspectRatio'), 'none');
  return { href: attr('href'), x: Number(attr('x')), y: Number(attr('y')), width: Number(attr('width')),
    height: Number(attr('height')), pw: png.readUInt32BE(16), ph: png.readUInt32BE(20), bytes: png.length };
}

check('relief: relief.png over the window (the Länder), relief-context.png over the whole extent, each a palette PNG of its size', () => {
  const de = relief('relief'), ctx = relief('relief-context');
  assert.equal(de.href, 'relief.png');
  assert.equal(ctx.href, 'relief-context.png');
  assert.deepEqual([de.x, de.y, de.width], [0, 0, MAP.width]);
  assert.ok(de.height >= MAP.height && de.height < MAP.height + 1, `height ${de.height}`);
  const [ex, ey, ew, eh] = MAP.extent;
  assert.deepEqual([ctx.x, ctx.y, ctx.width], [ex, ey, ew]);
  assert.ok(ctx.height >= eh && ctx.height < eh + 2, `height ${ctx.height}`);
  for (const r of [de, ctx]) {
    const ppu = r.pw / r.width; // the same pixel density across and down
    assert.ok(Math.abs(r.ph / ppu - r.height) < 1e-9, `${r.href}: ${r.pw} x ${r.ph} px vs ${r.width} x ${r.height}`);
  }
  assert.ok(de.pw / de.width > ctx.pw / ctx.width, 'the Länder sharper than the context land');
  assert.ok(de.bytes < 400_000, `relief.png ${de.bytes} B`);
  assert.ok(ctx.bytes < 300_000, `relief-context.png ${ctx.bytes} B`);
});

check('germany.css: relief tokens in all three blocks, both images, lake outline', () => {
  const css = site('germany.css');
  assert.equal((css.match(/--relief-opacity:/g) || []).length, 3);
  assert.match(css, /#overlays #relief,\s*#overlays #relief-context \{\s*opacity: var\(--relief-opacity\);\s*\}/);
  assert.doesNotMatch(css, /mix-blend-mode/, 'plain alpha: a blend mode leaves a fringe over the sea');
  assert.match(css, /#overlays #lakes \{[^}]*vector-effect: non-scaling-stroke;/);
});

console.log(`${checks} checks passed`);
