// water.js: WebGL heightfield water over the drifting gradient.
//
// Passes (all full-screen triangles):
//   drop    state -> state'   add queued tap/drag/hold impulses
//   sim     state -> state'   damped wave equation, leapfrog, 9-point
//                             isotropic Laplacian (round rings, not
//                             diamonds), a little viscosity against grid
//                             noise and an absorbing sponge at the edges
//   surface state -> surface  slope + curvature, interpolated between the
//                             last two sim steps (smooth at any refresh rate)
//   render  surface -> screen gradient refracted by the slope, lit (shade,
//                             caustic brightening, specular glint), dithered
//
// The sim runs on a coarse grid (2.5-4 CSS px per cell) at a fixed step rate,
// so wave speed in CSS px/s is the same on every device. When nothing has
// been touched for a few seconds the sim parks (state zeroed, no sim passes)
// and only the gradient is redrawn, at a low frame rate (see main.js). The
// shading fades out before that, so faint leftover rings never snap flat.
//
// Render-target formats, best first; each candidate must give a complete
// framebuffer *and* survive a write/read-back test, otherwise the next is
// tried:
//   WebGL2: RGBA16F (EXT_color_buffer_float or _half_float), RGBA32F
//   WebGL1: HALF_FLOAT_OES, FLOAT (if the implementation can render to them)
//   both:   RGBA8 with heights packed as 16-bit fixed point (needs highp)
// The surface texture is sampled with LINEAR filtering; when the float format
// isn't filterable it is RGBA8 too, with sqrt-companded values (precision
// where it matters: near zero). If nothing works, createWater() returns null
// and main.js uses the CSS + canvas-2D fallback.
//
// Known, packed tier only: for slow, smooth motion the per-step velocity
// damping is less than half a fixed-point step, so it never rounds through
// and the mean water level creeps up while the sim runs (measured: ~1e-3 per
// second on a 128x192 grid, ~1.5e-3 on 320x200, against RANGE = 4; the float
// tiers stay within ~1e-4). Invisible (rendering uses slopes only) and zeroed
// when the sim parks; main.js's HOLD_MAX keeps a still hold from running it up.

import { SIGMA, CHROMA_KEEP } from './palette.js';

const T = {
  minCellPx: 2.5, // CSS px per sim cell, lower bound...
  maxCellsLong: 640, // ...raised on big screens so the long side stays <= this
  speedPx: 165, // wave speed, CSS px per second
  courant2: 0.45, // (c dt / dx)^2 per step; stable up to ~0.6 here
  decay: 0.4, // amplitude decay rate, 1/s
  visc: 0.03, // per-step viscous smoothing
  spongeCells: 24, // absorbing border width
  spongeMin: 0.93, // velocity kept per step at the very edge
  heightPx: 26, // CSS px of surface height per sim unit (slope -> light)
  refractPx: 40, // apparent floor shift, CSS px per unit slope
  shade: 0.42, // OKLab L change for a fully tilted slope
  spec: 0.75,
  caustic: 0.4,
  dropPx: 44, // impulse radius (crater + rims)
  dropAmp: -0.35, // impulse depth (sim units)
  settle: 10, // seconds after the last impulse before the sim parks...
  fadeOut: 2.5, // ...with the last of these spent fading the shading to zero
  maxSteps: 8, // sim steps per frame at most (slow frames slow the sim)
  maxRenderScale: 1.5, // device-pixel-ratio cap
  maxRenderPixels: 2.4e6, // drawing-buffer pixel cap (4K screens, TVs)
};
const MAX_DROPS = 16;

const VERT = `attribute vec2 aPos;
varying vec2 vUv;
void main() {
  vUv = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

// Shared fragment prelude: precision + state/surface encodings for the tier.
function prelude(statePacked, surfPacked) {
  const state = statePacked
    ? `
// Heights as 16-bit fixed point in two 8-bit channels; 0 is exact (128, 0).
vec2 pack16(float h) {
  float x = clamp(floor(h * (32768.0 / RANGE) + 32768.5), 0.0, 65535.0);
  float hi = floor(x / 256.0);
  return (vec2(hi, x - hi * 256.0) + 0.25) / 255.0;
}
float unpack16(vec2 v) {
  vec2 b = floor(v * 255.0 + 0.5);
  return (b.x * 256.0 + b.y - 32768.0) * (RANGE / 32768.0);
}
vec4 encState(vec2 s) { return vec4(pack16(s.x), pack16(s.y)); }
vec2 decState(vec4 v) { return vec2(unpack16(v.xy), unpack16(v.zw)); }`
    : `
vec4 encState(vec2 s) { return vec4(clamp(s, -RANGE, RANGE), 0.0, 1.0); }
vec2 decState(vec4 v) { return v.xy; }`;
  const surf = surfPacked
    ? `
// sqrt companding: small slopes keep their precision in 8 bits.
vec4 encSurf(vec4 s) {
  vec4 x = clamp(s / SURF_SCALE, -1.0, 1.0);
  return 0.5 + 0.5 * sign(x) * sqrt(abs(x));
}
vec4 decSurf(vec4 v) {
  vec4 d = v * 2.0 - 1.0;
  return sign(d) * d * d * SURF_SCALE;
}`
    : `
vec4 encSurf(vec4 s) { return s; }
vec4 decSurf(vec4 v) { return v; }`;
  return `#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 vUv;
const float RANGE = 4.0;
const vec4 SURF_SCALE = vec4(1.0, 1.0, RANGE, 1.0);
${state}
${surf}
`;
}

const FILL = `
uniform vec2 uValue;
uniform float uSurface;
void main() {
  gl_FragColor = uSurface > 0.5 ? encSurf(vec4(0.0)) : encState(uValue);
}`;

const PROBE = `
uniform sampler2D uState;
void main() {
  gl_FragColor = vec4(decState(texture2D(uState, vUv)) / 8.0 + 0.5, 0.0, 1.0);
}`;

// Resize: carry the old grid over, anchored at the top-left in CSS px (the
// water stays where it was on screen), bilinear so nothing turns blocky.
const COPY = `
uniform sampler2D uState;
uniform vec2 uOldGrid;
uniform vec2 uScale; // new view size / old view size
vec2 T(vec2 cell) { return decState(texture2D(uState, (cell + 0.5) / uOldGrid)); }
void main() {
  vec2 uv = vec2(vUv.x * uScale.x, 1.0 - (1.0 - vUv.y) * uScale.y);
  vec2 x = uv * uOldGrid - 0.5;
  vec2 i = floor(x);
  vec2 f = x - i;
  vec2 s = mix(mix(T(i), T(i + vec2(1.0, 0.0)), f.x), mix(T(i + vec2(0.0, 1.0)), T(i + vec2(1.0, 1.0)), f.x), f.y);
  float inside = step(0.0, uv.x) * step(uv.x, 1.0) * step(0.0, uv.y) * step(uv.y, 1.0);
  gl_FragColor = encState(s * inside);
}`;

const DROP = `
uniform sampler2D uState;
uniform vec2 uGrid;
uniform vec4 uDrops[${MAX_DROPS}]; // x, y, radius (cells), amount
uniform int uCount;
void main() {
  vec2 s = decState(texture2D(uState, vUv));
  vec2 p = vUv * uGrid;
  float add = 0.0;
  for (int i = 0; i < ${MAX_DROPS}; i++) {
    if (i >= uCount) break;
    vec4 d = uDrops[i];
    float r = min(length(p - d.xy) / d.z, 1.0);
    // A crater with a raised rim and a second, fainter trough, windowed to
    // zero at the radius: released, it sheds a train of rings instead of a
    // single bump (the wave equation here is nearly non-dispersive, so the
    // train has to be in the impulse).
    add += d.w * cos(9.424778 * r) * (0.5 + 0.5 * cos(3.14159265 * r));
  }
  // Same offset on both: a displaced surface at rest, released.
  gl_FragColor = encState(s + add);
}`;

const SIM = `
uniform sampler2D uState;
uniform vec2 uTexel;
uniform float uC;
uniform float uDamp;
uniform float uVisc;
uniform vec2 uSponge;
uniform float uSpongeMin;
vec2 S(float x, float y) { return decState(texture2D(uState, vUv + vec2(x, y) * uTexel)); }
void main() {
  vec2 c = S(0.0, 0.0);
  vec2 n = S(0.0, 1.0);
  vec2 s = S(0.0, -1.0);
  vec2 e = S(1.0, 0.0);
  vec2 w = S(-1.0, 0.0);
  float diag = S(1.0, 1.0).x + S(-1.0, 1.0).x + S(1.0, -1.0).x + S(-1.0, -1.0).x;
  float lap = (4.0 * (n.x + s.x + e.x + w.x) + diag - 20.0 * c.x) / 6.0;
  float v = c.x - c.y;
  float lapV = (n.x - n.y) + (s.x - s.y) + (e.x - e.y) + (w.x - w.y) - 4.0 * v;
  vec2 edge = min(vUv, 1.0 - vUv) / uSponge;
  float keep = mix(uSpongeMin, 1.0, smoothstep(0.0, 1.0, min(edge.x, edge.y)));
  float h = c.x + v * uDamp * keep + uC * lap + uVisc * lapV;
  gl_FragColor = encState(vec2(h, c.x));
}`;

const SURFACE = `
uniform sampler2D uState;
uniform vec2 uTexel;
uniform float uAlpha;
float H(float x, float y) {
  vec2 s = decState(texture2D(uState, vUv + vec2(x, y) * uTexel));
  return mix(s.y, s.x, uAlpha);
}
void main() {
  float c = H(0.0, 0.0);
  float l = H(-1.0, 0.0);
  float r = H(1.0, 0.0);
  float b = H(0.0, -1.0);
  float t = H(0.0, 1.0);
  gl_FragColor = encSurf(vec4(0.5 * (r - l), 0.5 * (t - b), c, l + r + b + t - 4.0 * c));
}`;

const RENDER = `
uniform sampler2D uSurf;
uniform vec2 uRes;
uniform vec3 uLab0;
uniform vec3 uLab1;
uniform vec3 uLab2;
uniform vec3 uChroma;
uniform vec3 uPos;
uniform vec2 uDir;
uniform float uInvLen;
uniform float uSlope;
uniform float uCurv;
uniform float uRefract;
uniform float uShade;
uniform float uSpec;
uniform float uCaustic;

const float SIGMA = ${SIGMA.toFixed(5)};
const float KEEP = ${CHROMA_KEEP.toFixed(5)};
const vec3 LIGHT = vec3(-0.4511, 0.5514, 0.7018); // normalize(-0.45, 0.55, 0.70)
const vec3 HALFV = vec3(-0.2445, 0.2989, 0.9225); // normalize(LIGHT + view)
const float SPEC_FLAT = 0.0207; // pow(HALFV.z, 48.0)

float wgt(float t, float p) { float d = (t - p) / SIGMA; return exp(-d * d); }

// Mirrors Palette.blend() in palette.js.
vec3 gradLab(float t) {
  t = clamp(t, -0.25, 1.25);
  float w0 = wgt(t, uPos.x);
  float w1 = wgt(t, uPos.y);
  float w2 = wgt(t, uPos.z);
  float ws = w0 + w1 + w2;
  vec3 lab = (w0 * uLab0 + w1 * uLab1 + w2 * uLab2) / ws;
  float cm = dot(vec3(w0, w1, w2), uChroma) / ws;
  float len = length(lab.yz);
  lab.yz *= mix(len, cm, KEEP) / max(len, 1e-5);
  return lab;
}

vec3 oklabToLinear(vec3 c) {
  float l = c.x + 0.3963377774 * c.y + 0.2158037573 * c.z;
  float m = c.x - 0.1055613458 * c.y - 0.0638541728 * c.z;
  float s = c.x - 0.0894841775 * c.y - 1.2914855480 * c.z;
  vec3 k = vec3(l, m, s);
  k = k * k * k;
  return vec3(
     4.0767416621 * k.x - 3.3077115913 * k.y + 0.2309699292 * k.z,
    -1.2684380046 * k.x + 2.6097574011 * k.y - 0.3413193965 * k.z,
    -0.0041960863 * k.x - 0.7034186147 * k.y + 1.7076147010 * k.z);
}

vec3 toSrgb(vec3 c) {
  c = clamp(c, 0.0, 1.0);
  vec3 hi = 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055;
  return mix(c * 12.92, hi, step(0.0031308, c));
}

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}

void main() {
  vec4 s = decSurf(texture2D(uSurf, gl_FragCoord.xy / uRes));
  vec2 slope = s.xy * uSlope;
  // Mild dynamic-range compression: fading rings stay readable a little
  // longer, fresh ones don't blow out (1 at |slope| = 0.5).
  slope *= pow(length(slope) * 2.0 + 1e-6, -0.25);
  // Looking down through the water: the floor (the gradient) shifts with slope.
  vec2 p = gl_FragCoord.xy - 0.5 * uRes - slope * uRefract;
  vec3 lab = gradLab(0.5 + dot(p, uDir) * uInvLen);
  vec3 n = normalize(vec3(-slope, 1.0));
  // Slopes facing the light get brighter, the others darker; crests focus
  // light (negative curvature), troughs spread it.
  float curv = s.w * uCurv;
  lab.x += uShade * (dot(n, LIGHT) - LIGHT.z) - uCaustic * curv / (1.0 + 4.0 * abs(curv));
  vec3 rgb = oklabToLinear(lab);
  // Glint, minus what a flat surface would get (flat water stays the pure gradient).
  float spec = max(pow(max(dot(n, HALFV), 0.0), 48.0) - SPEC_FLAT, 0.0) / (1.0 - SPEC_FLAT);
  rgb += uSpec * spec * vec3(1.0, 0.97, 0.93);
  vec3 srgb = toSrgb(rgb);
  // Triangular dither against banding in slow, wide gradients.
  srgb += (hash12(gl_FragCoord.xy) + hash12(gl_FragCoord.xy + 71.37) - 1.0) / 255.0;
  gl_FragColor = vec4(srgb, 1.0);
}`;

const CTX_ATTRS = {
  alpha: false,
  antialias: false,
  depth: false,
  stencil: false,
  premultipliedAlpha: false,
  preserveDrawingBuffer: false,
  powerPreference: 'low-power', // an always-on page: integrated GPU is plenty
  failIfMajorPerformanceCaveat: true, // software GL at full screen would hog the CPU
};

// Returns a Water instance, or null if WebGL (or every render-target
// format) is unusable here.
export function createWater(canvas, settings, opts) {
  let gl = null;
  let gl2 = false;
  try {
    if (!opts.forceWebGL1) {
      gl = canvas.getContext('webgl2', CTX_ATTRS);
      gl2 = !!gl;
    }
    if (!gl) gl = canvas.getContext('webgl', CTX_ATTRS) || canvas.getContext('experimental-webgl', CTX_ATTRS);
  } catch (e) {
    gl = null;
  }
  if (!gl) return null;
  const water = new Water(canvas, gl, gl2, settings, opts);
  return water.init() ? water : null;
}

class Water {
  constructor(canvas, gl, gl2, settings, opts) {
    this.canvas = canvas;
    this.gl = gl;
    this.gl2 = gl2;
    this.settings = settings;
    this.opts = opts;
    this.ready = false;
    this.view = opts.view || { w: 1, h: 1, dpr: 1 }; // main.js's live, measured view
    this.gw = 0;
    this.gh = 0;
    this.cur = 0;
    this.drops = [];
    this.dropBuf = new Float32Array(MAX_DROPS * 4);
    this.clock = 0;
    this.activeUntil = -1;
    this.live = false; // sim running (vs. parked at rest)
    this.acc = 0; // fractional sim steps carried between frames
    this.label = '';
    this.listening = false;
  }

  // (Re)create every GL resource; also used after context restore.
  init() {
    const gl = this.gl;
    this.ready = false;
    this.gw = this.gh = 0;
    this.state = null;
    this.surf = null;
    this.live = false;
    this.drops.length = 0;
    if (gl.isContextLost()) return false;

    this.vs = this.compile(gl.VERTEX_SHADER, VERT);
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.BLEND);
    if (!this.vs) return false;

    const rgba8 = { name: 'rgba8', internal: gl.RGBA, type: gl.UNSIGNED_BYTE, packed: true, linear: true };
    this.rgba8 = rgba8;
    const fmt = this.pickFormat(rgba8);
    if (!fmt) return false;
    this.fmt = fmt;
    this.surfFmt = !fmt.packed && fmt.linear ? fmt : rgba8;
    this.surfPacked = this.surfFmt === rgba8;

    const pre = prelude(fmt.packed, this.surfPacked);
    this.p = {};
    for (const [name, src] of Object.entries({ FILL, COPY, DROP, SIM, SURFACE, RENDER })) {
      const prog = this.program(pre + src);
      if (!prog) return false;
      this.p[name] = prog;
    }
    this.label = `${this.gl2 ? 'webgl2' : 'webgl1'} ${fmt.name}${this.surfPacked && !fmt.packed ? ' (surface rgba8)' : ''}`;

    if (!this.listening) {
      this.listening = true;
      this.canvas.addEventListener('webglcontextlost', (e) => {
        e.preventDefault(); // tells the browser we want it restored
        this.ready = false;
        this.opts.onLost();
      });
      this.canvas.addEventListener('webglcontextrestored', () => {
        if (this.init()) this.opts.onRestored();
        // Lost again while re-initialising: another 'restored' will follow
        // and retries. Only a genuine failure is reported (main.js stays on
        // the fallback, but a later loss/restore cycle can still recover).
        else if (!this.gl.isContextLost()) this.opts.onFail();
      });
    }
    this.ready = true;
    this.resize(this.view);
    if (!this.state) this.ready = false; // couldn't allocate the grid after all
    return this.ready;
  }

  compile(type, src) {
    const gl = this.gl;
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      if (!gl.isContextLost()) console.warn('gradient-ripple: shader compile failed', gl.getShaderInfoLog(sh));
      gl.deleteShader(sh);
      return null;
    }
    return sh;
  }

  program(fragSrc) {
    const gl = this.gl;
    const fs = this.compile(gl.FRAGMENT_SHADER, fragSrc);
    if (!fs) return null;
    const prog = gl.createProgram();
    gl.attachShader(prog, this.vs);
    gl.attachShader(prog, fs);
    gl.bindAttribLocation(prog, 0, 'aPos');
    gl.linkProgram(prog);
    gl.deleteShader(fs);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      if (!gl.isContextLost()) console.warn('gradient-ripple: program link failed', gl.getProgramInfoLog(prog));
      gl.deleteProgram(prog);
      return null;
    }
    const u = {};
    const n = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < n; i++) {
      const name = gl.getActiveUniform(prog, i).name.replace(/\[0\]$/, '');
      u[name] = gl.getUniformLocation(prog, name);
    }
    return { prog, u };
  }

  // Try render-target formats best-first; the first one that is complete and
  // round-trips a known value through encode/decode wins.
  pickFormat(rgba8) {
    const gl = this.gl;
    const cands = [];
    if (!this.opts.forcePacked) {
      if (this.gl2) {
        const cbf = gl.getExtension('EXT_color_buffer_float');
        const cbhf = gl.getExtension('EXT_color_buffer_half_float');
        if (cbf || cbhf) cands.push({ name: 'rgba16f', internal: gl.RGBA16F, type: gl.HALF_FLOAT, packed: false, linear: true });
        if (cbf) {
          const lin = !!gl.getExtension('OES_texture_float_linear');
          cands.push({ name: 'rgba32f', internal: gl.RGBA32F, type: gl.FLOAT, packed: false, linear: lin });
        }
      } else {
        const hf = gl.getExtension('OES_texture_half_float');
        if (hf) {
          gl.getExtension('EXT_color_buffer_half_float');
          const lin = !!gl.getExtension('OES_texture_half_float_linear');
          cands.push({ name: 'half-float', internal: gl.RGBA, type: hf.HALF_FLOAT_OES, packed: false, linear: lin });
        }
        if (gl.getExtension('OES_texture_float')) {
          gl.getExtension('WEBGL_color_buffer_float');
          const lin = !!gl.getExtension('OES_texture_float_linear');
          cands.push({ name: 'float', internal: gl.RGBA, type: gl.FLOAT, packed: false, linear: lin });
        }
      }
    }
    cands.push(rgba8);
    for (const f of cands) if (this.testFormat(f, rgba8)) return f;
    return null;
  }

  testFormat(f, rgba8) {
    const gl = this.gl;
    while (gl.getError() !== gl.NO_ERROR && !gl.isContextLost());
    const pre = prelude(f.packed, false);
    const fill = this.program(pre + FILL);
    const probe = this.program(pre + PROBE);
    const a = this.target(f, 2, 2, gl.NEAREST);
    const b = this.target(rgba8, 2, 2, gl.NEAREST);
    let ok = false;
    if (fill && probe && a && b) {
      gl.useProgram(fill.prog);
      gl.uniform2f(fill.u.uValue, 0.3125, -1.25);
      gl.uniform1f(fill.u.uSurface, 0);
      this.draw(a);
      gl.useProgram(probe.prog);
      gl.bindTexture(gl.TEXTURE_2D, a.tex);
      this.draw(b);
      const px = new Uint8Array(16);
      gl.readPixels(0, 0, 2, 2, gl.RGBA, gl.UNSIGNED_BYTE, px);
      // 0.3125 / 8 + 0.5 -> 137.5; -1.25 / 8 + 0.5 -> 87.7
      ok = gl.getError() === gl.NO_ERROR && Math.abs(px[0] - 137.5) <= 1.5 && Math.abs(px[1] - 87.7) <= 1.5;
    }
    for (const p of [fill, probe]) if (p) gl.deleteProgram(p.prog);
    for (const t of [a, b]) if (t) this.free(t);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return ok;
  }

  target(f, w, h, filter) {
    const gl = this.gl;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, f.internal, w, h, 0, gl.RGBA, f.type, null);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    const complete = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    const t = { tex, fb, w, h };
    if (!complete) {
      this.free(t);
      return null;
    }
    return t;
  }

  free(t) {
    this.gl.deleteFramebuffer(t.fb);
    this.gl.deleteTexture(t.tex);
  }

  // Draw the full-screen triangle into target (null = canvas). The program
  // and its uniforms/texture must already be set.
  draw(t) {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, t ? t.fb : null);
    if (t) gl.viewport(0, 0, t.w, t.h);
    else gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  resize(view) {
    this.view = view;
    if (!this.ready) return;
    const w = Math.max(1, view.w);
    const h = Math.max(1, view.h);
    const scale = Math.min(view.dpr, T.maxRenderScale, Math.sqrt(T.maxRenderPixels / (w * h)));
    const bw = Math.max(1, Math.round(w * scale));
    const bh = Math.max(1, Math.round(h * scale));
    if (this.canvas.width !== bw) this.canvas.width = bw;
    if (this.canvas.height !== bh) this.canvas.height = bh;
    this.scale = bw / w;

    const cell = Math.max(T.minCellPx, Math.max(w, h) / T.maxCellsLong);
    const gw = Math.max(8, Math.round(w / cell));
    const gh = Math.max(8, Math.round(h / cell));
    this.cellPx = 0.5 * (w / gw + h / gh);
    this.sps = Math.min(240, Math.max(60, T.speedPx / (Math.sqrt(T.courant2) * this.cellPx)));
    // The grid always spans the whole view, so the old grid shows the
    // previous view size.
    const sx = this.lastW ? w / this.lastW : 1;
    const sy = this.lastH ? h / this.lastH : 1;
    this.lastW = w;
    this.lastH = h;
    if (gw !== this.gw || gh !== this.gh) this.allocGrid(gw, gh, sx, sy);
  }

  allocGrid(gw, gh, sx, sy) {
    const gl = this.gl;
    const next = [this.target(this.fmt, gw, gh, gl.NEAREST), this.target(this.fmt, gw, gh, gl.NEAREST)];
    const surf = this.target(this.surfFmt, gw, gh, gl.LINEAR);
    if (!next[0] || !next[1] || !surf) {
      // Shouldn't happen (the format passed its probe); park the sim rather than crash.
      for (const t of [...next, surf]) if (t) this.free(t);
      return;
    }
    const old = this.state;
    if (old && this.live) {
      // Carry running ripples over to the new grid.
      const p = this.p.COPY;
      gl.useProgram(p.prog);
      gl.uniform2f(p.u.uOldGrid, this.gw, this.gh);
      gl.uniform2f(p.u.uScale, sx, sy);
      gl.bindTexture(gl.TEXTURE_2D, old[this.cur].tex);
      this.draw(next[0]);
    }
    if (old) for (const t of old) this.free(t);
    if (this.surf) this.free(this.surf);
    this.state = next;
    this.surf = surf;
    this.cur = 0;
    this.gw = gw;
    this.gh = gh;
    if (old && this.live) this.updateSurface(1);
    else this.zero();
  }

  zero() {
    const gl = this.gl;
    const p = this.p.FILL;
    gl.useProgram(p.prog);
    gl.uniform2f(p.u.uValue, 0, 0);
    gl.uniform1f(p.u.uSurface, 0);
    this.draw(this.state[0]);
    this.draw(this.state[1]);
    gl.uniform1f(p.u.uSurface, 1);
    this.draw(this.surf);
  }

  // Returns whether the impulse was queued.
  addDrop(x, y, strength) {
    if (!this.ready || !this.state) return false;
    const rm = this.settings.reducedMotion;
    const v = this.view;
    this.drops.push(
      (x / v.w) * this.gw,
      (1 - y / v.h) * this.gh,
      (T.dropPx * (0.55 + 0.45 * strength)) / this.cellPx,
      T.dropAmp * strength * (rm ? 0.45 : 1),
    );
    this.activeUntil = this.clock + T.settle;
    return true;
  }

  applyDrops() {
    const gl = this.gl;
    const p = this.p.DROP;
    const d = this.drops;
    gl.useProgram(p.prog);
    gl.uniform2f(p.u.uGrid, this.gw, this.gh);
    for (let i = 0; i < d.length; i += MAX_DROPS * 4) {
      const n = Math.min(MAX_DROPS, (d.length - i) / 4);
      for (let k = 0; k < n * 4; k++) this.dropBuf[k] = d[i + k];
      gl.uniform4fv(p.u.uDrops, this.dropBuf);
      gl.uniform1i(p.u.uCount, n);
      gl.bindTexture(gl.TEXTURE_2D, this.state[this.cur].tex);
      this.draw(this.state[1 - this.cur]);
      this.cur = 1 - this.cur;
    }
    d.length = 0;
  }

  step(n) {
    const gl = this.gl;
    const p = this.p.SIM;
    const decay = T.decay * (this.settings.reducedMotion ? 1.8 : 1);
    gl.useProgram(p.prog);
    gl.uniform2f(p.u.uTexel, 1 / this.gw, 1 / this.gh);
    gl.uniform1f(p.u.uC, T.courant2);
    gl.uniform1f(p.u.uDamp, Math.exp(-decay / this.sps));
    gl.uniform1f(p.u.uVisc, T.visc);
    gl.uniform2f(p.u.uSponge, T.spongeCells / this.gw, T.spongeCells / this.gh);
    gl.uniform1f(p.u.uSpongeMin, T.spongeMin);
    for (let i = 0; i < n; i++) {
      gl.bindTexture(gl.TEXTURE_2D, this.state[this.cur].tex);
      this.draw(this.state[1 - this.cur]);
      this.cur = 1 - this.cur;
    }
  }

  updateSurface(alpha) {
    const gl = this.gl;
    const p = this.p.SURFACE;
    gl.useProgram(p.prog);
    gl.uniform2f(p.u.uTexel, 1 / this.gw, 1 / this.gh);
    gl.uniform1f(p.u.uAlpha, alpha);
    gl.bindTexture(gl.TEXTURE_2D, this.state[this.cur].tex);
    this.draw(this.surf);
  }

  // One animation frame. Returns true while ripples are alive (main.js then
  // keeps the full frame rate).
  frame(dt, pal) {
    if (!this.ready || !this.state) return false;
    this.clock += dt;
    const busy = this.drops.length > 0 || this.clock < this.activeUntil;
    if (busy) {
      if (!this.live) {
        this.live = true;
        this.acc = 0;
      }
      if (this.drops.length) this.applyDrops();
      this.acc += Math.min(dt, 0.1) * this.sps;
      const n = Math.min(T.maxSteps, Math.floor(this.acc));
      this.acc = Math.min(this.acc - n, 1);
      this.step(n);
      this.updateSurface(this.acc);
    } else if (this.live) {
      // Ripples have died out long ago; park at exactly zero.
      this.live = false;
      this.zero();
    }
    this.render(pal);
    return busy;
  }

  redraw(pal) {
    if (this.ready && this.state) this.render(pal);
  }

  render(pal) {
    const gl = this.gl;
    const p = this.p.RENDER;
    const u = p.u;
    const rm = this.settings.reducedMotion;
    const bw = this.canvas.width;
    const bh = this.canvas.height;
    const line = pal.line(bw, bh);
    // Over the last T.fadeOut seconds before parking, fade the surface's
    // effect to zero, so whatever faint rings are left never snap flat.
    const k = Math.min(1, Math.max(0, (this.activeUntil - this.clock) / T.fadeOut));
    const fade = this.live ? k * k * (3 - 2 * k) : 0;
    gl.useProgram(p.prog);
    gl.uniform2f(u.uRes, bw, bh);
    gl.uniform3fv(u.uLab0, pal.lab.subarray(0, 3));
    gl.uniform3fv(u.uLab1, pal.lab.subarray(3, 6));
    gl.uniform3fv(u.uLab2, pal.lab.subarray(6, 9));
    gl.uniform3fv(u.uChroma, pal.chroma);
    gl.uniform3fv(u.uPos, pal.pos);
    gl.uniform2f(u.uDir, line.dx, line.dy);
    gl.uniform1f(u.uInvLen, line.invLen);
    gl.uniform1f(u.uSlope, (fade * T.heightPx) / this.cellPx);
    gl.uniform1f(u.uCurv, (fade * T.heightPx) / (this.cellPx * this.cellPx));
    gl.uniform1f(u.uRefract, T.refractPx * this.scale);
    gl.uniform1f(u.uShade, T.shade);
    gl.uniform1f(u.uSpec, T.spec * (rm ? 0.5 : 1));
    gl.uniform1f(u.uCaustic, T.caustic);
    gl.bindTexture(gl.TEXTURE_2D, this.surf.tex);
    this.draw(null);
  }
}
