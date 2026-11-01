// Plain-node checks of site/quiz.js (rounds, colours, counters, reset,
// serialize/restore, seeded order). No packages: node tools/quiz.test.mjs
import assert from 'node:assert/strict';
import { Quiz, makeRng, mix, shuffled } from '../site/quiz.js';
import { COUNTRIES } from '../site/countries.js';

const ids = COUNTRIES.map((c) => c.id);
let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

const isPerm = (order) => order.length === ids.length && new Set(order).size === ids.length && order.every((id) => ids.includes(id));
const wrongFor = (q) => ids.find((id) => id !== q.target);
const finishRound = (q) => {
  let last;
  for (let i = q.done; i < q.total; i++) last = q.answer(q.target);
  return last;
};

check('data: 46 countries, unique names and capitals', () => {
  assert.equal(ids.length, 46);
  assert.equal(new Set(COUNTRIES.map((c) => c.name)).size, 46);
  assert.equal(new Set(COUNTRIES.map((c) => c.capital)).size, 46);
  assert.ok(!ids.includes('RUS'));
  for (const id of ['KOS', 'CYP', 'TUR', 'VAT']) assert.ok(ids.includes(id), id);
});

check('fresh quiz: name round, a permutation, nothing coloured', () => {
  const q = new Quiz(ids, 1);
  assert.equal(q.kind, 'country');
  assert.equal(q.round, 0);
  assert.equal(q.done, 0);
  assert.equal(q.total, 46);
  assert.ok(isPerm(q.order));
  assert.ok(ids.every((id) => q.colourOf(id) === 0));
});

check('seeded order: same seed same order, other seed other order', () => {
  assert.deepEqual(new Quiz(ids, 42).order, new Quiz(ids, 42).order);
  assert.notDeepEqual(new Quiz(ids, 42).order, new Quiz(ids, 43).order);
  assert.deepEqual(shuffled([1, 2, 3, 4, 5], makeRng(7)), shuffled([1, 2, 3, 4, 5], makeRng(7)));
  assert.notEqual(mix(1, 0, 0), mix(1, 0, 1));
});

check('miss: counts, question stays; unknown ids ignored', () => {
  const q = new Quiz(ids, 5);
  const t = q.target;
  assert.deepEqual(q.answer(wrongFor(q)), { result: 'miss', id: wrongFor(q) });
  assert.equal(q.misses, 1);
  assert.equal(q.roundMisses, 1);
  assert.equal(q.target, t);
  assert.equal(q.answer('RUS').result, 'ignored');
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

check('rounds wrap: names -> capitals (recolour to 2) -> names (back to 1)', () => {
  const q = new Quiz(ids, 9);
  q.answer(wrongFor(q));
  const r1 = finishRound(q);
  assert.deepEqual(r1.completed, { kind: 'country', misses: 1 });
  assert.equal(q.kind, 'capital');
  assert.equal(q.round, 1);
  assert.equal(q.done, 0);
  assert.equal(q.roundMisses, 0);
  assert.ok(isPerm(q.order));
  assert.ok(ids.every((id) => q.colourOf(id) === 1), 'map stays coloured between rounds');
  const t = q.target;
  q.answer(t);
  assert.equal(q.colourOf(t), 2);
  assert.equal(ids.filter((id) => q.colourOf(id) === 1).length, 45);
  const r2 = finishRound(q);
  assert.deepEqual(r2.completed, { kind: 'capital', misses: 0 });
  assert.equal(q.kind, 'country');
  assert.equal(q.round, 2);
  assert.ok(ids.every((id) => q.colourOf(id) === 2));
  q.answer(q.target);
  assert.equal(ids.filter((id) => q.colourOf(id) === 1).length, 1);
  assert.equal(q.correct, 93);
  assert.equal(q.misses, 1);
});

check('misclick on an already coloured country counts', () => {
  const q = new Quiz(ids, 3);
  const first = q.target;
  q.answer(first);
  assert.equal(q.answer(first).result, 'miss');
  assert.equal(q.misses, 1);
});

check('a round never opens with the country that closed the last one', () => {
  for (let seed = 0; seed < 300; seed++) {
    const q = new Quiz(ids, seed);
    for (let r = 0; r < 3; r++) {
      const last = q.order[q.total - 1];
      finishRound(q);
      assert.notEqual(q.order[0], last, `seed ${seed} round ${r}`);
      assert.ok(isPerm(q.order));
    }
  }
});

check('reset: counters 0, map blank, name round, new shuffle', () => {
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
  assert.equal(q.kind, 'country');
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
  for (let i = 0; i < 10; i++) a.answer(a.target);
  a.answer(wrongFor(a));
  const data = JSON.parse(JSON.stringify(a.serialize()));
  const b = Quiz.restore(data, ids);
  assert.ok(b);
  assert.deepEqual(b.serialize(), a.serialize());
  finishRound(a);
  finishRound(b);
  assert.deepEqual(b.serialize(), a.serialize(), 'next shuffle matches');
});

check('restore rejects what does not fit', () => {
  const good = new Quiz(ids, 1).serialize();
  const bad = [
    null,
    'x',
    { ...good, v: 2 },
    { ...good, seed: -1 },
    { ...good, seed: 2 ** 32 },
    { ...good, pos: 46 },
    { ...good, pos: 1.5 },
    { ...good, correct: -1 },
    { ...good, misses: '3' },
    { ...good, order: good.order.slice(1) },
    { ...good, order: [good.order[1], ...good.order.slice(1)] },
    { ...good, order: ['RUS', ...good.order.slice(1)] },
    { ...good, colours: { RUS: 1 } },
    { ...good, colours: { FRA: 3 } },
    { ...good, colours: [] },
    { ...good, roundMisses: undefined },
  ];
  for (const d of bad) assert.equal(Quiz.restore(d, ids), null, JSON.stringify(d)?.slice(0, 60));
  assert.equal(Quiz.restore(good, ids.slice(1)), null, 'changed country list');
  assert.ok(Quiz.restore(good, ids));
});

console.log(`${checks} checks passed`);
