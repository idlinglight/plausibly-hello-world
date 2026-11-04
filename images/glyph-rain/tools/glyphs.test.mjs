// Plain-node check of site/glyphs.js (the sets, reading glyphs.json, the
// caption) and of index.html's CSP-safe shape. Which glyphs a system can
// draw is decided in the browser (render.js); this checks the lists. No
// packages:
// node images/glyph-rain/tools/glyphs.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SETS, FALLBACK, ENV_NAME, FILE_PATH, parseRuntime, describe } from '../site/glyphs.js';

const here = dirname(fileURLToPath(import.meta.url));

// Every glyph one code point, visible on its own (no marks, format
// characters or spaces), no duplicates within a set.
for (const [name, s] of [...Object.entries(SETS), ['fallback', FALLBACK]]) {
  assert.ok(s.chars.length >= 7, `${name}: enough glyphs`);
  assert.equal(new Set(s.chars).size, s.chars.length, `${name}: no duplicates`);
  for (const ch of s.chars) {
    assert.equal([...ch].length, 1, `${name}: one code point each`);
    assert.doesNotMatch(ch, /[\p{M}\p{Cf}\p{Z}\p{Cc}]/u, `${name}: U+${ch.codePointAt(0).toString(16)} is drawable alone`);
  }
  assert.match(s.font, /(sans-serif|serif|monospace)$/, `${name}: font list ends in a generic family`);
}
const cp = (s) => s.chars.map((c) => c.codePointAt(0));
assert.equal(SETS.hieroglyphs.chars.length, 0x1342e - 0x13000 + 1);
assert.ok(!cp(SETS.hieroglyphs).includes(0x1342f), 'U+1342F (Unicode 15) left out');
assert.deepEqual([Math.min(...cp(SETS.runes)), Math.max(...cp(SETS.runes))], [0x16a0, 0x16ea]);
assert.ok(cp(SETS.music).every((c) => (c >= 0x2669 && c <= 0x266f) || (c >= 0x1d100 && c <= 0x1d1ff)), 'music: two blocks only');
console.log('ok the sets: single drawable code points, documented ranges');

// Each set names the switch that selects it, as the startup script does.
const scriptText = readFileSync(join(here, '../entrypoint/40-phw-glyphs.sh'), 'utf8');
assert.deepEqual([SETS.hieroglyphs.source, SETS.music.source, SETS.runes.source], ['default', ENV_NAME, FILE_PATH]);
assert.match(scriptText, new RegExp(`^SECRET_FILE=${FILE_PATH}$`, 'm'));
assert.match(scriptText, /\$\{PHW_GLYPHS:-\}/);
assert.equal(ENV_NAME, 'PHW_GLYPHS');
console.log('ok switch names agree with the startup script');

// parseRuntime: only known names and states get through.
const def = { sets: ['hieroglyphs'], env: 'unknown', file: 'unknown', loaded: false };
for (const bad of [null, undefined, 1, 'music', [], ['music'], {}, { glyphs: 'music' }, { glyphs: [] }, { glyphs: ['nope', 7] }, { glyphs: ['__proto__', 'constructor', 'toString'] }]) {
  assert.deepEqual(parseRuntime(bad), def, `fallback for ${JSON.stringify(bad)}`);
}
assert.deepEqual(parseRuntime({ glyphs: ['runes', 'runes', 'music'], env: 'match', file: 'match' }), { sets: ['runes', 'music'], env: 'match', file: 'match', loaded: true });
assert.deepEqual(parseRuntime({ glyphs: ['music'], env: 'weird', file: 'absent' }), { sets: ['music'], env: 'unknown', file: 'absent', loaded: true });
console.log('ok parseRuntime: unknown names and states fall back, never select');

// The caption.
assert.deepEqual(describe(parseRuntime({ glyphs: ['hieroglyphs'], env: 'unset', file: 'absent' })), { lines: ['Egyptian hieroglyphs · default'], notes: [] });
assert.deepEqual(describe(parseRuntime({ glyphs: ['music', 'runes'], env: 'match', file: 'match' })), { lines: ['Musical symbols · PHW_GLYPHS', 'Runes · /etc/phw/glyphs'], notes: [] });
assert.deepEqual(describe(parseRuntime(null)).notes, ['glyphs.json not loaded: default']);
assert.deepEqual(describe(parseRuntime({ glyphs: ['hieroglyphs'], env: 'other', file: 'directory' })).notes, ['PHW_GLYPHS has another value: ignored', '/etc/phw/glyphs is a folder: mount the volume one level up']);
assert.deepEqual(describe(parseRuntime({ glyphs: ['hieroglyphs'], env: 'unset', file: 'unreadable' })).notes, ['/etc/phw/glyphs isn\'t readable here']);
assert.deepEqual(describe(parseRuntime({ glyphs: ['hieroglyphs'], env: 'unset', file: 'notfile' })).notes, ['/etc/phw/glyphs isn\'t a regular file: ignored']);
assert.deepEqual(describe(parseRuntime({ glyphs: ['runes'], env: 'unset', file: 'match' }), ['runes']).lines, ['Runes (no font here: digits) · /etc/phw/glyphs']);
console.log('ok the caption: set and source per line, notes for switches that didn\'t take');

// index.html: no inline script or style (strict CSP), relative assets.
const html = readFileSync(join(here, '../site/index.html'), 'utf8');
assert.doesNotMatch(html, /<script(?![^>]*\ssrc=)[^>]*>/i, 'no inline <script>');
assert.doesNotMatch(html, /\sstyle=|<style/i, 'no inline style');
assert.doesNotMatch(html, /(src|href)="(\/|https?:)/i, 'relative asset paths only');
assert.match(html, /<title>Glyph Rain · phw<\/title>/);
console.log('ok index.html: CSP-safe, relative paths, title');
