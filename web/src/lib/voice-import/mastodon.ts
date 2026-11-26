/**
 * Mastodon archive: outbox.json, an ActivityStreams collection. `Create` carries a Note the account wrote;
 * `Announce` is a boost. The archive also holds followers-only and direct posts: those are counted for the
 * person and left on the device.
 */
import { emptyExport } from './meta';
import { asString, isRecord, isoFromText, stableId, stripHtml } from './text';
import type { Json } from './text';
import type { ExportItem, ParsedExport } from './types';

const LAYOUT = 'outbox';
const PUBLIC = new Set(['https://www.w3.org/ns/activitystreams#Public', 'as:Public', 'Public']);

export function looksLikeMastodon(json: unknown): boolean {
  return isRecord(json) && Array.isArray(json.orderedItems);
}

/** Public or unlisted: the public collection is addressed in `to` or `cc`, on the activity or on its object. */
function isPublic(...holders: (Json | null)[]): boolean {
  return holders.some((holder) => holder !== null && [holder.to, holder.cc].some((list) => (Array.isArray(list) ? list : [list]).some((target) => typeof target === 'string' && PUBLIC.has(target))));
}

/** The status id the server's own interface uses, when the object id has the usual `…/statuses/<id>` form. */
function statusId(object: Json, text: string, publishedAt?: string): string {
  const id = asString(object.id);
  const numeric = /\/statuses\/(\d{1,30})$/.exec(id)?.[1];
  if (numeric) return numeric;
  return id && id.length <= 300 ? id : stableId('mastodon', publishedAt ? Date.parse(publishedAt) / 1000 : undefined, text);
}

export function parseMastodon(json: unknown): ParsedExport {
  const result = emptyExport('mastodon', LAYOUT);
  if (!isRecord(json) || !Array.isArray(json.orderedItems)) return { ...result, notes: ['unknown_shape'] };
  for (const activity of json.orderedItems) {
    if (!isRecord(activity)) {
      result.skipped.unsupported++;
      continue;
    }
    const object = isRecord(activity.object) ? activity.object : null;
    if (!isPublic(activity, object)) {
      result.local.notPublic++;
      continue;
    }
    if (activity.type === 'Announce') {
      result.local.reposts++;
      continue;
    }
    if (activity.type !== 'Create' || !object || object.type !== 'Note') {
      result.skipped.unsupported++;
      continue;
    }
    const text = stripHtml(asString(object.content));
    if (!text) {
      result.skipped.empty++;
      continue;
    }
    const publishedAt = isoFromText(object.published) ?? isoFromText(activity.published);
    const item: ExportItem = { externalId: statusId(object, text, publishedAt), text };
    if (publishedAt) item.publishedAt = publishedAt;
    const url = asString(object.url) || asString(object.id);
    if (/^https:\/\//i.test(url)) item.permalink = url;
    item.kind = asString(object.inReplyTo) ? 'reply' : object.quote || object.quoteUrl || object.quoteUri ? 'quote' : 'original';
    result.items.push(item);
  }
  return result;
}
