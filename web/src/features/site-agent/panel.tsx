'use client';

/**
 * Where the Rafii conversation lives on screen (site agent spec §11.1):
 * - 1024px and wider: a docked column beside the page. It pushes the page instead of covering it and stays open
 *   while the person moves between pages (the open state is remembered).
 * - Tablets: a sheet from the right. Phones: a bottom sheet. Both close when a link inside takes the person to a page.
 * The conversation itself is the same everywhere; only the frame changes. ⌘J / Ctrl+J opens and closes it.
 * - While another dialog is open (an automation's builder, a confirmation) the page behind it, and so the docked
 *   column, is inert under that dialog's backdrop. ⌘J then opens the conversation as a sheet above the dialog; it
 *   closes with that dialog, and the column is back as it was.
 */
import { useCallback, useEffect, useRef, useSyncExternalStore } from 'react';
import { Drawer, DrawerContent, DrawerTitle } from '@/components/ui/drawer';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { siteConfig } from '@/config/site';
import { useWide } from '@/features/queue/use-wide';
import { SiteAgentChat } from './chat';
import { panelStore, usePanel } from './store';

const DOCK_QUERY = '(min-width: 1024px)';
export const LAUNCHER_ID = 'rafii-launcher';
export const PANEL_ID = 'rafii-panel';

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

/** Another modal dialog is open: our dialog components mark their backdrop `t-modal-backdrop`; Rafii's own sheet is not counted. */
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

/**
 * Escape while Rafii's sheet is open but focus has fallen out of it (onto the page): close Rafii only. Every open
 * dialog listens for Escape, so without this one key would also close the dialog underneath (an automation's builder).
 * With focus inside the sheet, the sheet's own handling already closes just the sheet.
 */
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

/** Keyboard shortcut and restore; mounted once in the app shell. */
export function SiteAgentHotkeys() {
  const docked = useDocked();
  useEffect(() => {
    panelStore.restore(docked);
  }, [docked]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing || event.key.toLowerCase() !== 'j' || !(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
      event.preventDefault();
      if (window.matchMedia(DOCK_QUERY).matches && (otherDialogOpen() || panelStore.get().above)) {
        // Above a dialog: the docked column is inert under it, so the sheet opens (or closes) instead.
        panelStore.setAbove(!panelStore.get().above);
        return;
      }
      const wasOpen = panelStore.get().open;
      panelStore.toggle();
      if (wasOpen) returnFocus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  return null;
}

/** The docked column; renders nothing below 1024px, while closed, or while the conversation is shown above a dialog. */
export function SiteAgentDock() {
  const open = usePanel((s) => s.open);
  const above = usePanel((s) => s.above);
  const docked = useDocked();
  const panel = useRef<HTMLElement>(null);
  const close = useCallback(() => {
    panelStore.setOpen(false);
    returnFocus();
  }, []);
  // Escape closes the docked panel only while focus is inside it (dialogs and menus above it handle their own).
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
    <aside
      ref={panel}
      id={PANEL_ID}
      aria-label={siteConfig.name}
      className='rafii-panel sticky top-0 z-20 flex h-svh w-[22rem] shrink-0 flex-col border-l border-[color-mix(in_oklch,var(--foreground)_8%,transparent)] xl:w-[25rem]'
    >
      <SiteAgentChat onClose={close} />
    </aside>
  );
}

/** The conversation as a sheet above another dialog, on docked layouts; it closes when that dialog does. */
const closeAbove = () => panelStore.setAbove(false);

export function SiteAgentAbove() {
  const above = usePanel((s) => s.above);
  const docked = useDocked();
  const other = useOtherDialog();
  useEscapeClosesOnlyRafii(docked && above, closeAbove);
  useEffect(() => {
    // The dialog underneath closed (or the window narrowed) while the person was using Rafii: carry on in the
    // column or the sheet instead of vanishing. Closing Rafii's own sheet only clears `above`.
    if (above && (!other || !docked)) {
      panelStore.setAbove(false);
      panelStore.setOpen(true);
    }
  }, [above, other, docked]);
  if (!docked || !above) return null;
  return (
    <Sheet open onOpenChange={(next) => !next && closeAbove()}>
      <SheetContent
        id={PANEL_ID}
        side='right'
        showCloseButton={false}
        aria-label={siteConfig.name}
        className='rafii-elevated gap-0 p-0 shadow-none data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-md'
      >
        <SheetTitle className='sr-only'>{siteConfig.name}</SheetTitle>
        <SiteAgentChat onClose={closeAbove} />
      </SheetContent>
    </Sheet>
  );
}

/** The tablet sheet and phone bottom sheet; renders nothing when docked. */
export function SiteAgentOverlay() {
  const open = usePanel((s) => s.open);
  const docked = useDocked();
  const wide = useWide();
  const close = useCallback(() => {
    panelStore.setOpen(false);
    returnFocus();
  }, []);
  useEscapeClosesOnlyRafii(open && !docked, close);
  if (docked) return null;
  const onOpenChange = (next: boolean) => {
    if (!next) close();
  };
  if (!wide) {
    return (
      <Drawer open={open} onOpenChange={onOpenChange}>
        <DrawerContent
          id={PANEL_ID}
          aria-label={siteConfig.name}
          className='rafii-elevated [--drawer-content-max-height:calc(100dvh-3rem)] [--drawer-height:calc(100dvh-3rem)] data-[swipe-direction=down]:rounded-t-[var(--rafii-radius-mobile-dialog)] data-[swipe-direction=down]:border-t-0'
        >
          <DrawerTitle className='sr-only'>{siteConfig.name}</DrawerTitle>
          <div className='flex min-h-0 flex-1 flex-col'>
            <SiteAgentChat onClose={close} onNavigate={close} autoFocus={false} />
          </div>
        </DrawerContent>
      </Drawer>
    );
  }
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        id={PANEL_ID}
        side='right'
        showCloseButton={false}
        aria-label={siteConfig.name}
        className='rafii-elevated gap-0 p-0 shadow-none data-[side=right]:w-full data-[side=right]:rounded-l-[var(--rafii-radius-dialog)] data-[side=right]:border-l-0 data-[side=right]:sm:max-w-md'
      >
        <SheetTitle className='sr-only'>{siteConfig.name}</SheetTitle>
        <SiteAgentChat onClose={close} onNavigate={close} />
      </SheetContent>
    </Sheet>
  );
}
