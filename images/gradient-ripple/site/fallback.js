// fallback.js: no WebGL (or the context was lost): the same drifting palette
// as a CSS linear-gradient on the backdrop, plus simple canvas-2D ripple
// rings on top. Also used temporarily while a lost WebGL context is being
// restored, so the screen never goes black.

const CSS_INTERVAL = 0.1; // s between backdrop gradient updates
const MAX_RINGS = 48;
const TRAIL_GAP = 48; // CSS px between drag-trail rings

export class Fallback {
  constructor(backdrop, settings) {
    this.backdrop = backdrop;
    this.settings = settings;
    this.canvas = null;
    this.ctx = null;
    this.rings = [];
    this.view = { w: 1, h: 1, dpr: 1 };
    this.cssAge = Infinity;
    this.dirty = false; // ring canvas has something on it
  }

  activate() {
    this.cssAge = Infinity;
    if (!this.canvas) {
      const c = document.createElement('canvas');
      c.id = 'rings';
      c.setAttribute('aria-hidden', 'true');
      this.backdrop.insertAdjacentElement('afterend', c);
      this.canvas = c;
      this.ctx = c.getContext('2d');
    }
    this.canvas.style.visibility = 'visible';
    this.resize(this.view);
  }

  deactivate() {
    this.rings.length = 0;
    if (this.canvas) this.canvas.style.visibility = 'hidden';
  }

  resize(view) {
    this.view = view;
    if (!this.canvas) return;
    const s = Math.min(view.dpr, 2);
    this.scale = s;
    this.canvas.width = Math.max(1, Math.round(view.w * s));
    this.canvas.height = Math.max(1, Math.round(view.h * s));
  }

  addDrop(x, y, strength) {
    if (!this.ctx) return;
    if (strength < 1) {
      // Drag trail: much sparser than the WebGL impulses, or it turns into
      // a wireframe tube.
      const t = this.lastTrail;
      if (t && Math.hypot(x - t.x, y - t.y) < TRAIL_GAP) return;
    }
    this.lastTrail = { x, y };
    this.rings.push({ x, y, age: 0, s: strength });
    if (this.rings.length > MAX_RINGS) this.rings.shift();
  }

  frame(dt, pal) {
    this.cssAge += dt;
    if (this.cssAge >= CSS_INTERVAL) this.paintBackdrop(pal);
    for (const r of this.rings) r.age += dt;
    this.drawRings();
    return this.rings.length > 0;
  }

  redraw(pal) {
    this.paintBackdrop(pal);
    this.drawRings();
  }

  paintBackdrop(pal) {
    this.cssAge = 0;
    this.backdrop.style.backgroundImage = pal.cssGradient();
  }

  drawRings() {
    const ctx = this.ctx;
    if (!ctx) return;
    const rm = this.settings.reducedMotion;
    const life = rm ? 1.6 : 2.6;
    this.rings = this.rings.filter((r) => r.age < life);
    if (!this.rings.length && !this.dirty) return;
    this.dirty = this.rings.length > 0;
    ctx.setTransform(this.scale, 0, 0, this.scale, 0, 0);
    ctx.clearRect(0, 0, this.view.w, this.view.h);
    for (const r of this.rings) {
      const k = r.age / life;
      const fade = (1 - k) * (1 - k) * Math.sqrt(r.s) * (rm ? 0.5 : 1);
      const count = r.s < 1 ? 1 : 3;
      for (let j = 0; j < count; j++) {
        const rad = r.age * 140 - j * 16;
        if (rad <= 1) continue;
        const a = fade * (0.45 - j * 0.12);
        ctx.lineWidth = 2.2 - j * 0.5;
        // A soft dark rim below a light one reads as a wave crest.
        ctx.globalAlpha = a * 0.35;
        ctx.strokeStyle = '#1a1030';
        ctx.beginPath();
        ctx.arc(r.x, r.y + 1.2, rad + 1.2, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = a;
        ctx.strokeStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(r.x, r.y, rad, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }
}
