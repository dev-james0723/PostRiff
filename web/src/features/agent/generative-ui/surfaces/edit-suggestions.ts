/**
 * "Change this view" suggestion chips, computed in the browser from the view itself (lane F; edit-suggestions design,
 * Option A). Pure: no React, no network, no model, no clock of its own (`now` is passed in), so the same view, selection,
 * language, zone and day always give the same chips in the same order.
 *
 * Inputs are what the browser already holds: the accepted canonical source (split with the trusted parser's library-free
 * `statementsOf`, so founder views work before the founder library loads), the public manifest's bindings and argument
 * schemas, the view's journeys and the person's LIVE `@selection` (the same object the edit request will carry). Every chip
 * is grounded: its binding, argument and value are in the manifest, the value is not the one already shown, and its words
 * come from the fixed table in edit-suggestions-copy.ts (counts, ISO dates and metric names are the only variable parts).
 *
 * A chip only fills the "What should change?" field; the existing "Update view" press stays the one billed step.
 *
 *   suggestEdits({ source, queries: manifest.queries, journeyIds, selection, language: 'en', timeZone: 'Asia/Hong_Kong', now: Date.now() })
 *   → [{ id: 'period:next', rule: 'seed', label: 'Next week', instruction: 'Change the period to the following week (2026-10-12 to 2026-10-18)' }, …]
 */
import type { JsonValue } from '@/lib/agent-runtime/ui-contracts';
import { statementsOf } from '@/lib/agent-runtime/ui-parser/validate';
import type { GenUiLanguage } from '../core/locale';
import {
  ADD_CHIPS,
  CHART_COMPONENTS,
  DATE_PERIOD_CHIPS,
  ENUM_PERIOD_CHIPS,
  FILTER_CHIPS,
  FUTURE_DATE_BINDINGS,
  JOURNEY_SEEDS,
  METRIC_COLUMN_ORDER,
  METRIC_NAMES,
  METRIC_SWAP_ORDER,
  METRIC_TABLE_MAX_COLUMNS,
  PAST_DATE_BINDINGS,
  pick,
  REMOVE_CHIPS,
  REMOVE_MIN_SECTIONS,
  SELECTION_CHIPS,
  SHAPE_CHIPS,
  type ChipText,
} from './edit-suggestions-copy';

export const MAX_SUGGESTIONS = 4;
/** Per rule family. */
const MAX_PER_RULE = 2;

/** Display order of the rule families (seed = the journey's tested edit, when it qualifies). */
export const SUGGESTION_RULES = ['selection', 'seed', 'filter', 'period', 'add', 'shape', 'remove'] as const;
export type SuggestionRule = (typeof SUGGESTION_RULES)[number];

export interface EditSuggestion {
  /** Stable identity of what the chip does (never shown). */
  id: string;
  rule: SuggestionRule;
  /** Short chip text. */
  label: string;
  /** What a tap puts in the field (what "Update view" would send). */
  instruction: string;
}

export interface SuggestInput {
  /** The accepted canonical source of the revision on screen. */
  source: string | null | undefined;
  /** The public manifest's bindings (`view.manifest.queries`). */
  queries: readonly { name: string; argsSchema?: unknown }[] | null | undefined;
  journeyIds: readonly string[] | null | undefined;
  /** The live `@selection` ({items, visible, listId}) the edit request would carry. */
  selection: JsonValue | null | undefined;
  language: GenUiLanguage;
  /** The person's IANA zone (dates use the Query's own literal zone first). */
  timeZone: string;
  /** Epoch milliseconds. */
  now: number;
}

// --- reading the source ----------------------------------------------------------------------------------------------------
type Node = { k: string } & Record<string, unknown>;
type Arg = { kind: 'literal'; value: JsonValue } | { kind: 'state' } | { kind: 'other' };

interface QueryInfo {
  id: string;
  binding: string;
  args: Map<string, Arg>;
}

interface ViewInfo {
  queries: QueryInfo[];
  /** Component name → its nodes, in source order. */
  components: Map<string, Node[]>;
  /** The root's sections in order: the component each one names (null when it is not a component). */
  sections: (string | null)[];
}

const isNode = (value: unknown): value is Node => !!value && typeof value === 'object' && !Array.isArray(value) && typeof (value as { k?: unknown }).k === 'string';

function argsOf(node: Node): Node[] {
  return Array.isArray(node.args) ? (node.args.filter(isNode) as Node[]) : [];
}

function literalOf(node: unknown): JsonValue | undefined {
  if (!isNode(node)) return undefined;
  switch (node.k) {
    case 'Str':
      return typeof node.v === 'string' ? node.v : undefined;
    case 'Num':
      return typeof node.v === 'number' && Number.isFinite(node.v) ? node.v : undefined;
    case 'Bool':
      return typeof node.v === 'boolean' ? node.v : undefined;
    case 'Null':
      return null;
    case 'UnaryOp': {
      const inner = literalOf(node.operand);
      return node.op === '-' && typeof inner === 'number' ? -inner : undefined;
    }
    case 'Arr': {
      const out: JsonValue[] = [];
      for (const el of Array.isArray(node.els) ? node.els : []) {
        const value = literalOf(el);
        if (value === undefined) return undefined;
        out.push(value);
      }
      return out;
    }
    default:
      return undefined;
  }
}

function argOf(node: unknown): Arg {
  if (isNode(node) && node.k === 'StateRef') return { kind: 'state' };
  const value = literalOf(node);
  return value === undefined ? { kind: 'other' } : { kind: 'literal', value };
}

function walk(node: unknown, visit: (node: Node) => void, depth = 0): void {
  if (depth > 64 || !node || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    for (const item of node) walk(item, visit, depth + 1);
    return;
  }
  if (!isNode(node)) return;
  visit(node);
  for (const value of Object.values(node)) if (value && typeof value === 'object') walk(value, visit, depth + 1);
}

function readView(source: string): ViewInfo | null {
  let statements: { id: string; ast: unknown }[];
  try {
    statements = statementsOf(source) as unknown as { id: string; ast: unknown }[];
  } catch {
    return null;
  }
  const byId = new Map<string, Node>();
  const queries: QueryInfo[] = [];
  const components = new Map<string, Node[]>();
  for (const statement of statements) {
    const ast = statement.ast;
    if (!isNode(ast)) continue;
    byId.set(statement.id, ast);
    if (ast.k === 'Comp' && ast.name === 'Query') {
      const [tool, args] = argsOf(ast);
      const binding = literalOf(tool);
      if (typeof binding !== 'string') continue;
      const map = new Map<string, Arg>();
      if (isNode(args) && args.k === 'Obj' && Array.isArray(args.entries)) {
        for (const entry of args.entries as unknown[]) {
          if (Array.isArray(entry) && typeof entry[0] === 'string') map.set(entry[0], argOf(entry[1]));
        }
      }
      queries.push({ id: statement.id, binding, args: map });
      continue;
    }
    walk(ast, (node) => {
      if (node.k !== 'Comp' || typeof node.name !== 'string' || node.name === 'Query' || node.name === 'Mutation') return;
      const list = components.get(node.name) ?? [];
      list.push(node);
      components.set(node.name, list);
    });
  }
  const root = byId.get('root');
  const children = root && root.k === 'Comp' ? argsOf(root)[0] : undefined;
  const sections = (isNode(children) && children.k === 'Arr' && Array.isArray(children.els) ? (children.els as unknown[]) : []).map((el) => {
    const target = isNode(el) && el.k === 'Ref' && typeof el.n === 'string' ? byId.get(el.n) : isNode(el) ? el : undefined;
    return target && target.k === 'Comp' && typeof target.name === 'string' ? target.name : null;
  });
  return { queries, components, sections };
}

// --- the manifest ----------------------------------------------------------------------------------------------------------
type Schema = Record<string, unknown>;

function propertiesOf(queries: SuggestInput['queries'], binding: string): Record<string, Schema> | null {
  const query = (queries ?? []).find((q) => q && q.name === binding);
  if (!query) return null;
  const schema = query.argsSchema as { properties?: unknown } | null | undefined;
  const props = schema && typeof schema === 'object' && schema.properties && typeof schema.properties === 'object' ? (schema.properties as Record<string, Schema>) : {};
  return props;
}

function accepts(prop: Schema | undefined, value: string | boolean): boolean {
  if (!prop) return false;
  if (typeof value === 'boolean') {
    const types = Array.isArray(prop.type) ? prop.type : [prop.type];
    return types.includes('boolean');
  }
  return Array.isArray(prop.enum) && prop.enum.includes(value);
}

// --- dates (calendar days, never shifted by the browser's own zone) ----------------------------------------------------------
const DAY_MS = 86_400_000;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const MAX_SPAN_DAYS = 366;

function dayOf(iso: unknown): number | null {
  if (typeof iso !== 'string') return null;
  const match = ISO_DATE.exec(iso);
  if (!match) return null;
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Date(ms).toISOString().slice(0, 10) === iso ? ms / DAY_MS : null;
}

const isoOf = (day: number) => new Date(day * DAY_MS).toISOString().slice(0, 10);

function zoneOk(zone: unknown): zone is string {
  if (typeof zone !== 'string' || !zone) return false;
  try {
    new Intl.DateTimeFormat('en', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** Today's calendar day in `zone`. */
function todayIn(zone: string, now: number): number | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(now));
    const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
    const ms = Date.UTC(get('year'), get('month') - 1, get('day'));
    return Number.isFinite(ms) ? ms / DAY_MS : null;
  } catch {
    return null;
  }
}

function nextMonthOf(today: number): [number, number] {
  const date = new Date(today * DAY_MS);
  const first = Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1) / DAY_MS;
  const last = Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 2, 0) / DAY_MS;
  return [first, last];
}

// --- candidates --------------------------------------------------------------------------------------------------------------
interface Candidate {
  id: string;
  rule: SuggestionRule;
  /** Chips that change the same thing share a key (at most `cap` of them are shown). */
  key: string;
  cap: number;
  text: ChipText;
  vars?: Record<string, string | number>;
}

function selectionItems(selection: SuggestInput['selection']): { type: string; id: string }[] {
  if (!selection || typeof selection !== 'object' || Array.isArray(selection)) return [];
  const items = (selection as Record<string, JsonValue>).items;
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is { type: string; id: string } => !!item && typeof item === 'object' && !Array.isArray(item)
    && typeof (item as Record<string, JsonValue>).type === 'string' && typeof (item as Record<string, JsonValue>).id === 'string')
    .map((item) => ({ type: item.type, id: item.id }));
}

function selectionCandidates(input: SuggestInput, view: ViewInfo): Candidate[] {
  const items = selectionItems(input.selection);
  if (!items.length) return [];
  const type = items[0].type;
  if (!items.every((item) => item.type === type)) return [];
  const n = items.length;
  const out: Candidate[] = [];
  for (const entry of SELECTION_CHIPS) {
    if (entry.type !== type || n < entry.min || n > entry.max) continue;
    if (!propertiesOf(input.queries, entry.binding)) continue;
    if (entry.unlessComponent && view.components.has(entry.unlessComponent)) continue;
    out.push({ id: `selection:${type}:${entry.kind}`, rule: 'selection', key: 'selection', cap: 1, text: entry.text, vars: { n } });
  }
  return out;
}

/** Queries a filter chip may change: not the picked records (an `ids` list) and not an argument the view already binds. */
function listQueries(view: ViewInfo, binding: string): QueryInfo[] {
  return view.queries.filter((q) => q.binding === binding && !q.args.has('ids') && !q.args.has('assetIds'));
}

function filterCandidates(input: SuggestInput, view: ViewInfo): Candidate[] {
  const out: Candidate[] = [];
  for (const entry of FILTER_CHIPS) {
    const props = propertiesOf(input.queries, entry.binding);
    if (!props || !props[entry.arg]) continue;
    const query = listQueries(view, entry.binding)[0];
    if (!query) continue;
    const arg = query.args.get(entry.arg);
    if (arg && arg.kind !== 'literal') continue;   // a $variable (the person switches it locally) or an expression
    const current = arg?.kind === 'literal' ? arg.value : entry.whenAbsent;
    for (const option of entry.values) {
      if (option.value === current || !accepts(props[entry.arg], option.value)) continue;
      out.push({ id: `filter:${entry.binding}.${entry.arg}:${String(option.value)}`, rule: 'filter', key: `${entry.binding}.${entry.arg}`, cap: 2, text: option.text });
    }
  }
  return out;
}

function periodCandidates(input: SuggestInput, view: ViewInfo): Candidate[] {
  const out: Candidate[] = [];
  const push = (id: string, text: ChipText, vars?: Record<string, string | number>) => out.push({ id, rule: 'period', key: 'period', cap: 2, text, vars });

  // Named periods (founder): one change for every Query of the view that takes `period`.
  const named = view.queries.filter((q) => {
    const props = propertiesOf(input.queries, q.binding);
    const arg = q.args.get('period');
    return props?.period && arg?.kind === 'literal' && typeof arg.value === 'string';
  });
  if (named.length) {
    const first = named[0].args.get('period');
    const current = first?.kind === 'literal' ? first.value : null;
    for (const option of ENUM_PERIOD_CHIPS) {
      if (option.value === current) continue;
      if (!named.every((q) => accepts(propertiesOf(input.queries, q.binding)?.period, option.value))) continue;
      push(`period:${option.value}`, option.text);
    }
    return out;
  }

  // Calendar dates: the first Query (in source order) whose binding takes start/end.
  const dated = view.queries.find((q) => {
    if (!PAST_DATE_BINDINGS.includes(q.binding) && !FUTURE_DATE_BINDINGS.includes(q.binding)) return false;
    const props = propertiesOf(input.queries, q.binding);
    return !!props?.start && !!props?.end && !['start', 'end'].some((k) => q.args.get(k) && q.args.get(k)?.kind !== 'literal');
  });
  if (!dated) return out;
  const zoneArg = dated.args.get('zone');
  const literalZone = zoneArg?.kind === 'literal' ? zoneArg.value : null;
  const zone = zoneOk(literalZone) ? literalZone : zoneOk(input.timeZone) ? input.timeZone : 'UTC';
  const today = todayIn(zone, input.now);
  const startArg = dated.args.get('start');
  const endArg = dated.args.get('end');
  const start = startArg?.kind === 'literal' ? dayOf(startArg.value) : null;
  const end = endArg?.kind === 'literal' ? dayOf(endArg.value) : null;
  const span = start !== null && end !== null && end >= start && end - start + 1 <= MAX_SPAN_DAYS ? end - start + 1 : null;
  const range = (from: number, to: number) => ({ start: isoOf(from), end: isoOf(to) });
  const same = (from: number, to: number) => start === from && end === to;
  const shift = (direction: 'next' | 'previous') => {
    if (span === null || start === null || end === null) return;
    const delta = direction === 'next' ? span : -span;
    const next = direction === 'next';
    const text = DATE_PERIOD_CHIPS[span === 1 ? (next ? 'nextDay' : 'previousDay') : span === 7 ? (next ? 'nextWeek' : 'previousWeek') : direction];
    push(`period:${direction}`, text, { n: span, ...range(start + delta, end + delta) });
  };
  const last = (days: 7 | 30) => {
    if (today === null) return;
    const from = today - (days - 1);
    if (same(from, today)) return;   // the view already shows exactly this window; an older window of that length still gets it
    push(`period:last${days}`, DATE_PERIOD_CHIPS[days === 7 ? 'last7' : 'last30'], range(from, today));
  };
  if (PAST_DATE_BINDINGS.includes(dated.binding)) {
    // Performance looks back: without dates the server reads the last 30 days.
    if (start === null && end === null && !startArg && !endArg) {
      if (today !== null) push('period:last7', DATE_PERIOD_CHIPS.last7, range(today - 6, today));
      return out;
    }
    last(7);
    shift('previous');
    last(30);
    return out;
  }
  shift('next');
  if (today !== null) {
    const [from, to] = nextMonthOf(today);
    if (!same(from, to)) push('period:nextMonth', DATE_PERIOD_CHIPS.nextMonth, range(from, to));
  }
  shift('previous');
  return out;
}

function addCandidates(input: SuggestInput, view: ViewInfo): Candidate[] {
  const used = new Set(view.queries.map((q) => q.binding));
  const out: Candidate[] = [];
  for (const entry of ADD_CHIPS) {
    if (used.has(entry.binding) || !propertiesOf(input.queries, entry.binding)) continue;
    if (entry.needsArg && !view.queries.some((q) => q.args.get(entry.needsArg as string)?.kind === 'literal')) continue;
    out.push({ id: `${entry.rule}:${entry.binding}`, rule: entry.rule, key: `${entry.rule}:${entry.binding}`, cap: 1, text: entry.text });
  }
  return out;
}

function metric(name: string): ChipText['label'] | null {
  return METRIC_NAMES[name] ?? null;
}

function shapeCandidates(input: SuggestInput, view: ViewInfo): Candidate[] {
  const out: Candidate[] = [];
  // Chart kind: offer the other kind only.
  for (const [name, fallback] of Object.entries(CHART_COMPONENTS)) {
    const chart = view.components.get(name)?.[0];
    if (!chart) continue;
    const kind = literalOf(argsOf(chart)[1]) ?? fallback;
    if (kind === 'line') out.push({ id: 'shape:chart:bar', rule: 'shape', key: 'chart', cap: 1, text: SHAPE_CHIPS.bar });
    else if (kind === 'bar') out.push({ id: 'shape:chart:line', rule: 'shape', key: 'chart', cap: 1, text: SHAPE_CHIPS.line });
    break;
  }
  // Like-for-like comparison: another metric of the manifest's enum.
  const compare = view.queries.find((q) => q.binding === 'analytics_compare');
  const compareMetric = compare?.args.get('metric');
  const compareProps = propertiesOf(input.queries, 'analytics_compare');
  if (compareMetric?.kind === 'literal' && typeof compareMetric.value === 'string' && metric(compareMetric.value) && compareProps?.metric) {
    const current = compareMetric.value;
    const next = METRIC_SWAP_ORDER.find((m) => m !== current && accepts(compareProps.metric, m));
    if (next) {
      out.push({ id: `shape:analytics_compare.metric:${next}`, rule: 'shape', key: 'analytics_compare.metric', cap: 1, text: SHAPE_CHIPS.swapMetric,
        vars: { metric: pick(metric(next) as ChipText['label'], input.language), current: pick(metric(current) as ChipText['label'], input.language) } });
    }
  }
  // A metrics table with room for one more column.
  const table = view.components.get('MetricTable')?.[0];
  const shown = table ? literalOf(argsOf(table)[1]) : undefined;
  if (Array.isArray(shown) && shown.length < METRIC_TABLE_MAX_COLUMNS && shown.every((m) => typeof m === 'string')) {
    const column = METRIC_COLUMN_ORDER.find((m) => !shown.includes(m));
    if (column) {
      out.push({ id: `shape:column:${column}`, rule: 'shape', key: 'columns', cap: 1, text: SHAPE_CHIPS.addColumn,
        vars: { metric: pick(metric(column) as ChipText['label'], input.language) } });
    }
  }
  // Founder cost against the previous period.
  const costs = view.queries.find((q) => q.binding === 'founder_costs');
  const compareArg = costs?.args.get('compare');
  if (costs && accepts(propertiesOf(input.queries, 'founder_costs')?.compare, true) && (!compareArg || (compareArg.kind === 'literal' && compareArg.value === false))) {
    out.push({ id: 'shape:founder_costs.compare', rule: 'shape', key: 'founder_costs.compare', cap: 1, text: SHAPE_CHIPS.compareCost });
  }
  return out;
}

function removeCandidates(view: ViewInfo): Candidate[] {
  if (view.sections.length < REMOVE_MIN_SECTIONS) return [];
  for (let i = view.sections.length - 1; i >= 0; i -= 1) {
    const name = view.sections[i];
    if (name && REMOVE_CHIPS[name] && view.sections.filter((s) => s === name).length === 1) {
      return [{ id: `remove:${name}`, rule: 'remove', key: 'remove', cap: 1, text: REMOVE_CHIPS[name] }];
    }
  }
  return [];
}

// --- choosing ----------------------------------------------------------------------------------------------------------------
/**
 * At most 4 chips, deterministic: the journey's tested edit moves into the `seed` family; then one chip per family in family
 * order, then a second per family, then a section removal. At most 2 per family and per argument (1 for other changes);
 * shown in family order.
 */
export function suggestEdits(input: SuggestInput): EditSuggestion[] {
  if (!input.source || !input.queries?.length) return [];
  const view = readView(input.source);
  if (!view) return [];
  const seeds = new Set((input.journeyIds ?? []).map((j) => JOURNEY_SEEDS[j]).filter(Boolean));
  const all = [
    ...selectionCandidates(input, view),
    ...filterCandidates(input, view),
    ...periodCandidates(input, view),
    ...addCandidates(input, view),
    ...shapeCandidates(input, view),
    ...removeCandidates(view),
  ].map((c, order) => ({ ...c, rule: c.rule !== 'selection' && seeds.has(c.id) ? ('seed' as const) : c.rule, order }));
  const rank = (rule: SuggestionRule) => SUGGESTION_RULES.indexOf(rule);
  const chosen: typeof all = [];
  const perRule = new Map<SuggestionRule, number>();
  const perKey = new Map<string, number>();
  const take = (candidate: (typeof all)[number]) => {
    if (chosen.length >= MAX_SUGGESTIONS || chosen.includes(candidate)) return;
    if ((perRule.get(candidate.rule) ?? 0) >= MAX_PER_RULE || (perKey.get(candidate.key) ?? 0) >= candidate.cap) return;
    chosen.push(candidate);
    perRule.set(candidate.rule, (perRule.get(candidate.rule) ?? 0) + 1);
    perKey.set(candidate.key, (perKey.get(candidate.key) ?? 0) + 1);
  };
  const families = SUGGESTION_RULES.filter((rule) => rule !== 'remove');
  for (let round = 0; round < MAX_PER_RULE; round += 1) {
    for (const rule of families) {
      const next = all.filter((c) => c.rule === rule && !chosen.includes(c)).find((c) => (perKey.get(c.key) ?? 0) < c.cap);
      if (next && (perRule.get(rule) ?? 0) === round) take(next);
    }
  }
  for (const candidate of all) if (candidate.rule === 'remove') take(candidate);
  return chosen
    .sort((a, b) => rank(a.rule) - rank(b.rule) || a.order - b.order)
    .map((c) => ({ id: c.id, rule: c.rule, label: pick(c.text.label, input.language, c.vars), instruction: pick(c.text.instruction, input.language, c.vars) }));
}

/**
 * Whether a chip the person filled still describes the view (same id, same words) when they press "Update view": the
 * selection, the day or the revision may have changed since. Returns the reason to stop, or null to send.
 */
export function staleSuggestion(filled: { id: string; rule: SuggestionRule; instruction: string }, current: readonly EditSuggestion[]): 'selection' | 'stale' | null {
  const now = current.find((c) => c.id === filled.id);
  if (now && now.instruction === filled.instruction) return null;
  return filled.rule === 'selection' ? 'selection' : 'stale';
}
