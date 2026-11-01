// contract.js: checks an image's config.js against the engine's contract
// (shared/map-quiz/README.md). No DOM: main.js runs checkConfig() at start
// (a broken config fails there, naming the field); an image's node test
// runs both checks.
// Shared map-quiz engine file: the source is shared/map-quiz/site/, images
// get byte-identical copies (python3 shared/sync.py). Edit the source.

const str = (v) => typeof v === 'string' && v !== '';

function bad(msg) {
  throw new Error(`config.js: ${msg} (contract: shared/map-quiz/README.md)`);
}

// Ids end up as element ids next to the page's own (main.js also checks
// those) and the engine's SVG layers.
const ID = /^[A-Za-z_][\w.-]*$/;
const RESERVED = /^(land|overlays|markers|fade(-.*)?)$/;

// Shapes and types.
export function checkConfig(config) {
  if (!config || typeof config !== 'object') bad('no default export object');
  const { map, items, rounds, text, view, attribution } = config;
  if (!map || !(map.width > 0 && map.height > 0) || !Array.isArray(map.extent) || map.extent.length !== 4) bad('map: { width, height, extent }');
  if (!Array.isArray(items) || !items.length) bad('items: a non-empty array');
  const seen = new Set();
  for (const it of items) {
    const id = it && it.id;
    if (typeof id !== 'string' || !ID.test(id) || RESERVED.test(id) || seen.has(id))
      bad(`items: id ${JSON.stringify(id)} (unique; letters, digits, _ . -, not first a digit; not land, overlays, markers, fade*)`);
    seen.add(id);
    if (it.marker !== undefined && !(Array.isArray(it.marker) && it.marker.length === 2 && it.marker.every(Number.isFinite) && it.size >= 0))
      bad(`items: ${id}: marker [x, y] (map units) needs a size`);
  }
  if (!Array.isArray(rounds) || !rounds.length) bad('rounds: a non-empty array');
  rounds.forEach((r, i) => {
    for (const k of ['key', 'label', 'prompt']) if (!r || !str(r[k])) bad(`rounds[${i}].${k}: a string`);
    for (const k of ['ask', 'miss', 'done']) if (typeof r[k] !== 'function') bad(`rounds[${i}].${k}: a function`);
  });
  if (new Set(rounds.map((r) => r.key)).size !== rounds.length) bad('rounds: each key once');
  if (!text || typeof text !== 'object') bad('text: an object');
  for (const k of ['newGame', 'reset', 'resetArmed', 'mapError']) if (!str(text[k])) bad(`text.${k}: a string`);
  if (!text.intro || !str(text.intro.mouse) || !str(text.intro.touch)) bad('text.intro: { mouse, touch }');
  if (typeof text.theme !== 'function') bad('text.theme: a function');
  if (attribution !== undefined && !str(attribution)) bad('attribution: a string');
  if (view !== undefined && !(view && typeof view === 'object' && (view.maxScale === undefined || view.maxScale > 0)))
    bad('view: { maxScale: CSS px per map unit, > 0 }');
}

// What the functions return, for every item: prompts and misclick labels
// non-empty, prompts unique per round (else a question is ambiguous), the
// round-complete and theme texts strings.
export function checkTexts(config) {
  checkConfig(config);
  const { items, rounds, text } = config;
  for (const r of rounds) {
    const asked = new Map();
    for (const it of items) {
      const a = r.ask(it);
      const m = r.miss(it);
      if (!str(a) || a !== a.trim()) bad(`rounds ${r.key}: ask(${it.id}) gives ${JSON.stringify(a)}`);
      if (!str(m)) bad(`rounds ${r.key}: miss(${it.id}) gives ${JSON.stringify(m)}`);
      if (asked.has(a)) bad(`rounds ${r.key}: ${it.id} and ${asked.get(a)} are both asked as ${JSON.stringify(a)}`);
      asked.set(a, it.id);
    }
    for (const misses of [0, 1, 2]) if (!str(r.done({ total: items.length, misses }))) bad(`rounds ${r.key}: done() gives no text`);
  }
  for (const other of ['light', 'dark'])
    for (const override of [false, true]) {
      const t = text.theme(other, override);
      if (!t || !str(t.label) || !str(t.title)) bad(`text.theme('${other}', ${override}): { label, title }`);
    }
}
