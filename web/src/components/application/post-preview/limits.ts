import { firstLine, restAfterFirstLine } from './parts';
import { NOTE_ORDER, type GuideNote } from './guides';
import type { PreviewPost } from './types';

/**
 * Text limits PostRiff is sure of, each with where it comes from. A channel missing here has no published limit
 * we could confirm, so its preview says nothing rather than guess. Counts follow each app's own rule.
 */

type Counter = (text: string) => number;

interface TextRule {
  /** The part of the post the app puts in the limited field: templates put the first line in title fields. */
  field: 'text' | 'title' | 'body';
  max: number;
  /** Unit as the note says it, plural. */
  unit: string;
  count: Counter;
  /** Only some posts use this field (Telegram captions media, TikTok's caption rule is for videos). */
  applies?: (post: PreviewPost) => boolean;
  /** Who the limit is for, when it is not everyone ("without Premium", "on default servers"). */
  scope?: string;
}

const codePoints: Counter = (text) => Array.from(text).length;

const segmenter = typeof Intl !== 'undefined' && 'Segmenter' in Intl ? new Intl.Segmenter('en', { granularity: 'grapheme' }) : null;
const graphemes: Counter = (text) => (segmenter ? Array.from(segmenter.segment(text)).length : codePoints(text));

const utf16: Counter = (text) => text.length;

const URL_PATTERN = /https?:\/\/[^\s]+|(?<![@\w.])(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|app|dev|co|me|tv|info|xyz|link|ly|hk|tw|jp|cn|uk|us|ca|au|de|fr|kr|sg|in)(?:\/[^\s]*)?(?![\w.-]*[a-z0-9])/giu;

/**
 * X's weighted count (twitter-text v3 config): Latin-range characters count 1, everything else 2, each emoji 2,
 * each link 23 however long.
 */
const X_LIGHT: [number, number][] = [
  [0, 4351],
  [8192, 8205],
  [8208, 8223],
  [8242, 8247]
];
const xWeighted: Counter = (text) => {
  let weight = 0;
  const rest = text.normalize('NFC').replace(URL_PATTERN, () => {
    weight += 23;
    return '';
  });
  const pieces = segmenter ? Array.from(segmenter.segment(rest), (s) => s.segment) : Array.from(rest);
  for (const piece of pieces) {
    if (/\p{Extended_Pictographic}/u.test(piece)) {
      weight += 2;
      continue;
    }
    for (const char of piece) {
      const code = char.codePointAt(0) ?? 0;
      weight += X_LIGHT.some(([start, end]) => code >= start && code <= end) ? 1 : 2;
    }
  }
  return weight;
};

/** Mastodon counts every link written with its protocol as 23, and a remote mention by its username only. */
const mastodonCount: Counter = (text) => {
  let links = 0;
  const rest = text.replace(/https?:\/\/[^\s]+/gu, () => {
    links += 1;
    return '';
  });
  return codePoints(rest.replace(/@([\p{L}\p{N}_]+)@[\w.-]+/gu, '@$1')) + links * 23;
};

const hasMedia = (post: PreviewPost) => post.media.some((item) => item.kind !== 'file');
const firstVisual = (post: PreviewPost) => post.media.find((item) => item.kind !== 'file');

const RULES: Record<string, TextRule[]> = {
  // LinkedIn Posts API commentary; also PostRiff's own contract limit.
  linkedin: [{ field: 'text', max: 3000, unit: 'characters', count: codePoints }],
  // Instagram Graph API content publishing: captions up to 2,200 characters.
  instagram: [{ field: 'text', max: 2200, unit: 'characters', count: codePoints }],
  // Threads API text posts; also PostRiff's own contract limit.
  threads: [{ field: 'text', max: 500, unit: 'characters', count: codePoints }],
  // twitter-text v3: 280 weighted characters for accounts without Premium.
  x: [{ field: 'text', max: 280, unit: 'characters by X’s count', count: xWeighted, scope: 'for accounts without Premium' }],
  // app.bsky.feed.post lexicon: text maxGraphemes 300.
  bluesky: [{ field: 'text', max: 300, unit: 'characters', count: graphemes }],
  // Mastodon's default MAX_CHARS; each server can change it.
  mastodon: [{ field: 'text', max: 500, unit: 'characters', count: mastodonCount, scope: 'on servers that keep the default' }],
  // Pixelfed's default max_caption_length; each server can change it.
  pixelfed: [{ field: 'text', max: 500, unit: 'characters', count: codePoints, scope: 'on servers that keep the default' }],
  // Facebook's post text limit.
  facebook: [{ field: 'text', max: 63206, unit: 'characters', count: codePoints }],
  // Pinterest API v5 pins: title 100, description 800.
  pinterest: [
    { field: 'title', max: 100, unit: 'characters in the title', count: codePoints },
    { field: 'body', max: 800, unit: 'characters in the description', count: codePoints }
  ],
  // Reddit post titles.
  reddit: [{ field: 'title', max: 300, unit: 'characters in the title', count: codePoints }],
  // YouTube Data API videos: title 100 characters.
  youtube: [{ field: 'title', max: 100, unit: 'characters in the title', count: codePoints }],
  // Telegram Bot API: messages 4,096 characters, media captions 1,024.
  telegram: [
    { field: 'text', max: 4096, unit: 'characters', count: utf16, applies: (post) => !hasMedia(post) },
    { field: 'text', max: 1024, unit: 'characters in a media caption', count: utf16, applies: hasMedia }
  ],
  // Discord message content.
  discord: [{ field: 'text', max: 2000, unit: 'characters', count: codePoints }],
  // Business Profile API local posts: summary up to 1,500 characters.
  'google-business-profile': [{ field: 'text', max: 1500, unit: 'characters', count: codePoints }],
  // LINE Messaging API text messages.
  'line-official-account': [{ field: 'text', max: 5000, unit: 'characters', count: utf16 }],
  // TikTok Content Posting API: a video's caption is up to 2,200 UTF-16 units.
  tiktok: [{ field: 'text', max: 2200, unit: 'characters', count: utf16, applies: (post) => firstVisual(post)?.kind === 'video' }]
};

function fieldText(post: PreviewPost, field: TextRule['field']) {
  if (field === 'title') return firstLine(post.text);
  if (field === 'body') return restAfterFirstLine(post.text);
  return post.text;
}

const n = (value: number) => value.toLocaleString('en-US');

/** Length notes for the post on its channel: one per limited field, a problem when over. */
export function limitNotes(post: PreviewPost): GuideNote[] {
  const notes: GuideNote[] = [];
  for (const rule of RULES[post.channel] ?? []) {
    if (rule.applies && !rule.applies(post)) continue;
    const text = fieldText(post, rule.field);
    if (!text) continue;
    const used = rule.count(text);
    const over = used - rule.max;
    notes.push(
      over > 0
        ? {
            tone: 'problem',
            order: NOTE_ORDER.limit,
            text: `${n(used)} / ${n(rule.max)} ${rule.unit}: ${n(over)} over ${post.channelName}’s limit${rule.scope ? ` ${rule.scope}` : ''}`
          }
        : { tone: 'check', order: NOTE_ORDER.limit, text: `${n(used)} / ${n(rule.max)} ${rule.unit}` }
    );
  }
  if (post.channel === 'instagram') {
    // Instagram Graph API: at most 30 hashtags and 20 @ tags in a caption.
    const hashtags = post.text.match(/#[\p{L}\p{N}_]+/gu)?.length ?? 0;
    const mentions = post.text.match(/(?<![\w@])@[\p{L}\p{N}_.]+/gu)?.length ?? 0;
    if (hashtags > 30) notes.push({ tone: 'problem', order: NOTE_ORDER.limit, text: `${hashtags} hashtags: Instagram allows 30` });
    if (mentions > 20) notes.push({ tone: 'problem', order: NOTE_ORDER.limit, text: `${mentions} @mentions: Instagram allows 20` });
  }
  if (post.channel === 'youtube' && /[<>]/.test(post.text)) {
    // YouTube Data API rejects < and > in titles and descriptions.
    notes.push({ tone: 'problem', order: NOTE_ORDER.limit, text: 'YouTube titles and descriptions can’t contain < or >' });
  }
  return notes;
}

export const LIMITED_CHANNELS = Object.keys(RULES);
