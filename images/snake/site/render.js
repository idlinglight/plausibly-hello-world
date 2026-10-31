// render.js: draws the board, the snake and the fruit (canvas 2D).
//
// Everything is drawn in cell units (1 = one cell, cell (x, y) spans x..x+1)
// through the canvas transform. The board is a torus, so anything that
// pokes out over an edge is drawn again, shifted by the board size, and the
// clip to the board cuts both copies: the snake slides out of one side and
// in at the other.
//
// Movement is smooth although the game moves in whole cells. The body is
// drawn along its path: head tip, every cell centre behind it, tail end.
// Between two steps only the tip and the tail end move (`alpha` of the way);
// corners stay put. Colour and swallowed-fruit bulges are laid out by
// distance from the tip, so they glide along with the head. (Moving every
// segment part of the way instead cuts each corner short mid-step: the
// corners flicker at the step rate.)
//
// Growth: in the rules the tail stays put for one step. Drawn like that it
// stops dead and reads as a hitch, so the drawn tail end eases instead: it
// starts slowing GROW_LEAD steps early (growth is known in advance) and
// never drops below half speed. Meanwhile it reaches back into the cell the
// tail just left, so the drawn snake is never shorter than the cells it
// holds (nothing to run into that isn't drawn).
//
// Death: the head bumps into what it hit, a burst marks the spot, and a ring
// stays around the hit cell while the snake fades to grey.

import { DX, DY, MEAL_SPEED } from './game.js';

const C = {
  board: '#133229',
  boardAlt: '#15362d',
  boardMid: [20, 52, 43], // between the two, for fading things into the board
  edge: 'rgba(210, 255, 232, 0.07)',
  shadow: 'rgba(0, 10, 6, 0.28)',
  head: [158, 245, 194],
  neck: [111, 227, 168],
  tail: [36, 158, 138],
  sheen: 'rgba(235, 255, 244, 0.09)',
  dead: [120, 150, 138],
  crash: '#ff7a6b',
  crashRgb: '255, 122, 107',
  eye: '#f4fff9',
  pupil: '#0b1d18',
  tongue: '#ff7a93',
  fruit: '#ffb454',
  fruitLight: '#ffe2a8',
  fruitGlow: '255, 180, 84',
  leaf: '#7fe8ae',
};

const BODY_W = 0.66; // snake thickness, in cells
const HEAD_R = 0.42;
const SHEEN_W = 0.2; // a lighter line down the back
const BAND_LEN = 1; // cells of body per colour step …
const FADE_LEN = 24; // … from the neck colour to the tail colour over this length
const TAPER_LEN = 2.5; // the last cells of body get thinner …
const TAPER_MIN = 0.5; // … down to this much of BODY_W
const TAPER_STEPS = 10;
const LUMP = 1.32; // a meal on its way down: a bulge this much thicker than the body …
const LUMP_MERGE = 1.2; // … flattening into the tail over its last this-many cells
const GROW_LEAD = 2; // steps before a growth step that the tail starts easing
const EYE_MS = 45; // the eyes turn with the head over roughly this long
const RING_MS = 480;
const POP_MS = 280; // new fruit grows in
const BUMP = 0.36; // death: the head pushes this far into what it hit …
const BUMP_MS = 110; // … over this long
const BURST_MS = 520;
const DEATH_FLASH_MS = 600;
const DEATH_FADE_MS = 700;

const mix = (a, b, t) => [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * t));
const rgb = (c, k = 1) => `rgb(${Math.round(c[0] * k)}, ${Math.round(c[1] * k)}, ${Math.round(c[2] * k)})`;

export class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.bg = document.createElement('canvas'); // the board, redrawn on resize only
    this.dpr = 1;
    this.cell = 20;
    this.ox = 0;
    this.oy = 0;
    this.cols = 1;
    this.rows = 1;
    this.bodyColors = [];
    this.rings = []; // { x, y, t0 }: eat effect
    this.fruitBorn = -Infinity;
    this.deathAt = -1;
    this.reduced = false;
    this.eyeAngle = null;
    this.lastDraw = 0;
    this.growSoon = []; // scratch for game.upcomingGrowth()
    // Last frame, for tests: body length drawn (cells), and how far the tip
    // has come (game.steps + alpha). Tail end speed = 1 - dLength / dTip.
    this.lengthDrawn = 0;
    this.tipDrawn = 0;
    // Centre line of the body (x/y pairs), per-segment vectors, and the
    // distance from the tip at each point. Reused between frames.
    this.pts = new Float64Array(0);
    this.dlt = new Float64Array(0);
    this.acc = new Float64Array(0);
    this.offs = new Float64Array(8); // copies(): up to 4 offset pairs
  }

  // Places a cols x rows board centred in `area` (CSS px: x, y, w, h) on a
  // canvas of `view` (w, h, dpr), then redraws the cached board.
  layout(view, area, cols, rows) {
    const dpr = Math.min(view.dpr || 1, 2);
    const cell = Math.max(4, Math.floor(Math.min(area.w / cols, area.h / rows)));
    this.dpr = dpr;
    this.cell = cell;
    this.cols = cols;
    this.rows = rows;
    this.ox = Math.round(area.x + (area.w - cols * cell) / 2);
    this.oy = Math.round(area.y + (area.h - rows * cell) / 2);
    const w = Math.max(1, Math.round(view.w * dpr));
    const h = Math.max(1, Math.round(view.h * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.bg.width = w;
    this.bg.height = h;
    this.drawBoard();
  }

  // Board-relative CSS px -> cell coordinates (fractional).
  toCell(x, y) {
    return { x: (x - this.ox) / this.cell, y: (y - this.oy) / this.cell };
  }

  boardPath(ctx) {
    ctx.beginPath();
    const r = Math.min(0.45, this.cols / 4, this.rows / 4);
    if (ctx.roundRect) ctx.roundRect(0, 0, this.cols, this.rows, r);
    else ctx.rect(0, 0, this.cols, this.rows);
  }

  toBoard(ctx) {
    const k = this.dpr * this.cell;
    ctx.setTransform(k, 0, 0, k, this.dpr * this.ox, this.dpr * this.oy);
  }

  drawBoard() {
    const ctx = this.bg.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.bg.width, this.bg.height);
    this.toBoard(ctx);
    ctx.save();
    ctx.shadowColor = 'rgba(0, 0, 0, 0.35)';
    ctx.shadowBlur = 24 * this.dpr;
    ctx.shadowOffsetY = 6 * this.dpr;
    this.boardPath(ctx);
    ctx.fillStyle = C.board;
    ctx.fill();
    ctx.restore();
    ctx.save();
    this.boardPath(ctx);
    ctx.clip();
    ctx.fillStyle = C.boardAlt;
    for (let y = 0; y < this.rows; y++) {
      for (let x = (y & 1); x < this.cols; x += 2) ctx.fillRect(x, y, 1, 1);
    }
    ctx.restore();
    this.boardPath(ctx);
    ctx.lineWidth = 2 / this.cell;
    ctx.strokeStyle = C.edge;
    ctx.stroke();
  }

  // Events from the game loop.
  newRound(now) {
    this.rings.length = 0;
    this.deathAt = -1;
    this.fruitBorn = now;
    this.eyeAngle = null;
  }

  ate(cell, now) {
    if (!this.reduced) this.rings.push({ x: cell % this.cols, y: Math.floor(cell / this.cols), t0: now });
    this.fruitBorn = now;
  }

  died(now) {
    this.deathAt = now;
  }

  // Still animating something on its own (effects, death), so the loop
  // should keep drawing even while the game stands still?
  busy(now) {
    if (this.rings.length) return true;
    if (now - this.fruitBorn < POP_MS) return true;
    return this.deathAt >= 0 && now - this.deathAt < Math.max(DEATH_FLASH_MS + DEATH_FADE_MS, BURST_MS);
  }

  // The whole frame. alpha: 0..1 of the way from the previous step to the
  // current one. tongue: 0..1 while the tongue is out, else 0.
  draw(game, alpha, now, tongue) {
    const ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = 'copy';
    ctx.drawImage(this.bg, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    this.toBoard(ctx);
    ctx.save();
    this.boardPath(ctx);
    ctx.clip();
    this.drawFruit(ctx, game, now);
    this.drawRings(ctx, now);
    this.drawSnake(ctx, game, alpha, now, tongue);
    ctx.restore();
  }

  drawFruit(ctx, game, now) {
    if (game.fruit < 0) return;
    const x = (game.fruit % this.cols) + 0.5;
    const y = Math.floor(game.fruit / this.cols) + 0.5;
    let s = Math.min(1, (now - this.fruitBorn) / POP_MS);
    s = s < 1 ? 1 + 2.7 * Math.pow(s - 1, 3) + 1.7 * Math.pow(s - 1, 2) : 1; // ease-out-back
    if (!this.reduced) s *= 1 + 0.05 * Math.sin(now * 0.004);
    if (s <= 0) return;
    const glow = ctx.createRadialGradient(x, y, 0, x, y, 0.95 * s);
    glow.addColorStop(0, `rgba(${C.fruitGlow}, 0.34)`);
    glow.addColorStop(1, `rgba(${C.fruitGlow}, 0)`);
    ctx.fillStyle = glow;
    ctx.fillRect(x - 1, y - 1, 2, 2);
    ctx.beginPath();
    ctx.arc(x, y + 0.03, 0.3 * s, 0, Math.PI * 2);
    ctx.fillStyle = C.fruit;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(x - 0.1 * s, y - 0.07 * s, 0.09 * s, 0, Math.PI * 2);
    ctx.fillStyle = C.fruitLight;
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(x + 0.12 * s, y - 0.3 * s, 0.13 * s, 0.06 * s, -0.6, 0, Math.PI * 2);
    ctx.fillStyle = C.leaf;
    ctx.fill();
  }

  drawRings(ctx, now) {
    this.rings = this.rings.filter((r) => now - r.t0 < RING_MS);
    for (const r of this.rings) {
      const t = (now - r.t0) / RING_MS;
      const e = 1 - Math.pow(1 - t, 3);
      ctx.beginPath();
      ctx.arc(r.x + 0.5, r.y + 0.5, 0.3 + 1.1 * e, 0, Math.PI * 2);
      ctx.lineWidth = 0.14 * (1 - t);
      ctx.strokeStyle = `rgba(${C.fruitGlow}, ${0.8 * (1 - t)})`;
      ctx.stroke();
    }
  }

  // Body colour of step b (BAND_LEN cells each, counted from the tip). A
  // dead snake is grey, faded towards the board by `fade` (1: not at all) —
  // opaque colours, as translucent strokes would show darker spots wherever
  // two of them overlap.
  bodyColor(b, grey, fade) {
    if (grey) return rgb(mix(C.dead, C.boardMid, 1 - fade));
    if (!this.bodyColors[b]) {
      this.bodyColors[b] = rgb(mix(C.neck, C.tail, Math.min(1, (b * BAND_LEN) / FADE_LEN)));
    }
    return this.bodyColors[b];
  }

  // The copies of a shape spanning [x0, x1] x [y0, y1] needed to show it
  // on the torus: (0, 0), plus shifted ones where it pokes out over an edge.
  // Writes the offsets to this.offs as x/y pairs; returns how many. (No
  // arrays or callbacks per call: this runs for every segment, every frame.)
  copies(x0, x1, y0, y1) {
    const { cols, rows, offs } = this;
    const sx = x0 < 0 ? cols : x1 > cols ? -cols : 0;
    const sy = y0 < 0 ? rows : y1 > rows ? -rows : 0;
    let k = 0;
    for (let a = 0; a < (sx ? 2 : 1); a++) {
      for (let b = 0; b < (sy ? 2 : 1); b++) {
        offs[k++] = a * sx;
        offs[k++] = b * sy;
      }
    }
    return k / 2;
  }

  // Adds a circle of radius r at (x, y), with its torus copies, to the path.
  addCircle(ctx, x, y, r) {
    const offs = this.offs;
    const m = this.copies(x - r, x + r, y - r, y + r);
    for (let k = 0; k < m; k++) {
      ctx.moveTo(x + offs[k * 2] + r, y + offs[k * 2 + 1]);
      ctx.arc(x + offs[k * 2], y + offs[k * 2 + 1], r, 0, Math.PI * 2);
    }
  }

  drawSnake(ctx, game, alpha, now, tongue) {
    const { cols, rows, offs } = this;
    const cells = game.cells;
    const n = cells.length;
    if (!n) return;
    const dead = !game.alive;
    if (dead || game.steps === 0) alpha = 1;
    const dt = Math.min(100, Math.max(0, now - this.lastDraw));
    this.lastDraw = now;

    // Death: bump into what was hit; flash a few times, then fade to grey.
    let bump = 0;
    let fade = 1;
    let flashOff = false;
    if (dead && this.deathAt >= 0) {
      const t = now - this.deathAt;
      const b = this.reduced ? 1 : Math.min(1, t / BUMP_MS);
      if (game.crash >= 0) bump = BUMP * (1 - (1 - b) * (1 - b));
      if (t < DEATH_FLASH_MS) flashOff = !this.reduced && Math.floor(t / 150) % 2 === 1;
      else fade = 1 - 0.6 * Math.min(1, (t - DEATH_FLASH_MS) / DEATH_FADE_MS);
    }
    const grey = dead && (flashOff || fade < 1);

    // Centre line, head to tail (see the top of this file).
    // Points at most: tip (+1 when bumping), the n - 1 cells behind it, the
    // tail end, up to 3 vacated cells. Typed arrays drop writes past their
    // end silently, so size by points, with room to grow.
    const most = n + 5;
    if (this.acc.length < most) {
      const cap = most * 2;
      this.pts = new Float64Array(cap * 2);
      this.dlt = new Float64Array(cap * 2);
      this.acc = new Float64Array(cap);
    }
    const P = this.pts;
    const D = this.dlt;
    const A = this.acc;
    let m = 0;
    const put = (x, y) => {
      if (x < 0) x += cols;
      else if (x >= cols) x -= cols;
      if (y < 0) y += rows;
      else if (y >= rows) y -= rows;
      P[m * 2] = x;
      P[m * 2 + 1] = y;
      m++;
    };
    const cx = (c) => (c % cols) + 0.5;
    const cy = (c) => Math.floor(c / cols) + 0.5;
    // The single-cell step from cell a to the neighbouring cell b, across
    // an edge if need be: each component -1, 0 or 1.
    const stepX = (a, b) => {
      const d = (b % cols) - (a % cols);
      return d > 1 ? d - cols : d < -1 ? d + cols : d;
    };
    const stepY = (a, b) => {
      const d = Math.floor(b / cols) - Math.floor(a / cols);
      return d > 1 ? d - rows : d < -1 ? d + rows : d;
    };
    const head = cells[0];
    if (bump > 0) {
      put(cx(head) + DX[game.dir] * bump, cy(head) + DY[game.dir] * bump);
      put(cx(head), cy(head));
    } else {
      const prev = n > 1 ? cells[1] : game.prevTail;
      put(cx(prev) + stepX(prev, head) * alpha, cy(prev) + stepY(prev, head) * alpha);
    }
    for (let i = 1; i < n; i++) put(cx(cells[i]), cy(cells[i]));
    // Growth easing (top of file): how far the drawn tail reaches back
    // beyond the real tail end, and the cells behind it to reach into.
    let reach = 0;
    if (n > 1) {
      const last = cells[n - 1];
      const gone = game.prevTail;
      put(cx(gone) + stepX(gone, last) * alpha, cy(gone) + stepY(gone, last) * alpha);
    }
    const tailIdx = m - 1;
    if (n > 1 && !dead) {
      const u = game.steps + alpha;
      const ease = (k) => {
        const v = u - k; // growth step k shows during u in [k, k + 1)
        if (v < -GROW_LEAD || v >= 1) return 0;
        const x = (v + GROW_LEAD) / (GROW_LEAD + 1);
        return x * x * (3 - 2 * x) - Math.min(1, Math.max(0, v));
      };
      for (const k of game.grewAt) reach += ease(k);
      for (const k of game.upcomingGrowth(GROW_LEAD + 1, this.growSoon)) reach += ease(k);
      if (reach > 0) {
        for (const c of game.vacated) {
          if (game.occ[c]) break; // the snake is back in it: stop short
          put(cx(c), cy(c));
        }
      }
    }
    A[0] = 0;
    for (let k = 0; k < m - 1; k++) {
      let dx = P[k * 2 + 2] - P[k * 2];
      let dy = P[k * 2 + 3] - P[k * 2 + 1];
      if (dx > cols / 2) dx -= cols;
      else if (dx < -cols / 2) dx += cols;
      if (dy > rows / 2) dy -= rows;
      else if (dy < -rows / 2) dy += rows;
      D[k * 2] = dx;
      D[k * 2 + 1] = dy;
      A[k + 1] = A[k] + Math.hypot(dx, dy);
    }
    const total = Math.min(A[m - 1], A[tailIdx] + reach);
    this.lengthDrawn = total;
    this.tipDrawn = game.steps + alpha;

    // Adds the stretch of body from distance s0 to s1 (from the tip) to the
    // path, as straight pieces (round caps join them), with torus copies.
    const addRange = (s0, s1, r) => {
      if (s1 <= s0 || m < 2) return;
      let lo = 0;
      let hi = m - 2;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (A[mid + 1] <= s0) lo = mid + 1;
        else hi = mid;
      }
      for (let k = lo; k < m - 1 && A[k] < s1; k++) {
        const len = A[k + 1] - A[k];
        if (len <= 0) continue;
        const t0 = Math.max(0, (s0 - A[k]) / len);
        const t1 = Math.min(1, (s1 - A[k]) / len);
        if (t1 <= t0) continue;
        const x0 = P[k * 2] + D[k * 2] * t0;
        const y0 = P[k * 2 + 1] + D[k * 2 + 1] * t0;
        const x1 = P[k * 2] + D[k * 2] * t1;
        const y1 = P[k * 2 + 1] + D[k * 2 + 1] * t1;
        const c = this.copies(Math.min(x0, x1) - r, Math.max(x0, x1) + r, Math.min(y0, y1) - r, Math.max(y0, y1) + r);
        for (let j = 0; j < c; j++) {
          ctx.moveTo(x0 + offs[j * 2], y0 + offs[j * 2 + 1]);
          ctx.lineTo(x1 + offs[j * 2], y1 + offs[j * 2 + 1]);
        }
      }
    };
    // The point at distance s from the tip, into px, py.
    let px = P[0];
    let py = P[1];
    const pointAt = (s) => {
      let k = 0;
      while (k < m - 2 && A[k + 1] < s) k++;
      const len = A[k + 1] - A[k];
      const t = len > 0 ? Math.min(1, Math.max(0, (s - A[k]) / len)) : 0;
      px = P[k * 2] + D[k * 2] * t;
      py = P[k * 2 + 1] + D[k * 2 + 1] * t;
    };
    const taperStart = Math.max(0, total - TAPER_LEN);
    const tl = total - taperStart;
    const widthAt = (s) => (s <= taperStart || tl <= 0 ? 1 : 1 - ((1 - TAPER_MIN) * (s - taperStart)) / tl);
    const bands = Math.ceil(FADE_LEN / BAND_LEN);
    const colorAt = (s) => this.bodyColor(Math.min(bands, Math.floor(s / BAND_LEN)), grey, fade);

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Soft shadow under the whole body, one path.
    if (m > 1) {
      ctx.save();
      ctx.translate(0.06, 0.12);
      ctx.beginPath();
      addRange(0, total, BODY_W / 2);
      ctx.lineWidth = BODY_W * 0.92;
      ctx.strokeStyle = C.shadow;
      ctx.globalAlpha = fade;
      ctx.stroke();
      ctx.restore();
    }

    // Body: colour steps from the tip; past FADE_LEN one colour; the tail
    // end tapers.
    for (let b = 0, s0 = 0; s0 < taperStart; b++, s0 += BAND_LEN) {
      const s1 = b >= bands ? taperStart : Math.min(taperStart, s0 + BAND_LEN);
      ctx.beginPath();
      addRange(s0, s1, BODY_W / 2);
      ctx.lineWidth = BODY_W;
      ctx.strokeStyle = this.bodyColor(b, grey, fade);
      ctx.stroke();
      if (s1 >= taperStart) break;
    }
    for (let j = 0; j < TAPER_STEPS && tl > 0; j++) {
      const s0 = taperStart + (tl * j) / TAPER_STEPS;
      const s1 = taperStart + (tl * (j + 1)) / TAPER_STEPS;
      const w = BODY_W * widthAt((s0 + s1) / 2);
      ctx.beginPath();
      addRange(s0, s1, w / 2);
      ctx.lineWidth = w;
      ctx.strokeStyle = colorAt(s0);
      ctx.stroke();
    }

    // A lighter line down the back, one path.
    if (taperStart > 0.5) {
      ctx.beginPath();
      addRange(0.2, taperStart + tl * 0.4, SHEEN_W / 2);
      ctx.lineWidth = SHEEN_W;
      ctx.strokeStyle = grey ? `rgba(235, 255, 244, ${0.05 * fade})` : C.sheen;
      ctx.stroke();
    }

    // Meals (game.js): a bulge sliding down the body (l: distance from the
    // tip), swelling in just behind the head and flattening into the tail
    // end as the snake grows. Nearly full size in the taper until then, so
    // the arrival shows. Drawn with reduced motion too: it's game state.
    for (const at of game.meals) {
      const l = (game.steps + alpha - at) * MEAL_SPEED;
      if (l <= 0.2 || l >= total) continue;
      pointAt(l);
      const body = (BODY_W / 2) * widthAt(l);
      const full = (BODY_W / 2) * (0.75 + 0.25 * widthAt(l)) * LUMP;
      const r = body + (full - body) * Math.min(1, l / 1.5) * Math.min(1, (total - l) / LUMP_MERGE);
      ctx.beginPath();
      this.addCircle(ctx, px, py, r);
      ctx.fillStyle = colorAt(l);
      ctx.fill();
    }

    // Death: a ring around the cell the head ran into, kept while the round
    // is over, so it's clear what ended it.
    if (dead && game.crash >= 0) {
      ctx.beginPath();
      this.addCircle(ctx, cx(game.crash), cy(game.crash), 0.5);
      ctx.lineWidth = 0.08;
      ctx.strokeStyle = C.crash;
      ctx.stroke();
    }

    // Head, eyes, tongue. The eyes follow the heading, turning briefly.
    const hx = P[0];
    const hy = P[1];
    const target = Math.atan2(DY[game.dir], DX[game.dir]);
    if (this.eyeAngle === null || dead || this.reduced) {
      this.eyeAngle = target;
    } else {
      let d = target - this.eyeAngle;
      while (d > Math.PI) d -= 2 * Math.PI;
      while (d < -Math.PI) d += 2 * Math.PI;
      this.eyeAngle += d * (1 - Math.exp(-dt / EYE_MS));
    }
    const vx = Math.cos(this.eyeAngle);
    const vy = Math.sin(this.eyeAngle);
    // A dead head fades less than the body: it should stay easy to find.
    const headFade = Math.max(fade, 0.85);
    const headColor = grey ? rgb(mix(C.dead.map((v) => v * 1.2), C.boardMid, 1 - headFade)) : rgb(C.head);
    const pupilColor = grey ? rgb(mix([11, 29, 24], C.boardMid, 1 - headFade)) : C.pupil;
    const heads = this.copies(hx - 0.9, hx + 0.9, hy - 0.9, hy + 0.9);
    for (let k = 0; k < heads; k++) {
      const x = hx + offs[k * 2];
      const y = hy + offs[k * 2 + 1];
      if (tongue > 0 && !dead) {
        const out = Math.sin(Math.PI * tongue) * 0.36;
        const tx = x + vx * (HEAD_R + out);
        const ty = y + vy * (HEAD_R + out);
        ctx.beginPath();
        ctx.moveTo(x + vx * HEAD_R * 0.8, y + vy * HEAD_R * 0.8);
        ctx.lineTo(tx, ty);
        ctx.lineTo(tx + (vx - vy) * 0.1, ty + (vy + vx) * 0.1);
        ctx.moveTo(tx, ty);
        ctx.lineTo(tx + (vx + vy) * 0.1, ty + (vy - vx) * 0.1);
        ctx.lineWidth = 0.055;
        ctx.strokeStyle = C.tongue;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(x, y, HEAD_R, 0, Math.PI * 2);
      ctx.fillStyle = headColor;
      ctx.fill();
      // Eyes: either side of the heading, a little forward.
      for (let side = -1; side <= 1; side += 2) {
        const ex = x + vx * 0.13 - vy * 0.2 * side;
        const ey = y + vy * 0.13 + vx * 0.2 * side;
        if (dead) {
          ctx.beginPath();
          const e = 0.07;
          ctx.moveTo(ex - e, ey - e);
          ctx.lineTo(ex + e, ey + e);
          ctx.moveTo(ex + e, ey - e);
          ctx.lineTo(ex - e, ey + e);
          ctx.lineWidth = 0.05;
          ctx.strokeStyle = pupilColor;
          ctx.stroke();
          continue;
        }
        ctx.beginPath();
        ctx.arc(ex, ey, 0.105, 0, Math.PI * 2);
        ctx.fillStyle = C.eye;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(ex + vx * 0.04, ey + vy * 0.04, 0.058, 0, Math.PI * 2);
        ctx.fillStyle = C.pupil;
        ctx.fill();
      }
    }

    // Death: a burst where the head hit, on top of everything.
    if (dead && game.crash >= 0 && !this.reduced && this.deathAt >= 0) {
      const t = (now - this.deathAt) / BURST_MS;
      if (t < 1) {
        const x = cx(head) + DX[game.dir] * 0.5;
        const y = cy(head) + DY[game.dir] * 0.5;
        const e = 1 - Math.pow(1 - t, 3);
        ctx.beginPath();
        this.addCircle(ctx, x, y, 0.2 + 0.8 * e);
        const r0 = 0.3 + 0.55 * e;
        const r1 = r0 + 0.28 * (1 - t);
        const c = this.copies(x - r1, x + r1, y - r1, y + r1);
        for (let j = 0; j < c; j++) {
          for (let a = 0; a < 6; a++) {
            const ang = (a * Math.PI) / 3 + 0.5;
            const ux = Math.cos(ang);
            const uy = Math.sin(ang);
            ctx.moveTo(x + offs[j * 2] + ux * r0, y + offs[j * 2 + 1] + uy * r0);
            ctx.lineTo(x + offs[j * 2] + ux * r1, y + offs[j * 2 + 1] + uy * r1);
          }
        }
        ctx.lineWidth = 0.1 * (1 - t) + 0.02;
        ctx.strokeStyle = `rgba(${C.crashRgb}, ${1 - t})`;
        ctx.stroke();
      }
    }
  }
}
