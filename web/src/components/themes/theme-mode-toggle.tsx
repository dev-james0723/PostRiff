'use client';

import { Icons } from '@/components/icons';
import { useTheme } from 'next-themes';
import * as React from 'react';

import { ActionSwapIcon } from '@/components/motion/action-swap';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Kbd } from '@/components/ui/kbd';
import { startThemeTransition } from '@/lib/theme-transition';

const subscribeToNothing = () => () => {};
const onClient = () => true;
const onServer = () => false;

export function ThemeModeToggle() {
  const { setTheme, resolvedTheme } = useTheme();
  // The resolved theme only exists in the browser: the server and the hydration pass render the
  // neutral icon, then the sun or moon takes over without a mismatch.
  const mounted = React.useSyncExternalStore(subscribeToNothing, onClient, onServer);
  const mode = resolvedTheme === 'dark' ? 'dark' : 'light';

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

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant='ghost'
            size='icon'
            className='group/toggle size-8'
            aria-label='Toggle theme'
            onClick={handleThemeToggle}
          />
        }
      >
        {mounted ? (
          <ActionSwapIcon value={mode} animation='roll'>
            {mode === 'dark' ? <Icons.moon /> : <Icons.sun />}
          </ActionSwapIcon>
        ) : (
          <Icons.brightness />
        )}
        <span className='sr-only'>Toggle theme</span>
      </TooltipTrigger>
      <TooltipContent>
        Toggle theme <Kbd>⌘⇧D</Kbd> <Kbd>D D</Kbd>
      </TooltipContent>
    </Tooltip>
  );
}
