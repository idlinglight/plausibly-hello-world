// game.js: the rules. No DOM, so it also runs under plain node.
//
// The board is a torus: leaving one edge enters at the opposite one. Cells
// are numbered y * cols + x. The snake is a list of cells, head first; a
// cell can hold at most one segment. Each step the head moves one cell,
// the tail follows unless the snake is growing, and running into its own
// body ends the round. One fruit at a time; eating it grows the snake by
// one segment.

export const UP = 0;
export const RIGHT = 1;
export const DOWN = 2;
export const LEFT = 3;
export const DX = [0, 1, 0, -1];
export const DY = [-1, 0, 1, 0];

const QUEUE_MAX = 2; // turns buffered between steps, so quick double turns work
const FRUIT_MIN_DIST = 3; // new fruit keeps this far from the head if it can

// Small, seedable PRNG (mulberry32): same seed, same game.
export function makeRng(seed) {
  let a = seed >>> 0;
  return function rng() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Game {
  constructor(cols, rows, rng) {
    this.cols = cols;
    this.rows = rows;
    this.rng = rng;
    this.occ = new Uint8Array(cols * rows); // 1 = a segment is here
    this.reset(RIGHT);
  }

  // A fresh round: a short snake in the middle, heading `dir`.
  reset(dir, length = 4) {
    const { cols, rows } = this;
    this.occ.fill(0);
    this.dir = dir;
    this.queue = [];
    this.cells = [];
    const hx = Math.floor(cols / 2);
    const hy = Math.floor(rows / 2);
    const len = Math.max(1, Math.min(length, cols * rows - 1));
    for (let i = 0; i < len; i++) {
      const c = this.wrapIndex(hx - DX[dir] * i, hy - DY[dir] * i);
      if (this.occ[c]) break; // tiny boards: don't overlap itself
      this.cells.push(c);
      this.occ[c] = 1;
    }
    this.prevTail = this.cells[this.cells.length - 1];
    this.grow = 0;
    this.eaten = 0;
    this.steps = 0;
    this.alive = true;
    this.fruit = -1;
    this.placeFruit();
  }

  wrapIndex(x, y) {
    const { cols, rows } = this;
    return (((y % rows) + rows) % rows) * cols + (((x % cols) + cols) % cols);
  }

  // The cell one step from `c` in direction `d`, wrapping at the edges.
  neighbor(c, d) {
    const { cols } = this;
    return this.wrapIndex((c % cols) + DX[d], Math.floor(c / cols) + DY[d]);
  }

  get head() {
    return this.cells[0];
  }

  // The direction the next queued step will take.
  get heading() {
    return this.queue.length ? this.queue[this.queue.length - 1] : this.dir;
  }

  // Queues a turn. Ignored if it repeats or reverses the heading (a snake
  // can't turn back into its own neck) or the queue is full.
  turn(d) {
    const h = this.heading;
    if (d === h || d === (h + 2) % 4 || this.queue.length >= QUEUE_MAX) return false;
    this.queue.push(d);
    return true;
  }

  // One step. Returns 'move', 'eat', 'die' or 'full' (no room for fruit:
  // the board is won).
  step() {
    if (!this.alive) return 'die';
    if (this.queue.length) this.dir = this.queue.shift();
    const next = this.neighbor(this.head, this.dir);
    const tail = this.cells[this.cells.length - 1];
    const tailMoves = this.grow === 0;
    // The tail's cell is free to enter if the tail moves out this step.
    if (this.occ[next] && !(tailMoves && next === tail)) {
      this.alive = false;
      return 'die';
    }
    this.prevTail = tail;
    if (tailMoves) {
      this.cells.pop();
      this.occ[tail] = 0;
    } else {
      this.grow--;
    }
    this.cells.unshift(next);
    this.occ[next] = 1;
    this.steps++;
    if (next === this.fruit) {
      this.eaten++;
      this.grow++;
      if (!this.placeFruit()) return 'full';
      return 'eat';
    }
    return 'move';
  }

  // Puts the fruit on a random free cell, preferably not right in front of
  // the head. Returns false if there is no free cell.
  placeFruit() {
    const { cols, rows, occ } = this;
    const n = cols * rows;
    const free = n - this.cells.length;
    if (free <= 0) {
      this.fruit = -1;
      return false;
    }
    const hx = this.head % cols;
    const hy = Math.floor(this.head / cols);
    const far = (c) => {
      const dx = Math.abs((c % cols) - hx);
      const dy = Math.abs(Math.floor(c / cols) - hy);
      return Math.min(dx, cols - dx) + Math.min(dy, rows - dy) >= FRUIT_MIN_DIST;
    };
    // Rejection sampling is fast while the board is mostly empty; once it
    // fills up, pick uniformly from a list of the free cells instead.
    if (free > n / 4) {
      for (let tries = 0; tries < 64; tries++) {
        const c = Math.floor(this.rng() * n);
        if (!occ[c] && far(c)) {
          this.fruit = c;
          return true;
        }
      }
    }
    const cells = [];
    const near = [];
    for (let c = 0; c < n; c++) if (!occ[c]) (far(c) ? cells : near).push(c);
    const pool = cells.length ? cells : near;
    this.fruit = pool[Math.floor(this.rng() * pool.length)];
    return true;
  }
}
