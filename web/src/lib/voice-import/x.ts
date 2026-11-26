/**
 * X archive: data/tweets.js (tweets-part1.js … when split; tweet.js in older archives) and data/note-tweet.js.
 * Each file is `window.YTD.<section>.part<N> = [ … ]`. Only the post sections are read; every other section
 * of the archive (messages, likes, account) is refused before any of it is parsed.
 */
import { emptyExport } from './meta';
import { asString, decodeEntities, isRecord, isoFromText, parseJson } from './text';
import type { ExportItem, ParsedExport } from './types';

const WRAPPER = /^\s*window\.YTD\.([A-Za-z0-9_]+)\.part\d+\s*=\s*/;
const SECTIONS: Record<string, 'tweets' | 'note-tweet'> = { tweets: 'tweets', tweet: 'tweets', community_tweet: 'tweets', note_tweet: 'note-tweet' };
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

/** `tweets` or `note-tweet` for a post file, `other` for any other archive section, `null` when the text is not an X archive file. */
export function xSection(text: string): 'tweets' | 'note-tweet' | 'other' | null {
  const match = WRAPPER.exec(text.slice(0, 200));
  return match ? (SECTIONS[match[1]] ?? 'other') : null;
}

/** "Sun Feb 18 12:33:11 +0000 2024", parsed by hand because browsers disagree on this format. */
export function xDate(value: unknown): string | undefined {
  const match = /^\w{3} (\w{3}) (\d{1,2}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2}) (\d{4})$/.exec(asString(value).trim());
  if (!match) return isoFromText(value);
  const month = MONTHS.indexOf(match[1].toLowerCase());
  if (month < 0) return undefined;
  const offset = (Number(match[7]) * 60 + Number(match[8])) * (match[6] === '-' ? -1 : 1);
  const ms = Date.UTC(Number(match[9]), month, Number(match[2]), Number(match[3]), Number(match[4]), Number(match[5])) - offset * 60_000;
  return Number.isFinite(ms) ? new Date(ms).toISOString() : undefined;
}

function tweetItem(entry: unknown): ExportItem | 'empty' | null {
  const tweet = isRecord(entry) && isRecord(entry.tweet) ? entry.tweet : null;
  const id = tweet ? asString(tweet.id_str) || asString(tweet.id) : '';
  if (!tweet || !/^\d{1,30}$/.test(id)) return null;
  // The archive escapes &, < and > in post text.
  const text = decodeEntities(asString(tweet.full_text) || asString(tweet.text)).trim();
  if (!text) return 'empty';
  const item: ExportItem = { externalId: id, text, permalink: `https://x.com/i/web/status/${id}`, kind: text.startsWith('RT @') ? 'repost' : asString(tweet.in_reply_to_status_id_str) ? 'reply' : 'original' };
  const publishedAt = xDate(tweet.created_at);
  if (publishedAt) item.publishedAt = publishedAt;
  return item;
}

function noteItem(entry: unknown): ExportItem | 'empty' | null {
  const note = isRecord(entry) && isRecord(entry.noteTweet) ? entry.noteTweet : null;
  const id = note ? asString(note.noteTweetId) : '';
  if (!note || !id) return null;
  const text = isRecord(note.core) ? asString(note.core.text).trim() : '';
  if (!text) return 'empty';
  // A note has no post id of its own in the archive; `combineNotes` joins it to its shortened post when both files are given.
  const item: ExportItem = { externalId: `note:${id}`, text };
  const publishedAt = isoFromText(note.createdAt);
  if (publishedAt) item.publishedAt = publishedAt;
  return item;
}

export function parseX(text: string): ParsedExport {
  const section = xSection(text);
  const layout = section === 'note-tweet' ? 'note-tweet' : 'tweets';
  const result = emptyExport('x', layout);
  if (section !== 'tweets' && section !== 'note-tweet') return { ...result, notes: ['unknown_shape'] };
  const json = parseJson(text.replace(WRAPPER, ''));
  if (json === undefined) return { ...result, notes: ['not_json'] };
  if (!Array.isArray(json)) return { ...result, notes: ['unknown_shape'] };
  for (const entry of json) {
    const item = section === 'tweets' ? tweetItem(entry) : noteItem(entry);
    if (item === null) result.skipped.unsupported++;
    else if (item === 'empty') result.skipped.empty++;
    else result.items.push(item);
  }
  return result;
}

const squash = (text: string) => text.replace(/\s+/g, ' ').trim();

/**
 * A long post appears twice in the archive: in full in note-tweet.js, and cut short in tweets.js. When a note
 * starts with a post's shortened text and the two were created within ten seconds, the post takes the full text
 * and the note is dropped, so one piece of writing is one record. A note with no such post stays as it is.
 */
export function combineNotes(items: ExportItem[]): ExportItem[] {
  const notes = items.filter((item) => item.externalId.startsWith('note:'));
  if (!notes.length) return items;
  const posts = items.filter((item) => !item.externalId.startsWith('note:') && item.kind !== 'repost');
  const fullText = new Map<string, string>();
  const joined = new Set<string>();
  for (const note of notes) {
    const full = squash(note.text);
    const time = note.publishedAt ? Date.parse(note.publishedAt) : Number.NaN;
    const match = posts.find((post) => {
      if (fullText.has(post.externalId)) return false;
      const short = squash(post.text).replace(/\s*https:\/\/t\.co\/\w+$/, '').replace(/[…\s]+$/, '');
      if (short.length < 20 || short.length >= full.length || !full.startsWith(short)) return false;
      const posted = post.publishedAt ? Date.parse(post.publishedAt) : Number.NaN;
      return Number.isNaN(time) || Number.isNaN(posted) ? short.length >= 80 : Math.abs(time - posted) <= 10_000;
    });
    if (match) {
      fullText.set(match.externalId, note.text);
      joined.add(note.externalId);
    }
  }
  return items.filter((item) => !joined.has(item.externalId)).map((item) => (fullText.has(item.externalId) ? { ...item, text: fullText.get(item.externalId) as string } : item));
}
