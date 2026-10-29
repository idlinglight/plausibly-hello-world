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

function measure() {
  view.w = glCanvas.clientWidth || window.innerWidth || 1;
  view.h = glCanvas.clientHeight || window.innerHeight || 1;
  view.dpr = window.devicePixelRatio || 1;
}

function useWater(on) {
  if (on && water) {
    fallback.deactivate();
    mode = water;
    glCanvas.style.visibility = 'visible';
    // Fade in over the CSS backdrop (next frame, so the transition runs).
    requestAnimationFrame(() => glCanvas.classList.add('on'));
    root.dataset.renderer = water.label;
  } else {
    // Hide at once (no fade): a lost context shows nothing useful.
    glCanvas.classList.remove('on');
    glCanvas.style.visibility = 'hidden';
    mode = fallback;
    fallback.activate();
    root.dataset.renderer = water ? 'fallback (webgl context lost)' : 'fallback (no webgl)';
  }
  measure();
  mode.resize(view);
  mode.redraw(palette);
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

const pointers = new Map(); // pointerId -> { x, y, carry }

function onDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, carry: 0 });
  mode.addDrop(e.clientX, e.clientY, 1);
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
      mode.addDrop(p.x + (dx * s) / dist, p.y + (dy * s) / dist, TRAIL_STRENGTH);
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
  measure();
  mode.resize(view);
  mode.redraw(palette); // resizing a canvas clears it; repaint before the next paint
}
if (window.ResizeObserver) new ResizeObserver(onResize).observe(glCanvas);
addEventListener('resize', onResize); // also catches devicePixelRatio changes (zoom)

document.addEventListener('visibilitychange', () => {
  if (document.hidden) stop();
  else start();
});

// ---- go ---------------------------------------------------------------

measure();
if (!force.includes('nogl')) {
  water = createWater(glCanvas, settings, {
    forceWebGL1: force.includes('webgl1'),
    forcePacked: force.includes('rgba8'),
    onLost: () => useWater(false),
    onRestored: () => useWater(true),
    onFail: () => {
      water = null;
      useWater(false);
    },
  });
}
useWater(!!water);
updateTheme();
if (!document.hidden) start();
