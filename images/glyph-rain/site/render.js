// Canvas 2D renderer. Each set's glyphs are drawn once into atlases at the
// cell size (trail green, a pale green for just-passed cells, the head
// white with a glow); a frame then clears to black and copies every lit
// cell from an atlas, its brightness as alpha. No text layout per frame.

const TRAIL = '#2bef68';
const NEAR = '#b8ffcb';
const HEAD = '#f2fff5';
const GLOW = 'rgba(150, 255, 180, 0.85)';
const NEAR_S = 0.18; // seconds a cell stays pale after its head passed

// Missing glyphs (tofu) are drawn alike whatever their code point: the
// font's .notdef box, the system's last-resort glyph or a hex box. Their
// metrics equal those of a code point no font has (U+0378, U+1D127, both
// unassigned; as many hex digits as the glyphs they're compared with, as
// a hex box widens with them). Equal metrics → missing.
const TOFU_BMP = '\u0378';
const TOFU_SMP = '\u{1d127}';

function metrics(g, ch) {
  const m = g.measureText(ch);
  return [m.width, m.actualBoundingBoxLeft, m.actualBoundingBoxRight, m.actualBoundingBoxAscent, m.actualBoundingBoxDescent];
}
const same = (a, b) => a.every((v, i) => Math.abs(v - b[i]) < 0.01);

function canvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

// The glyphs of set this system draws, each with its ink box at font size
// px. upright: only signs whose ink fits a cell standing up. filter false:
// every glyph, unchecked (the digits fallback of last resort). Cached per
// set, size and filter (measuring the hieroglyphs takes a few ms).
const cache = new Map();
export function usableGlyphs(set, px, filter = true) {
  const key = `${set.label}|${px}|${filter}`;
  if (cache.has(key)) return cache.get(key);
  const g = canvas(8, 8).getContext('2d');
  g.font = `${px}px ${set.font}`;
  const tofu = [metrics(g, TOFU_BMP), metrics(g, TOFU_SMP)];
  const out = [];
  for (const ch of set.chars) {
    const m = metrics(g, ch);
    if (!filter) {
      out.push({ ch, left: m[1], right: m[2], ascent: m[3], descent: m[4] });
      continue;
    }
    if (same(m, tofu[ch.codePointAt(0) > 0xffff ? 1 : 0])) continue;
    const w = m[1] + m[2];
    const h = m[3] + m[4];
    if (w < px * 0.08 || h < px * 0.08) continue; // no ink to speak of
    if (set.upright && (w / h < 0.45 || w / h > 1.35 || Math.max(w, h) < px * 0.5)) continue;
    out.push({ ch, left: m[1], right: m[2], ascent: m[3], descent: m[4] });
  }
  cache.set(key, out);
  return out;
}

export class Renderer {
  constructor(el) {
    this.canvas = el;
    this.g = el.getContext('2d', { alpha: false });
    this.atlases = [];
    this.sheets = new Map(); // (set, cell) → atlas: a resize at the same cell size redraws none
  }

  // sets: [{ label, font, px, glyphs: usableGlyphs(set, px) }]; cell: device px.
  setup(sets, cell, width, height) {
    if (cell !== this.cell) this.sheets.clear(); // only the current size is kept
    this.cell = cell;
    this.canvas.width = width;
    this.canvas.height = height;
    this.atlases = sets.map((s) => {
      const key = `${s.label}|${s.glyphs.length}`;
      if (!this.sheets.has(key)) this.sheets.set(key, this.atlas(s, cell));
      return this.sheets.get(key);
    });
  }

  // One sheet per colour; slots of cell + 2 * pad px (the head's glow
  // needs room around the glyph, or it ends in a visible square).
  atlas(set, cell) {
    const sheet = (color, pad = 0) => {
      const slot = cell + 2 * pad;
      const per = Math.max(1, Math.floor(2048 / slot));
      const c = canvas(per * slot, Math.ceil(set.glyphs.length / per) * slot);
      const g = c.getContext('2d');
      g.fillStyle = color;
      if (pad) {
        g.shadowColor = GLOW;
        g.shadowBlur = cell * 0.3;
      }
      g.font = `${set.px}px ${set.font}`;
      set.glyphs.forEach((q, i) => {
        // The ink box (measured at set.px) scaled to 78 % of the cell and
        // centred: small and large signs weigh alike in the rain.
        const k = Math.min(1.6, (cell * 0.78) / Math.max(q.left + q.right, q.ascent + q.descent));
        g.setTransform(k, 0, 0, k, (i % per) * slot + slot / 2, Math.floor(i / per) * slot + slot / 2);
        g.fillText(q.ch, (q.left - q.right) / 2, (q.ascent - q.descent) / 2);
      });
      return { c, per, slot, pad };
    };
    return { trail: sheet(TRAIL), near: sheet(NEAR), head: sheet(HEAD, Math.round(cell * 0.4)) };
  }

  draw(sim) {
    const { g, cell } = this;
    const cols = sim.cols;
    const blit = (sh, i) => {
      const q = sim.glyph[i];
      const x = (i % cols) * cell - sh.pad;
      const y = Math.floor(i / cols) * cell - sh.pad;
      g.drawImage(sh.c, (q % sh.per) * sh.slot, Math.floor(q / sh.per) * sh.slot, sh.slot, sh.slot, x, y, sh.slot, sh.slot);
    };
    g.globalAlpha = 1;
    g.fillStyle = '#000';
    g.fillRect(0, 0, this.canvas.width, this.canvas.height);
    for (let i = 0, n = cols * sim.rows; i < n; i++) {
      const l = sim.level(i);
      if (l < 0.015) continue;
      const a = this.atlases[sim.set[i]];
      g.globalAlpha = l * l * (3 - 2 * l) * 0.95; // smoothstep: a long dim tail
      blit(a.trail, i);
      const age = sim.t - sim.litAt[i];
      if (age < NEAR_S) {
        g.globalAlpha = 1 - age / NEAR_S;
        blit(a.near, i);
      }
    }
    g.globalAlpha = 1;
    for (const i of sim.headCells()) blit(this.atlases[sim.set[i]].head, i);
  }
}
