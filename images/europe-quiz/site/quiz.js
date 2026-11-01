// quiz.js: the rules. No DOM, so it also runs under plain node.
//
// A game is an endless run of rounds. Even rounds (0, 2, …) ask for every
// country by name, odd rounds by its capital, each round in its own
// shuffled order; the answer is always a country (an id). A correct answer
// colours that country with the round's colour (1 in name rounds, 2 in
// capital rounds) and moves on; the last one starts the next round at once.
// Colours carry over: each round recolours the map as it goes, so the map
// is blank only at the start of a game. A wrong answer (any other quiz
// country, coloured or not) counts as a miss and the question stays.
// Unknown ids (sea, context land) are ignored.
//
// Shuffles are reproducible: round r of game g with seed s always gets the
// same order, from makeRng(mix(s, g, r)); a round never opens with the
// country that closed the round before. reset() starts game g + 1: colours
// and counters cleared, a fresh name round.

export const KINDS = ['country', 'capital'];
export const VERSION = 1; // of serialize()'s format

// Small, seedable PRNG (mulberry32), as in the snake image.
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

// Mixes integers into one 32-bit seed (murmur3-style finalizer per part).
export function mix(...parts) {
  let h = 0x9e3779b9;
  for (const p of parts) {
    h = Math.imul(h ^ (p >>> 0), 0x85ebca6b);
    h ^= h >>> 13;
    h = Math.imul(h, 0xc2b2ae35);
    h ^= h >>> 16;
  }
  return h >>> 0;
}

export function shuffled(items, rng) {
  const a = items.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

const isCount = (v) => Number.isSafeInteger(v) && v >= 0;

export class Quiz {
  // ids: the quiz set (any stable order); seed: 32-bit integer.
  constructor(ids, seed) {
    this.ids = ids.slice();
    this.idSet = new Set(this.ids);
    this.seed = seed >>> 0;
    this.game = 0;
    this.colours = {}; // id -> 1 | 2
    this.correct = 0;
    this.misses = 0;
    this.roundMisses = 0;
    this.start(0, null);
  }

  start(round, prevLast) {
    this.round = round;
    this.pos = 0;
    this.roundMisses = 0;
    const rng = makeRng(mix(this.seed, this.game, round));
    const order = shuffled(this.ids, rng);
    if (order.length > 1 && order[0] === prevLast) {
      const j = 1 + Math.floor(rng() * (order.length - 1));
      [order[0], order[j]] = [order[j], order[0]];
    }
    this.order = order;
  }

  get kind() {
    return KINDS[this.round % 2];
  }

  get target() {
    return this.order[this.pos];
  }

  get total() {
    return this.order.length;
  }

  // Found so far in this round.
  get done() {
    return this.pos;
  }

  colourOf(id) {
    return this.colours[id] || 0;
  }

  // -> { result: 'correct' | 'miss' | 'ignored', id, completed? }
  // completed (on the last correct answer of a round): { kind, misses } of
  // the round just finished; the quiz is already in the next one.
  answer(id) {
    if (!this.idSet.has(id)) return { result: 'ignored', id };
    if (id !== this.target) {
      this.misses++;
      this.roundMisses++;
      return { result: 'miss', id };
    }
    this.correct++;
    this.colours[id] = (this.round % 2) + 1;
    this.pos++;
    if (this.pos < this.order.length) return { result: 'correct', id };
    const completed = { kind: this.kind, misses: this.roundMisses };
    this.start(this.round + 1, id);
    return { result: 'correct', id, completed };
  }

  reset() {
    this.game++;
    this.colours = {};
    this.correct = 0;
    this.misses = 0;
    this.start(0, null);
  }

  serialize() {
    return {
      v: VERSION,
      seed: this.seed,
      game: this.game,
      round: this.round,
      pos: this.pos,
      order: this.order.slice(),
      colours: { ...this.colours },
      correct: this.correct,
      misses: this.misses,
      roundMisses: this.roundMisses,
    };
  }

  // A Quiz from serialize()'s output, or null if it doesn't fit `ids`
  // (another version, a changed country list, tampering).
  static restore(data, ids) {
    if (!data || typeof data !== 'object' || data.v !== VERSION) return null;
    const { seed, game, round, pos, order, colours, correct, misses, roundMisses } = data;
    if (!Number.isSafeInteger(seed) || seed < 0 || seed > 0xffffffff) return null;
    if (![game, round, pos, correct, misses, roundMisses].every(isCount)) return null;
    if (!Array.isArray(order) || order.length !== ids.length || pos >= order.length) return null;
    const idSet = new Set(ids);
    if (new Set(order).size !== order.length || !order.every((id) => idSet.has(id))) return null;
    if (!colours || typeof colours !== 'object' || Array.isArray(colours)) return null;
    for (const [id, c] of Object.entries(colours)) if (!idSet.has(id) || (c !== 1 && c !== 2)) return null;
    const q = new Quiz(ids, seed);
    Object.assign(q, { game, round, pos, order: order.slice(), colours: { ...colours }, correct, misses, roundMisses });
    return q;
  }
}
