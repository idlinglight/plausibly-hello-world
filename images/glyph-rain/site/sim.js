// The rain as data, no DOM (tools/sim.test.mjs runs it under plain node).
//
// A grid of cells. Heads fall down the columns at their own speed; each
// cell a head enters gets a random glyph of the head's set and starts to
// fade from that moment, over the head's fade time. Now and then a lit
// cell swaps its glyph. At most MAX_PER_COL heads share a column.

export const MAX_PER_COL = 2;
const SPEED = [6, 19]; // rows per second
const FADE = [0.9, 2.8]; // seconds until a lit cell is dark again
const GAP = [0.8, 7]; // seconds between two heads starting in a column
const SWAPS = 0.25; // glyph swaps per lit cell and second

// mulberry32: small, fast, seedable (?seed=<int>).
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const between = (r, [lo, hi]) => lo + r() * (hi - lo);

export class Sim {
  // counts: glyphs per set (index = set number in the cells).
  constructor(cols, rows, counts, random = Math.random) {
    this.cols = cols;
    this.rows = rows;
    this.counts = counts;
    this.r = random;
    this.t = 0;
    const n = cols * rows;
    this.glyph = new Uint16Array(n);
    this.set = new Uint8Array(n);
    this.litAt = new Float64Array(n).fill(-Infinity);
    this.fade = new Float32Array(n).fill(1);
    this.heads = []; // { col, y, row, speed, fade, set }
    this.nextStart = Float64Array.from({ length: cols }, () => this.r() * GAP[1]);
  }

  // Brightness of cell i now: 1 when lit, 0 once its fade time is over.
  level(i) {
    const age = this.t - this.litAt[i];
    return age >= this.fade[i] ? 0 : 1 - age / this.fade[i];
  }

  // A head in column col, entering at row (default: above the top edge).
  start(col, row = -1) {
    const mine = this.heads.filter((h) => h.col === col);
    if (mine.length >= MAX_PER_COL) this.heads.splice(this.heads.indexOf(mine[0]), 1);
    const set = Math.floor(this.r() * this.counts.length);
    this.heads.push({ col, y: row, row: row - 1, speed: between(this.r, SPEED), fade: between(this.r, FADE), set });
  }

  light(col, row, h) {
    const i = row * this.cols + col;
    this.glyph[i] = Math.floor(this.r() * this.counts[h.set]);
    this.set[i] = h.set;
    this.litAt[i] = this.t;
    this.fade[i] = h.fade;
  }

  step(dt) {
    this.t += dt;
    for (let c = 0; c < this.cols; c++) {
      if (this.t < this.nextStart[c]) continue;
      if (this.heads.filter((h) => h.col === c).length < MAX_PER_COL) this.start(c);
      this.nextStart[c] = this.t + between(this.r, GAP);
    }
    for (const h of this.heads) {
      h.y += h.speed * dt;
      const to = Math.min(Math.floor(h.y), this.rows - 1);
      for (let row = Math.max(h.row + 1, 0); row <= to; row++) this.light(h.col, row, h);
      h.row = Math.max(h.row, to);
    }
    this.heads = this.heads.filter((h) => h.y < this.rows + 1);
    // Swaps: each cell is sampled SWAPS times a second on average, and a
    // sampled cell that is lit changes its glyph.
    const n = this.cols * this.rows;
    let k = n * SWAPS * dt;
    for (; k >= 1 || this.r() < k; k--) {
      const i = Math.floor(this.r() * n);
      if (this.level(i) > 0) this.glyph[i] = Math.floor(this.r() * this.counts[this.set[i]]);
    }
  }

  // The head cells (drawn bright), as cell indices.
  headCells() {
    const out = [];
    for (const h of this.heads) if (h.row >= 0 && h.y < this.rows) out.push(h.row * this.cols + h.col);
    return out;
  }
}
