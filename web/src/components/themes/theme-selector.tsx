'use client';

import { useThemeConfig } from '@/components/themes/active-theme';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';

import { Icons } from '../icons';
import { Kbd } from '@/components/ui/kbd';
import { THEMES } from './theme.config';

/**
 * The Appearance control: every theme stays available (Rafii is the default), on a quiet glass
 * trigger that matches the header's other controls. `T T` cycles it from the palette.
 */
export function ThemeSelector() {
  const { activeTheme, setActiveTheme } = useThemeConfig();

  return (
    <div className='flex items-center gap-2'>
      <Label htmlFor='theme-selector' className='sr-only'>
        Appearance
      </Label>
      <Select
        items={THEMES.map((theme) => ({ value: theme.value, label: theme.name }))}
        value={activeTheme}
        onValueChange={(value) => {
          if (value !== null) setActiveTheme(value);
        }}
      >
        <SelectTrigger
          id='theme-selector'
          aria-label='Appearance'
          className='rafii-glass hover:rafii-glass-selected h-8 justify-start rounded-[var(--rafii-radius-control)] border-0 bg-transparent pr-2 pl-2.5 dark:bg-transparent dark:hover:bg-transparent *:data-[slot=select-value]:w-24'
        >
          <span className='text-muted-foreground hidden sm:block'>
            <Icons.palette />
          </span>
          <span className='text-muted-foreground block sm:hidden'>Appearance</span>
          <SelectValue placeholder='Select an appearance' />
          <Kbd>T T</Kbd>
        </SelectTrigger>
        <SelectContent align='end' className='rafii-elevated rounded-2xl bg-transparent ring-0'>
          {THEMES.length > 0 && (
            <>
              <SelectGroup>
                <SelectLabel className='rafii-eyebrow'>Appearance</SelectLabel>
                {THEMES.map((theme) => (
                  <SelectItem key={theme.name} value={theme.value}>
                    {theme.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </>
          )}
        </SelectContent>
      </Select>
    </div>
  );
}
