/**
 * The client chip model for a message (chat-context SPEC §5.1): what the person added with ＋ or `@`, and the exact
 * `references`/`attachments` fields the request carries. Pure: no React, no `@/` imports (node --test transpiles it).
 *
 * The server re-derives every label and re-checks every id (turn_references.py); a chip label here is for display and
 * for the request digest only. `labelFor` mirrors `turn_references.label_for` through tests/fixtures/chip-labels.json
 * and `postRoleDefault` mirrors REWORK_CUES through tests/fixtures/rework-cues.json.
 */

export type ChipKind = "post" | "template" | "source" | "image" | "video"; // accounts/folders never become chips on the web
export type PostRole = "rework" | "inspire";
export type MediaRole = "post" | "reference";
export type Slot = "A" | "B" | "C" | "D";

export interface Chip {
  key: string;
  kind: ChipKind;
  id: string;
  label: string;
  role?: PostRole | MediaRole;
  slot?: Slot;
  meta?: {
    platform?: string;
    mime?: string;
    duration?: number;
    width?: number;
    height?: number;
    thumb?: string;
    /** A video this browser couldn't take frames from ("No preview in this browser"), or couldn't time ("Length not checked."). */
    noPreview?: boolean;
    lengthUnchecked?: boolean;
  };
  upload?: {
    status: "preparing" | "uploading" | "checking" | "ready" | "failed";
    progress?: number;
    message?: string;
  };
  read?: { status: "idle" | "reading" | "read" | "failed"; note?: string; milliCredits?: number };
}

export interface Reference {
  kind: "post" | "template" | "source";
  id: string;
  label?: string;
  role?: PostRole;
}

export interface Attachment {
  assetId: string;
  role: MediaRole;
  slot?: Slot;
}

export interface RequestFields {
  references?: Reference[];
  attachments?: Attachment[];
}

export const LIMITS = { references: 12, posts: 3, attachments: 4, videos: 1 } as const;
export const SLOTS: readonly Slot[] = ["A", "B", "C", "D"];
const LABEL_MAX = 80;

function isMedia(kind: ChipKind): kind is "image" | "video" {
  return kind === "image" || kind === "video";
}

/**
 * The request fields for these chips, built once and sent byte-identically to the estimate, the quote and the turn
 * (SPEC §3 S4). Insertion order is kept; chips still uploading are skipped (send is disabled then anyway); duplicates
 * (kind+id) and anything past the limits are dropped; keys are omitted when empty; image generation sends none.
 */
export function requestFields(
  chips: readonly Chip[],
  opts: { imageGeneration: boolean },
): RequestFields {
  if (opts.imageGeneration) return {};
  const seen = new Set<string>();
  const references: Reference[] = [];
  const attachments: Attachment[] = [];
  let posts = 0;
  let videos = 0;
  for (const chip of chips) {
    if (chip.upload && chip.upload.status !== "ready") continue;
    const key = `${isMedia(chip.kind) ? "asset" : chip.kind}:${chip.id}`;
    if (seen.has(key)) continue;
    if (isMedia(chip.kind)) {
      if (
        attachments.length >= LIMITS.attachments ||
        (chip.kind === "video" && videos >= LIMITS.videos)
      )
        continue;
      seen.add(key);
      videos += chip.kind === "video" ? 1 : 0;
      const role: MediaRole = chip.role === "reference" ? "reference" : "post";
      attachments.push({ assetId: chip.id, role, ...(chip.slot ? { slot: chip.slot } : {}) });
      continue;
    }
    if (references.length >= LIMITS.references || (chip.kind === "post" && posts >= LIMITS.posts))
      continue;
    seen.add(key);
    posts += chip.kind === "post" ? 1 : 0;
    const label = chip.label ? Array.from(chip.label).slice(0, LABEL_MAX).join("") : undefined;
    const role =
      chip.kind === "post" && (chip.role === "rework" || chip.role === "inspire")
        ? chip.role
        : undefined;
    references.push({
      kind: chip.kind,
      id: chip.id,
      ...(label ? { label } : {}),
      ...(role ? { role } : {}),
    });
  }
  return {
    ...(references.length ? { references } : {}),
    ...(attachments.length ? { attachments } : {}),
  };
}

/** The first free media slot, so "Photo A" / "Video B" stay stable for this message. */
export function nextSlot(chips: readonly Chip[]): Slot | null {
  const taken = new Set(chips.filter((chip) => isMedia(chip.kind)).map((chip) => chip.slot));
  return SLOTS.find((slot) => !taken.has(slot)) ?? null;
}

// --- labels (mirror of turn_references.label_for) -------------------------------------------------------------------

// Zero-width joiner and text/emoji variation selectors left dangling at a cut.
const TRAILING_JOINERS = /(?:\u200d|\ufe0e|\ufe0f)+$/u;

// The same line breaks as Python's str.splitlines(), without a control-character regex.
const LINE_BREAKS = new Set([
  "\n",
  "\r",
  "\v",
  "\f",
  "\u001c",
  "\u001d",
  "\u001e",
  "\u0085",
  "\u2028",
  "\u2029",
]);

function splitLines(text: string): string[] {
  const lines: string[] = [];
  let current = "";
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (!LINE_BREAKS.has(ch)) {
      current += ch;
      continue;
    }
    lines.push(current);
    current = "";
    if (ch === "\r" && text[i + 1] === "\n") i += 1;
  }
  lines.push(current);
  return lines;
}

function clip(value: unknown, limit: number): string {
  const text = (typeof value === "string" ? value : "").replace(/\s+/gu, " ").trim();
  // Code points, never a lone surrogate (Array.from splits by code point; lone surrogates are dropped).
  const points = Array.from(text).filter(
    (ch) => !(ch.length === 1 && ch.charCodeAt(0) >= 0xd800 && ch.charCodeAt(0) <= 0xdfff),
  );
  return points.slice(0, limit).join("").replace(TRAILING_JOINERS, "").trimEnd();
}

export function labelFor(
  kind: string,
  record: Record<string, unknown> | null | undefined,
  slot?: string | null,
): string {
  const r = record ?? {};
  if (kind === "post") {
    const text = typeof r.text === "string" ? r.text : "";
    const first = splitLines(text).find((line) => line.trim()) ?? "";
    return clip(first, 24) || `${(r.platform as string) || "Social"} draft`;
  }
  if (kind === "account") {
    const account = clip(r.account, 40);
    return clip(
      account
        ? `${(r.platform as string) || "Account"} · ${account}`
        : (r.platform as string) || "Account",
      40,
    );
  }
  if (kind === "image" || kind === "video")
    return `${kind === "video" ? "Video" : "Photo"} ${slot || "A"}`;
  const fallback: Record<string, string> = {
    template: "Template",
    source: "Source",
    folder: "Folder",
    campaign: "Campaign",
  };
  return clip(kind === "source" ? r.title : r.name, 40) || fallback[kind] || "Item";
}

// --- default post role (mirror of REWORK_CUES) ------------------------------------------------------------------------

export const REWORK_CUES =
  /(改寫|改写|修改|縮短|缩短|精簡|精简|潤飾|润饰|翻譯|翻译|改|\b(?:rewrite|rework|shorten|tighten|trim|edit|fix|polish|translate|adapt|update|revise|condense)\b)/i;

/** With exactly one post, a rewrite verb in the message makes it the rework; otherwise posts are for ideas. */
export function postRoleDefault(text: string, postCount = 1): PostRole {
  return postCount === 1 && REWORK_CUES.test(text) ? "rework" : "inspire";
}

/** Choosing Rework on one post turns any other rework post into "For ideas" (only one post can be reworked). */
export function setPostRole(chips: readonly Chip[], key: string, role: PostRole): Chip[] {
  return chips.map((chip) => {
    if (chip.key === key) return { ...chip, role };
    if (role === "rework" && chip.kind === "post" && chip.role === "rework")
      return { ...chip, role: "inspire" };
    return chip;
  });
}

// --- inserting a picked label -------------------------------------------------------------------------------------------

const CJK =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\u3000-\u303f\uff00-\uffef]/u; // CJK symbols and punctuation, full-width forms

/**
 * Replace `value[start, end)` (the `@query`) with the label as plain text: 「label」 when a neighbouring character is
 * CJK, “label” otherwise. No spaces are added between CJK characters. Returns the new value and the caret after it.
 */
export function insertLabel(
  value: string,
  start: number,
  end: number,
  label: string,
): { value: string; caret: number; inserted: string } {
  const before = Array.from(value.slice(0, start)).pop() ?? "";
  const after = Array.from(value.slice(end))[0] ?? "";
  const cjk = CJK.test(before) || CJK.test(after);
  const inserted = cjk ? `「${label}」` : `“${label}”`;
  const next = value.slice(0, start) + inserted + value.slice(end);
  return { value: next, caret: start + inserted.length, inserted };
}
