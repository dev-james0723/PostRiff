'use client';

import { Icons } from '@/components/icons';
import { useTheme } from 'next-themes';
import * as React from 'react';

import { ActionSwapIcon } from '@/components/motion/action-swap';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Kbd } from '@/components/ui/kbd';
import { startThemeTransition } from '@/lib/theme-transition';
import { cn } from '@/lib/utils';

const subscribeToNothing = () => () => {};
const onClient = () => true;
const onServer = () => false;

export function ThemeModeToggle({ mobileTab = false }: { mobileTab?: boolean }) {
  const { setTheme, resolvedTheme } = useTheme();
  // The resolved theme only exists in the browser: the server and the hydration pass render the
  // neutral icon, then the sun or moon takes over without a mismatch.
  const mounted = React.useSyncExternalStore(subscribeToNothing, onClient, onServer);
  const mode = resolvedTheme === 'dark' ? 'dark' : 'light';
  const nextMode = mode === 'dark' ? 'light' : 'dark';
  const actionLabel = mounted ? `Switch to ${nextMode} mode` : 'Change color mode';

  const handleThemeToggle = React.useCallback(
    (e?: React.MouseEvent) => {
      const newMode = resolvedTheme === 'dark' ? 'light' : 'dark';
      // Circular reveal from the click point (falls back to center for the
      // keyboard shortcut, which passes no event).
      startThemeTransition(() => setTheme(newMode), e);
    },
    [resolvedTheme, setTheme]
  );

  // Cmd/Ctrl+Shift+D toggles the theme; kbar separately handles the 'D D' sequence
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'd' || !e.shiftKey || !(e.metaKey || e.ctrlKey)) return;
      const target = e.target as HTMLElement | null;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        target?.isContentEditable
      ) {
        return;
      }
      e.preventDefault();
      handleThemeToggle();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleThemeToggle]);

  const control = (
    <Button
      variant='ghost'
      size={mobileTab ? 'default' : 'icon'}
      className={cn(
        'group/toggle',
        mobileTab
          ? 'rafii-focus relative z-[1] min-h-[3.25rem] min-w-11 w-full flex-col gap-1 rounded-2xl px-0 text-[10px] font-medium text-muted-foreground min-[360px]:text-[11px]'
          : 'size-8'
      )}
      aria-label={actionLabel}
      onClick={handleThemeToggle}
    >
      <span aria-hidden>
        {mounted ? (
          <ActionSwapIcon value={mode} animation='roll'>
            {mode === 'dark' ? (
              <Icons.moon className={mobileTab ? 'size-5' : undefined} />
            ) : (
              <Icons.sun className={mobileTab ? 'size-5' : undefined} />
            )}
          </ActionSwapIcon>
        ) : (
          <Icons.brightness className={mobileTab ? 'size-5' : undefined} />
        )}
      </span>
      {mobileTab ? (
        <span aria-hidden>{mounted ? (mode === 'dark' ? 'Dark' : 'Light') : 'Theme'}</span>
      ) : (
        <span className='sr-only'>{actionLabel}</span>
      )}
    </Button>
  );

  if (mobileTab) return control;

  return (
    <Tooltip>
      <TooltipTrigger render={control} />
      <TooltipContent>
        {actionLabel} <Kbd>⌘⇧D</Kbd> <Kbd>D D</Kbd>
      </TooltipContent>
    </Tooltip>
  );
}
