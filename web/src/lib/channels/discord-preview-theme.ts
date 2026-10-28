/**
 * Colours for the Discord message preview. Discord draws its own message list in its own two themes, so the preview
 * uses fixed Discord-like values instead of the app's tokens (the surrounding labels and notes use the app's tokens).
 * Values follow Discord's published dark and light chat palettes; the dark timestamp is a little lighter than
 * Discord's so small text stays above 4.5:1 here. `tests/discord-sender-name.test.cjs` asserts every pair below.
 * Framework free so the contrast check runs in node.
 */

export type PreviewTheme = 'dark' | 'light';

export interface PreviewPalette {
  /** The message list background. */
  surface: string;
  /** Border around the message box. */
  edge: string;
  /** Author name. */
  name: string;
  /** Message text. */
  text: string;
  /** Timestamp and the muted "no name yet" placeholder. */
  muted: string;
  appTagBackground: string;
  appTagText: string;
  avatarBackground: string;
  avatarForeground: string;
}

export const DISCORD_PREVIEW_PALETTE: Record<PreviewTheme, PreviewPalette> = {
  dark: {
    surface: '#313338',
    edge: '#1e1f22',
    name: '#f2f3f5',
    text: '#dbdee1',
    muted: '#a1a6ae',
    appTagBackground: '#5865f2',
    appTagText: '#ffffff',
    avatarBackground: '#4e5058',
    avatarForeground: '#dbdee1'
  },
  light: {
    surface: '#ffffff',
    edge: '#d1d4d9',
    name: '#060607',
    text: '#313338',
    muted: '#5c5e66',
    appTagBackground: '#5865f2',
    appTagText: '#ffffff',
    avatarBackground: '#e3e5e8',
    avatarForeground: '#4e5058'
  }
};

function channel(value: number): number {
  const scaled = value / 255;
  return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

/** WCAG 2.x relative luminance of `#rrggbb`. */
export function relativeLuminance(hex: string): number {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!match) throw new Error(`Not a #rrggbb colour: ${hex}`);
  const [red, green, blue] = [match[1], match[2], match[3]].map((part) => channel(parseInt(part, 16)));
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

/** WCAG 2.x contrast ratio between two `#rrggbb` colours (1 to 21). */
export function contrastRatio(foreground: string, background: string): number {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

/** The text/background pairs the preview draws, with the minimum ratio each needs (all are small text: 4.5). */
export const PREVIEW_CONTRAST_PAIRS: readonly { label: string; foreground: keyof PreviewPalette; background: keyof PreviewPalette; minimum: number }[] = [
  { label: 'message text on the message list', foreground: 'text', background: 'surface', minimum: 4.5 },
  { label: 'author name on the message list', foreground: 'name', background: 'surface', minimum: 4.5 },
  { label: 'timestamp on the message list', foreground: 'muted', background: 'surface', minimum: 4.5 },
  { label: 'APP tag text on the APP tag', foreground: 'appTagText', background: 'appTagBackground', minimum: 4.5 },
  { label: 'avatar placeholder glyph on the placeholder', foreground: 'avatarForeground', background: 'avatarBackground', minimum: 3 }
];
