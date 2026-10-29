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
// Input: a tap drops one impulse, a drag a trail of weak ones, and a press
// held (nearly) still keeps dipping in place, so the tap's rings carry on as
// one even sequence for as long as it stays down.
//
// Loop: full frame rate only while ripples are alive or a press is held;
// otherwise the gradient drifts so slowly that ~12 fps is indistinguishable,
// so we wake up rarely. Hidden tab: no frames at all, and the drift clock
// stops.

import { Palette } from './palette.js';
import { createWater } from './water.js';
import { Fallback } from './fallback.js';

const IDLE_MS = 83;
const TRAIL_SPACING = 10; // CSS px between drag-trail impulses
const TRAIL_STRENGTH = 0.2; // relative to a tap
const HOLD_STRENGTH = 0.2; // a held press's dips, relative to a tap (timing: mode.holdRhythm)
// A press that hasn't moved for this long is forgotten (no more dips).
// Nobody holds still that long, but a release can still go missing (let go
// over an OS overlay that takes no focus), and a forgotten press would
// otherwise dip on at full frame rate forever. It also bounds how long a
// still hold keeps the sim from parking (see the packed tier's level creep
// in water.js).
const HOLD_MAX = 5 * 60 * 1000; // ms
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
// The renderer in use, water.js's or fallback.js's. Both provide what this
// file relies on: resize(view), redraw(palette), frame(dt, palette) -> still
// animating?, addDrop(x, y, strength, key, kind) -> impulse used? (kind:
// undefined = tap, 'trail' or 'hold'; key: the pointer's record), and
// holdRhythm = { first, every } in ms: how long after a tap or trail
// impulse a held press's first dip is due, and the spacing of the rest.
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
  // Pointer records are stamped with performance.now() in the event
  // handlers, so the dips are timed on that clock too, not on the rAF one.
  const dipping = pointers.size > 0 && dipHeld(performance.now());
  const busy = mode.frame(dt, palette);
  themeAge += dt;
  if (themeAge >= THEME_INTERVAL) updateTheme();
  if (busy || dipping) rafId = requestAnimationFrame(tick);
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

// pointerId -> { x, y, carry, type, movedAt, nextDipAt }: one per press
// still down, times from performance.now(). The record also serves the
// renderers as a per-pointer key (fallback.js spaces its trail rings per
// pointer).
const pointers = new Map();

// A held press keeps dipping, in step with the rings: a tap or trail
// impulse puts its next dip holdRhythm.first ahead (as the tap's own rings
// run out), each dip the next one holdRhythm.every ahead, one per ring, so
// the sequence stays even. A drag's trail keeps pushing that out, so drags
// faster than TRAIL_SPACING per `first` are unchanged; slower ones dip too,
// as a slowly moving finger in water should. Called from tick(), so it
// follows the current renderer (also across a context loss) and the parking
// countdown starts at the last dip. Returns whether any press is still
// dipping (the loop then keeps the full frame rate).
function dipHeld(now) {
  const { every } = mode.holdRhythm;
  let dipping = false;
  for (const [id, p] of pointers) {
    if (now - p.movedAt > HOLD_MAX) {
      pointers.delete(id);
      continue;
    }
    dipping = true;
    if (now < p.nextDipAt) continue;
    // Keep the beat (a late frame must not stretch the spacing), unless we
    // are a whole beat behind (a stall): then restart from now.
    p.nextDipAt = (now - p.nextDipAt < every ? p.nextDipAt : now) + every;
    mode.addDrop(p.x, p.y, HOLD_STRENGTH, p, 'hold');
  }
  return dipping;
}

function onDown(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  const t = performance.now();
  const p = { x: e.clientX, y: e.clientY, carry: 0, type: e.pointerType, movedAt: t, nextDipAt: t + mode.holdRhythm.first };
  pointers.set(e.pointerId, p);
  // Captured, the release reaches us wherever it happens, and a capture lost
  // any other way (lostpointercapture below) ends the press as well.
  try {
    e.target.setPointerCapture(e.pointerId);
  } catch (err) {
    // no capturable target, or the pointer is already gone: nothing to do
  }
  mode.addDrop(e.clientX, e.clientY, 1, p);
  wake();
}

function onMove(e) {
  const p = pointers.get(e.pointerId);
  if (!p) return;
  if (e.buttons === 0 && (e.pointerType === 'mouse' || e.pointerType === 'pen')) {
    pointers.delete(e.pointerId); // released where we didn't see it (a pen: lifted to hover)
    return;
  }
  const list = (e.getCoalescedEvents && e.getCoalescedEvents()) || [];
  const events = list.length ? list : [e];
  let applied = false;
  for (const ev of events) {
    const dx = ev.clientX - p.x;
    const dy = ev.clientY - p.y;
    const dist = Math.hypot(dx, dy);
    // Emit impulses every TRAIL_SPACING px along the path.
    let s = TRAIL_SPACING - p.carry;
    while (s <= dist) {
      if (mode.addDrop(p.x + (dx * s) / dist, p.y + (dy * s) / dist, TRAIL_STRENGTH, p, 'trail')) applied = true;
      s += TRAIL_SPACING;
    }
    p.carry = (p.carry + dist) % TRAIL_SPACING;
    p.x = ev.clientX;
    p.y = ev.clientY;
  }
  // Only impulses the renderer used count (the fallback thins out trails,
  // so a slow drag there still gets its dips): they restart the stillness
  // clock (HOLD_MAX) and push the next dip out.
  if (applied) {
    p.movedAt = performance.now();
    p.nextDipAt = p.movedAt + mode.holdRhythm.first;
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
addEventListener('lostpointercapture', onUp); // also right after every release: deleting twice is harmless
// A release we may never see (switched app or window): end every hold.
addEventListener('blur', () => pointers.clear());
// A long-press on a touch screen fires contextmenu; the menu or selection
// UI it can bring up would interrupt the press, so that one is suppressed.
// Any other contextmenu is a real request (right click, Mac Ctrl+click, pen
// barrel button, Menu key): the menu opens, and as it may swallow the
// release, every hold ends.
addEventListener('contextmenu', (e) => {
  let touchHeld = false;
  for (const p of pointers.values()) if (p.type === 'touch') touchHeld = true;
  if (touchHeld && (e.pointerType === undefined || e.pointerType === 'touch')) e.preventDefault();
  else pointers.clear();
});

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
  if (document.hidden) {
    pointers.clear(); // no dipping on in the background, nor after coming back
    stop();
  } else start();
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
