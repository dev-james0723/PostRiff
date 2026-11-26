/**
 * Sending an export's posts: at most 200 records and under 512 kB per request, one request after another, with
 * progress counted from what the workspace acknowledged. The file itself is never sent.
 */
import { countChars } from './text';
import type { ExportItem, ItemsBody } from './types';

export const MAX_BATCH_ITEMS = 200;
/** The items route accepts 512 kB. This budget is lower so the rest of the body (skipped counts, the final flag) always fits. */
export const MAX_BATCH_BYTES = 480_000;
/** A stored post holds at most 20,000 characters. A longer one is left out and counted, never cut. */
export const MAX_POST_CHARS = 20_000;

const encoder = new TextEncoder();

/** The record's size inside the JSON body, in bytes, with its separating comma. */
export function itemBytes(item: ExportItem): number {
  return encoder.encode(JSON.stringify(item)).length + 1;
}

export interface BatchPlan {
  batches: ExportItem[][];
  /** Posts longer than the limit: left on the device and reported with the upload as unsupported. */
  tooLong: number;
}

export function planBatches(items: ExportItem[], limits: { maxItems?: number; maxBytes?: number } = {}): BatchPlan {
  const maxItems = limits.maxItems ?? MAX_BATCH_ITEMS;
  const maxBytes = limits.maxBytes ?? MAX_BATCH_BYTES;
  const batches: ExportItem[][] = [];
  let current: ExportItem[] = [];
  let bytes = 0;
  let tooLong = 0;
  for (const item of items) {
    const size = itemBytes(item);
    if (size > maxBytes || (item.text.length > MAX_POST_CHARS && countChars(item.text) > MAX_POST_CHARS)) {
      tooLong++;
      continue;
    }
    if (current.length >= maxItems || bytes + size > maxBytes) {
      batches.push(current);
      current = [];
      bytes = 0;
    }
    current.push(item);
    bytes += size;
  }
  if (current.length) batches.push(current);
  return { batches, tooLong };
}

/**
 * The key an uploaded export's posts are filed under: the account name as typed, trimmed, without a leading @ and in
 * lower case, so a later upload for the same account joins the same records.
 */
export function exportAccountKey(label: string): string {
  return [...label.trim().replace(/^@+/, '').toLowerCase().replace(/\s+/g, ' ')].slice(0, 200).join('');
}

export interface SendProgress {
  /** Posts the workspace has acknowledged so far. */
  sent: number;
  total: number;
  batch: number;
  batches: number;
}

export type SendResult<T> = { ok: true; last: T | undefined } | { ok: false; next: number; cancelled: boolean; error?: unknown };

/**
 * Sends the batches in order, starting at `from` (a resumed upload continues where it stopped; the route stores a
 * record by its id, so sending a batch again changes nothing). The skipped counts travel with the last batch, which
 * also closes the upload. A failure stops the run and reports which batch to resume from; nothing is retried silently.
 */
export async function sendBatches<T>(
  batches: ExportItem[][],
  options: { send: (body: ItemsBody) => Promise<T>; skipped: { unsupported: number; empty: number }; from?: number; onProgress?: (progress: SendProgress) => void; cancelled?: () => boolean }
): Promise<SendResult<T>> {
  const total = batches.reduce((sum, batch) => sum + batch.length, 0);
  const from = options.from ?? 0;
  let sent = batches.slice(0, from).reduce((sum, batch) => sum + batch.length, 0);
  let last: T | undefined;
  for (let index = from; index < batches.length; index++) {
    if (options.cancelled?.()) return { ok: false, next: index, cancelled: true };
    const final = index === batches.length - 1;
    try {
      // `seq` (from 1) is the batch's place in the upload: the route counts a batch it already has once, so a resend
      // after a lost reply neither adds posts twice nor leaves a finished upload looking stopped.
      last = await options.send({ items: batches[index], seq: index + 1, ...(final ? { skipped: options.skipped, final: true } : {}) });
    } catch (error) {
      return { ok: false, next: index, cancelled: false, error };
    }
    sent += batches[index].length;
    options.onProgress?.({ sent, total, batch: index + 1, batches: batches.length });
  }
  return { ok: true, last };
}
