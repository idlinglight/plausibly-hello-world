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
  for (let i = q.done; i < q.total; i++) last = q.answer(q.target);
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
  assert.deepEqual(r1.completed, { kind: 0, misses: 1 });
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
  assert.deepEqual(r2.completed, { kind: 1, misses: 0 });
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

check('kinds must be a positive integer', () => {
  for (const k of [0, -1, 1.5, '2']) assert.throws(() => new Quiz(ids, 1, k), RangeError);
});

check('a single region: every answer completes a round', () => {
  const q = new Quiz(['only'], 3);
  assert.deepEqual(q.answer('only').completed, { kind: 0, misses: 0 });
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

check('restore: the number of kinds comes from the caller', () => {
  const a = new Quiz(ids, 77, 3);
  finishRound(a);
  finishRound(a);
  const b = Quiz.restore(a.serialize(), ids, 3);
  assert.equal(b.kind, 2);
  assert.equal(Quiz.restore(a.serialize(), ids, 2).kind, 0);
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

console.log(`${checks} checks passed`);
