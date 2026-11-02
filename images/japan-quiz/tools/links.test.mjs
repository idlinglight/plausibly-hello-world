// Plain-node checks of the prompt links in config.js: which title each
// round links (the asked one's: a capital round the capital's) and the
// URL encoding, on made-up titles, so they don't depend on the data
// (data.test.mjs: checkTexts calls every round's link for every asked
// answer). No packages:
// node images/japan-quiz/tools/links.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import config from '../site/config.js';

const W = 'https://en.wikipedia.org/wiki/';

// Each round links the field of the japan.js entry it asks about.
assert.deepEqual(config.rounds.map((r) => [r.key, r.link({ wiki: 'wiki', capitalWiki: 'capitalWiki' }).slice(W.length)]),
  [['islands', 'wiki'], ['regions', 'wiki'], ['prefectures', 'wiki'], ['capitals', 'capitalWiki']]);
console.log('ok every round links the asked title');

// Spaces as _, the rest as Wikipedia's own URLs have it; ? # % & + stay
// part of the title; every URL as the browser would write it, and back.
const link = config.rounds[0].link;
for (const [title, path] of [
  ['Tirana', 'Tirana'],
  ['Bosnia and Herzegovina', 'Bosnia_and_Herzegovina'],
  ["Côte d'Ivoire", "C%C3%B4te_d'Ivoire"],
  ['Washington, D.C.', 'Washington,_D.C.'],
  ['Ōita Prefecture', '%C5%8Cita_Prefecture'],
  ['Saint John\'s, Antigua and Barbuda', "Saint_John's,_Antigua_and_Barbuda"],
  ['AC/DC', 'AC/DC'],
  ['Star Wars: Episode IV – A New Hope', 'Star_Wars:_Episode_IV_%E2%80%93_A_New_Hope'],
  ['What? (film)', 'What%3F_(film)'],
  ['C#', 'C%23'],
  ['100% (song)', '100%25_(song)'],
  ['AT&T', 'AT%26T'],
  ['Rock+Roll', 'Rock%2BRoll'],
]) {
  const u = link({ wiki: title });
  assert.equal(u, W + path, title);
  assert.equal(new URL(u).href, u, title);
  assert.equal(decodeURIComponent(new URL(u).pathname.slice('/wiki/'.length)).replaceAll('_', ' '), title, title);
}
console.log('ok titles encoded, readable where Wikipedia is');

for (const missing of [undefined, '', null]) assert.throws(() => link({ wiki: missing }), /no Wikipedia title/);
console.log('ok a missing title throws (checkTexts names the answer)');

assert.equal(config.text.link('Shinjuku'), 'Shinjuku on Wikipedia (opens a new tab)');
console.log('ok the link\'s name');
