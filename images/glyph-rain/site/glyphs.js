// The glyph sets, and what the runtime file (glyphs.json, written at
// container start by /docker-entrypoint.d/40-phw-glyphs.sh) selects.
// No DOM: tools/glyphs.test.mjs runs this under plain node.
//
// There is deliberately no URL or storage override: the set on screen is
// the signal that a switch reached the container, so only the container
// may pick it.

export const ENV_NAME = 'PHW_GLYPHS';
export const FILE_PATH = '/etc/phw/glyphs';

const span = (lo, hi) => Array.from({ length: hi - lo + 1 }, (_, i) => String.fromCodePoint(lo + i));
const cps = (...list) => list.map((cp) => String.fromCodePoint(cp));

// System fonts only (nothing is downloaded). Each list names the fonts
// that have the block on Windows, Android/Linux and Apple systems; the
// browser's own fallback still applies after them.
export const SETS = {
  hieroglyphs: {
    label: 'Egyptian hieroglyphs',
    source: 'default',
    font: '"Noto Sans Egyptian Hieroglyphs", "Segoe UI Historic", sans-serif',
    // The whole block but U+1342F (Unicode 15, not in the fonts yet). The
    // renderer keeps the signs that fit an upright cell (upright: true).
    chars: span(0x13000, 0x1342e),
    upright: true,
  },
  music: {
    label: 'Musical symbols',
    source: ENV_NAME,
    font: '"Segoe UI Symbol", "Noto Music", "Apple Symbols", "Noto Sans Symbols 2", serif',
    chars: [
      ...'♩♪♫♬♭♮♯',
      // Musical Symbols block: repeats, segno, coda, fermatas, breath mark,
      // clefs, double sharp and flat, rests, notes, dynamics, pedal marks.
      // Apple systems draw only some of these (no notes, no rests); the
      // renderer drops glyphs a system can't draw.
      ...cps(0x1d106, 0x1d107, 0x1d10b, 0x1d10c, 0x1d110, 0x1d111, 0x1d112),
      ...span(0x1d11e, 0x1d124),
      ...cps(0x1d12a, 0x1d12b),
      ...span(0x1d13b, 0x1d140),
      ...span(0x1d15d, 0x1d164),
      ...span(0x1d18f, 0x1d191),
      ...cps(0x1d1ae, 0x1d1af),
    ],
  },
  runes: {
    label: 'Runes',
    source: FILE_PATH,
    font: '"Segoe UI Historic", "Noto Sans Runic", "Apple Symbols", sans-serif',
    // The runes proper: U+16A0–16EA (no punctuation, no golden numbers,
    // no Unicode 7 additions).
    chars: span(0x16a0, 0x16ea),
  },
};

// Shown instead of a set whose fonts are missing on this system.
export const FALLBACK = {
  label: 'digits',
  font: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  chars: span(0x30, 0x39),
};

export const ENV_STATES = ['unset', 'match', 'other'];
export const FILE_STATES = ['absent', 'match', 'other', 'unreadable', 'directory'];

// glyphs.json (parsed, or null when it didn't load) → { sets, env, file,
// loaded }. Unknown names and states are dropped, so a damaged file can
// only fall back to the default, never select something.
export function parseRuntime(data) {
  const ok = data !== null && typeof data === 'object' && !Array.isArray(data);
  const listed = ok && Array.isArray(data.glyphs) ? data.glyphs : [];
  const sets = [...new Set(listed.filter((n) => typeof n === 'string' && Object.hasOwn(SETS, n)))];
  return {
    sets: sets.length ? sets : ['hieroglyphs'],
    env: ok && ENV_STATES.includes(data.env) ? data.env : 'unknown',
    file: ok && FILE_STATES.includes(data.file) ? data.file : 'unknown',
    loaded: ok && sets.length > 0,
  };
}

// The caption: one line per shown set ("Runes · /etc/phw/glyphs"), then a
// note per switch that is set but didn't take, or if the file didn't load.
// missing: names of sets drawn as FALLBACK because their fonts are absent.
export function describe(rt, missing = []) {
  const lines = rt.sets.map((n) => {
    const s = SETS[n];
    const what = missing.includes(n) ? `${s.label} (no font here: ${FALLBACK.label})` : s.label;
    return `${what} · ${s.source}`;
  });
  const notes = [];
  if (!rt.loaded) notes.push('glyphs.json not loaded: default');
  if (rt.env === 'other') notes.push(`${ENV_NAME} has another value: ignored`);
  if (rt.file === 'other') notes.push(`${FILE_PATH} has other content: ignored`);
  if (rt.file === 'unreadable') notes.push(`${FILE_PATH} isn't readable here`);
  if (rt.file === 'directory') notes.push(`${FILE_PATH} is a folder: mount the volume one level up`);
  return { lines, notes };
}
