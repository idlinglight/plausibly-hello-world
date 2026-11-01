// contract.js: checks an image's config.js against the engine's contract
// (shared/map-quiz/README.md) and turns its rounds into what the rules
// need (roundSpecs). No DOM: main.js runs checkConfig() and roundSpecs()
// at start (a broken config fails there, naming the field); an image's
// node test runs checkTexts() (which runs both).
// Shared map-quiz engine file: the source is shared/map-quiz/site/, images
// get byte-identical copies (python3 shared/sync.py). Edit the source.

const str = (v) => typeof v === 'string' && v !== '';

function bad(msg) {
  throw new Error(`config.js: ${msg} (contract: shared/map-quiz/README.md)`);
}

// Ids end up as element ids next to the page's own and those of map.svg's
// and the engine's layers (main.js checks map.svg's ids against all of
// them when it loads).
const ID = /^[A-Za-z_][\w.-]*$/;
const RESERVED = /^(land|overlays|regions|markers|fade(-.*)?)$/;
const num = (v) => typeof v === 'number' && Number.isFinite(v);

const LANG = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/; // a BCP 47 tag, e.g. ja, ja-Hira

function checkMarker(m, size, where) {
  if (m !== undefined && !(Array.isArray(m) && m.length === 2 && m.every(num) && num(size) && size >= 0))
    bad(`${where}: marker [x, y] (map units) needs a size`);
}

// Shapes and types.
export function checkConfig(config) {
  if (!config || typeof config !== 'object') bad('no default export object');
  const { map, items, rounds, text, view, attribution, blockingOverlays, carryColours } = config;
  if (!map || !num(map.width) || !num(map.height) || !(map.width > 0 && map.height > 0)) bad('map: width and height, finite numbers > 0');
  const ex = map.extent;
  if (!Array.isArray(ex) || ex.length !== 4 || !ex.every(num) || !(ex[2] > 0 && ex[3] > 0)) bad('map: extent [x, y, w, h], finite numbers, w and h > 0');
  if (!Array.isArray(items) || !items.length) bad('items: a non-empty array');
  const seen = new Set();
  for (const it of items) {
    const id = it && it.id;
    if (typeof id !== 'string' || !ID.test(id) || RESERVED.test(id) || seen.has(id))
      bad(`items: id ${JSON.stringify(id)} (unique; letters, digits, _ . -, not first a digit; not land, overlays, regions, markers, fade*)`);
    seen.add(id);
    checkMarker(it.marker, it.size, `items: ${id}`);
  }
  if (!Array.isArray(rounds) || !rounds.length) bad('rounds: a non-empty array');
  const answered = new Set(); // items in some round's answers
  rounds.forEach((r, i) => {
    for (const k of ['key', 'label', 'prompt']) if (!r || !str(r[k])) bad(`rounds[${i}].${k}: a string`);
    for (const k of ['ask', 'miss', 'done']) if (typeof r[k] !== 'function') bad(`rounds[${i}].${k}: a function`);
    for (const k of ['asked', 'sub', 'missSub']) if (r[k] !== undefined && typeof r[k] !== 'function') bad(`rounds[${i}].${k}: a function`);
    if (r.subLang !== undefined && !(typeof r.subLang === 'string' && LANG.test(r.subLang))) bad(`rounds[${i}].subLang: a language tag (e.g. 'ja')`);
    if (r.answers === undefined) {
      for (const id of seen) answered.add(id);
      return;
    }
    // Answers: groups of items (pieces); an item in none is inert in this round.
    if (!Array.isArray(r.answers) || !r.answers.length) bad(`rounds[${i}].answers: a non-empty array`);
    const ans = new Set();
    const owner = new Map();
    for (const a of r.answers) {
      const id = a && a.id;
      if (typeof id !== 'string' || !ID.test(id) || ans.has(id))
        bad(`rounds[${i}].answers: id ${JSON.stringify(id)} (unique in the round; letters, digits, _ . -, not first a digit)`);
      ans.add(id);
      if (!Array.isArray(a.pieces) || !a.pieces.length) bad(`rounds[${i}].answers: ${id}: pieces, a non-empty array of item ids`);
      // an answer may share its id with one of its own pieces (niigata = niigata + niigata-isles), never another's
      if (seen.has(id) && !a.pieces.includes(id)) bad(`rounds[${i}].answers: ${id} is an item's id but not one of its pieces`);
      for (const p of a.pieces) {
        if (!seen.has(p)) bad(`rounds[${i}].answers: ${id}: piece ${JSON.stringify(p)} is not an item's id`);
        if (owner.has(p)) bad(`rounds[${i}].answers: piece ${p} in ${owner.get(p)} and ${id} (at most one answer per round)`);
        owner.set(p, id);
        answered.add(p);
      }
      checkMarker(a.marker, a.size, `rounds[${i}].answers: ${id}`);
    }
  });
  for (const id of seen) if (!answered.has(id)) bad(`items: ${id} is in no round's answers (inert everywhere: make it context land)`);
  if (new Set(rounds.map((r) => r.key)).size !== rounds.length) bad('rounds: each key once');
  if (!text || typeof text !== 'object') bad('text: an object');
  for (const k of ['newGame', 'reset', 'resetArmed', 'mapError']) if (!str(text[k])) bad(`text.${k}: a string`);
  if (!text.intro || !str(text.intro.mouse) || !str(text.intro.touch)) bad('text.intro: { mouse, touch }');
  if (typeof text.theme !== 'function') bad('text.theme: a function');
  if (attribution !== undefined && !str(attribution)) bad('attribution: a string');
  if (carryColours !== undefined && typeof carryColours !== 'boolean') bad('carryColours: true or false');
  if (view !== undefined && !(view && typeof view === 'object' && (view.maxScale === undefined || (num(view.maxScale) && view.maxScale > 0)) &&
      (view.besideHud === undefined || typeof view.besideHud === 'boolean')))
    bad('view: { maxScale: CSS px per map unit, > 0; besideHud: boolean }');
  const blocking = new Set();
  if (blockingOverlays !== undefined) {
    // overlay ids in map.svg (main.js checks they are <path>s in #overlays)
    if (!Array.isArray(blockingOverlays)) bad('blockingOverlays: an array of overlay ids');
    for (const id of blockingOverlays) {
      if (typeof id !== 'string' || !ID.test(id) || RESERVED.test(id) || seen.has(id) || blocking.has(id))
        bad(`blockingOverlays: id ${JSON.stringify(id)} (unique; an overlay's id in map.svg, not an item's)`);
      blocking.add(id);
    }
  }
  rounds.forEach((r, i) => {
    if (r.lines === undefined) return;
    // line overlays shown in this round (main.js checks they are <path>s in #overlays)
    if (!Array.isArray(r.lines)) bad(`rounds[${i}].lines: an array of overlay ids`);
    const once = new Set();
    for (const id of r.lines) {
      if (typeof id !== 'string' || !ID.test(id) || RESERVED.test(id) || seen.has(id) || once.has(id) || blocking.has(id))
        bad(`rounds[${i}].lines: id ${JSON.stringify(id)} (unique; an overlay's id in map.svg, not an item's or a blocking overlay's)`);
      once.add(id);
    }
  });
}

// The rounds as the rules need them (config already checked): per round
// { key, answers: [{ id, pieces }], asked: [answer ids, configured order],
// byId: Map(answer id -> the config object the texts get) }. Without
// round.answers, every item is its own answer (byId -> the item); asked:
// those round.asked(answer) is true for, else all. Throws if a round asks
// nothing.
export function roundSpecs(config) {
  const { items, rounds } = config;
  return rounds.map((r, i) => {
    const list = r.answers || items;
    const answers = list.map((a) => ({ id: a.id, pieces: r.answers ? a.pieces.slice() : [a.id] }));
    const byId = new Map(list.map((a) => [a.id, a]));
    let asked = answers.map((a) => a.id);
    if (r.asked) {
      asked = list.filter((a) => {
        const v = r.asked(a);
        if (typeof v !== 'boolean') bad(`rounds ${r.key}: asked(${a.id}) gives ${JSON.stringify(v)}, not true or false`);
        return v;
      }).map((a) => a.id);
    }
    if (!asked.length) bad(`rounds[${i}] (${r.key}): asks nothing (asked() is false for every answer)`);
    return { key: r.key, answers, asked, byId };
  });
}

// What the functions return, for every answer of every round: prompts
// (and sub-lines) for the asked ones, misclick labels for all, non-empty;
// prompts unique per round (else a question is ambiguous), the
// round-complete and theme texts strings.
export function checkTexts(config) {
  checkConfig(config);
  const specs = roundSpecs(config);
  const { rounds, text } = config;
  rounds.forEach((r, i) => {
    const { answers, asked, byId } = specs[i];
    const isAsked = new Set(asked);
    const prompts = new Map();
    for (const { id } of answers) {
      const it = byId.get(id);
      if (isAsked.has(id)) {
        const a = r.ask(it);
        if (!str(a) || a !== a.trim()) bad(`rounds ${r.key}: ask(${id}) gives ${JSON.stringify(a)}`);
        if (prompts.has(a)) bad(`rounds ${r.key}: ${id} and ${prompts.get(a)} are both asked as ${JSON.stringify(a)}`);
        prompts.set(a, id);
      }
      const m = r.miss(it);
      if (!str(m)) bad(`rounds ${r.key}: miss(${id}) gives ${JSON.stringify(m)}`);
      for (const [k, need] of [['sub', isAsked.has(id)], ['missSub', true]]) {
        if (!r[k] || !need) continue;
        const v = r[k](it);
        if (!str(v)) bad(`rounds ${r.key}: ${k}(${id}) gives ${JSON.stringify(v)}`);
      }
    }
    for (const misses of [0, 1, 2]) if (!str(r.done({ total: asked.length, misses }))) bad(`rounds ${r.key}: done() gives no text`);
  });
  for (const other of ['light', 'dark'])
    for (const override of [false, true]) {
      const t = text.theme(other, override);
      if (!t || !str(t.label) || !str(t.title)) bad(`text.theme('${other}', ${override}): { label, title }`);
    }
}
