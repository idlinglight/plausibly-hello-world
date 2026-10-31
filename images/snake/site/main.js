// main.js: modes, game loop, input, HUD.
//
// Modes (<html data-mode="...">):
//   demo      the autopilot plays (autopilot.js) — what a visitor sees first
//   demo-end  a demo snake just died; a new demo starts shortly
//   play      a person plays: arrow keys / WASD, swipes, or a tap or click
//             beside the head steers towards it
//   paused    Space (in play) / P / Esc / the pause button, or leaving the
//             tab or window
//   over      a person's round ended; any key or tap plays again, and after
//             a while the demo takes over again
//   idle      prefers-reduced-motion: nothing moves until someone plays
// Any direction input outside `play` starts a fresh round for the person.
// A player who stops steering for PLAY_IDLE_MS hands over to the autopilot
// (with reduced motion: the round pauses).
//
// Loop: the game steps at a fixed rate; frames in between draw the snake
// part of the way (render.js). Frames run only while something moves; a
// hidden tab gets none (the browser stops requestAnimationFrame).
//
// Debug: ?seed=<int> makes fruit and autopilot reproducible.

import { Game, UP, RIGHT, DOWN, LEFT, makeRng } from './game.js';
import { Autopilot } from './autopilot.js';
import { Renderer } from './render.js';

const DEMO_TPS = 10; // steps per second
const PLAY_TPS = 7; // at the start of a round …
const PLAY_TPS_MAX = 13; // … rising per fruit to this
const PLAY_TPS_GAIN = 0.15;
const DEMO_RESTART_MS = 1700;
const OVER_TO_DEMO_MS = 15000;
const PLAY_IDLE_MS = 30000;
const RESTART_GRACE_MS = 500; // after dying, ignore input this long (a held key)
const MAX_DT = 250; // longer gaps between frames don't fast-forward the game
const HUD_H = 48; // CSS px kept free above the board (style.css #hud)
const HINT_H = 44; // … and below it (#hint)
const TONGUE_MS = 260;
const BEST_KEY = 'phw-snake-best';

const root = document.documentElement;
const canvas = document.getElementById('board');
const scoreLabel = document.getElementById('score-label');
const scoreValue = document.getElementById('score');
const bestValue = document.getElementById('best');
const hint = document.getElementById('hint');
const pauseButton = document.getElementById('pause');
const safe = document.getElementById('safe');

const params = new URLSearchParams(location.search);
const seedParam = parseInt(params.get('seed') || '', 10);
const seed = Number.isFinite(seedParam) ? seedParam : crypto.getRandomValues(new Uint32Array(1))[0];
const rng = makeRng(seed);

const coarse = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches);
const motionQuery = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : null;
let reduced = !!(motionQuery && motionQuery.matches);

const view = { w: 1, h: 1, dpr: 1 };
const renderer = new Renderer(canvas);
renderer.reduced = reduced;
const autopilot = new Autopilot(rng);
let game = null;

let mode = '';
let pausedFrom = 'play';
let tickMs = 1000 / DEMO_TPS;
let acc = 0; // ms since the last step
let last = 0; // timestamp of the last frame
let raf = 0;
let timer = 0;
let endedAt = 0;
let lastInput = 0;
let handedOver = false; // demo continuing a person's round
let newBest = false;
let tongueAt = 0;
let nextTongue = 0;
let press = null; // the pointer press being tracked for swipes
let best = loadBest();

// ── Layout ──────────────────────────────────────────────────────────────

function measure() {
  view.w = window.innerWidth || canvas.clientWidth || 1;
  view.h = window.innerHeight || canvas.clientHeight || 1;
  view.dpr = window.devicePixelRatio || 1;
}

// The rectangle the board may use (CSS px): the viewport minus safe-area
// insets (notches), a margin, and the HUD and hint bands.
function boardArea() {
  const cs = getComputedStyle(safe);
  const inset = (k) => parseFloat(cs[k]) || 0;
  const m = Math.max(10, Math.round(Math.min(view.w, view.h) * 0.025));
  const left = inset('paddingLeft') + m;
  const right = inset('paddingRight') + m;
  const top = inset('paddingTop') + HUD_H;
  const bottom = inset('paddingBottom') + HINT_H;
  return {
    x: left,
    y: top,
    w: Math.max(40, view.w - left - right),
    h: Math.max(40, view.h - top - bottom),
  };
}

// Board size for an area: chunky cells, about 17 across the short side.
function gridFor(area) {
  const cell = Math.min(38, Math.max(18, Math.round(Math.min(area.w, area.h) / 17)));
  return { cols: Math.max(5, Math.floor(area.w / cell)), rows: Math.max(5, Math.floor(area.h / cell)) };
}

// Fits the board to the viewport. regrid: pick a new board size for the
// viewport (only between rounds); otherwise the current board is rescaled.
function fit(regrid) {
  measure();
  const area = boardArea();
  if (regrid || !game) {
    const g = gridFor(area);
    if (!game || g.cols !== game.cols || g.rows !== game.rows) game = new Game(g.cols, g.rows, rng);
  }
  renderer.layout(view, area, game.cols, game.rows);
  root.dataset.grid = game.cols + 'x' + game.rows;
}

function gridIsStale() {
  const g = gridFor(boardArea());
  return g.cols !== game.cols || g.rows !== game.rows;
}

// ── Modes ───────────────────────────────────────────────────────────────

function setMode(m) {
  mode = m;
  root.dataset.mode = m;
  clearTimeout(timer);
  timer = 0;
  updateHud();
}

const running = () => mode === 'demo' || mode === 'play';

function newRound(dir) {
  fit(true);
  game.reset(dir);
  autopilot.newRound(game);
  renderer.newRound(performance.now());
  acc = 0;
  newBest = false;
  handedOver = false;
}

function startDemo() {
  newRound(RIGHT);
  tickMs = 1000 / DEMO_TPS;
  setMode('demo');
  wake();
}

function startIdle() {
  newRound(RIGHT);
  setMode('idle');
  wake();
}

function startPlay(dir) {
  newRound(dir);
  tickMs = 1000 / PLAY_TPS;
  lastInput = performance.now();
  setMode('play');
  wake();
}

// Between rounds, with nobody playing: the demo, or a still board.
function rest() {
  if (reduced) startIdle();
  else startDemo();
}

function pause() {
  if (!running()) return;
  pausedFrom = mode;
  setMode('paused');
  wake();
}

function resume() {
  if (mode !== 'paused') return;
  if (pausedFrom === 'play') lastInput = performance.now();
  setMode(pausedFrom);
  wake();
}

function ended(now, ev) {
  endedAt = now;
  press = null; // a swipe still in progress must not start the next round
  if (ev === 'die') renderer.died(now);
  if (mode === 'demo') {
    setMode('demo-end');
    timer = setTimeout(rest, DEMO_RESTART_MS);
  } else {
    setMode('over');
    hint.textContent = ev === 'full' ? 'Board full — well played!' : overText();
    if (!reduced) timer = setTimeout(rest, OVER_TO_DEMO_MS);
  }
}

// ── Loop ────────────────────────────────────────────────────────────────

function wake() {
  if (raf || document.hidden) return;
  last = performance.now();
  raf = requestAnimationFrame(frame);
}

function frame(now) {
  raf = 0;
  const dt = Math.max(0, Math.min(now - last, MAX_DT));
  last = now;
  if (running()) {
    acc += dt;
    for (let k = 0; k < 4 && acc >= tickMs && running(); k++) {
      acc -= tickMs;
      tick(now);
    }
    acc = Math.min(acc, tickMs);
  }
  renderer.draw(game, tickMs > 0 ? acc / tickMs : 1, now, tongue(now));
  if (running() || renderer.busy(now)) raf = requestAnimationFrame(frame);
}

function tick(now) {
  if (mode === 'play' && now - lastInput > PLAY_IDLE_MS) {
    // Nobody's steering any more: the autopilot carries on (from the
    // current length), or with reduced motion the round just pauses.
    if (reduced) {
      pause();
      return;
    }
    game.queue.length = 0;
    autopilot.newRound(game, game.cells.length);
    handedOver = true;
    tickMs = 1000 / DEMO_TPS;
    setMode('demo');
  }
  if (mode === 'demo') game.turn(autopilot.choose(game));
  const fruit = game.fruit;
  const ev = game.step();
  if (ev === 'eat' || ev === 'full') {
    renderer.ate(fruit, now);
    if (mode === 'play') {
      tickMs = 1000 / Math.min(PLAY_TPS_MAX, PLAY_TPS + game.eaten * PLAY_TPS_GAIN);
      if (game.eaten > best) {
        best = game.eaten;
        newBest = true;
        saveBest(best);
      }
    }
    updateScore();
  }
  if (ev === 'die' || ev === 'full') ended(now, ev);
}

// Tongue flicks: every few seconds while moving. Returns 0..1 while out.
function tongue(now) {
  if (reduced || !running()) return 0;
  if (now >= nextTongue) {
    tongueAt = now;
    nextTongue = now + 2500 + Math.random() * 4000;
  }
  const t = (now - tongueAt) / TONGUE_MS;
  return t > 0 && t < 1 ? t : 0;
}

// ── Input ───────────────────────────────────────────────────────────────

// A direction from keys or a swipe.
function steer(d) {
  const now = performance.now();
  switch (mode) {
    case 'play':
      lastInput = now;
      game.turn(d);
      break;
    case 'paused':
      if (pausedFrom === 'play') {
        resume();
        game.turn(d);
      } else {
        startPlay(d);
      }
      break;
    case 'over':
      if (now - endedAt > RESTART_GRACE_MS) startPlay(d);
      break;
    default: // demo, demo-end, idle
      startPlay(d);
  }
}

// A tap or click that wasn't a swipe.
function tap(x, y) {
  const c = renderer.toCell(x, y);
  if (mode === 'play') {
    // Turn towards the tap, across the current heading.
    lastInput = performance.now();
    const hx = (game.head % game.cols) + 0.5;
    const hy = Math.floor(game.head / game.cols) + 0.5;
    const h = game.heading;
    if (h === LEFT || h === RIGHT) {
      if (Math.abs(c.y - hy) >= 0.5) game.turn(c.y < hy ? UP : DOWN);
    } else if (Math.abs(c.x - hx) >= 0.5) {
      game.turn(c.x < hx ? LEFT : RIGHT);
    }
    return;
  }
  if (mode === 'paused') {
    resume();
    return;
  }
  // Start heading from the middle of the board towards the tap.
  const dx = c.x - game.cols / 2;
  const dy = c.y - game.rows / 2;
  const d = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? LEFT : RIGHT) : dy < 0 ? UP : DOWN;
  if (mode === 'over' && performance.now() - endedAt <= RESTART_GRACE_MS) return;
  startPlay(d);
}

const KEYS = {
  ArrowUp: UP,
  KeyW: UP,
  ArrowRight: RIGHT,
  KeyD: RIGHT,
  ArrowDown: DOWN,
  KeyS: DOWN,
  ArrowLeft: LEFT,
  KeyA: LEFT,
};

window.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const onButton = e.target instanceof Element && e.target.closest('button');
  if (onButton && (e.code === 'Space' || e.code === 'Enter' || e.code === 'NumpadEnter')) return; // the button's own
  const d = KEYS[e.code];
  if (d !== undefined) {
    e.preventDefault();
    // Auto-repeat of a held key: harmless while playing, but it must not
    // start a round (it would outlast the restart grace).
    if (!e.repeat || mode === 'play') steer(d);
    return;
  }
  if (e.repeat) {
    if (e.code === 'Space') e.preventDefault();
    return; // a held Space / P would toggle pause on and off
  }
  switch (e.code) {
    case 'Space': // pauses a person's round; elsewhere starts one
      e.preventDefault();
      if (mode === 'paused') resume();
      else if (mode === 'play') pause();
      else steer(RIGHT);
      break;
    case 'KeyP': // pauses anything that moves, the demo too
      if (mode === 'paused') resume();
      else pause();
      break;
    case 'Escape':
      pause();
      break;
    case 'Enter':
    case 'NumpadEnter':
      if (mode === 'paused') resume();
      else if (mode !== 'play') steer(RIGHT);
      break;
  }
});

// Swipes: once a press has moved far enough, its main axis is a direction;
// the press can keep going and turn again (the start point follows).
window.addEventListener('pointerdown', (e) => {
  if (!e.isPrimary || e.button > 0) return;
  if (e.target instanceof Element && e.target.closest('button')) return;
  press = { id: e.pointerId, x: e.clientX, y: e.clientY, swiped: false };
});
window.addEventListener('pointermove', (e) => {
  if (!press || e.pointerId !== press.id) return;
  const dx = e.clientX - press.x;
  const dy = e.clientY - press.y;
  const min = Math.max(14, renderer.cell * 0.6);
  if (Math.max(Math.abs(dx), Math.abs(dy)) < min) return;
  steer(Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? LEFT : RIGHT) : dy < 0 ? UP : DOWN);
  press.x = e.clientX;
  press.y = e.clientY;
  press.swiped = true;
});
window.addEventListener('pointerup', (e) => {
  if (!press || e.pointerId !== press.id) return;
  if (!press.swiped) tap(e.clientX, e.clientY);
  press = null;
});
window.addEventListener('pointercancel', () => (press = null));

pauseButton.addEventListener('click', () => {
  if (mode === 'paused') resume();
  else pause();
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    if (mode === 'play') pause();
  } else {
    wake();
  }
});
window.addEventListener('blur', () => {
  if (mode === 'play') pause();
});

let resizeQueued = false;
window.addEventListener('resize', () => {
  if (resizeQueued) return;
  resizeQueued = true;
  requestAnimationFrame(() => {
    resizeQueued = false;
    measure();
    // A person's round (also one the autopilot took over) keeps its board,
    // rescaled; otherwise a board that no longer suits the viewport is
    // replaced.
    const replaceable = (mode === 'demo' && !handedOver) || mode === 'demo-end' || mode === 'idle';
    if (replaceable && gridIsStale()) rest();
    else fit(false);
    wake();
  });
});

if (motionQuery) {
  const onMotion = (e) => {
    reduced = e.matches;
    renderer.reduced = reduced;
    const demo = mode === 'demo' || mode === 'demo-end' || (mode === 'paused' && pausedFrom === 'demo');
    if (reduced && demo) startIdle();
    else if (!reduced && mode === 'idle') startDemo();
  };
  if (motionQuery.addEventListener) motionQuery.addEventListener('change', onMotion);
  else if (motionQuery.addListener) motionQuery.addListener(onMotion);
}

// ── HUD ─────────────────────────────────────────────────────────────────

function updateScore() {
  scoreValue.textContent = String(game ? game.eaten : 0);
  bestValue.textContent = String(best);
}

const HOW_TO = coarse ? 'swipe or tap to play' : 'arrow keys, WASD or click to play';

function overText() {
  const again = coarse ? 'tap to play again' : 'press a key or click to play again';
  return `Game over · ${game.eaten}${newBest ? ' · new best!' : ''} — ${again}`;
}

function updateHud() {
  updateScore();
  const demo = mode === 'demo' || mode === 'demo-end';
  scoreLabel.textContent = demo || (mode === 'paused' && pausedFrom === 'demo') ? 'demo' : 'score';
  pauseButton.setAttribute('aria-label', mode === 'paused' ? 'Resume' : 'Pause');
  pauseButton.setAttribute('aria-pressed', mode === 'paused' ? 'true' : 'false');
  switch (mode) {
    case 'demo':
    case 'demo-end':
    case 'idle':
      hint.textContent = handedOver ? 'Autopilot — ' + HOW_TO : HOW_TO[0].toUpperCase() + HOW_TO.slice(1);
      break;
    case 'paused':
      hint.textContent = coarse ? 'Paused — tap to go on' : 'Paused — press Space or click to go on';
      break;
    case 'play':
      hint.textContent = '';
      break;
    // 'over': set by ended()
  }
}

function loadBest() {
  try {
    return Math.max(0, parseInt(localStorage.getItem(BEST_KEY) || '0', 10) || 0);
  } catch {
    return 0;
  }
}

function saveBest(v) {
  try {
    localStorage.setItem(BEST_KEY, String(v));
  } catch {
    // storage blocked (private mode etc.): best only lasts this visit
  }
}

// ── Start ───────────────────────────────────────────────────────────────

rest();
