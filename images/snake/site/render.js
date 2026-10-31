// render.js: draws the board, the snake and the fruit (canvas 2D).
//
// Everything is drawn in cell units (1 = one cell, cell (x, y) spans x..x+1)
// through the canvas transform. The board is a torus, so anything that
// pokes out over an edge is drawn again, shifted by the board size, and the
// clip to the board cuts both copies: the snake slides out of one side and
// in at the other.
//
// Movement is smooth although the game moves in whole cells: between two
// steps every segment is drawn part of the way (`alpha`) from where it was
// to where it is now.

import { DX, DY } from './game.js';

const C = {
  board: '#133229',
  boardAlt: '#15362d',
  boardMid: [20, 52, 43], // between the two, for fading things into the board
  edge: 'rgba(210, 255, 232, 0.07)',
  shadow: 'rgba(0, 10, 6, 0.28)',
  head: [158, 245, 194],
  neck: [111, 227, 168],
  tail: [36, 158, 138],
  stripe: 0.84, // stripe bands: this much of the colour's brightness
  dead: [120, 150, 138],
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
const BAND = 3; // segments per stripe band
const FADE_BANDS = 10; // bands over which the colour goes from neck to tail
const TAPER = 5; // segments over which the tail gets thinner
const LUMP_SPEED = 1.6; // a swallowed fruit moves down the body this many segments per step
const LUMP = 1.32; // … as a bulge this much thicker than the body
const RING_MS = 480;
const POP_MS = 280; // new fruit grows in
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
    this.bandColors = [];
    this.rings = []; // { x, y, t0 }: eat effect
    this.lumps = []; // game.steps at which a fruit was swallowed
    this.fruitBorn = -Infinity;
    this.deathAt = -1;
    this.reduced = false;
    this.pos = new Float32Array(0); // segment positions, x/y pairs
    this.offs = [];
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
    this.lumps.length = 0;
    this.deathAt = -1;
    this.fruitBorn = now;
  }

  ate(game, cell, now) {
    if (!this.reduced) {
      this.rings.push({ x: cell % this.cols, y: Math.floor(cell / this.cols), t0: now });
      this.lumps.push(game.steps);
    }
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
    return this.deathAt >= 0 && now - this.deathAt < DEATH_FLASH_MS + DEATH_FADE_MS;
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

  // Colour of stripe band b (a band is BAND segments, counted from the
  // head). A dead snake is grey, faded towards the board by `fade` (1: not
  // at all) — opaque colours, as translucent strokes would show darker
  // spots wherever two of them overlap.
  bandColor(b, dead, fade = 1) {
    if (dead) return rgb(mix(C.dead.map((v) => v * (b % 2 ? C.stripe : 1)), C.boardMid, 1 - fade));
    if (!this.bandColors[b]) {
      this.bandColors[b] = rgb(mix(C.neck, C.tail, Math.min(1, b / FADE_BANDS)), b % 2 ? C.stripe : 1);
    }
    return this.bandColors[b];
  }

  // Calls fn(dx, dy) for each copy of a shape spanning [x0, x1] x [y0, y1]
  // that is needed to show it on the torus: (0, 0), plus shifted copies
  // where it pokes out over an edge.
  copies(x0, x1, y0, y1, fn) {
    const { cols, rows } = this;
    const xs = x0 < 0 ? [0, cols] : x1 > cols ? [0, -cols] : [0];
    const ys = y0 < 0 ? [0, rows] : y1 > rows ? [0, -rows] : [0];
    for (const dx of xs) for (const dy of ys) fn(dx, dy);
  }

  drawSnake(ctx, game, alpha, now, tongue) {
    const { cols, rows } = this;
    const cells = game.cells;
    const n = cells.length;
    if (!n) return;
    const dead = !game.alive;
    if (dead || game.steps === 0) alpha = 1;

    // Segment centres, interpolated, in [0, cols) x [0, rows).
    if (this.pos.length < n * 2) this.pos = new Float32Array(n * 4);
    const pos = this.pos;
    for (let i = 0; i < n; i++) {
      const cur = cells[i];
      const prev = i < n - 1 ? cells[i + 1] : game.prevTail;
      const cx = cur % cols;
      const cy = (cur - cx) / cols;
      const px = prev % cols;
      const py = (prev - px) / cols;
      let dx = cx - px;
      let dy = cy - py;
      if (dx > 1) dx -= cols;
      else if (dx < -1) dx += cols;
      if (dy > 1) dy -= rows;
      else if (dy < -1) dy += rows;
      let x = px + dx * alpha + 0.5;
      let y = py + dy * alpha + 0.5;
      if (x < 0) x += cols;
      else if (x >= cols) x -= cols;
      if (y < 0) y += rows;
      else if (y >= rows) y -= rows;
      pos[i * 2] = x;
      pos[i * 2 + 1] = y;
    }

    // Wrapped vector from segment i + 1 to segment i.
    const seg = (i) => {
      let dx = pos[i * 2] - pos[i * 2 + 2];
      let dy = pos[i * 2 + 1] - pos[i * 2 + 3];
      if (dx > cols / 2) dx -= cols;
      else if (dx < -cols / 2) dx += cols;
      if (dy > rows / 2) dy -= rows;
      else if (dy < -rows / 2) dy += rows;
      return [dx, dy];
    };
    const addSeg = (i, r) => {
      const ax = pos[i * 2 + 2];
      const ay = pos[i * 2 + 3];
      const [dx, dy] = seg(i);
      const bx = ax + dx;
      const by = ay + dy;
      this.copies(Math.min(ax, bx) - r, Math.max(ax, bx) + r, Math.min(ay, by) - r, Math.max(ay, by) + r, (ox, oy) => {
        ctx.moveTo(ax + ox, ay + oy);
        ctx.lineTo(bx + ox, by + oy);
      });
    };

    // Death: flash a few times, then fade to a dim, grey snake.
    let fade = 1;
    let flashOff = false;
    if (dead && this.deathAt >= 0) {
      const t = now - this.deathAt;
      if (t < DEATH_FLASH_MS) flashOff = !this.reduced && Math.floor(t / 150) % 2 === 1;
      else fade = 1 - 0.6 * Math.min(1, (t - DEATH_FLASH_MS) / DEATH_FADE_MS);
    }
    const grey = dead && (flashOff || fade < 1);
    const tint = (c) => (grey ? rgb(mix(c, C.boardMid, 1 - fade)) : rgb(c));
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Soft shadow under the whole body, one path.
    if (n > 1) {
      ctx.save();
      ctx.translate(0.06, 0.12);
      ctx.beginPath();
      for (let i = n - 2; i >= 0; i--) addSeg(i, BODY_W);
      ctx.lineWidth = BODY_W;
      ctx.strokeStyle = C.shadow;
      ctx.globalAlpha = fade;
      ctx.stroke();
      ctx.restore();
    }

    // Body, tail first so each band's round end overlaps the next one
    // towards the tail (reads as scales). Consecutive segments with the same
    // colour and width share one stroke.
    const taper = (i) => Math.min(1, 0.45 + (0.55 * (n - 1.5 - i)) / TAPER);
    let style = '';
    let width = 0;
    const flush = () => {
      if (!style) return;
      ctx.lineWidth = width;
      ctx.strokeStyle = style;
      ctx.stroke();
    };
    for (let i = n - 2; i >= 0; i--) {
      const w = BODY_W * taper(i);
      const s = this.bandColor(Math.floor(i / BAND), grey, fade);
      if (s !== style || w !== width) {
        flush();
        ctx.beginPath();
        style = s;
        width = w;
      }
      addSeg(i, w);
    }
    flush();

    // Swallowed fruit: a bulge sliding down the body (l: segments from the
    // head, fractional), swelling in just behind the head.
    const lumps = this.lumps;
    while (lumps.length && (game.steps + alpha - lumps[0]) * LUMP_SPEED > n) lumps.shift();
    for (const at of lumps) {
      const l = (game.steps + alpha - at) * LUMP_SPEED;
      if (l <= 0 || l >= n - 1) continue;
      const i = Math.floor(l);
      const [dx, dy] = seg(i);
      const x = pos[i * 2] - dx * (l - i);
      const y = pos[i * 2 + 1] - dy * (l - i);
      const r = (BODY_W / 2) * taper(l) * (1 + (LUMP - 1) * Math.min(1, l / 1.5));
      ctx.fillStyle = this.bandColor(Math.floor(l / BAND), grey, fade);
      this.copies(x - r, x + r, y - r, y + r, (ox, oy) => {
        ctx.beginPath();
        ctx.arc(x + ox, y + oy, r, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    // Head, eyes, tongue.
    const hx = pos[0];
    const hy = pos[1];
    let vx = DX[game.dir];
    let vy = DY[game.dir];
    if (n > 1) {
      const [dx, dy] = seg(0);
      const len = Math.hypot(dx, dy);
      if (len > 0.05) {
        vx = dx / len;
        vy = dy / len;
      }
    }
    const headColor = grey ? tint(C.dead.map((v) => v * 1.12)) : rgb(C.head);
    const pupilColor = grey ? tint([11, 29, 24]) : C.pupil;
    this.copies(hx - 0.9, hx + 0.9, hy - 0.9, hy + 0.9, (ox, oy) => {
      const x = hx + ox;
      const y = hy + oy;
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
      for (const side of [-1, 1]) {
        const ex = x + vx * 0.13 - vy * 0.2 * side;
        const ey = y + vy * 0.13 + vx * 0.2 * side;
        if (dead) {
          ctx.beginPath();
          const k = 0.07;
          ctx.moveTo(ex - k, ey - k);
          ctx.lineTo(ex + k, ey + k);
          ctx.moveTo(ex + k, ey - k);
          ctx.lineTo(ex - k, ey + k);
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
    });
  }
}
