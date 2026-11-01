// Plain-node replay of real wheel events through the engine's wheel.js:
// every recorded gesture must be classified as the device that made it
// (mouse wheel → zoom, trackpad → pan). No packages:
// node shared/map-quiz/tools/wheel.test.mjs
// The events (wheel-fixture.json) were recorded on macOS in Safari, Chrome
// and Firefox at 100 % and 125 % page zoom; see "about" in the file.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { wheelKind } from '../site/wheel.js';

const fixture = JSON.parse(readFileSync(new URL('./wheel-fixture.json', import.meta.url), 'utf8'));
const col = Object.fromEntries(fixture.columns.map((c, i) => [c, i]));
const rows = fixture.rows.map((r) => Object.fromEntries(Object.entries(col).map(([c, i]) => [c, r[i]])));
const expected = (label) => (label.startsWith('mouse') ? 'mouse' : 'trackpad');
const kind = (r) => wheelKind({ deltaMode: r.deltaMode, deltaX: r.deltaX, deltaY: r.deltaY, wheelDeltaY: r.wheelDeltaY }, r.dpr);

let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

check('fixture covers mouse and trackpad in Safari, Chrome and Firefox, at 100 % and zoomed', () => {
  const seen = new Set(rows.map((r) => `${r.browser.split(' ')[0]} ${expected(r.label)} ${r.zoomPct === 100 ? 100 : 'zoom'}`));
  for (const b of ['Safari', 'Chrome', 'Firefox'])
    for (const d of ['mouse', 'trackpad'])
      for (const z of [100, 'zoom']) assert.ok(seen.has(`${b} ${d} ${z}`), `${b} ${d} ${z}`);
});

// What decides: the first event of each gesture (main.js keeps the answer).
const groups = new Map();
for (const r of rows) {
  const key = `${r.browser}|${r.zoomPct}|${r.label}`;
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push(r);
}
for (const [key, list] of groups) {
  const [browser, zoom, label] = key.split('|');
  const first = list.filter((r) => r.indexInGesture === 0);
  check(`${browser} ${zoom} %, ${label}: ${first.length} gestures open as ${expected(label)}`, () => {
    for (const r of first) assert.equal(kind(r), expected(label), JSON.stringify(r));
  });
}

// Robustness: if a gesture's start were missed (a gap measured
// differently), the next events would still be read the same way.
check('the 2nd and 3rd event of every gesture classify the same', () => {
  for (const r of rows.filter((r) => r.indexInGesture > 0)) assert.equal(kind(r), expected(r.label), JSON.stringify(r));
});

// Not recorded, seen in headless Chrome: with an emulated device pixel
// ratio, a CDP −120 notch arrives divided by the ratio.
check('synthetic: notches divided by the device pixel ratio are mice', () => {
  assert.equal(wheelKind({ deltaMode: 0, deltaX: 0, deltaY: -40, wheelDeltaY: 40 }, 3), 'mouse');
  assert.equal(wheelKind({ deltaMode: 0, deltaX: 0, deltaY: -48, wheelDeltaY: 48 }, 2.5), 'mouse');
  assert.equal(wheelKind({ deltaMode: 0, deltaX: 0, deltaY: -120, wheelDeltaY: 120 }, 1), 'mouse');
  assert.equal(wheelKind({ deltaMode: 0, deltaX: 0, deltaY: -2, wheelDeltaY: 6 }, 3), 'trackpad');
});

// Why wheelDeltaY ≈ −3 × deltaY is not used: WebKit reports it for mice too.
check('Safari mouse events satisfy the −3 × deltaY relation (so it proves nothing)', () => {
  const m = rows.filter((r) => r.browser.startsWith('Safari') && r.label.startsWith('mouse'));
  assert.ok(m.length > 0);
  for (const r of m) assert.ok(Math.abs(r.wheelDeltaY + 3 * r.deltaY) <= 1, JSON.stringify(r));
});

console.log(`${checks} checks passed`);
