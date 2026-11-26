// wiki.js: Wikipedia article URLs for an image's config.js (rounds[].link),
// e.g. link: (c) => wikipediaUrl('en', c.wiki). A helper images may use;
// main.js doesn't load it, and the rest of the engine knows nothing about
// Wikipedia. No DOM (node tests: shared/map-quiz/tools/wiki.test.mjs).
// Shared map-quiz engine file: the source is shared/map-quiz/site/, images
// get byte-identical copies (python3 shared/sync.py). Edit the source.

// A Wikipedia language code: en, de, ja, simple, zh-yue, be-tarask …
const LANG = /^[a-z]{2,10}(-[a-z]{2,10}){0,2}$/;

// The article's URL as Wikipedia writes them: spaces as _, percent-encoded
// (UTF-8) but for letters, digits, - _ . ! ~ * ' ( ) , / : (so ? # % & +
// stay part of the title). Throws on a bad language code or no title, so
// checkTexts names the answer that has none.
export function wikipediaUrl(lang, title) {
  if (typeof lang !== 'string' || !LANG.test(lang)) throw new Error(`wikipediaUrl: language ${JSON.stringify(lang)} is not a Wikipedia language code (e.g. 'en')`);
  if (typeof title !== 'string' || !title.trim()) throw new Error(`no Wikipedia title: ${JSON.stringify(title)}`);
  const path = encodeURIComponent(title.replaceAll(' ', '_')).replace(/%2C|%2F|%3A/g, decodeURIComponent);
  return `https://${lang}.wikipedia.org/wiki/${path}`;
}
