'use client';

import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';

/**
 * Ambient particle field that answers the pointer. Purely decorative: it reads no workspace
 * data and must never be mistaken for data (no counts, no progress, no pulses tied to state).
 *
 * - Draws in `currentColor` (`text-foreground` by default), so the dots follow every theme in
 *   light and dark without a colour table of its own; a theme switch repaints even when paused.
 * - Runs at most 60 frames a second, only while the tab is visible and the canvas is on screen.
 *   Under `prefers-reduced-motion` nothing is drawn at all. When the connection asks to save
 *   data, one still frame is drawn and nothing animates.
 * - Coarse pointers (touch) get half the particles, no hairlines and no pointer physics; touch
 *   events never pull the field. Leaving the window or losing focus releases the pointer.
 * - `quiet` fades the field back (for example while the person is typing), and `safeArea`
 *   (a CSS selector) dims whatever sits behind that element so text in front stays legible.
 *   Both are read through refs, so changing them never reseeds the field.
 * - The canvas is `pointer-events-none` and `aria-hidden`; mount it behind content inside a
 *   `relative isolate` parent with a negative z-index.
 */
export interface ParticleFieldProps extends React.HTMLAttributes<HTMLCanvasElement> {
  /** Particles per 10,000 CSS px² (about 2 fills a 1200×700 area with ~170); capped by `max`. */
  density?: number;
  /** Hard cap on particle count (the line pass is O(n²)). */
  max?: number;
  /** Radius of the pointer's influence in CSS px. */
  radius?: number;
  /** Whether particles flee from the pointer or gather round it. */
  mode?: 'repel' | 'attract';
  /** Two particles closer than this are joined by a hairline; 0 disables lines. */
  link?: number;
  /** Peak dot opacity. Lines use a fraction of it. */
  alpha?: number;
  /** Fade the field back while something in front needs attention. */
  quiet?: boolean;
  /** Selector of an element whose area the field dims (a heading in front of it). */
  safeArea?: string;
}

interface Particle {
  x: number;
  y: number;
  /** Base drift, px/s. Never decays, so the field keeps breathing at rest. */
  dx: number;
  dy: number;
  /** Reactive velocity from the pointer, px/s. Decays back to zero. */
  vx: number;
  vy: number;
  r: number;
  phase: number;
}

const TAU = Math.PI * 2;
const FRAME_MS = 1000 / 60;
const QUIET_LEVEL = 0.4;
const SAFE_LEVEL = 0.3;
/** Line opacity is drawn in a few batches instead of one stroke per line. */
const LINE_BUCKETS = 3;

export function ParticleField({
  density = 1.8,
  max = 140,
  radius = 160,
  mode = 'repel',
  link = 110,
  alpha = 0.55,
  quiet = false,
  safeArea,
  className,
  ...props
}: ParticleFieldProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const quietRef = useRef(quiet);
  quietRef.current = quiet;
  const safeAreaRef = useRef(safeArea);
  safeAreaRef.current = safeArea;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
    const coarse = window.matchMedia('(pointer: coarse)');
    const saveData = Boolean((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData);

    let width = 0;
    let height = 0;
    let particles: Particle[] = [];
    let color = '#888';
    let raf = 0;
    let last = 0;
    let lastDraw = 0;
    let running = false;
    let tabVisible = !document.hidden;
    let onScreen = true;
    let quietness = quietRef.current ? 1 : 0;
    const pointer = { x: -1e4, y: -1e4, active: false, strength: 0 };

    // An unseeded generator is fine: the field is ornament.
    const rand = (lo: number, hi: number) => lo + Math.random() * (hi - lo);

    const spawn = (): Particle => {
      const angle = rand(0, TAU);
      const speed = rand(5, 14);
      return { x: rand(0, width), y: rand(0, height), dx: Math.cos(angle) * speed, dy: Math.sin(angle) * speed, vx: 0, vy: 0, r: rand(0.9, 2.2), phase: rand(0, TAU) };
    };

    const readColor = () => {
      color = getComputedStyle(canvas).color || '#888';
    };

    const seed = () => {
      const scale = coarse.matches ? 0.5 : 1;
      const target = Math.min(Math.round(max * scale), Math.round(((width * height) / 10000) * density * scale));
      if (particles.length > target) particles = particles.slice(0, target);
      while (particles.length < target) particles.push(spawn());
      for (const p of particles) {
        if (p.x > width) p.x = rand(0, width);
        if (p.y > height) p.y = rand(0, height);
      }
    };

    /** The safe area in canvas coordinates, read once per frame. */
    const safeRect = () => {
      const selector = safeAreaRef.current;
      if (!selector) return null;
      const el = document.querySelector(selector);
      if (!el) return null;
      const a = el.getBoundingClientRect();
      const c = canvas.getBoundingClientRect();
      const pad = 24;
      return { l: a.left - c.left - pad, t: a.top - c.top - pad, r: a.right - c.left + pad, b: a.bottom - c.top + pad };
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      if (reduce.matches) return;
      const level = alpha * (1 - quietness * (1 - QUIET_LEVEL));
      const safe = safeRect();
      const dim = (x: number, y: number) => (safe && x > safe.l && x < safe.r && y > safe.t && y < safe.b ? SAFE_LEVEL : 1);
      ctx.fillStyle = color;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;

      const lines = link > 0 && !coarse.matches;
      if (lines) {
        const linkSq = link * link;
        const buckets: Path2D[] = Array.from({ length: LINE_BUCKETS }, () => new Path2D());
        const used = Array.from({ length: LINE_BUCKETS }, () => false);
        for (let i = 0; i < particles.length; i++) {
          const a = particles[i];
          for (let j = i + 1; j < particles.length; j++) {
            const b = particles[j];
            const ddx = a.x - b.x;
            const ddy = a.y - b.y;
            const dSq = ddx * ddx + ddy * ddy;
            if (dSq >= linkSq) continue;
            const strength = (1 - Math.sqrt(dSq) / link) * dim((a.x + b.x) / 2, (a.y + b.y) / 2);
            const bucket = Math.min(LINE_BUCKETS - 1, Math.floor(strength * LINE_BUCKETS));
            buckets[bucket].moveTo(a.x, a.y);
            buckets[bucket].lineTo(b.x, b.y);
            used[bucket] = true;
          }
        }
        for (let k = 0; k < LINE_BUCKETS; k++) {
          if (!used[k]) continue;
          ctx.globalAlpha = level * 0.28 * ((k + 0.5) / LINE_BUCKETS);
          ctx.stroke(buckets[k]);
        }
      }
      for (const p of particles) {
        // A slow twinkle per particle; opacity only, never position.
        ctx.globalAlpha = level * (0.6 + 0.4 * Math.sin(p.phase)) * dim(p.x, p.y);
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, TAU);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    const step = (dt: number) => {
      const influence = coarse.matches ? 0 : pointer.strength;
      // Ease the pointer's presence and the quiet level in and out, so nothing snaps.
      pointer.strength += ((pointer.active ? 1 : 0) - pointer.strength) * Math.min(1, dt * 6);
      quietness += ((quietRef.current ? 1 : 0) - quietness) * Math.min(1, dt * 5);
      const decay = Math.exp(-dt * 2.2);
      const rSq = radius * radius;
      const sign = mode === 'repel' ? 1 : -1;
      for (const p of particles) {
        if (influence > 0.001) {
          const ddx = p.x - pointer.x;
          const ddy = p.y - pointer.y;
          const dSq = ddx * ddx + ddy * ddy;
          if (dSq < rSq && dSq > 0.01) {
            const d = Math.sqrt(dSq);
            const falloff = 1 - d / radius;
            const force = falloff * falloff * 260 * influence * sign;
            p.vx += (ddx / d) * force * dt;
            p.vy += (ddy / d) * force * dt;
            if (mode === 'attract') {
              // A little swirl so gathered particles orbit instead of collapsing on the cursor.
              p.vx += (-ddy / d) * falloff * 40 * influence * dt;
              p.vy += (ddx / d) * falloff * 40 * influence * dt;
            }
          }
        }
        p.vx *= decay;
        p.vy *= decay;
        p.x += (p.dx + p.vx) * dt;
        p.y += (p.dy + p.vy) * dt;
        p.phase += dt * 0.9;
        // Wrap with a small margin so a dot never pops at the edge.
        if (p.x < -4) p.x = width + 4;
        else if (p.x > width + 4) p.x = -4;
        if (p.y < -4) p.y = height + 4;
        else if (p.y > height + 4) p.y = -4;
      }
    };

    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      // High-refresh displays get 60 frames a second, not 120.
      if (lastDraw && t - lastDraw < FRAME_MS - 1) return;
      const dt = last ? Math.min(0.05, (t - last) / 1000) : 0;
      last = t;
      lastDraw = t;
      step(dt);
      draw();
    };

    const sync = () => {
      const shouldRun = !reduce.matches && !saveData && tabVisible && onScreen;
      if (shouldRun && !running) {
        running = true;
        last = 0;
        lastDraw = 0;
        raf = requestAnimationFrame(frame);
      } else if (!shouldRun && running) {
        running = false;
        cancelAnimationFrame(raf);
        raf = 0;
      }
      if (!running) {
        quietness = quietRef.current ? 1 : 0;
        draw();
      }
    };

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width));
      height = Math.max(1, Math.round(rect.height));
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
      draw();
    };

    const release = () => {
      pointer.active = false;
    };
    const onMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return;
      const rect = canvas.getBoundingClientRect();
      pointer.x = event.clientX - rect.left;
      pointer.y = event.clientY - rect.top;
      pointer.active = pointer.x >= 0 && pointer.y >= 0 && pointer.x <= width && pointer.y <= height;
    };
    const onOut = (event: PointerEvent) => {
      // `relatedTarget` is null when the pointer leaves the document altogether.
      if (!event.relatedTarget) release();
    };
    const onVisibility = () => {
      tabVisible = !document.hidden;
      sync();
    };
    const onTheme = () => {
      readColor();
      if (!running) draw();
    };
    const onPreference = () => {
      seed();
      sync();
    };

    readColor();
    resize();
    sync();

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const io = new IntersectionObserver(
      (entries) => {
        onScreen = entries.some((e) => e.isIntersecting);
        sync();
      },
      { threshold: 0 }
    );
    io.observe(canvas);
    // Theme switches land as attribute changes on <html>; re-read the colour then.
    const mo = new MutationObserver(onTheme);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onMove, { passive: true });
    window.addEventListener('blur', release);
    document.addEventListener('pointerout', onOut);
    document.addEventListener('visibilitychange', onVisibility);
    reduce.addEventListener('change', sync);
    coarse.addEventListener('change', onPreference);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      mo.disconnect();
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onMove);
      window.removeEventListener('blur', release);
      document.removeEventListener('pointerout', onOut);
      document.removeEventListener('visibilitychange', onVisibility);
      reduce.removeEventListener('change', sync);
      coarse.removeEventListener('change', onPreference);
    };
  }, [density, max, radius, mode, link, alpha]);

  return (
    <canvas
      ref={ref}
      aria-hidden
      data-slot='particle-field'
      className={cn('text-foreground pointer-events-none block h-full w-full select-none print:hidden', className)}
      {...props}
    />
  );
}
