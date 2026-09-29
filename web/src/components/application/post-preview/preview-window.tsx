'use client';

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useReducedMotion } from 'motion/react';
import { containsPoint, dockWindow, fitWindow, phoneScale, viewportBounds, WINDOW_PRESETS, type Rect } from './preview-window-geometry';

interface WindowState { mode: 'docked' | 'floating'; x: number; y: number; width: number }
interface Gesture {
  id: number; kind: 'move' | 'resize'; startX: number; startY: number;
  before: WindowState; rect: Rect; active: boolean; target: HTMLElement;
}
const INITIAL: WindowState = { mode: 'docked', x: 0, y: 0, width: WINDOW_PRESETS.M };
const CONTROL = 'rafii-focus min-h-11 min-w-11 rounded-md px-2 text-xs hover:bg-muted focus-visible:outline-2';

/** One portal and one child tree in every mode; moving the window never remounts media. */
export function PreviewWindow({ active, available, label, onDock, children }: {
  active: boolean; available: boolean; label: string; onDock: () => void;
  children: (scale: number) => ReactNode;
}) {
  const slot = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const initialized = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [state, setState] = useState<WindowState>(INITIAL);
  const stateRef = useRef(state);
  stateRef.current = state;
  const [geometry, setGeometry] = useState<{ bounds: Rect; slot: Rect; ready: boolean; enabled: boolean; compact: boolean }>({
    bounds: { x: 12, y: 76, width: 1000, height: 800 },
    slot: { x: 0, y: 0, width: 336, height: 0 }, ready: false, enabled: false, compact: false
  });
  const [dragging, setDragging] = useState(false);
  const [candidate, setCandidate] = useState(false);
  const [animate, setAnimate] = useState(false);
  const reduceMotion = useReducedMotion();
  const dock = dockWindow(geometry.slot, state.width, geometry.bounds);
  const rect = state.mode === 'docked' ? dock : fitWindow(state, geometry.bounds);
  const visible = geometry.ready && geometry.enabled && available && (active || state.mode === 'floating');

  function commit(next: WindowState) { stateRef.current = next; setState(next); }
  function animateChange() {
    if (timer.current) clearTimeout(timer.current);
    setAnimate(true);
    timer.current = setTimeout(() => setAnimate(false), 240);
  }
  function dockNow() {
    animateChange();
    commit({ ...stateRef.current, mode: 'docked' });
    onDock();
  }
  function cancelGesture() {
    const current = gesture.current;
    if (!current) return;
    gesture.current = null;
    commit(current.before);
    setDragging(false); setCandidate(false); setAnimate(false);
    if (current.target.hasPointerCapture(current.id)) current.target.releasePointerCapture(current.id);
  }

  useEffect(() => {
    // The portal destination is assigned once, never changed when docking or selecting Sources.
    setHost(document.body);
    let frame = 0;
    const measure = () => {
      frame = 0;
      const element = slot.current;
      if (!element) return;
      const measured = element.getBoundingClientRect();
      const viewport = window.visualViewport;
      const bounds = viewportBounds({ x: viewport?.offsetLeft ?? 0, y: viewport?.offsetTop ?? 0,
        width: viewport?.width ?? window.innerWidth, height: viewport?.height ?? window.innerHeight },
        document.querySelector('#main-content > header')?.getBoundingClientRect().bottom ?? 64);
      const enabled = window.matchMedia('(min-width: 768px)').matches;
      const layoutWidth = element.closest('[data-conversation-layout]')?.getBoundingClientRect().width ?? window.innerWidth;
      const compact = layoutWidth < 704;
      const next = { bounds, slot: { x: measured.x, y: measured.y, width: measured.width, height: measured.height },
        ready: measured.width > 0, enabled, compact };
      setGeometry((previous) => JSON.stringify(previous) === JSON.stringify(next) ? previous : next);
      // On a narrow tablet workspace, begin with the compact floating window rather than crush the chat column.
      // This runs only at the first usable tablet/desktop measurement. Later resizes never change mode.
      if (!initialized.current && enabled && measured.width > 0) {
        initialized.current = true;
        if (compact) {
          const fitted = fitWindow({ x: bounds.x + bounds.width, y: bounds.y + 56, width: WINDOW_PRESETS.S }, bounds);
          const initial: WindowState = { ...fitted, mode: 'floating' };
          stateRef.current = initial; setState(initial);
        }
      }
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const onScroll = () => { setAnimate(false); schedule(); };
    const observer = new ResizeObserver(schedule);
    if (slot.current) {
      observer.observe(slot.current);
      const layout = slot.current.closest('[data-conversation-layout]');
      if (layout) observer.observe(layout);
    }
    const header = document.querySelector('#main-content > header');
    if (header) observer.observe(header);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    window.visualViewport?.addEventListener('resize', onScroll);
    window.visualViewport?.addEventListener('scroll', onScroll);
    measure();
    return () => {
      observer.disconnect(); cancelAnimationFrame(frame);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
      window.visualViewport?.removeEventListener('resize', onScroll);
      window.visualViewport?.removeEventListener('scroll', onScroll);
      if (timer.current) clearTimeout(timer.current);
      const current = gesture.current;
      gesture.current = null;
      if (current?.target.hasPointerCapture(current.id)) current.target.releasePointerCapture(current.id);
    };
  }, []);

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && gesture.current) { event.preventDefault(); cancelGesture(); }
    };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  });

  function start(event: ReactPointerEvent<HTMLElement>, kind: Gesture['kind']) {
    if (!event.isPrimary || event.button !== 0 || gesture.current) return;
    event.preventDefault(); event.currentTarget.focus();
    gesture.current = { id: event.pointerId, kind, startX: event.clientX, startY: event.clientY,
      before: { ...stateRef.current }, rect, active: false, target: event.currentTarget };
    event.currentTarget.setPointerCapture(event.pointerId);
    setAnimate(false);
  }
  function update(event: ReactPointerEvent<HTMLElement>) {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.startX;
    const dy = event.clientY - current.startY;
    if (!current.active && Math.hypot(dx, dy) < 6) return;
    current.active = true;
    const widthDelta = Math.abs(dx) >= Math.abs(dy * 393 / 852) ? dx : dy * 393 / 852;
    const next = fitWindow(current.kind === 'move'
      ? { x: current.rect.x + dx, y: current.rect.y + dy, width: current.rect.width }
      : { x: current.rect.x, y: current.rect.y, width: current.rect.width + widthDelta }, geometry.bounds);
    commit({ ...next, mode: 'floating' });
    setDragging(current.kind === 'move');
    setCandidate(current.kind === 'move' && containsPoint(dock, { x: event.clientX, y: event.clientY }));
  }
  function finish(event: ReactPointerEvent<HTMLElement>) {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    // Apply the release coordinate too; React may not have rendered the final pointermove yet.
    update(event);
    gesture.current = null;
    setDragging(false); setCandidate(false);
    if (current.active && current.kind === 'move' && containsPoint(dock, { x: event.clientX, y: event.clientY })) dockNow();
    if (current.target.hasPointerCapture(current.id)) current.target.releasePointerCapture(current.id);
  }
  function position(horizontal: 'left' | 'right', vertical: 'top' | 'bottom') {
    animateChange();
    commit({ ...fitWindow({ width: rect.width,
      x: horizontal === 'left' ? geometry.bounds.x : geometry.bounds.x + geometry.bounds.width - rect.width,
      y: vertical === 'top' ? geometry.bounds.y : geometry.bounds.y + geometry.bounds.height - rect.height }, geometry.bounds), mode: 'floating' });
  }
  const pointerHandlers = { onPointerMove: update, onPointerUp: finish, onPointerCancel: cancelGesture, onLostPointerCapture: cancelGesture };

  return (
    <>
      <div ref={slot} data-preview-dock-slot className='relative w-full'
        style={{ height: active ? (available ? (geometry.compact && state.mode === 'floating' ? 64 : dock.height) : 80) : 0 }}>
        {active && !available && <p className='text-muted-foreground py-4 text-sm'>Nothing to preview yet</p>}
        {active && available && state.mode === 'floating' && (
          <button type='button' onClick={dockNow} className='rafii-focus text-muted-foreground h-full w-full rounded-xl border border-dashed p-3 text-xs'>
            Preview is floating. Drop here or click to dock.
          </button>
        )}
      </div>
      {host && createPortal(
        <>
          {visible && dragging && <div data-preview-dock-target aria-hidden className='pointer-events-none fixed z-20 rounded-2xl border-2 border-dashed border-foreground/40 bg-background/70'
            style={{ left: dock.x, top: dock.y, width: dock.width, height: dock.height, opacity: candidate ? 1 : 0.35 }}>
            <span className='bg-background absolute inset-x-2 top-2 rounded-md p-3 text-center text-xs text-foreground'>{candidate ? 'Release to dock' : 'Original preview position'}</span>
          </div>}
          <section data-preview-window data-mode={state.mode} aria-label='Post preview window' aria-hidden={!visible} inert={!visible}
            className='border-border bg-background text-foreground fixed z-30 flex flex-col overflow-hidden rounded-2xl border'
            style={{ left: rect.x, top: rect.y, width: rect.width, height: rect.height, visibility: visible ? 'visible' : 'hidden',
              pointerEvents: visible ? 'auto' : 'none', boxShadow: state.mode === 'floating' ? '0 18px 48px -18px rgb(0 0 0 / 0.32)' : 'none',
              transition: animate && !reduceMotion ? 'left 220ms ease, top 220ms ease, width 220ms ease, height 220ms ease, box-shadow 140ms ease' : 'none' }}>
            <header className='flex shrink-0 items-center gap-1 border-b px-1'>
              <button type='button' data-preview-drag-handle aria-label='Move preview. Drag or use arrow keys.'
                title='Drag to float. Arrow keys move; Shift moves faster. Escape cancels a gesture.'
                className={`${CONTROL} flex min-w-0 flex-1 cursor-grab items-center gap-2 text-left active:cursor-grabbing`}
                style={{ touchAction: 'none' }} onPointerDown={(event) => start(event, 'move')} {...pointerHandlers}
                onKeyDown={(event) => {
                  const delta: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
                  const step = delta[event.key];
                  if (!step || gesture.current) return;
                  event.preventDefault(); setAnimate(false);
                  const distance = event.shiftKey ? 40 : 10;
                  commit({ ...fitWindow({ x: rect.x + step[0] * distance, y: rect.y + step[1] * distance, width: rect.width }, geometry.bounds), mode: 'floating' });
                }}><span aria-hidden>⠿</span><span>Preview</span></button>
              <button type='button' className={CONTROL} onClick={() => {
                if (state.mode === 'floating') dockNow();
                else { animateChange(); commit({ ...fitWindow({ x: rect.x - 16, y: rect.y + 16, width: rect.width }, geometry.bounds), mode: 'floating' }); }
              }}>{state.mode === 'floating' ? 'Dock' : 'Float'}</button>
              <details className='relative'>
                <summary className={`${CONTROL} flex cursor-pointer list-none items-center justify-center`} aria-label='Preview size and position'>⋯</summary>
                <div className='border-border bg-background absolute right-0 top-full z-10 w-48 rounded-lg border p-2 shadow-lg'>
                  <p className='px-2 text-xs'>Size</p>
                  <div className='flex'>{Object.entries(WINDOW_PRESETS).map(([size, width]) => <button key={size} type='button' className={CONTROL} aria-label={`Preview size ${size}`} onClick={() => { animateChange(); commit({ ...stateRef.current, width }); }}>{size}</button>)}</div>
                  <p className='px-2 text-xs'>Move to corner</p>
                  <div className='grid grid-cols-2'>{(['top', 'bottom'] as const).flatMap((vertical) => (['left', 'right'] as const).map((horizontal) =>
                    <button key={`${vertical}-${horizontal}`} type='button' className={CONTROL} onClick={() => position(horizontal, vertical)}>{vertical} {horizontal}</button>))}</div>
                </div>
              </details>
            </header>
            <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pt-2 pb-8' data-preview-window-body>
              <p className='text-muted-foreground mb-2 text-xs'>{label}</p>
              {children(phoneScale(rect.width))}
            </div>
            <button type='button' data-preview-resize-handle aria-label='Resize preview. Use the size menu for preset sizes.'
              className={`${CONTROL} bg-background absolute right-0 bottom-0 cursor-nwse-resize`}
              style={{ touchAction: 'none' }} onPointerDown={(event) => start(event, 'resize')} {...pointerHandlers}>↘</button>
          </section>
          <span role='status' aria-live='polite' className='sr-only'>{visible ? (state.mode === 'floating' ? 'Preview floating. Use Dock to return it.' : 'Preview docked.') : ''}</span>
        </>, host
      )}
    </>
  );
}
