'use client';

import { ReactNode, createContext, useCallback, useContext, useEffect, useState } from 'react';

import { DEFAULT_THEME, THEME_COOKIE } from './theme.config';

// Earlier versions wrote every visitor's theme to this cookie on each visit, including the starter
// default nobody picked, which kept returning visitors on that old theme after the default changed.
const LEGACY_COOKIE = 'active_theme';

function writeCookie(name: string, value: string, maxAge: number) {
  if (typeof window === 'undefined') return;

  document.cookie = `${name}=${value}; path=/; max-age=${maxAge}; SameSite=Lax; ${window.location.protocol === 'https:' ? 'Secure;' : ''}`;
}

type ThemeContextType = {
  activeTheme: string;
  setActiveTheme: (theme: string) => void;
};

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ActiveThemeProvider({
  children,
  initialTheme
}: {
  children: ReactNode;
  initialTheme?: string;
}) {
  const themeToUse = initialTheme || DEFAULT_THEME;
  const [activeTheme, setActiveThemeState] = useState<string>(themeToUse);

  // Remembered only once the person picks a theme, so a later default still reaches everyone else.
  const setActiveTheme = useCallback((theme: string) => {
    writeCookie(THEME_COOKIE, theme, 31536000);
    setActiveThemeState(theme);
  }, []);

  useEffect(() => {
    if (document.cookie.split('; ').some((c) => c.startsWith(`${LEGACY_COOKIE}=`))) writeCookie(LEGACY_COOKIE, '', 0);
  }, []);

  useEffect(() => {
    if (document.documentElement.getAttribute('data-theme') === activeTheme) return;

    // Remove existing data-theme attribute
    document.documentElement.removeAttribute('data-theme');

    // Remove any theme classes from body (cleanup)
    Array.from(document.body.classList)
      .filter((className) => className.startsWith('theme-'))
      .forEach((className) => {
        document.body.classList.remove(className);
      });

    // Set data-theme on html element
    if (activeTheme) {
      document.documentElement.setAttribute('data-theme', activeTheme);
    }
  }, [activeTheme]);

  return (
    <ThemeContext.Provider value={{ activeTheme, setActiveTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useThemeConfig() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useThemeConfig must be used within an ActiveThemeProvider');
  }
  return context;
}
