'use client';
import { useEffect, useState } from 'react';
import { useRegisterActions } from 'kbar';
import { rafiiDialog, rafiiDialogFooter } from '@/components/auth/form-styles';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Kbd } from '@/components/ui/kbd';
import { navGroups } from '@/config/nav-config';
import { useFilteredNavGroups } from '@/hooks/use-nav';
import { cn } from '@/lib/utils';

export const SHORTCUTS_EVENT = 'postriff:shortcuts';

/** The keyboard shortcut sheet: an elevated glass dialog (DNA §12.2) opened by `?`, the help menu or the palette. */
export function ShortcutsDialog() {
  const [open, setOpen] = useState(false);
  const groups = useFilteredNavGroups(navGroups);
  useEffect(() => {
    const show = () => setOpen(true);
    const key = (event: KeyboardEvent) => {
      if (event.key !== '?' || event.metaKey || event.ctrlKey || event.altKey || window.matchMedia('(max-width: 767px)').matches) return;
      if (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
      event.preventDefault();
      setOpen(true);
    };
    window.addEventListener(SHORTCUTS_EVENT, show);
    window.addEventListener('keydown', key);
    return () => {
      window.removeEventListener(SHORTCUTS_EVENT, show);
      window.removeEventListener('keydown', key);
    };
  }, []);
  useRegisterActions([{ id: 'keyboard-shortcuts', name: 'Keyboard shortcuts', section: 'Help', perform: () => setOpen(true) }], []);
  const entries = [
    { title: 'Search and commands', shortcut: ['⌘ / Ctrl', 'K'] },
    { title: 'Toggle sidebar', shortcut: ['⌘ / Ctrl', 'B'] },
    { title: 'Page information', shortcut: ['⌘ / Ctrl', 'I'] },
    { title: 'Toggle theme', shortcut: ['⌘ / Ctrl', 'Shift', 'D'] },
    ...groups.flatMap((g) => g.items).filter((i) => i.shortcut?.length),
    { title: 'Keyboard shortcuts', shortcut: ['?'] }
  ];
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className={cn(rafiiDialog, 'max-h-[85dvh] gap-5 overflow-y-auto sm:max-w-xl')}>
        <DialogHeader className='gap-1.5 pr-8'>
          <DialogTitle className='text-foreground text-xl font-medium tracking-tight'>Keyboard shortcuts</DialogTitle>
          <DialogDescription className='leading-relaxed'>Type letter pairs outside text fields.</DialogDescription>
        </DialogHeader>
        <dl className='grid gap-1.5 sm:grid-cols-2'>
          {entries.map((item) => (
            <div key={item.title} className='rafii-quiet flex min-h-11 items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2'>
              <dt className='text-foreground text-sm'>{item.title}</dt>
              <dd className='flex shrink-0 gap-1'>
                {item.shortcut?.map((key, index) => (
                  <Kbd key={`${key}-${index}`}>{key}</Kbd>
                ))}
              </dd>
            </div>
          ))}
        </dl>
        <DialogFooter className={rafiiDialogFooter}>
          <Button variant='glass' size='control' onClick={() => setOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
