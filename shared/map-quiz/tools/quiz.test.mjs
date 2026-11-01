// Plain-node checks of the engine's quiz.js on synthetic regions (rounds,
// kinds, colours, counters, reset, serialize/restore, seeded order).
// No packages: node shared/map-quiz/tools/quiz.test.mjs
import assert from 'node:assert/strict';
import { Quiz, makeRng, mix, shuffled } from '../site/quiz.js';

const ids = Array.from({ length: 12 }, (_, i) => `r${String(i + 1).padStart(2, '0')}`);
const N = ids.length;
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

const isPerm = (order, set = ids) => order.length === set.length && new Set(order).size === set.length && order.every((id) => set.includes(id));
const wrongFor = (q) => q.ids.find((id) => id !== q.target);
const finishRound = (q) => {
  let last;
  const n = q.total; // the next round may ask another number
  for (let i = q.done; i < n; i++) last = q.answer(q.target);
  return last;
};

check('fresh quiz: first kind, a permutation, nothing coloured', () => {
  const q = new Quiz(ids, 1);
  assert.equal(q.kind, 0);
  assert.equal(q.colour, 1);
  assert.equal(q.round, 0);
  assert.equal(q.done, 0);
  assert.equal(q.total, N);
  assert.ok(isPerm(q.order));
  assert.ok(ids.every((id) => q.colourOf(id) === 0));
});

check('seeded order: same seed same order, other seed other order', () => {
  assert.deepEqual(new Quiz(ids, 42).order, new Quiz(ids, 42).order);
  assert.notDeepEqual(new Quiz(ids, 42).order, new Quiz(ids, 43).order);
  assert.deepEqual(shuffled([1, 2, 3, 4, 5], makeRng(7)), shuffled([1, 2, 3, 4, 5], makeRng(7)));
  assert.notEqual(mix(1, 0, 0), mix(1, 0, 1));
});

check('the shuffle does not depend on the number of kinds', () => {
  assert.deepEqual(new Quiz(ids, 42, 1).order, new Quiz(ids, 42, 3).order);
});

check('miss: counts, question stays; unknown ids ignored', () => {
  const q = new Quiz(ids, 5);
  const t = q.target;
  assert.deepEqual(q.answer(wrongFor(q)), { result: 'miss', id: wrongFor(q) });
  assert.equal(q.misses, 1);
  assert.equal(q.roundMisses, 1);
  assert.equal(q.target, t);
  assert.equal(q.answer('elsewhere').result, 'ignored');
  assert.equal(q.answer('land').result, 'ignored');
  assert.equal(q.misses, 1);
  assert.equal(q.correct, 0);
});

check('correct: colours with 1, moves on', () => {
  const q = new Quiz(ids, 5);
  const t = q.target;
  const r = q.answer(t);
  assert.equal(r.result, 'correct');
  assert.equal(r.completed, undefined);
  assert.equal(q.colourOf(t), 1);
  assert.equal(q.done, 1);
  assert.equal(q.correct, 1);
  assert.notEqual(q.target, t);
});

check('2 kinds: kind 0 -> kind 1 (recolour to 2) -> kind 0 (back to 1)', () => {
  const q = new Quiz(ids, 9, 2);
  q.answer(wrongFor(q));
  const r1 = finishRound(q);
  assert.deepEqual(r1.completed, { kind: 0, misses: 1, total: N });
  assert.equal(q.kind, 1);
  assert.equal(q.colour, 2);
  assert.equal(q.round, 1);
  assert.equal(q.done, 0);
  assert.equal(q.roundMisses, 0);
  assert.ok(isPerm(q.order));
  assert.ok(ids.every((id) => q.colourOf(id) === 1), 'map stays coloured between rounds');
  const t = q.target;
  q.answer(t);
  assert.equal(q.colourOf(t), 2);
  assert.equal(ids.filter((id) => q.colourOf(id) === 1).length, N - 1);
  const r2 = finishRound(q);
  assert.deepEqual(r2.completed, { kind: 1, misses: 0, total: N });
  assert.equal(q.kind, 0);
  assert.equal(q.round, 2);
  assert.ok(ids.every((id) => q.colourOf(id) === 2));
  q.answer(q.target);
  assert.equal(ids.filter((id) => q.colourOf(id) === 1).length, 1);
  assert.equal(q.correct, 2 * N + 1);
  assert.equal(q.misses, 1);
});

check('3 kinds cycle 0 1 2 0, colours alternate 1 2 1 2', () => {
  const q = new Quiz(ids, 4, 3);
  const seen = [];
  for (let r = 0; r < 4; r++) {
    seen.push([q.kind, q.colour]);
    const res = finishRound(q);
    assert.equal(res.completed.kind, seen[r][0]);
    assert.ok(ids.every((id) => q.colourOf(id) === seen[r][1]));
  }
  assert.deepEqual(seen, [[0, 1], [1, 2], [2, 1], [0, 2]]);
});

check('1 kind: always kind 0, the colours still alternate', () => {
  const q = new Quiz(ids, 4, 1);
  finishRound(q);
  assert.equal(q.kind, 0);
  assert.equal(q.colour, 2);
});

check('kinds: a positive integer or a non-empty array of keys', () => {
  for (const k of [0, -1, 1.5, '2', [], [1, 2], ['a', null]]) assert.throws(() => new Quiz(ids, 1, k), RangeError);
  const q = new Quiz(ids, 1, ['names', 'numbers', 'x']);
  assert.equal(q.kinds, 3);
  finishRound(q);
  assert.equal(q.kind, 1);
});

check('a single region: every answer completes a round', () => {
  const q = new Quiz(['only'], 3);
  assert.deepEqual(q.answer('only').completed, { kind: 0, misses: 0, total: 1 });
  assert.equal(q.target, 'only');
  assert.equal(q.colourOf('only'), 1);
  q.answer('only');
  assert.equal(q.colourOf('only'), 2);
});

check('misclick on an already coloured region counts', () => {
  const q = new Quiz(ids, 3);
  const first = q.target;
  q.answer(first);
  assert.equal(q.answer(first).result, 'miss');
  assert.equal(q.misses, 1);
});

check('a round never opens with the region that closed the last one', () => {
  for (const set of [ids, ['a', 'b'], ['a', 'b', 'c']]) {
    for (let seed = 0; seed < 300; seed++) {
      const q = new Quiz(set, seed);
      for (let r = 0; r < 3; r++) {
        const last = q.order[q.total - 1];
        finishRound(q);
        assert.notEqual(q.order[0], last, `seed ${seed} round ${r}`);
        assert.ok(isPerm(q.order, set));
      }
    }
  }
});

check('reset: counters 0, map blank, first kind, new shuffle', () => {
  const q = new Quiz(ids, 11);
  const before = q.order.slice();
  finishRound(q);
  q.answer(q.target);
  q.answer(wrongFor(q));
  q.reset();
  assert.equal(q.correct, 0);
  assert.equal(q.misses, 0);
  assert.equal(q.roundMisses, 0);
  assert.equal(q.round, 0);
  assert.equal(q.kind, 0);
  assert.equal(q.done, 0);
  assert.equal(q.game, 1);
  assert.ok(ids.every((id) => q.colourOf(id) === 0));
  assert.notDeepEqual(q.order, before);
  // reproducible per seed: reset of another quiz with the same seed matches
  const p = new Quiz(ids, 11);
  p.reset();
  assert.deepEqual(p.order, q.order);
});

check('serialize/restore: round trip through JSON, play continues identically', () => {
  const a = new Quiz(ids, 77);
  finishRound(a);
  for (let i = 0; i < 5; i++) a.answer(a.target);
  a.answer(wrongFor(a));
  const data = JSON.parse(JSON.stringify(a.serialize()));
  const b = Quiz.restore(data, ids);
  assert.ok(b);
  assert.deepEqual(b.serialize(), a.serialize());
  assert.equal(b.kind, a.kind);
  finishRound(a);
  finishRound(b);
  assert.deepEqual(b.serialize(), a.serialize(), 'next shuffle matches');
});

check('restore: only with the same round kinds (keys, or a count)', () => {
  const keys = ['names', 'numbers', 'districts'];
  const a = new Quiz(ids, 77, keys);
  finishRound(a);
  finishRound(a);
  const saved = JSON.parse(JSON.stringify(a.serialize()));
  assert.deepEqual(saved.kinds, keys);
  assert.equal(Quiz.restore(saved, ids, keys).kind, 2);
  assert.equal(Quiz.restore(saved, ids, ['names', 'numbers']), null, 'a kind removed');
  assert.equal(Quiz.restore(saved, ids, ['numbers', 'names', 'districts']), null, 'reordered');
  assert.equal(Quiz.restore(saved, ids, ['names', 'numbers', 'other']), null, 'renamed');
  assert.equal(Quiz.restore(saved, ids, 3).kind, 2, 'a count compares counts');
  assert.equal(Quiz.restore(saved, ids, 2), null);
  assert.equal(new Quiz(ids, 1, 3).serialize().kinds, 3);
  for (const bad of [null, 'names', 2.5, [1, 2, 3]]) assert.equal(Quiz.restore({ ...saved, kinds: bad }, ids, keys), null, JSON.stringify(bad));
});

check('restore: a save without kinds (europe-quiz before they were stored) means two', () => {
  const a = new Quiz(ids, 5, ['countries', 'capitals']);
  finishRound(a);
  a.answer(a.target);
  const legacy = a.serialize();
  delete legacy.kinds;
  const b = Quiz.restore(legacy, ids, ['countries', 'capitals']);
  assert.ok(b);
  assert.equal(b.kind, 1);
  assert.equal(b.done, 1);
  assert.deepEqual(b.serialize().kinds, ['countries', 'capitals'], 'saved again with kinds');
  assert.ok(Quiz.restore(legacy, ids, 2));
  assert.equal(Quiz.restore(legacy, ids, ['names', 'numbers', 'x']), null);
  assert.equal(Quiz.restore(legacy, ids, 1), null);
});

check('restore rejects what does not fit', () => {
  const good = new Quiz(ids, 1).serialize();
  const bad = [
    null,
    'x',
    { ...good, v: 2 },
    { ...good, seed: -1 },
    { ...good, seed: 2 ** 32 },
    { ...good, pos: N },
    { ...good, pos: 1.5 },
    { ...good, correct: -1 },
    { ...good, misses: '3' },
    { ...good, order: good.order.slice(1) },
    { ...good, order: [good.order[1], ...good.order.slice(1)] },
    { ...good, order: ['elsewhere', ...good.order.slice(1)] },
    { ...good, colours: { elsewhere: 1 } },
    { ...good, colours: { [ids[0]]: 3 } },
    { ...good, colours: [] },
    { ...good, roundMisses: undefined },
  ];
  for (const d of bad) assert.equal(Quiz.restore(d, ids), null, JSON.stringify(d)?.slice(0, 60));
  assert.equal(Quiz.restore(good, ids.slice(1)), null, 'changed region list');
  assert.ok(Quiz.restore(good, ids));
});

// ── Round specs: answers as groups of pieces, inert pieces, asked subsets ──

// The order rule before grouped rounds (37bd3a6), for one-piece answers.
function oldOrder(set, seed, game, round, prevLast) {
  const rng = makeRng(mix(seed, game, round));
  const order = shuffled(set, rng);
  if (order.length > 1 && order[0] === prevLast) {
    const j = 1 + Math.floor(rng() * (order.length - 1));
    [order[0], order[j]] = [order[j], order[0]];
  }
  return order;
}

check('one piece per answer: the same orders as before grouped rounds, in every form', () => {
  const singles = { key: 'y', answers: ids.map((id) => ({ id, pieces: [id] })) };
  for (let seed = 0; seed < 300; seed++) {
    const forms = [new Quiz(ids, seed, 3), new Quiz(ids, seed, ['x', 'y', 'z']), new Quiz(ids, seed, [{ key: 'x' }, singles, 'z'])];
    let last = null;
    for (let r = 0; r < 4; r++) {
      const want = oldOrder(ids, seed, 0, r, last);
      for (const q of forms) assert.deepEqual(q.order, want, `seed ${seed} round ${r}`);
      last = want[want.length - 1];
      for (const q of forms) finishRound(q);
    }
  }
});

check('identity specs = keys: saves restore across the forms', () => {
  const keys = ['x', 'y', 'z'];
  const specs = [{ key: 'x' }, { key: 'y' }, { key: 'z', answers: ids.map((id) => ({ id, pieces: [id] })) }];
  const a = new Quiz(ids, 9, keys);
  finishRound(a);
  finishRound(a);
  a.answer(a.target);
  const saved = JSON.parse(JSON.stringify(a.serialize()));
  const b = Quiz.restore(saved, ids, specs);
  assert.deepEqual(b.serialize(), a.serialize());
  finishRound(a);
  finishRound(b);
  assert.deepEqual(b.serialize(), a.serialize());
  const back = Quiz.restore(JSON.parse(JSON.stringify(b.serialize())), ids, keys);
  assert.deepEqual(back.serialize(), a.serialize());
});

// 8 pieces: two groups and three inert pieces, then every piece alone, then
// a subset round (asked given out of configured order on purpose).
const P = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'p7', 'p8'];
const GROUPS = { key: 'groups', answers: [{ id: 'g1', pieces: ['p1', 'p2', 'p3'] }, { id: 'g2', pieces: ['p4', 'p5'] }] };
const SINGLES = { key: 'singles' };
const SUBSET = { key: 'subset', answers: P.map((id) => ({ id, pieces: [id] })), asked: ['p5', 'p1', 'p3'] };
const KINDS = [GROUPS, SINGLES, SUBSET];

check('groups: total = asked answers, a correct answer colours its whole group, inert pieces and piece ids ignored', () => {
  const q = new Quiz(P, 3, KINDS);
  assert.equal(q.total, 2);
  assert.deepEqual([...q.order].sort(), ['g1', 'g2']);
  assert.equal(q.answerOf('p2'), 'g1');
  assert.equal(q.answerOf('p6'), null, 'inert');
  assert.equal(q.answerOf('sea'), null);
  assert.deepEqual(q.piecesOf('g2'), ['p4', 'p5']);
  assert.deepEqual(q.piecesOf('p4'), [], 'a piece is no answer of this kind');
  assert.equal(q.answer('p1').result, 'ignored');
  assert.equal(q.answer('p6').result, 'ignored');
  const t = q.target;
  const other = t === 'g1' ? 'g2' : 'g1';
  assert.deepEqual(q.answer(other), { result: 'miss', id: other });
  assert.equal(q.target, t);
  const r = q.answer(t);
  assert.equal(r.result, 'correct');
  assert.deepEqual(r.pieces, GROUPS.answers.find((a) => a.id === t).pieces);
  assert.ok(P.every((p) => q.colourOf(p) === (r.pieces.includes(p) ? 1 : 0)));
  const done = q.answer(q.target);
  assert.deepEqual(done.completed, { kind: 0, misses: 1, total: 2 });
  assert.equal(q.kind, 1);
  assert.equal(q.total, 8);
  assert.deepEqual(P.map((p) => q.colourOf(p)), [1, 1, 1, 1, 1, 0, 0, 0]);
});

check('singles after groups, then a subset round: colours carry per piece, not-asked answers are misses', () => {
  const q = new Quiz(P, 4, KINDS);
  finishRound(q);
  assert.equal(q.answer('g1').result, 'ignored', 'a group id is no answer of this kind');
  assert.equal(q.answerOf('p6'), 'p6');
  assert.deepEqual(finishRound(q).completed, { kind: 1, misses: 0, total: 8 });
  assert.ok(P.every((p) => q.colourOf(p) === 2));
  assert.equal(q.kind, 2);
  assert.equal(q.total, 3);
  assert.deepEqual([...q.order].sort(), ['p1', 'p3', 'p5']);
  const t = q.target;
  assert.deepEqual(q.answer('p2'), { result: 'miss', id: 'p2' }, 'not asked: a misclick');
  assert.equal(q.target, t);
  q.answer(t);
  assert.equal(q.answer(t).result, 'miss', 'found already');
  assert.deepEqual(finishRound(q).completed, { kind: 2, misses: 2, total: 3 });
  assert.deepEqual(P.map((p) => q.colourOf(p)), [1, 2, 1, 2, 1, 2, 2, 2], 'not-asked pieces keep their colour');
  assert.equal(q.kind, 0);
  finishRound(q);
  assert.deepEqual(P.map((p) => q.colourOf(p)), [2, 2, 2, 2, 2, 2, 2, 2], 'inert p6-p8 keep theirs');
  // the shuffle starts from the configured order, whatever order asked came in
  const again = [GROUPS, SINGLES, { ...SUBSET, asked: ['p1', 'p3', 'p5'] }];
  for (let seed = 0; seed < 50; seed++) {
    const a = new Quiz(P, seed, KINDS);
    const b = new Quiz(P, seed, again);
    finishRound(a), finishRound(a), finishRound(b), finishRound(b);
    assert.deepEqual(a.order, b.order);
  }
});

check('answer ids may equal one of their pieces, and repeat across rounds', () => {
  const pieces = ['niigata', 'niigata-isles', 'nagano', 'kagawa', 'ehime'];
  const islands = { key: 'islands', answers: [{ id: 'isl-honshu', pieces: ['niigata', 'nagano'] }, { id: 'shikoku', pieces: ['kagawa', 'ehime'] }] };
  const regions = { key: 'regions', answers: [{ id: 'reg-chubu', pieces: ['niigata', 'niigata-isles', 'nagano'] }, { id: 'shikoku', pieces: ['ehime', 'kagawa'] }] };
  const prefs = { key: 'prefectures', answers: [
    { id: 'niigata', pieces: ['niigata', 'niigata-isles'] }, { id: 'nagano', pieces: ['nagano'] },
    { id: 'kagawa', pieces: ['kagawa'] }, { id: 'ehime', pieces: ['ehime'] },
  ] };
  const q = new Quiz(pieces, 1, [islands, regions, prefs]);
  assert.equal(q.answerOf('niigata'), 'isl-honshu');
  assert.equal(q.answerOf('niigata-isles'), null, 'inert in the islands round');
  assert.equal(q.answer('niigata').result, 'ignored', 'a piece id, no answer here');
  assert.deepEqual(q.piecesOf('shikoku'), ['kagawa', 'ehime']);
  finishRound(q);
  assert.equal(q.answerOf('niigata-isles'), 'reg-chubu');
  assert.deepEqual(q.piecesOf('shikoku'), ['ehime', 'kagawa'], 'same id, this round\'s pieces');
  finishRound(q);
  assert.equal(q.answerOf('niigata-isles'), 'niigata');
  assert.equal(q.answerOf('niigata'), 'niigata');
  assert.deepEqual(q.piecesOf('niigata'), ['niigata', 'niigata-isles']);
  while (q.target !== 'niigata') q.answer(q.target);
  const r = q.answer('niigata');
  assert.deepEqual(r.pieces, ['niigata', 'niigata-isles']);
  assert.equal(q.colourOf('niigata-isles'), 1);
  assert.equal(q.colourOf('niigata'), 1);
});

check('a round never opens with an answer sharing a piece with the last one, unless all do', () => {
  for (let seed = 0; seed < 300; seed++) {
    const q = new Quiz(P, seed, [GROUPS, SINGLES]);
    for (let r = 0; r < 4; r++) {
      const last = q.piecesOf(q.order[q.total - 1]);
      finishRound(q);
      assert.ok(!q.piecesOf(q.order[0]).some((p) => last.includes(p)), `seed ${seed} round ${r}`);
    }
    // all-overlap fallback: every answer shares a piece with the last one: no swap
    const whole = { key: 'whole', answers: [{ id: 'all', pieces: ['a', 'b', 'c'] }] };
    const w = new Quiz(['a', 'b', 'c'], seed, [whole, 'singles']);
    finishRound(w);
    assert.deepEqual(w.order, shuffled(['a', 'b', 'c'], makeRng(mix(seed, 0, 1))));
  }
});

check('restore: grouped and subset rounds; a changed asked set or grouping is turned down', () => {
  const a = new Quiz(P, 5, KINDS);
  finishRound(a);
  finishRound(a);
  a.answer(a.target);
  const saved = JSON.parse(JSON.stringify(a.serialize()));
  assert.equal(saved.v, 1);
  assert.deepEqual(saved.kinds, ['groups', 'singles', 'subset']);
  const b = Quiz.restore(saved, P, KINDS);
  assert.deepEqual(b.serialize(), a.serialize());
  finishRound(a);
  finishRound(b);
  assert.deepEqual(b.serialize(), a.serialize());
  for (const asked of [['p1', 'p3'], ['p1', 'p3', 'p5', 'p7'], ['p1', 'p3', 'p6']])
    assert.equal(Quiz.restore(saved, P, [GROUPS, SINGLES, { ...SUBSET, asked }]), null, asked.join());
  const inGroups = JSON.parse(JSON.stringify(new Quiz(P, 5, KINDS).serialize()));
  assert.ok(Quiz.restore(inGroups, P, KINDS));
  const regrouped = { key: 'groups', answers: [{ id: 'g1', pieces: ['p1', 'p2'] }, { id: 'g3', pieces: ['p4', 'p5'] }] };
  assert.equal(Quiz.restore(inGroups, P, [regrouped, SINGLES, SUBSET]), null, 'answer ids changed');
  assert.equal(Quiz.restore({ ...inGroups, colours: { g1: 1 } }, P, KINDS), null, 'colours are per piece');
});

check('constructor: RangeError for a piece in two answers, unknown pieces, a round asking nothing', () => {
  const bads = [
    [{ key: 'x', answers: [{ id: 'g', pieces: ['p1', 'p2'] }, { id: 'h', pieces: ['p2'] }] }],
    [{ key: 'x', answers: [{ id: 'g', pieces: ['p1', 'p1'] }] }],
    [{ key: 'x', answers: [{ id: 'g', pieces: ['p1', 'zz'] }] }],
    [{ key: 'x', answers: [{ id: 'g', pieces: [] }] }],
    [{ key: 'x', answers: [{ id: 'g', pieces: ['p1'] }, { id: 'g', pieces: ['p2'] }] }],
    [{ key: 'x', answers: [] }],
    [{ key: 'x', answers: 'g' }],
    [{ key: 'x', asked: [] }],
    [{ key: 'x', asked: ['nope'] }],
    [{ key: 'x', answers: [{ id: 'g', pieces: ['p1'] }], asked: ['p1'] }],
    [{ answers: [{ id: 'g', pieces: ['p1'] }] }],
    ['a', null],
  ];
  for (const k of bads) assert.throws(() => new Quiz(P, 1, k), RangeError, JSON.stringify(k));
});

console.log(`${checks} checks passed`);
