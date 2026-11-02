// Plain-node check of the prompt links in config.js: which title each
// round links (the asked one's; the capital rounds the capital's), on made-up
// titles, so it doesn't depend on the data (data.test.mjs: checkTexts calls
// every round's link for every asked answer). The URL encoding is the
// engine's wiki.js (shared/map-quiz/tools/wiki.test.mjs). No packages:
// node images/world-quiz/tools/links.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import config from '../site/config.js';
import { wikipediaUrl } from '../site/wiki.js';

// Each round links the English article named by the field of the countries.js
// entry it asks about.
const entry = { wiki: 'Title A', capitalWiki: 'Title B' };
const field = (u) => Object.keys(entry).find((k) => u === wikipediaUrl('en', entry[k]));
assert.deepEqual(config.rounds.map((r) => [r.key, field(r.link(entry))]), [['countries', 'wiki'], ['capitals', 'capitalWiki'], ['all-countries', 'wiki'], ['all-capitals', 'capitalWiki']]);
console.log('ok every round links the asked title, English Wikipedia');

assert.equal(config.text.link('Shinjuku'), 'Shinjuku on Wikipedia (opens a new tab)');
console.log('ok the link\'s name');
