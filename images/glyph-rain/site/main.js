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

let renderer, sim, sets, raf = 0, last = 0;

function cellSize() {
  const css = Math.round(Math.min(28, Math.max(16, Math.sqrt(innerWidth * innerHeight) / 44)));
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  return { css, dpr, px: Math.round(css * dpr) };
}

function build() {
  const { css, dpr, px } = cellSize();
  const cols = Math.ceil(innerWidth / css);
  const rows = Math.ceil(innerHeight / css);
  const drawn = sets.map((s) => ({ font: s.font, px, glyphs: usableGlyphs(s, px) }));
  renderer.setup(drawn, px, Math.round(innerWidth * dpr), Math.round(innerHeight * dpr));
  sim = new Sim(cols, rows, drawn.map((d) => d.glyphs.length), random);
  for (let t = 0; t < PREFILL_S; t += 1 / 30) sim.step(1 / 30);
  renderer.draw(sim);
}

function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000 || 0);
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

async function main() {
  const rt = parseRuntime(await loadRuntime());
  // A set this system has too few glyphs for is drawn as FALLBACK.
  const px = cellSize().px;
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
    resizeTimer = setTimeout(() => {
      build();
      run();
    }, 150);
  });
  reduced.addEventListener('change', run);

  // A tap or click starts a head where it landed.
  canvasEl.addEventListener('pointerdown', (e) => {
    if (reduced.matches) return;
    const { css } = cellSize();
    sim.start(Math.min(sim.cols - 1, Math.floor(e.clientX / css)), Math.floor(e.clientY / css));
  });
}

main();
