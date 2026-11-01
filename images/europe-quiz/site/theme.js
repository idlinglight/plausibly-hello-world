// theme.js: light/dark theme. A classic script in <head>, after the
// stylesheet, so <html data-theme> is set before the first paint (no flash
// of the other theme).
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
// The theme-color meta follows the --sea colour (the page background).
(function () {
  'use strict';
  var KEY = 'phw-europe-quiz-theme';
  var root = document.documentElement;
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
    var theme = override || os();
    var other = theme === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', theme);
    root.setAttribute('data-theme-pref', override || 'auto');
    var meta = document.querySelector('meta[name="theme-color"]');
    var sea = getComputedStyle(root).getPropertyValue('--sea').trim();
    if (meta && sea) meta.setAttribute('content', sea);
    var button = document.getElementById('theme');
    if (button) {
      button.setAttribute('aria-label', 'Switch to ' + other + ' theme');
      button.title = override ? 'Back to the system setting (' + other + ')' : 'Switch to the ' + other + ' theme';
    }
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
