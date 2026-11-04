// Plain-node check of site/sim.js, the rain without the drawing: seeded
// runs repeat, heads stay in their limits, every lit cell holds a glyph of
// its set. No packages:
// node images/glyph-rain/tools/sim.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { Sim, rng, MAX_PER_COL } from '../site/sim.js';

const run = (seed, counts = [500], secs = 20, cols = 60, rows = 40) => {
  const s = new Sim(cols, rows, counts, rng(seed));
  for (let t = 0; t < secs; t += 1 / 30) s.step(1 / 30);
  return s;
};

{
  const a = run(7);
  const b = run(7);
  const c = run(8);
  assert.deepEqual([...a.glyph], [...b.glyph]);
  assert.deepEqual([...a.litAt], [...b.litAt]);
  assert.notDeepEqual([...a.glyph], [...c.glyph]);
  console.log('ok the same seed, the same rain');
}

{
  const counts = [17, 75];
  const s = new Sim(50, 30, counts, rng(3));
  let lit = 0;
  let maxHeads = 0;
  const setsSeen = new Set();
  for (let f = 0; f < 30 * 30; f++) {
    s.step(1 / 30);
    const per = new Map();
    for (const h of s.heads) per.set(h.col, (per.get(h.col) ?? 0) + 1);
    maxHeads = Math.max(maxHeads, ...per.values(), 0);
    for (const h of s.heads) {
      assert.ok(h.col >= 0 && h.col < s.cols);
      assert.ok(h.y < s.rows + 1, 'heads leave at the bottom');
    }
    for (const i of s.headCells()) assert.ok(i >= 0 && i < s.cols * s.rows);
  }
  for (let i = 0; i < s.cols * s.rows; i++) {
    const l = s.level(i);
    assert.ok(l >= 0 && l <= 1);
    if (l > 0) {
      lit++;
      setsSeen.add(s.set[i]);
      assert.ok(s.glyph[i] < counts[s.set[i]], 'glyph index within its set');
    }
  }
  assert.ok(maxHeads <= MAX_PER_COL, `at most ${MAX_PER_COL} heads per column`);
  const share = lit / (s.cols * s.rows);
  assert.ok(share > 0.08 && share < 0.7, `lit share ${share.toFixed(2)}: rain, not empty, not solid`);
  assert.deepEqual([...setsSeen].sort(), [0, 1], 'both sets fall when two are shown');
  console.log(`ok limits hold over 30 s; ${(share * 100).toFixed(0)} % of cells lit; mixed sets both fall`);
}

{
  // A tap: a head starts at that row and lights downwards from there.
  const s = new Sim(10, 20, [9], rng(1));
  s.nextStart.fill(Infinity); // no heads of their own
  s.start(4, 12);
  for (let f = 0; f < 15; f++) s.step(1 / 30);
  const litRows = [];
  for (let r = 0; r < 20; r++) if (s.level(r * 10 + 4) > 0) litRows.push(r);
  assert.ok(litRows.length > 0 && litRows[0] === 12, 'lit from the tapped row down');
  for (let c = 0; c < 10; c++) if (c !== 4) for (let r = 0; r < 20; r++) assert.equal(s.level(r * 10 + c), 0);
  // A third start in a column replaces its oldest head.
  s.start(4, 0);
  s.start(4, 3);
  assert.equal(s.heads.filter((h) => h.col === 4).length, MAX_PER_COL);
  console.log('ok a tap starts a head at its row; a full column drops its oldest head');
}
