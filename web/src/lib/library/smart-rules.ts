/**
 * Smart Collection rules in the browser (collections.py, rule_schema 1). The builder only offers the server's allowlist
 * of fields, operators and value types — never free text that could become a query — and checks values the same way
 * before anything is sent. The plain-language explanation always comes from the server.
 *
 * No imports: web/tests/library-intelligence-ui.test.cjs transpiles this module on its own.
 */

export type RuleValueType = 'kinds' | 'tag' | 'tags' | 'text120' | 'text200' | 'date' | 'mime' | 'languages' | 'states' | 'source_kinds' | 'ms' | 'orientation' | 'usage';

export const RULE_KINDS = ['image', 'video', 'audio', 'document', 'file'] as const;
export const RULE_SOURCE_KINDS = ['upload', 'link', 'note', 'artifact'] as const;
export const RULE_ORIENTATIONS = ['portrait', 'landscape', 'square'] as const;
export const RULE_TAG_ORIGINS = ['user', 'ai_suggested', 'any'] as const;
export const RULE_CAPABILITIES = ['preview', 'extract', 'transcribe', 'visual', 'embed_text', 'embed_visual', 'understand'] as const;
export const RULE_CAPABILITY_STATES = ['not_requested', 'queued', 'processing', 'ready', 'partial', 'unsupported', 'failed', 'cancelled', 'blocked_permission', 'blocked_budget'] as const;
export const MAX_RULE_ROWS = 40;

/** field → label and operator → (label, value type). Mirrors collections.FIELDS exactly. */
export const RULE_FIELDS: Readonly<Record<string, { label: string; ops: Readonly<Record<string, { label: string; value: RuleValueType }>> }>> = {
  kind: { label: 'Type', ops: { in: { label: 'is one of', value: 'kinds' } } },
  tag: { label: 'Tag', ops: { has: { label: 'is', value: 'tag' }, has_any: { label: 'is any of', value: 'tags' } } },
  title_contains: { label: 'Title', ops: { contains: { label: 'contains', value: 'text120' } } },
  filename_contains: { label: 'File name', ops: { contains: { label: 'contains', value: 'text120' } } },
  created_after: { label: 'Added', ops: { on_or_after: { label: 'on or after', value: 'date' } } },
  created_before: { label: 'Added', ops: { before: { label: 'before', value: 'date' } } },
  mime_prefix: { label: 'Content type', ops: { starts_with: { label: 'starts with', value: 'mime' } } },
  language: { label: 'Language', ops: { in: { label: 'is one of', value: 'languages' } } },
  capability: { label: 'Processing', ops: { in: { label: 'is one of', value: 'states' } } },
  source_kind: { label: 'Added as', ops: { in: { label: 'one of', value: 'source_kinds' } } },
  duration_ms: { label: 'Length', ops: { gte: { label: 'at least', value: 'ms' }, lte: { label: 'at most', value: 'ms' } } },
  orientation: { label: 'Orientation', ops: { eq: { label: 'is', value: 'orientation' } } },
  usage: { label: 'Used in posts', ops: { eq: { label: 'is', value: 'usage' } } },
  text_matches: { label: 'Words inside', ops: { matches: { label: 'match', value: 'text200' } } }
};

export interface RuleRow {
  field: string;
  op: string;
  value: unknown;
  origin?: (typeof RULE_TAG_ORIGINS)[number];
  timeZone?: string;
  capability?: (typeof RULE_CAPABILITIES)[number];
}

export interface RuleDraft {
  join: 'all' | 'any';
  rows: RuleRow[];
}

/** Links, markup and query text never go into a rule (the server refuses them too). */
const UNSAFE = /(<\s*script|javascript:|\bselect\b[^\n]{0,40}\bfrom\b|\bdrop\s+table\b|https?:\/\/|<\s*\/?\s*[a-z])/i;
const LANGUAGE = /^[a-z]{2,3}(-[A-Za-z]{2,4})?$/;
const MIME = /^[a-z]+(\/[a-z0-9.+-]*)?$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

function hasControl(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 32 || code === 127) return true;
  }
  return false;
}

export function isRuleField(field: string): boolean {
  return Object.prototype.hasOwnProperty.call(RULE_FIELDS, field);
}

export function opsFor(field: string): string[] {
  return isRuleField(field) ? Object.keys(RULE_FIELDS[field].ops) : [];
}

export function valueTypeOf(field: string, op: string): RuleValueType | null {
  if (!isRuleField(field)) return null;
  const entry = RULE_FIELDS[field].ops[op];
  return entry ? entry.value : null;
}

function defaultValue(type: RuleValueType): unknown {
  switch (type) {
    case 'kinds':
    case 'tags':
    case 'languages':
    case 'states':
    case 'source_kinds':
      return [];
    case 'ms':
      return 60_000;
    case 'orientation':
      return 'portrait';
    case 'usage':
      return 'unused';
    default:
      return '';
  }
}

export function defaultRow(field: string, timeZone = 'UTC'): RuleRow {
  const op = opsFor(field)[0] ?? '';
  const type = valueTypeOf(field, op);
  const row: RuleRow = { field, op, value: type ? defaultValue(type) : '' };
  if (field === 'tag') row.origin = 'user';
  if (field === 'created_after' || field === 'created_before') row.timeZone = timeZone;
  if (field === 'capability') row.capability = 'transcribe';
  return row;
}

/** Comma- or line-separated words, trimmed and de-duplicated. */
export function parseList(text: string): string[] {
  return [...new Set(text.split(/[,\n]/).map((part) => part.trim()).filter(Boolean))];
}

function text(value: unknown, max: number, what: string): string | null {
  if (typeof value !== 'string' || !value.trim() || value.length > max || hasControl(value)) return `Use ${what} of 1 to ${max} characters.`;
  if (UNSAFE.test(value)) return 'Rules hold plain words, not links, markup or query text.';
  return null;
}

function list(value: unknown, max: number, allowed: readonly string[] | null, what: string): string | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > max) return `Choose 1 to ${max} ${what}.`;
  if (allowed && !value.every((item) => typeof item === 'string' && allowed.includes(item))) return `Choose from the listed ${what}.`;
  return null;
}

/** The first problem with one criterion, in words, or null. */
export function validateRow(row: RuleRow): string | null {
  if (!isRuleField(row.field)) return 'Choose a criterion from the list.';
  const type = valueTypeOf(row.field, row.op);
  if (!type) return `Choose how ${RULE_FIELDS[row.field].label.toLowerCase()} should match.`;
  const value = row.value;
  switch (type) {
    case 'kinds':
      return list(value, RULE_KINDS.length, RULE_KINDS, 'types');
    case 'source_kinds':
      return list(value, RULE_SOURCE_KINDS.length, RULE_SOURCE_KINDS, 'sources');
    case 'states':
      if (!row.capability || !(RULE_CAPABILITIES as readonly string[]).includes(row.capability)) return 'Choose which processing step to check.';
      return list(value, RULE_CAPABILITY_STATES.length, RULE_CAPABILITY_STATES, 'processing states');
    case 'tag':
      if (row.origin !== undefined && !(RULE_TAG_ORIGINS as readonly string[]).includes(row.origin)) return 'Choose whose tags count.';
      return text(value, 40, 'a tag');
    case 'tags': {
      const problem = list(value, 20, null, 'tags');
      return problem ?? ((value as unknown[]).map((tag) => text(tag, 40, 'a tag')).find(Boolean) || null);
    }
    case 'text120':
      return text(value, 120, 'text');
    case 'text200':
      return text(value, 200, 'words to match');
    case 'date':
      if (typeof value !== 'string' || !DAY.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) return 'Use a date such as 2026-10-08.';
      return null;
    case 'mime':
      return typeof value === 'string' && value.trim().length >= 1 && value.length <= 100 && MIME.test(value.trim().toLowerCase()) ? null : 'Use a content type such as audio/ or image/png.';
    case 'languages': {
      const problem = list(value, 8, null, 'languages');
      return problem ?? ((value as unknown[]).every((code) => typeof code === 'string' && LANGUAGE.test(code)) ? null : 'Use language codes such as yue, zh-Hant or en.');
    }
    case 'ms':
      return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 86_400_000 ? null : 'Use a length up to 24 hours.';
    case 'orientation':
      return (RULE_ORIENTATIONS as readonly string[]).includes(value as string) ? null : 'Choose portrait, landscape or square.';
    case 'usage':
      return value === 'used' || value === 'unused' ? null : 'Choose used or unused.';
    default:
      return 'Choose a criterion from the list.';
  }
}

export type BuiltRule = { ok: true; rule: Record<string, unknown> } | { ok: false; errors: string[] };

/** The rule to send: `{all|any: [predicates]}` from allowlisted rows only. */
export function buildRule(draft: RuleDraft): BuiltRule {
  if (!draft.rows.length) return { ok: false, errors: ['Add at least one criterion.'] };
  if (draft.rows.length > MAX_RULE_ROWS) return { ok: false, errors: [`Use at most ${MAX_RULE_ROWS} criteria.`] };
  const errors = draft.rows.map(validateRow).map((error, index) => (error ? `Criterion ${index + 1}: ${error}` : null)).filter((error): error is string => Boolean(error));
  if (errors.length) return { ok: false, errors };
  const predicates = draft.rows.map((row) => {
    const value = typeof row.value === 'string' ? row.value.trim() : row.value;
    const predicate: Record<string, unknown> = { field: row.field, op: row.op, value };
    if (row.field === 'tag') predicate.origin = row.origin ?? 'user';
    if (row.field === 'created_after' || row.field === 'created_before') predicate.timeZone = row.timeZone ?? 'UTC';
    if (row.field === 'capability') predicate.capability = row.capability;
    return predicate;
  });
  return { ok: true, rule: { [draft.join === 'any' ? 'any' : 'all']: predicates } };
}

/**
 * A saved rule back into editable rows. Only a flat all/any list of predicates is editable here; anything nested
 * returns null and the collection keeps its saved criteria until replaced as a whole.
 */
export function draftFromRule(rule: unknown): RuleDraft | null {
  if (!rule || typeof rule !== 'object') return null;
  const record = rule as Record<string, unknown>;
  const join = Array.isArray(record.all) ? 'all' : Array.isArray(record.any) ? 'any' : null;
  if (!join) return null;
  const rows: RuleRow[] = [];
  for (const node of record[join] as unknown[]) {
    if (!node || typeof node !== 'object' || 'all' in node || 'any' in node || 'not' in node) return null;
    const predicate = node as Record<string, unknown>;
    if (typeof predicate.field !== 'string' || typeof predicate.op !== 'string' || !isRuleField(predicate.field)) return null;
    const row: RuleRow = { field: predicate.field, op: predicate.op, value: predicate.value };
    if (typeof predicate.origin === 'string') row.origin = predicate.origin as RuleRow['origin'];
    if (typeof predicate.timeZone === 'string') row.timeZone = predicate.timeZone;
    if (typeof predicate.capability === 'string') row.capability = predicate.capability as RuleRow['capability'];
    rows.push(row);
  }
  return { join, rows };
}

export interface PreviewLike {
  count: number;
  changes: { added: { count: number }; removed: { count: number } } | null;
  coverage?: { partial: boolean; notYetProcessed: number };
}

/** "14 items · 3 joining · 1 leaving" — before/after from the server's own counts. */
export function previewSummary(preview: PreviewLike): { total: string; joining: number | null; leaving: number | null; line: string } {
  const total = `${preview.count.toLocaleString('en-US')} ${preview.count === 1 ? 'item' : 'items'}`;
  const joining = preview.changes ? preview.changes.added.count : null;
  const leaving = preview.changes ? preview.changes.removed.count : null;
  const parts = [total];
  if (joining !== null) parts.push(`${joining} joining`);
  if (leaving !== null) parts.push(`${leaving} leaving`);
  if (preview.coverage?.notYetProcessed) parts.push(`${preview.coverage.notYetProcessed} still processing`);
  return { total, joining, leaving, line: parts.join(' · ') };
}

export interface CollectionEnvelope {
  actionId: string;
  uiInstanceId: string;
  actionType: 'collection.save' | 'collection.override' | 'collection.undo';
  targetRefs: { assetId: string; versionId: string; sha256: string }[];
  expectedRevision: number | null;
  payload: Record<string, unknown>;
}

/** collection.save: a new collection sends no revision; saving criteria sends the revision it was edited from. */
export function saveEnvelope(rule: Record<string, unknown>, options: { name?: string; collectionId?: string | null; revision?: number | null; actionId: string }): CollectionEnvelope {
  const payload: Record<string, unknown> = { rule };
  if (options.collectionId) payload.collectionId = options.collectionId;
  if (options.name !== undefined) payload.name = options.name;
  return { actionId: options.actionId, uiInstanceId: 'library-smart-collection', actionType: 'collection.save', targetRefs: [], expectedRevision: options.collectionId ? (options.revision ?? null) : null, payload };
}

/** collection.override: include or exclude these items, or clear their override, at the revision the person saw. */
export function overrideEnvelope(collectionId: string, mode: 'include' | 'exclude' | 'clear', refs: CollectionEnvelope['targetRefs'], revision: number, actionId: string): CollectionEnvelope {
  return { actionId, uiInstanceId: 'library-smart-collection', actionType: 'collection.override', targetRefs: refs.slice(0, 200), expectedRevision: revision, payload: { collectionId, mode } };
}

/** collection.undo: restores the previous criteria and overrides as a new revision. */
export function undoEnvelope(collectionId: string, revision: number, actionId: string): CollectionEnvelope {
  return { actionId, uiInstanceId: 'library-smart-collection', actionType: 'collection.undo', targetRefs: [], expectedRevision: revision, payload: { collectionId } };
}

export function originLabel(origin: string): string {
  return origin === 'include' ? 'Included by you' : origin === 'rule' ? 'Matches the criteria' : 'Added by hand';
}
