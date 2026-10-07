'use client';

/**
 * Where Founder Rafii lives on screen, with the site agent's mechanics (`features/site-agent/panel.tsx`): a docked
 * column from 1024px that pushes the page and remembers being open; a right sheet on tablets and a full-height sheet
 * on phones; ⌘J / Ctrl+J toggles it; above another dialog the conversation opens as a sheet instead. The same element
 * ids as the site agent keep the page outline reader from reading the panel back to Rafii.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { useWide } from '@/features/queue/use-wide';
import { FounderChat } from './chat';
import { founderPanelStore, useFounderPanel } from './store';

const DOCK_QUERY = '(min-width: 1024px)';
export const LAUNCHER_ID = 'rafii-launcher';
export const PANEL_ID = 'rafii-panel';
const PANEL_NAME = 'Founder Rafii';

function subscribeDock(onChange: () => void) {
  const query = window.matchMedia(DOCK_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

export function useDocked() {
  return useSyncExternalStore(subscribeDock, () => window.matchMedia(DOCK_QUERY).matches, () => false);
}

function returnFocus() {
  requestAnimationFrame(() => document.getElementById(LAUNCHER_ID)?.focus({ preventScroll: true }));
}

/** Another modal dialog is open (our dialogs mark their backdrop `t-modal-backdrop`); Rafii's own sheet is not counted. */
function otherDialogOpen() {
  return [...document.querySelectorAll('.t-modal-backdrop[data-open]')].some((backdrop) => !backdrop.closest('[data-base-ui-portal]')?.querySelector(`#${PANEL_ID}`));
}

function subscribeDialogs(onChange: () => void) {
  let frame = 0;
  const observer = new MutationObserver(() => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      onChange();
    });
  });
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-open'] });
  return () => {
    observer.disconnect();
    if (frame) cancelAnimationFrame(frame);
  };
}

export function useOtherDialog() {
  return useSyncExternalStore(subscribeDialogs, otherDialogOpen, () => false);
}

/** Escape with focus outside the open sheet closes Rafii only, never the dialog underneath. */
function useEscapeClosesOnlyRafii(active: boolean, close: () => void) {
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || document.getElementById(PANEL_ID)?.contains(document.activeElement)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      close();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [active, close]);
}

/** Keyboard shortcut and restore; mounted once in the founder shell. */
export function FounderPanelHotkeys() {
  const docked = useDocked();
  useEffect(() => {
    founderPanelStore.restore(docked);
  }, [docked]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing || event.key.toLowerCase() !== 'j' || !(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      event.preventDefault();
      if (window.matchMedia(DOCK_QUERY).matches && (otherDialogOpen() || founderPanelStore.get().above)) {
        founderPanelStore.setAbove(!founderPanelStore.get().above);
        return;
      }
      const wasOpen = founderPanelStore.get().open;
      founderPanelStore.toggle();
      if (wasOpen) returnFocus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return null;
}

/** The docked column; nothing below 1024px, while closed, or while the conversation is shown above a dialog. */
export function FounderPanelDock() {
  const open = useFounderPanel((s) => s.open);
  const above = useFounderPanel((s) => s.above);
  const docked = useDocked();
  const panel = useRef<HTMLElement>(null);
  const close = useCallback(() => {
    founderPanelStore.setOpen(false);
    returnFocus();
  }, []);
  useEffect(() => {
    if (!open || !docked) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && panel.current?.contains(document.activeElement)) close();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, docked, close]);
  if (!open || !docked || above) return null;
  return (
    <aside ref={panel} id={PANEL_ID} aria-label={PANEL_NAME} className='rafii-panel sticky top-0 z-20 flex h-dvh w-[29rem] shrink-0 flex-col border-l border-[color-mix(in_oklch,var(--foreground)_8%,transparent)] xl:w-[33rem]'>
      <FounderChat onClose={close} />
    </aside>
  );
}

const closeAbove = () => founderPanelStore.setAbove(false);

/** The conversation as a sheet above another dialog on docked layouts; it closes when that dialog does. */
export function FounderPanelAbove() {
  const above = useFounderPanel((s) => s.above);
  const docked = useDocked();
  const other = useOtherDialog();
  useEscapeClosesOnlyRafii(docked && above, closeAbove);
  useEffect(() => {
    if (above && (!other || !docked)) {
      founderPanelStore.setAbove(false);
      founderPanelStore.setOpen(true);
    }
  }, [above, other, docked]);
  if (!docked || !above) return null;
  return (
    <Sheet open onOpenChange={(next) => !next && closeAbove()}>
      <SheetContent id={PANEL_ID} side='right' showCloseButton={false} aria-label={PANEL_NAME} className='rafii-elevated gap-0 p-0 shadow-none data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-md'>
        <SheetTitle className='sr-only'>{PANEL_NAME}</SheetTitle>
        <FounderChat onClose={closeAbove} />
      </SheetContent>
    </Sheet>
  );
}

/** A full-viewport conversation on phones; a spacious right sheet on tablets. */
export function FounderPanelOverlay() {
  const open = useFounderPanel((s) => s.open);
  const docked = useDocked();
  const wide = useWide();
  useEffect(() => {
    if (!open || docked || wide || !window.visualViewport) return;
    const viewport = window.visualViewport;
    const update = () => {
      document.documentElement.style.setProperty('--rafii-chat-visible-height', `${viewport.height}px`);
      document.documentElement.style.setProperty('--rafii-chat-visible-top', `${viewport.offsetTop}px`);
    };
    update();
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
    return () => {
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
      document.documentElement.style.removeProperty('--rafii-chat-visible-height');
      document.documentElement.style.removeProperty('--rafii-chat-visible-top');
    };
  }, [open, docked, wide]);
  const close = useCallback(() => {
    founderPanelStore.setOpen(false);
    returnFocus();
  }, []);
  useEscapeClosesOnlyRafii(open && !docked, close);
  if (docked) return null;
  return (
    <Sheet open={open} onOpenChange={(next) => !next && close()}>
      <SheetContent
        id={PANEL_ID}
        side='right'
        showCloseButton={false}
        aria-label={PANEL_NAME}
        className={wide ? 'rafii-elevated gap-0 p-0 shadow-none data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-[36rem]' : 'rafii-elevated rafii-mobile-chat fixed inset-0 h-dvh max-h-dvh w-screen max-w-none gap-0 overflow-hidden rounded-none border-0 p-0 shadow-none'}
      >
        <SheetTitle className='sr-only'>{PANEL_NAME}</SheetTitle>
        <FounderChat onClose={close} onNavigate={close} autoFocus={wide} />
      </SheetContent>
    </Sheet>
  );
}
