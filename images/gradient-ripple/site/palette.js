// palette.js: the slowly drifting gradient, shared by the WebGL and CSS paths.
//
// Three colour stops in OKLCH around a slowly wandering base hue (analogous
// scheme: neighbouring stops stay 26-62 degrees apart), lightness and chroma
// held in a calm band, chroma limited to what sRGB can show. Every parameter
// follows smooth value noise (Catmull-Rom through random knots tens of
// seconds apart, two octaves with incommensurate periods), so the motion is
// continuous, aperiodic and never jumps. Hue and angle are integrated from
// noisy rates, so over hours they wander through everything.
//
// Stops are blended with Gaussian weights in OKLab, then the blended chroma
// is pulled back toward the stops' mean chroma: this keeps midpoints from
// going grey (the "muddy middle" of plain sRGB or OKLab interpolation).
// The render shader in water.js implements blend() identically; keep the
// two in sync.

export const SIGMA = 0.36; // width of each stop's Gaussian weight (in t units)
export const CHROMA_KEEP = 0.75; // 0 = plain OKLab blend, 1 = keep mean chroma

const DEG = Math.PI / 180;
const clamp = (x, lo, hi) => (x < lo ? lo : x > hi ? hi : x);
const wrap360 = (x) => ((x % 360) + 360) % 360;
const unit = (v) => 0.5 + 0.5 * v; // [-1, 1] -> [0, 1]

// Integer hash -> [0, 1). Deterministic per (seed, knot index).
function hash01(seed, i) {
  let h = (seed ^ Math.imul(i | 0, 0x9e3779b1)) >>> 0;
  h = Math.imul(h ^ (h >>> 16), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

// Smooth 1D value noise in [-1, 1]: Catmull-Rom through random knots
// `period` seconds apart. C1-continuous, so there are no visible "stops".
function noise(seed, period, t) {
  const u = t / period;
  const i = Math.floor(u);
  const f = u - i;
  const p0 = hash01(seed, i - 1) * 2 - 1;
  const p1 = hash01(seed, i) * 2 - 1;
  const p2 = hash01(seed, i + 1) * 2 - 1;
  const p3 = hash01(seed, i + 2) * 2 - 1;
  const f2 = f * f;
  const f3 = f2 * f;
  const v =
    0.5 *
    (2 * p1 +
      (p2 - p0) * f +
      (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 +
      (3 * p1 - p0 - 3 * p2 + p3) * f3);
  return clamp(v, -1, 1);
}

// Two octaves; the second period is an irrational fraction of the first so
// the sum never lines up into an obvious rhythm.
function fbm(seed, period, t) {
  return 0.7 * noise(seed, period, t) + 0.3 * noise(seed ^ 0x5bd1e995, period * 0.381966, t);
}

// OKLab -> linear sRGB (Bjorn Ottosson's reference matrices).
export function oklabToLinear(L, a, b, out) {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.291485548 * b;
  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;
  out[0] = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  out[1] = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  out[2] = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return out;
}

const scratch = [0, 0, 0];
const inGamut = (c) => c[0] >= -1e-4 && c[0] <= 1.0001 && c[1] >= -1e-4 && c[1] <= 1.0001 && c[2] >= -1e-4 && c[2] <= 1.0001;

// Largest chroma at (L, hue) that still fits in sRGB.
function maxChroma(L, hDeg) {
  const ca = Math.cos(hDeg * DEG);
  const sa = Math.sin(hDeg * DEG);
  let lo = 0;
  let hi = 0.4;
  for (let i = 0; i < 14; i++) {
    const m = 0.5 * (lo + hi);
    if (inGamut(oklabToLinear(L, m * ca, m * sa, scratch))) lo = m;
    else hi = m;
  }
  return lo;
}

// Yellows and oranges only look good light: dark yellow is olive, dark
// orange is brown. Lightness floor per OKLCH hue, linearly interpolated.
const FLOOR_H = [0, 25, 45, 65, 85, 105, 125, 145, 170, 360];
const FLOOR_L = [0.44, 0.58, 0.68, 0.79, 0.86, 0.89, 0.84, 0.66, 0.46, 0.44];
function lightnessFloor(hDeg) {
  let i = 1;
  while (FLOOR_H[i] < hDeg) i++;
  const f = (hDeg - FLOOR_H[i - 1]) / (FLOOR_H[i] - FLOOR_H[i - 1]);
  return FLOOR_L[i - 1] + (FLOOR_L[i] - FLOOR_L[i - 1]) * f;
}

// Ambers and yellows need extra chroma at that lightness to read as "sunny"
// rather than mustard or khaki.
function chromaBoost(hDeg) {
  const c = Math.max(0, Math.cos((hDeg - 95) * 1.6 * DEG));
  return 0.05 * c * c;
}

function linearTo8bit(c) {
  c = clamp(c, 0, 1);
  const s = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.round(s * 255);
}

export class Palette {
  constructor(seed = (Math.random() * 4294967296) >>> 0) {
    this.seed = seed;
    this.ch = [];
    for (let k = 0; k < 16; k++) this.ch.push((seed + Math.imul(k + 1, 0x632be5ab)) >>> 0);
    this.t = 1000 + hash01(seed, 7) * 1e5; // random start point in noise space
    this.hue = hash01(seed, 11) * 360;
    this.angle = hash01(seed, 13) * 360; // CSS convention: 0 = to top, 90 = to right
    this.lab = new Float32Array(9); // 3 stops x (L, a, b)
    this.chroma = new Float32Array(3);
    this.pos = new Float32Array([0, 0.5, 1]);
    this.advance(0);
  }

  // Move the palette forward by dt seconds of drift time.
  advance(dt) {
    const t = (this.t += dt);
    const c = this.ch;
    this.hue = wrap360(this.hue + dt * 1.2 * fbm(c[0], 53, t)); // up to ~1.2 deg/s
    this.angle = wrap360(this.angle + dt * 2.0 * fbm(c[1], 41, t)); // up to ~2 deg/s

    const spreadA = 26 + 36 * unit(fbm(c[2], 67, t));
    const spreadB = 26 + 36 * unit(fbm(c[3], 79, t));
    const lMid = 0.67 + 0.05 * fbm(c[4], 151, t) + 0.025 * fbm(c[5], 47, t);
    // Signed: which end is lighter flips now and then, passing through "flat".
    const lAmp = (0.08 + 0.1 * unit(fbm(c[6], 73, t))) * fbm(c[7], 109, t);

    for (let i = 0; i < 3; i++) {
      const h = wrap360(i === 0 ? this.hue - spreadA : i === 1 ? this.hue : this.hue + spreadB);
      const l0 = i === 0 ? lMid - lAmp : i === 2 ? lMid + lAmp : lMid + 0.03 * fbm(c[8], 61, t);
      const L = clamp(Math.max(l0, lightnessFloor(h)), 0.42, 0.9);
      const want = 0.095 + 0.055 * unit(fbm(c[9 + i], 59 + 6 * i, t)) + chromaBoost(h);
      const C = Math.min(want, 0.94 * maxChroma(L, h));
      this.lab[i * 3] = L;
      this.lab[i * 3 + 1] = C * Math.cos(h * DEG);
      this.lab[i * 3 + 2] = C * Math.sin(h * DEG);
      this.chroma[i] = C;
    }
    this.pos[1] = 0.5 + 0.13 * fbm(c[12], 89, t);
  }

  // Gradient colour at t (0..1 along the gradient line) as OKLab.
  // Mirrors gradLab() in the render shader.
  blend(t, out) {
    t = clamp(t, -0.25, 1.25);
    let ws = 0;
    let L = 0;
    let A = 0;
    let B = 0;
    let C = 0;
    for (let i = 0; i < 3; i++) {
      const d = (t - this.pos[i]) / SIGMA;
      const w = Math.exp(-d * d);
      ws += w;
      L += w * this.lab[i * 3];
      A += w * this.lab[i * 3 + 1];
      B += w * this.lab[i * 3 + 2];
      C += w * this.chroma[i];
    }
    L /= ws;
    A /= ws;
    B /= ws;
    C /= ws;
    const len = Math.hypot(A, B);
    const k = (len + (C - len) * CHROMA_KEEP) / Math.max(len, 1e-5);
    out[0] = L;
    out[1] = A * k;
    out[2] = B * k;
    return out;
  }

  // Gradient colour at t as an 8-bit sRGB CSS string.
  cssColorAt(t) {
    const lab = this.blend(t, [0, 0, 0]);
    const rgb = oklabToLinear(lab[0], lab[1], lab[2], [0, 0, 0]);
    return `rgb(${linearTo8bit(rgb[0])}, ${linearTo8bit(rgb[1])}, ${linearTo8bit(rgb[2])})`;
  }

  // The same gradient as a CSS linear-gradient (sampled; for the no-WebGL path).
  cssGradient(samples = 9) {
    let s = `linear-gradient(${this.angle.toFixed(2)}deg`;
    for (let i = 0; i < samples; i++) {
      const t = i / (samples - 1);
      s += `, ${this.cssColorAt(t)} ${(t * 100).toFixed(1)}%`;
    }
    return s + ')';
  }

  // Position along the gradient line (CSS semantics) of point (x, y), in CSS
  // px with y pointing down, for a w x h box.
  tAt(x, y, w, h) {
    const a = this.angle * DEG;
    const dx = Math.sin(a);
    const dy = Math.cos(a);
    const len = Math.abs(w * dx) + Math.abs(h * dy);
    return 0.5 + ((x - w / 2) * dx + (h / 2 - y) * dy) / len;
  }
}
