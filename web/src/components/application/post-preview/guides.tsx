'use client';

import { createContext, useContext, useEffect, useId, useMemo, useSyncExternalStore, type ReactNode } from 'react';

/**
 * Guides: what a reader will not see, measured from the drawn post, listed under the phone and marked on it on
 * request. Parts of a template report notes while they are mounted; nothing here guesses at an app's rules
 * beyond what the template already draws and what `limits.ts` cites.
 */

/** A redline pink no template uses, so marks never read as part of an app. */
export const GUIDE_COLOR = '#f5367f';

export interface GuideNote {
  /** `problem` blocks or breaks the post; `check` is worth a look; `legend` explains marks while they show. */
  tone: 'problem' | 'check' | 'legend';
  text: string;
  /** Lower sorts first; see `NOTE_ORDER`. */
  order: number;
  /** The note has a mark to draw on the phone, so the guides toggle is worth offering. */
  marks?: boolean;
}

export const NOTE_ORDER = { limit: 0, media: 1, crop: 2, fold: 3, cover: 4 } as const;

type Listener = () => void;

export interface GuideStore {
  set: (key: string, note: GuideNote | null) => void;
  subscribe: (listener: Listener) => () => void;
  snapshot: () => GuideNote[];
}

const same = (a: GuideNote, b: GuideNote) => a.text === b.text && a.tone === b.tone && a.order === b.order && a.marks === b.marks;

export function createGuideStore(): GuideStore {
  const notes = new Map<string, GuideNote>();
  const listeners = new Set<Listener>();
  let snapshot: GuideNote[] = [];
  return {
    set(key, note) {
      const current = notes.get(key);
      if (note ? current && same(current, note) : !current) return;
      if (note) notes.set(key, note);
      else notes.delete(key);
      snapshot = [...notes.values()].toSorted((a, b) => a.order - b.order);
      listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    snapshot: () => snapshot
  };
}

const EMPTY: GuideNote[] = [];

export function useGuideNotes(store: GuideStore) {
  return useSyncExternalStore(store.subscribe, store.snapshot, () => EMPTY);
}

interface GuideContextValue {
  store: GuideStore;
  /** Marks are drawn on the phone. */
  show: boolean;
  /** The app's name as notes say it. */
  channelName: string;
}

const GuideContext = createContext<GuideContextValue | null>(null);

export function GuideProvider({ store, show, channelName, children }: GuideContextValue & { children: ReactNode }) {
  const value = useMemo(() => ({ store, show, channelName }), [store, show, channelName]);
  return <GuideContext.Provider value={value}>{children}</GuideContext.Provider>;
}

/** Null outside a preview (a template rendered on its own), where parts report nothing and draw no marks. */
export function useGuides() {
  return useContext(GuideContext);
}

/** Reports `note` while the calling part is mounted; null withdraws it. */
export function useGuideNote(note: GuideNote | null) {
  const store = useContext(GuideContext)?.store;
  const key = useId();
  const text = note?.text;
  const tone = note?.tone;
  const order = note?.order;
  const marks = note?.marks;
  useEffect(() => {
    if (!store) return;
    store.set(key, text !== undefined && tone !== undefined && order !== undefined ? { text, tone, order, marks } : null);
  }, [store, key, text, tone, order, marks]);
  useEffect(() => () => store?.set(key, null), [store, key]);
}

/** Classes for a "more" label that follows a cut caption: outlined while guides show. */
export const FOLD_MARK = 'in-data-[guides=on]:outline-2 in-data-[guides=on]:outline-offset-2 in-data-[guides=on]:outline-[#f5367f] in-data-[guides=on]:outline-dashed';

/** Classes for app controls drawn over the media (top bar, side rail, caption): shaded while guides show. */
export const COVER_MARK =
  'in-data-[guides=on]:bg-[#f5367f]/35 in-data-[guides=on]:outline-2 in-data-[guides=on]:-outline-offset-2 in-data-[guides=on]:outline-white/85 in-data-[guides=on]:outline-dashed';

const count = (value: number) => value.toLocaleString('en-US');

/** Scripts written without spaces, where any character boundary is a word boundary. */
const UNSPACED = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Thai}]/u;
const WORD_END = /[\p{L}\p{M}\p{N}]$/u;
const WORD_START = /^[\p{L}\p{M}\p{N}]/u;

/**
 * The last few words a reader sees before the cut, for quoting in a note. A word the cut splits is left out, so
 * the quote never ends on half a word; `next` is the text right after the cut.
 */
function lastWords(shown: string, next: string) {
  let text = shown.replace(/\s+/g, ' ').trimEnd();
  if (WORD_END.test(text) && WORD_START.test(next) && !UNSPACED.test(text.slice(-1))) {
    const cut = text.search(/[\p{L}\p{M}\p{N}]+$/u);
    if (cut > 0) text = text.slice(0, cut).trimEnd();
  }
  const chars = Array.from(text);
  const size = UNSPACED.test(chars.slice(-12).join('')) ? 12 : 26;
  const tail = chars.slice(-size).join('');
  const space = tail.indexOf(' ');
  return (chars.length > size && space > 0 && space < tail.length - 8 ? tail.slice(space + 1) : tail).trim();
}

/**
 * A fold note: how much of the text shows before the app cuts it. `more` is the app's label when it shows one;
 * `label` names the text when it is not the whole post (a title); `next` is the text right after the cut.
 */
export function foldNote(shown: string, { more, label, next = '' }: { more?: string; label?: string; next?: string } = {}): GuideNote {
  const n = count(Array.from(shown).length);
  const words = lastWords(shown, next);
  const quote = words ? `, ending “…${words}”` : '';
  const text = more
    ? `About ${n} characters show before “${more}”${quote}`
    : `${label ?? 'The text'} shows about ${n} characters in the feed${quote}`;
  return { tone: 'check', order: NOTE_ORDER.fold, marks: true, text };
}

/** Reports a caption the template cut by length (`truncateCaption`), for overlays that cannot measure lines. */
export function useCaptionFold(caption: { text: string; cut: boolean; rest?: string }, more: string) {
  useGuideNote(caption.cut ? foldNote(caption.text.replace(/…$/, ''), { more, next: caption.rest }) : null);
}

/** Explains the shaded controls while guides show, for templates that draw app controls over the media. */
export function useCoverLegend() {
  const channelName = useContext(GuideContext)?.channelName ?? 'The app';
  useGuideNote({ tone: 'legend', order: NOTE_ORDER.cover, marks: true, text: `Shaded: where ${channelName}'s buttons and caption sit over the picture` });
}

const RATIOS: [string, number][] = [
  ['1:1', 1],
  ['4:5', 5 / 4],
  ['3:4', 4 / 3],
  ['2:3', 3 / 2],
  ['9:16', 16 / 9],
  ['16:9', 9 / 16],
  ['1.91:1', 1 / 1.91],
  ['4:3', 3 / 4],
  ['3:2', 2 / 3],
  ['2:1', 1 / 2]
];

/** Width:height for a height/width ratio, by its common name when it is one. */
export function ratioName(ratio: number) {
  const known = RATIOS.find(([, value]) => Math.abs(value - ratio) / value < 0.015);
  if (known) return known[0];
  return ratio >= 1 ? `1:${(Math.round(ratio * 100) / 100).toString()}` : `${(Math.round((1 / ratio) * 100) / 100).toString()}:1`;
}

/** How much of a picture a box hides when the picture fills it (both ratios are height/width). */
export function hiddenShare(mediaRatio: number, boxRatio: number) {
  return mediaRatio > boxRatio
    ? { axis: 'height' as const, share: 1 - boxRatio / mediaRatio }
    : { axis: 'width' as const, share: 1 - mediaRatio / boxRatio };
}

export function cropNote(boxRatio: number, hidden: { axis: 'height' | 'width'; share: number }, channelName: string): GuideNote {
  return {
    tone: 'check',
    order: NOTE_ORDER.crop,
    marks: true,
    text: `${channelName} shows this photo at ${ratioName(boxRatio)}, hiding about ${Math.round(hidden.share * 100)}% of its ${hidden.axis}`
  };
}
