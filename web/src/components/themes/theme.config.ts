/**
 * Default theme that loads when no user preference is set
 * Change this value to set a different default theme
 */
export const DEFAULT_THEME = 'rafii';

/** Cookie holding a theme the person picked (unset means DEFAULT_THEME). */
export const THEME_COOKIE = 'postriff_theme';

export const THEMES = [
  {
    name: 'Rafii',
    value: 'rafii'
  },
  {
    name: 'Claude',
    value: 'claude'
  },
  {
    name: 'Discord',
    value: 'discord'
  },
  {
    name: 'Supabase',
    value: 'supabase'
  },
  {
    name: 'Vercel',
    value: 'vercel'
  },
  {
    name: 'Mono',
    value: 'mono'
  },
  {
    name: 'Notebook',
    value: 'notebook'
  },
  {
    name: 'Light Green',
    value: 'light-green'
  },
  {
    name: 'Zen',
    value: 'zen'
  },
  {
    name: 'Astro Vista',
    value: 'astro-vista'
  },
  {
    name: 'WhatsApp',
    value: 'whatsapp'
  }
];
