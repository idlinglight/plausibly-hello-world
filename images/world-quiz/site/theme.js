// theme.js: light/dark theme. A classic script in <head>, after the
// stylesheet, so <html data-theme> is set before the first paint (no flash
// of the other theme).
// Shared map-quiz engine file: the source is shared/map-quiz/site/, images
// get byte-identical copies (python3 shared/sync.py). Edit the source.
//
// The page follows the OS (prefers-color-scheme) unless an override is
// stored. The toggle button (#theme) stores the other theme while following
// the OS, and clears the override while one is set — back to following the
// OS. An override that matches the OS is dropped (at load and live, when
// the OS setting changes), so the override always differs from the OS and
// every press of the toggle visibly switches.
//
// <html data-theme> = the theme shown (light | dark);
// <html data-theme-pref> = auto | light | dark (the stored override).
// The override is stored per image: localStorage "phw-<data-quiz>-theme",
// <html data-quiz> being the image's name. The theme-color meta follows
// the --sea colour (the page background). No text here: main.js labels the
// button from the image's config (it watches the two attributes).
(function () {
  'use strict';
  var root = document.documentElement;
  var KEY = 'phw-' + (root.getAttribute('data-quiz') || 'map-quiz') + '-theme';
  var query = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var override = load();

  function os() {
    return query && query.matches ? 'dark' : 'light';
  }

  function load() {
    try {
      var v = localStorage.getItem(KEY);
      return v === 'light' || v === 'dark' ? v : null;
    } catch (e) {
      return null;
    }
  }

  function store(v) {
    try {
      if (v) localStorage.setItem(KEY, v);
      else localStorage.removeItem(KEY);
    } catch (e) {
      // storage blocked: the override lasts until the page is left
    }
  }

  function apply() {
    if (override && override === os()) {
      override = null;
      store(null);
    }
    root.setAttribute('data-theme', override || os());
    root.setAttribute('data-theme-pref', override || 'auto');
    var meta = document.querySelector('meta[name="theme-color"]');
    var sea = getComputedStyle(root).getPropertyValue('--sea').trim();
    if (meta && sea) meta.setAttribute('content', sea);
  }

  function toggle() {
    override = override ? null : os() === 'dark' ? 'light' : 'dark';
    store(override);
    apply();
  }

  apply();
  if (query) {
    if (query.addEventListener) query.addEventListener('change', apply);
    else if (query.addListener) query.addListener(apply);
  }
  // Another tab changed the override.
  window.addEventListener('storage', function (e) {
    if (e.key === KEY || e.key === null) {
      override = load();
      apply();
    }
  });
  document.addEventListener('DOMContentLoaded', function () {
    var button = document.getElementById('theme');
    if (button) button.addEventListener('click', toggle);
    apply();
  });
})();
