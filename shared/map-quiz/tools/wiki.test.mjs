// Plain-node checks of the engine's wiki.js (Wikipedia article URLs for
// an image's config.js). No packages:
// node shared/map-quiz/tools/wiki.test.mjs   (Node 22.12+)
import assert from 'node:assert/strict';
import { wikipediaUrl } from '../site/wiki.js';

let checks = 0;
function check(name, fn) {
  fn();
  checks++;
  console.log('ok', name);
}

// The same encoding, written another way: character by character.
const spelled = (lang, t) => `https://${lang}.wikipedia.org/wiki/` + [...t].map((ch) => (ch === ' ' ? '_' : /[A-Za-z0-9\-_.!~*'(),/:]/.test(ch) ? ch
  : [...new TextEncoder().encode(ch)].map((b) => '%' + b.toString(16).toUpperCase().padStart(2, '0')).join(''))).join('');

check('titles: spaces as _, readable where Wikipedia is, ? # % & + part of the title', () => {
  for (const [title, path] of [
    ['Tirana', 'Tirana'],
    ['Bosnia and Herzegovina', 'Bosnia_and_Herzegovina'],
    ["Côte d'Ivoire", "C%C3%B4te_d'Ivoire"],
    ['Washington, D.C.', 'Washington,_D.C.'],
    ['Ōita Prefecture', '%C5%8Cita_Prefecture'],
    ["St. John's, Antigua and Barbuda", "St._John's,_Antigua_and_Barbuda"],
    ['Georgia (country)', 'Georgia_(country)'],
    ['AC/DC', 'AC/DC'],
    ['Star Wars: Episode IV – A New Hope', 'Star_Wars:_Episode_IV_%E2%80%93_A_New_Hope'],
    ['What? (film)', 'What%3F_(film)'],
    ['C#', 'C%23'],
    ['100% (song)', '100%25_(song)'],
    ['AT&T', 'AT%26T'],
    ['Rock+Roll', 'Rock%2BRoll'],
    ['東京', '%E6%9D%B1%E4%BA%AC'],
  ]) {
    const u = wikipediaUrl('en', title);
    assert.equal(u, 'https://en.wikipedia.org/wiki/' + path, title);
    assert.equal(u, spelled('en', title), title);
    assert.equal(new URL(u).href, u, `${title}: as the browser writes it`);
    assert.equal(decodeURIComponent(new URL(u).pathname.slice('/wiki/'.length)).replaceAll('_', ' '), title, `${title}: back`);
  }
});

check('languages: the host; a bad code or no title throws', () => {
  assert.equal(wikipediaUrl('de', 'Innere Stadt (Wien)'), 'https://de.wikipedia.org/wiki/Innere_Stadt_(Wien)');
  for (const lang of ['ja', 'simple', 'zh-yue', 'be-tarask', 'zh-min-nan']) assert.equal(new URL(wikipediaUrl(lang, 'X')).host, `${lang}.wikipedia.org`, lang);
  for (const lang of ['', 'e', 'EN', 'en_US', 'en.', '../x', 'en/wiki', 'evil.com#', undefined, 7])
    assert.throws(() => wikipediaUrl(lang, 'X'), /is not a Wikipedia language code/, String(lang));
  for (const title of [undefined, null, '', '  ', 7]) assert.throws(() => wikipediaUrl('en', title), /no Wikipedia title/, String(title));
});

console.log(`${checks} checks passed`);
