// Glyph Rain: loads the runtime file, picks the glyph sets, runs the rain.
// ?seed=<int> makes the rain reproducible. <html data-glyphs> lists the
// sets shown, data-env / data-file the switches' states (glyphs.js).

import { SETS, FALLBACK, parseRuntime, describe } from './glyphs.js';
import { Sim, rng } from './sim.js';
import { Renderer, usableGlyphs } from './render.js';

const MIN_GLYPHS = 6; // fewer usable glyphs: the set's fonts are missing (ChromeOS draws 7 music signs)
const PREFILL_S = 5; // seconds simulated before the first frame (no empty start)

const root = document.documentElement;
const canvasEl = document.getElementById('rain');
const caption = document.getElementById('caption');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const seed = Number.parseInt(new URLSearchParams(location.search).get('seed') ?? '', 10);
const random = Number.isFinite(seed) ? rng(seed) : Math.random;

async function loadRuntime() {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const res = await fetch('glyphs.json', { signal: ctl.signal, redirect: 'error' });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function showCaption(rt, missing) {
  const { lines, notes } = describe(rt, missing);
  caption.replaceChildren(
    ...lines.map((t) => Object.assign(document.createElement('span'), { className: 'set', textContent: t })),
    ...notes.map((t) => Object.assign(document.createElement('span'), { className: 'note', textContent: t })),
  );
}

let renderer, sim, sets, geom = null, raf = 0, last = 0;

// Everything is laid out in device pixels: the grid covers the canvas
// exactly at any pixel ratio, and taps map with the geometry the current
// grid was built with.
function geometry() {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const css = Math.round(Math.min(28, Math.max(16, Math.sqrt(innerWidth * innerHeight) / 44)));
  const px = Math.round(css * dpr);
  const w = Math.round(innerWidth * dpr);
  const h = Math.round(innerHeight * dpr);
  return { dpr, px, w, h, cols: Math.ceil(w / px), rows: Math.ceil(h / px) };
}

// What a set is drawn with at px. A set with no drawable glyph at this
// size (the startup check passed it at another) falls back to the digits,
// taken without the ink filter, so a set is never empty.
function drawable(set, px) {
  const glyphs = usableGlyphs(set, px);
  if (glyphs.length) return { label: set.label, font: set.font, px, glyphs };
  return { label: FALLBACK.label, font: FALLBACK.font, px, glyphs: usableGlyphs(FALLBACK, px, false) };
}

// Rebuilds when the geometry changed; returns whether it did.
function build() {
  const g = geometry();
  if (geom && ['dpr', 'px', 'w', 'h'].every((k) => g[k] === geom[k])) return false;
  geom = g;
  const drawn = sets.map((s) => drawable(s, g.px));
  renderer.setup(drawn, g.px, g.w, g.h);
  sim = new Sim(g.cols, g.rows, drawn.map((d) => d.glyphs.length), random);
  for (let t = 0; t < PREFILL_S; t += 1 / 30) sim.step(1 / 30);
  renderer.draw(sim);
  return true;
}

function frame(now) {
  // Clamped at both ends: a long pause, and a first timestamp earlier than
  // the performance.now() run() stored.
  const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
  last = now;
  sim.step(dt);
  renderer.draw(sim);
  raf = requestAnimationFrame(frame);
}

function run() {
  cancelAnimationFrame(raf);
  raf = 0;
  root.dataset.motion = reduced.matches ? 'still' : 'rain';
  if (reduced.matches) return; // a still frame (drawn by build) until motion is allowed
  last = performance.now();
  raf = requestAnimationFrame(frame);
}

function rebuild() {
  if (build()) run();
}

// A pixel ratio change at the same CSS size (a window moved to another
// screen) fires no resize event; this media query does.
function watchPixelRatio() {
  matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`).addEventListener(
    'change',
    () => {
      rebuild();
      watchPixelRatio();
    },
    { once: true },
  );
}

async function main() {
  const rt = parseRuntime(await loadRuntime());
  // A set this system has too few glyphs for is drawn as FALLBACK.
  const px = geometry().px;
  const missing = rt.sets.filter((n) => usableGlyphs(SETS[n], px).length < MIN_GLYPHS);
  sets = rt.sets.map((n) => (missing.includes(n) ? FALLBACK : SETS[n]));

  root.dataset.glyphs = rt.sets.join(' ');
  root.dataset.env = rt.env;
  root.dataset.file = rt.file;
  if (missing.length) root.dataset.missing = missing.join(' ');
  showCaption(rt, missing);

  renderer = new Renderer(canvasEl);
  build();
  run();

  let resizeTimer = 0;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(rebuild, 150);
  });
  watchPixelRatio();
  reduced.addEventListener('change', run);

  // A tap or click starts a head where it landed (not in the still frame).
  canvasEl.addEventListener('pointerdown', (e) => {
    if (reduced.matches) return;
    const col = Math.floor((e.clientX * geom.dpr) / geom.px);
    const row = Math.floor((e.clientY * geom.dpr) / geom.px);
    sim.start(Math.min(sim.cols - 1, Math.max(0, col)), Math.min(sim.rows - 1, Math.max(0, row)));
  });
}

main();
