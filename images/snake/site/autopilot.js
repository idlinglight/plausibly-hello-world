// autopilot.js: steers the snake while nobody is playing (demo mode).
//
// Each step:
//   1. Breadth-first search from the head to the fruit. It knows the body
//      moves: segment j of a snake of length L leaves its cell after L - j
//      steps (later while it is still growing), so a cell counts as free if
//      it will be vacated by the time the head gets there.
//   2. Take that path only if it is safe: after eating, the head must
//      still be able to reach the tail, i.e. it can always follow its own
//      tail out of whatever it just got into.
//   3. Otherwise buy time: of the legal moves, prefer one that keeps the
//      tail reachable, then the most room, then the longest way round.
// The search prefers straight runs, so paths look like a player's (L-shaped)
// rather than a staircase.
//
// Played this way it fills ~90 % of the board, which takes most of an hour
// and doesn't look like much. So each round picks a target length; past it
// the snake gets careless: step 2 is skipped (greedy), and now and then it
// turns without looking (SLIP_CHANCE per step), like a player's slip of the
// thumb. That ends the round within a minute or so, and the demo starts over.
//
// Pure logic, no DOM: also runs under plain node.

const SLIP_CHANCE = 0.03; // per step, once careless

export class Autopilot {
  constructor(rng) {
    this.rng = rng;
    this.grid = '';
    this.lastEaten = -1;
    this.hungry = 0; // steps since the last fruit
    this.target = 0; // length at which it gets careless
  }

  // Call at the start of each round, and when taking over a person's round
  // (base: its current length, so a long snake isn't careless at once).
  // Target: base + 15 to 5-12 % of the board.
  newRound(game, base = 0) {
    const n = game.cols * game.rows;
    const lo = Math.min(15, Math.floor(n * 0.1));
    const hi = Math.max(lo, Math.min(80, Math.floor(n * 0.12)));
    this.target = base + lo + Math.floor(this.rng() * (hi - lo + 1));
    this.lastEaten = game.eaten;
    this.hungry = 0;
  }

  // (Re)builds the lookup tables when the board size changes.
  setup(game) {
    const grid = game.cols + 'x' + game.rows;
    if (grid === this.grid) return;
    this.grid = grid;
    const n = game.cols * game.rows;
    this.n = n;
    this.nb = new Int32Array(n * 4); // nb[c * 4 + d]: neighbour of c in direction d
    for (let c = 0; c < n; c++) for (let d = 0; d < 4; d++) this.nb[c * 4 + d] = game.neighbor(c, d);
    this.freeAt = new Int32Array(n);
    this.dist = new Int32Array(n);
    this.queue = new Int32Array(n);
  }

  // Returns the direction (0-3) to take next.
  choose(game) {
    this.setup(game);
    if (!this.target) this.newRound(game);
    if (game.eaten !== this.lastEaten) {
      this.lastEaten = game.eaten;
      this.hungry = 0;
    } else {
      this.hungry++;
    }
    const { cells, grow, fruit, head } = game;
    const back = (game.dir + 2) % 4;
    const neck = this.nb[head * 4 + back]; // no reversing into it

    // Greedy: long enough for this round. Takes risks, also when there's no
    // path to the fruit (then just any move that isn't fatal right away).
    const greedy = cells.length >= this.target;
    if (greedy && this.rng() < SLIP_CHANCE) {
      const turn = this.rng() < 0.5 ? 1 : 3; // left or right, unchecked
      return (game.dir + turn) % 4;
    }

    this.fillFreeAt(cells, grow);
    this.bfs(head, neck);
    if (fruit >= 0 && this.dist[fruit] > 0) {
      const path = this.pathTo(fruit);
      // Also after circling for a whole board's worth of steps without a
      // safe way in: go for the fruit, even at the risk of a dead end.
      if (greedy || this.hungry > this.n || this.tailOk(this.advance(cells, grow, path, true))) {
        return this.dirTo(head, path[0]);
      }
    }

    const tail = cells[cells.length - 1];
    let best = game.dir;
    let bestScore = -Infinity;
    for (let d = 0; d < 4; d++) {
      if (d === back) continue;
      const c = this.nb[head * 4 + d];
      if (game.occ[c] && !(c === tail && grow === 0)) continue; // would die right away
      if (greedy) {
        const score = (d === game.dir ? 0.5 : 0) + this.rng();
        if (score > bestScore) {
          bestScore = score;
          best = d;
        }
        continue;
      }
      const v = this.advance(cells, grow, [c], c === fruit);
      const reach = this.evaluate(v);
      const tailDist = this.dist[v.cells[v.cells.length - 1]];
      const score =
        (v.cells.length === 1 || tailDist > 0 ? 1e9 : 0) +
        reach * 1e3 +
        Math.min(tailDist, 999) +
        (d === game.dir ? 0.5 : 0) +
        this.rng() * 0.25;
      if (score > bestScore) {
        bestScore = score;
        best = d;
      }
    }
    return best;
  }

  // freeAt[c] = steps until cell c is free (0: free now).
  fillFreeAt(cells, grow) {
    const { freeAt } = this;
    const len = cells.length;
    freeAt.fill(0);
    for (let j = 0; j < len; j++) freeAt[cells[j]] = len - j + grow;
  }

  // Breadth-first search from `start` (time 0), entering a cell only if it
  // is free on arrival. `ban`: a cell not to enter on the first step.
  // Fills dist (-1 = unreachable); returns the number of cells reached.
  bfs(start, ban = -1) {
    const { nb, freeAt, dist, queue } = this;
    dist.fill(-1);
    dist[start] = 0;
    queue[0] = start;
    let qh = 0;
    let qt = 1;
    while (qh < qt) {
      const c = queue[qh++];
      const t = dist[c] + 1;
      for (let d = 0; d < 4; d++) {
        const m = nb[c * 4 + d];
        if (dist[m] >= 0 || freeAt[m] > t || (c === start && m === ban)) continue;
        dist[m] = t;
        queue[qt++] = m;
      }
    }
    return qt;
  }

  // The path to `target` from the last bfs(), as cells from the head's
  // neighbour to the target. Walks back from the target, keeping straight
  // runs where it can choose.
  pathTo(target) {
    const { nb, dist, rng } = this;
    const path = [];
    let cur = target;
    let last = -1;
    const options = [];
    for (let k = dist[target]; k > 0; k--) {
      path.push(cur);
      options.length = 0;
      let pick = -1;
      for (let d = 0; d < 4; d++) {
        const p = nb[cur * 4 + d];
        if (dist[p] !== k - 1) continue;
        const stepDir = (d + 2) % 4; // direction of the step p -> cur
        if (stepDir === last) pick = d;
        options.push(d);
      }
      if (pick < 0) pick = options[Math.floor(rng() * options.length)];
      cur = nb[cur * 4 + pick];
      last = (pick + 2) % 4;
    }
    return path.reverse();
  }

  dirTo(from, to) {
    for (let d = 0; d < 4; d++) if (this.nb[from * 4 + d] === to) return d;
    return 0;
  }

  // The snake after following `path` (cells, head's neighbour first),
  // eating at the end if `ate`.
  advance(cells, grow, path, ate) {
    const steps = path.length;
    const used = Math.min(steps, grow); // growth spent on the way
    const len = cells.length + used;
    const out = new Array(len);
    let k = 0;
    for (let i = steps - 1; i >= 0 && k < len; i--) out[k++] = path[i];
    for (let j = 0; k < len; j++) out[k++] = cells[j];
    return { cells: out, grow: grow - used + (ate ? 1 : 0) };
  }

  // bfs() from the head of snake `v`; returns the number of cells reached.
  evaluate(v) {
    this.fillFreeAt(v.cells, v.grow);
    const len = v.cells.length;
    const ban = len > 1 ? v.cells[1] : -1;
    return this.bfs(v.cells[0], ban);
  }

  // Can snake `v` reach its own tail?
  tailOk(v) {
    this.evaluate(v);
    return v.cells.length === 1 || this.dist[v.cells[v.cells.length - 1]] > 0;
  }
}
