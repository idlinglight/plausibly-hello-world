// Plain-node check of the prompt links in config.js: which title each
// round links (the asked one's; the capitals round the capital's), on made-up
// titles, so it doesn't depend on the data (data.test.mjs: checkTexts calls
// every round's link for every asked answer). The URL encoding is the
// engine's wiki.js (shared/map-quiz/tools/wiki.test.mjs). No packages:
// node images/germany-quiz/tools/links.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import config from '../site/config.js';
import { wikipediaUrl } from '../site/wiki.js';

// Each round links the German article named by the field of the states.js
// entry it asks about.
const entry = { wiki: 'Titel A', capitalWiki: 'Titel B' };
const field = (u) => Object.keys(entry).find((k) => u === wikipediaUrl('de', entry[k]));
assert.deepEqual(config.rounds.map((r) => [r.key, field(r.link(entry))]), [['states', 'wiki'], ['capitals', 'capitalWiki']]);
assert.ok(config.rounds[0].link(entry).startsWith('https://de.wikipedia.org/wiki/'));
console.log('ok every round links the asked title, German Wikipedia');

assert.equal(config.text.link('München'), 'München auf Wikipedia (neuer Tab)');
console.log('ok the link\'s name');
