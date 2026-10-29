// main.js: picks a renderer, runs the loop, routes input.
//
// Renderer: WebGL water (water.js) if it initialises, else the CSS +
// canvas-2D fallback (fallback.js). The fallback also covers the gap while a
// lost WebGL context is being restored. <html data-renderer="..."> says
// which one is running.
//
// Debug: ?force=webgl1 | rgba8 | nogl (comma-separated) exercises the lower
// tiers; ?seed=<int> gives a reproducible palette.
//
// Loop: full frame rate only while ripples are alive; otherwise the gradient
// drifts so slowly that ~12 fps is indistinguishable, so we wake up rarely.
// Hidden tab: no frames at all, and the drift clock stops.

import { Palette } from './palette.js';
import { createWater } from './water.js';
import { Fallback } from './fallback.js';

const IDLE_MS = 83;
const TRAIL_SPACING = 10; // CSS px between drag-trail impulses
const TRAIL_STRENGTH = 0.2; // relative to a tap
const THEME_INTERVAL = 2; // s between <meta name=theme-color> updates

const root = document.documentElement;
const backdrop = document.getElementById('backdrop');
const glCanvas = document.getElementById('water');
const themeMeta = document.querySelector('meta[name="theme-color"]');
const params = new URLSearchParams(location.search);
const force = (params.get('force') || '').split(',');
const seed = parseInt(params.get('seed') || '', 10);

const motionQuery = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : null;
const settings = { reducedMotion: !!(motionQuery && motionQuery.matches) };
if (motionQuery) {
  const onMotion = (e) => (settings.reducedMotion = e.matches);
  if (motionQuery.addEventListener) motionQuery.addEventListener('change', onMotion);
  else if (motionQuery.addListener) motionQuery.addListener(onMotion);
}

const palette = new Palette(Number.isFinite(seed) ? seed >>> 0 : undefined);
const view = { w: 1, h: 1, dpr: 1 };
const fallback = new Fallback(backdrop, settings);
let water = null;
let mode = fallback;

// Updates `view`; returns whether anything changed.
function measure() {
  const w = glCanvas.clientWidth || window.innerWidth || 1;
  const h = glCanvas.clientHeight || window.innerHeight || 1;
  const dpr = window.devicePixelRatio || 1;
  const changed = w !== view.w || h !== view.h || dpr !== view.dpr;
  view.w = w;
  view.h = h;
  view.dpr = dpr;
  return changed;
}

function useWater(on, why) {
  measure();
  if (on && water && water.ready) {
    fallback.deactivate();
    // What shows through while the canvas fades in: the same palette.
    fallback.paintBackdrop(palette);
    mode = water;
    glCanvas.style.visibility = 'visible';
    mode.resize(view);
    mode.redraw(palette);
    // Fade in. Flushing styles first makes the transition start from the
    // current opacity; doing it synchronously (no deferred callback) means a
    // context loss right after can't be undone by a stale callback.
    void getComputedStyle(glCanvas).opacity;
    glCanvas.classList.add('on');
    root.dataset.renderer = water.label;
  } else {
    // Hide at once (no fade): a lost context shows nothing useful.
    glCanvas.classList.remove('on');
    glCanvas.style.visibility = 'hidden';
    mode = fallback;
    fallback.activate();
    mode.resize(view);
    mode.redraw(palette);
    root.dataset.renderer = `fallback (${why || 'no webgl'})`;
  }
  wake();
}

// ---- loop -------------------------------------------------------------

let running = false;
let rafId = 0;
let timerId = 0;
let last = 0;
let themeAge = Infinity;

function tick(now) {
  rafId = 0;
  if (!running) return;
  const dt = Math.min(Math.max((now - last) / 1000, 0), 0.25);
  last = now;
  if ((window.devicePixelRatio || 1) !== view.dpr) onResize();
  palette.advance(dt * (settings.reducedMotion ? 0.3 : 1));
  const busy = mode.frame(dt, palette);
  themeAge += dt;
  if (themeAge >= THEME_INTERVAL) updateTheme();
  if (busy) rafId = requestAnimationFrame(tick);
  else timerId = setTimeout(idleWake, IDLE_MS);
}

function idleWake() {
  timerId = 0;
  if (running && !rafId) rafId = requestAnimationFrame(tick);
}

function wake() {
  if (!running) return;
  if (timerId) {
    clearTimeout(timerId);
    timerId = 0;
  }
  if (!rafId) rafId = requestAnimationFrame(tick);
}

function start() {
  if (running) return;
  running = true;
  last = performance.now();
  wake();
}

function stop() {
  running = false;
  if (rafId) cancelAnimationFrame(rafId);
  if (timerId) clearTimeout(timerId);
  rafId = timerId = 0;
}

function updateTheme() {
  themeAge = 0;
  if (themeMeta) themeMeta.setAttribute('content', palette.cssColorAt(palette.tAt(view.w / 2, 0, view.w, view.h)));
}

// ---- input ------------------------------------------------------------

// pointerId -> { x, y, carry }. The record also serves the renderers as a
// per-pointer key (fallback.js spaces its trail rings per pointer).
const pointers = new Map();

function onDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  const p = { x: e.clientX, y: e.clientY, carry: 0 };
  pointers.set(e.pointerId, p);
  mode.addDrop(e.clientX, e.clientY, 1, p);
  wake();
}

function onMove(e) {
  const p = pointers.get(e.pointerId);
  if (!p) return;
  if (e.pointerType === 'mouse' && e.buttons === 0) {
    pointers.delete(e.pointerId); // released outside the window
    return;
  }
  const list = (e.getCoalescedEvents && e.getCoalescedEvents()) || [];
  const events = list.length ? list : [e];
  for (const ev of events) {
    const dx = ev.clientX - p.x;
    const dy = ev.clientY - p.y;
    const dist = Math.hypot(dx, dy);
    // Emit impulses every TRAIL_SPACING px along the path.
    let s = TRAIL_SPACING - p.carry;
    while (s <= dist) {
      mode.addDrop(p.x + (dx * s) / dist, p.y + (dy * s) / dist, TRAIL_STRENGTH, p);
      s += TRAIL_SPACING;
    }
    p.carry = (p.carry + dist) % TRAIL_SPACING;
    p.x = ev.clientX;
    p.y = ev.clientY;
  }
  wake();
}

function onUp(e) {
  pointers.delete(e.pointerId);
}

addEventListener('pointerdown', onDown);
addEventListener('pointermove', onMove);
addEventListener('pointerup', onUp);
addEventListener('pointercancel', onUp);

// ---- lifecycle --------------------------------------------------------

function onResize() {
  if (!measure()) return;
  mode.resize(view);
  mode.redraw(palette); // resizing a canvas clears it; repaint before the next paint
}
if (window.ResizeObserver) new ResizeObserver(onResize).observe(glCanvas);
else addEventListener('resize', onResize);
// devicePixelRatio can change without any CSS size change (window moved to
// another monitor), which no resize event reports: tick() compares it.

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stop();
  else start();
});

// ---- go ---------------------------------------------------------------

measure();
if (!force.includes('nogl')) {
  water = createWater(glCanvas, settings, {
    view,
    forceWebGL1: force.includes('webgl1'),
    forcePacked: force.includes('rgba8'),
    onLost: () => useWater(false, 'webgl context lost'),
    onRestored: () => useWater(true),
    // Keep `water`: a later loss/restore cycle may still bring it back.
    onFail: () => useWater(false, 'webgl re-init failed'),
  });
}
useWater(!!water);
updateTheme();
if (!document.hidden) start();
