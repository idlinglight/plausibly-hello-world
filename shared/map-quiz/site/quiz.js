// quiz.js: the rules. No DOM, so it also runs under plain node.
// Shared map-quiz engine file: the source is shared/map-quiz/site/, images
// get byte-identical copies (python3 shared/sync.py). Edit the source.
//
// A game is an endless run of rounds over one set of map pieces (ids: one
// <path> each). Round r uses round kind r % kinds (the image's
// config.rounds: names, capitals, numbers …). A kind's answers are its
// pieces one by one (the default), or groups of them ({ id, pieces }: an
// island of several prefectures, a region); a piece in no answer of the
// kind is inert in its rounds (context land, never an answer). Round r
// asks every asked answer of its kind once (all of them, or the subset
// the kind names), in its own shuffled order. A correct answer colours
// all its pieces with the round's colour (1 in even rounds, 2 in odd
// ones) and moves on; the last one starts the next round at once. Colours
// are per piece and carry over: each round recolours the map as it goes,
// so the map is blank only at the start of a game. A wrong answer (any
// other answer of the kind: asked or not, found or not) counts as a miss
// and the question stays. Ids that are no answer of the kind (sea,
// context land, inert pieces) are ignored.
//
// Shuffles are reproducible: round r of game g with seed s always gets the
// same order, from makeRng(mix(s, g, r)) over the asked answers in their
// configured order; a round never opens with an answer that shares a
// piece with the one that closed the round before (unless every one does).
// reset() starts game g + 1: colours and counters cleared, a fresh first
// round.
//
// A saved game records its round kinds (the rounds' keys), so restore()
// turns it down once the image's rounds change: a saved round index would
// otherwise continue as a different kind. Saves from before that field
// (europe-quiz only) had two kinds and restore wherever there are two.
// Where a kind groups pieces or asks a subset, the save also records a
// fingerprint of every kind's answers (their pieces) and asked answers,
// and restore() turns it down when they changed; a save of kinds with one
// piece per answer has no such field (its format predates grouping).

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

// Saved kinds (keys or a count) against the current ones: keys must match
// exactly when both sides have them, otherwise the counts.
function sameKinds(saved, now) {
  const count = (k) => (Array.isArray(k) ? k.length : k);
  if (Array.isArray(saved) && !saved.every((k) => typeof k === 'string')) return false;
  if (!Array.isArray(saved) && !Number.isSafeInteger(saved)) return false;
  if (Array.isArray(saved) && Array.isArray(now)) return saved.length === now.length && saved.every((k, i) => k === now[i]);
  return count(saved) === count(now);
}

// One round kind: answers (id -> pieces), the owner of each piece, the
// asked answers in configured order. k: a round key (every piece its own
// answer, all asked) or { key, answers?: [{ id, pieces }], asked?: [ids] }
// (contract.js roundSpecs makes these from config.rounds).
function kindOf(k, i, idSet, identity) {
  if (typeof k === 'string') return { ...identity, key: k };
  if (!k || typeof k !== 'object' || typeof k.key !== 'string') throw new RangeError(`kinds[${i}]: a round key or { key, answers?, asked? }`);
  const where = `kinds[${i}] (${k.key})`;
  let { piecesOf, owner } = identity;
  if (k.answers !== undefined) {
    if (!Array.isArray(k.answers) || !k.answers.length) throw new RangeError(`${where}: answers, a non-empty array`);
    piecesOf = new Map();
    owner = new Map();
    for (const a of k.answers) {
      if (!a || typeof a.id !== 'string' || piecesOf.has(a.id) || !Array.isArray(a.pieces) || !a.pieces.length)
        throw new RangeError(`${where}: answer ${JSON.stringify(a && a.id)}: a unique id and a non-empty list of pieces`);
      for (const p of a.pieces) {
        if (!idSet.has(p)) throw new RangeError(`${where}: answer ${a.id}: ${JSON.stringify(p)} is no piece`);
        if (owner.has(p)) throw new RangeError(`${where}: piece ${p} in ${owner.get(p)} and ${a.id}`);
        owner.set(p, a.id);
      }
      piecesOf.set(a.id, a.pieces.slice());
    }
  }
  let asked = [...piecesOf.keys()];
  if (k.asked !== undefined) {
    if (!Array.isArray(k.asked) || !k.asked.every((id) => piecesOf.has(id))) throw new RangeError(`${where}: asked, a list of its answers' ids`);
    const set = new Set(k.asked);
    asked = asked.filter((id) => set.has(id)); // configured order, whatever order asked came in
  }
  if (!asked.length) throw new RangeError(`${where}: asks nothing`);
  // grouped: anything but one piece per answer (in piece order), all asked
  const grouped = !(asked.length === identity.asked.length &&
    [...piecesOf].every(([id, pieces], j) => pieces.length === 1 && pieces[0] === id && identity.asked[j] === id));
  return { key: k.key, piecesOf, owner, asked, askedSet: new Set(asked), grouped };
}

// The save's fingerprint of the kinds' answers and asked answers (8 hex
// digits, FNV-1a), or null when every kind has one piece per answer, all
// asked.
function fingerprint(specs) {
  if (!specs.some((k) => k.grouped)) return null;
  const text = specs.map((k) => (k.grouped
    ? `${k.key}=${[...k.piecesOf].map(([id, pieces]) => `${id}:${pieces.join('+')}`).join(',')}|${k.asked.join(',')}`
    : `${k.key}=*`)).join('\n');
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193);
  return (h >>> 0).toString(16).padStart(8, '0');
}

export class Quiz {
  // ids: the map's pieces (config.items' ids; any stable order); seed:
  // 32-bit integer; kinds: the round kinds that cycle, as a count, their
  // keys (config.rounds' keys), or specs { key, answers?, asked? } (see
  // kindOf; a key alone is a kind where every piece is its own answer).
  constructor(ids, seed, kinds = 2) {
    const n = Array.isArray(kinds) ? kinds.length : kinds;
    if (!Number.isSafeInteger(n) || n < 1) throw new RangeError('kinds: a positive integer, or a non-empty array of round keys or specs');
    this.ids = ids.slice();
    this.idSet = new Set(this.ids);
    const identity = { key: null, piecesOf: new Map(this.ids.map((id) => [id, [id]])), owner: new Map(this.ids.map((id) => [id, id])), grouped: false };
    identity.asked = [...identity.piecesOf.keys()];
    identity.askedSet = new Set(identity.asked);
    this.specs = Array.isArray(kinds) ? kinds.map((k, i) => kindOf(k, i, this.idSet, identity)) : Array.from({ length: n }, () => identity);
    this.kinds = n;
    this.kindKeys = Array.isArray(kinds) ? this.specs.map((k) => k.key) : null;
    this.groups = fingerprint(this.specs); // null for one piece per answer
    this.seed = seed >>> 0;
    this.game = 0;
    this.colours = {}; // piece id -> 1 | 2
    this.correct = 0;
    this.misses = 0;
    this.roundMisses = 0;
    this.start(0, null);
  }

  // prev: the pieces of the answer that closed the round before (or null).
  start(round, prev) {
    this.round = round;
    this.pos = 0;
    this.roundMisses = 0;
    const k = this.specs[round % this.kinds];
    const rng = makeRng(mix(this.seed, this.game, round));
    const order = shuffled(k.asked, rng);
    const last = new Set(prev || []);
    const meets = (id) => k.piecesOf.get(id).some((p) => last.has(p));
    if (order.length > 1 && meets(order[0])) {
      // Swap in one that doesn't (for single pieces: any but the first).
      const cands = [];
      for (let i = 1; i < order.length; i++) if (!meets(order[i])) cands.push(i);
      if (cands.length) {
        const j = cands[Math.floor(rng() * cands.length)];
        [order[0], order[j]] = [order[j], order[0]];
      }
    }
    this.order = order;
  }

  // The current round's kind: an index into config.rounds.
  get kind() {
    return this.round % this.kinds;
  }

  // The current round's colour: 1 (A) in even rounds, 2 (B) in odd ones.
  get colour() {
    return (this.round % 2) + 1;
  }

  // The asked answer (an answer id of the current kind).
  get target() {
    return this.order[this.pos];
  }

  // Answers asked in this round.
  get total() {
    return this.order.length;
  }

  // Found so far in this round.
  get done() {
    return this.pos;
  }

  // A piece's colour: 0, 1 or 2.
  colourOf(id) {
    return this.colours[id] || 0;
  }

  // The current kind's answer a piece belongs to; null if it is inert
  // (or no piece).
  answerOf(piece) {
    const a = this.specs[this.kind].owner.get(piece);
    return a === undefined ? null : a;
  }

  // The pieces of an answer of the current kind ([] for any other id).
  piecesOf(id) {
    const p = this.specs[this.kind].piecesOf.get(id);
    return p ? p.slice() : [];
  }

  // -> { result: 'correct' | 'miss' | 'ignored', id, pieces?, completed? }
  // pieces (correct, miss): the answer's pieces in the round it was given
  // in (a correct answer has coloured them). completed (on the last correct
  // answer of a round): { kind, misses, total } of the round just
  // finished; the quiz is already in the next one, so piecesOf() and
  // answerOf() describe that one.
  answer(id) {
    const k = this.specs[this.kind];
    if (!k.piecesOf.has(id)) return { result: 'ignored', id };
    if (id !== this.target) {
      this.misses++;
      this.roundMisses++;
      return { result: 'miss', id, pieces: k.piecesOf.get(id).slice() };
    }
    this.correct++;
    const pieces = k.piecesOf.get(id).slice();
    for (const p of pieces) this.colours[p] = this.colour;
    this.pos++;
    if (this.pos < this.order.length) return { result: 'correct', id, pieces };
    const completed = { kind: this.kind, misses: this.roundMisses, total: this.order.length };
    this.start(this.round + 1, pieces);
    return { result: 'correct', id, pieces, completed };
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
      kinds: this.kindKeys ? this.kindKeys.slice() : this.kinds,
      ...(this.groups ? { groups: this.groups } : {}),
    };
  }

  // A Quiz from serialize()'s output, or null if it doesn't fit `ids` and
  // `kinds` (another version, changed pieces, rounds, answers or asked
  // answers, tampering). kinds: as for the constructor.
  static restore(data, ids, kinds = 2) {
    if (!data || typeof data !== 'object' || data.v !== VERSION) return null;
    const now = Array.isArray(kinds) ? kinds.map((k) => (typeof k === 'string' ? k : k && k.key)) : kinds;
    if (!sameKinds(data.kinds === undefined ? 2 : data.kinds, now)) return null;
    const { seed, game, round, pos, order, colours, correct, misses, roundMisses } = data;
    if (!Number.isSafeInteger(seed) || seed < 0 || seed > 0xffffffff) return null;
    if (![game, round, pos, correct, misses, roundMisses].every(isCount)) return null;
    const q = new Quiz(ids, seed, kinds);
    if ((data.groups === undefined ? null : data.groups) !== q.groups) return null; // answers or asked changed
    const k = q.specs[round % q.kinds];
    if (!Array.isArray(order) || order.length !== k.asked.length || pos >= order.length) return null;
    if (new Set(order).size !== order.length || !order.every((id) => k.askedSet.has(id))) return null;
    if (!colours || typeof colours !== 'object' || Array.isArray(colours)) return null;
    for (const [id, c] of Object.entries(colours)) if (!q.idSet.has(id) || (c !== 1 && c !== 2)) return null;
    Object.assign(q, { game, round, pos, order: order.slice(), colours: { ...colours }, correct, misses, roundMisses });
    return q;
  }
}
