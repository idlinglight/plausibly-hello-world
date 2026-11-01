// wheel.js: mouse wheel or trackpad? Plain wheel events don't say which
// device sent them, so main.js asks this once per gesture (its first event)
// and keeps the answer through the gesture, momentum included. No DOM: the
// replay test (shared/map-quiz/tools/wheel.test.mjs) runs it under plain
// node against recorded events (wheel-fixture.json beside it).
// Shared map-quiz engine file: the source is shared/map-quiz/site/, images
// get byte-identical copies (python3 shared/sync.py). Edit the source.
//
// Rules, from real devices on macOS (Safari 27, Chrome 156, Firefox 159, a
// built-in trackpad and a wheel mouse, at 100 % and 125 % page zoom):
// 1. deltaMode LINE / PAGE → mouse. Firefox reports a mouse wheel in lines
//    (at any zoom) — but only if deltaMode is read before deltaX / deltaY,
//    otherwise it converts lines to pixels; callers read it first.
// 2. deltaX ≠ 0 → trackpad: a mouse wheel scrolls one axis. (Shift + wheel
//    on macOS gives deltaX too; it pans sideways then, which is fine.)
// 3. Trackpad deltas are whole pixels: whole CSS pixels in Safari (which
//    doesn't scale wheel deltas with page zoom), whole device pixels
//    (deltaY × devicePixelRatio) in Chrome and Firefox, which do (0.8 CSS px
//    at 125 % is 2 device px). A macOS mouse notch is 4.000244140625 CSS px
//    (divided by the zoom in Chrome) and accelerated steps are fractional
//    too: whole in neither unit → mouse.
// 4. Whole pixels with wheelDeltaY a multiple of ±120 → mouse: Chrome's
//    notch count, as on other systems where a notch is e.g. 100 whole px
//    (not recorded here; on macOS trackpads open with |wheelDeltaY| < 120).
//    Also when wheelDeltaY × devicePixelRatio is one: Chrome can divide
//    wheel deltas by the device pixel ratio (seen with emulated ratios in
//    headless Chrome: a −120 notch arrives as −40 / 40 at ratio 3).
// 5. Otherwise trackpad.
// Not caught: a mouse whose steps come out whole in CSS or device pixels
// without 120-steps (seen nowhere so far; possible elsewhere, or under page
// zoom off macOS). It pans then; ctrl + wheel, pinch, the buttons and the
// keys still zoom. The -3 × deltaY relation of wheelDeltaY is no use:
// WebKit reports it for mouse wheels too.

const whole = (v) => Math.abs(v - Math.round(v)) < 1e-5;
const notches = (v) => v !== 0 && whole(v / 120);

// e: { deltaMode, deltaX, deltaY, wheelDeltaY } (deltaMode read first),
// dpr: window.devicePixelRatio.
export function wheelKind(e, dpr = 1) {
  if (e.deltaMode !== 0) return 'mouse';
  if (e.deltaX !== 0) return 'trackpad';
  const dy = e.deltaY;
  if (!whole(dy) && !whole(dy * dpr)) return 'mouse';
  const w = e.wheelDeltaY;
  if (typeof w === 'number' && (notches(w) || notches(w * dpr))) return 'mouse';
  return 'trackpad';
}
