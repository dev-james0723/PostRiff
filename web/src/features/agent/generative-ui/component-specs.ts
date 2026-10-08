/**
 * Rafii Generative UI component specs (rafii-genui/1): the single source of component names, descriptions and props.
 *
 * React-free and erasable TypeScript only. Three consumers read the very same objects:
 *   - web/scripts/generate-openui-assets.mjs builds the JSON Schemas, per-journey prompts and library hashes from them;
 *   - web/src/lib/agent-runtime/ui-parser (trusted Node validator) builds its parser from them;
 *   - library.tsx / founder-library.tsx attach the React renderers to them.
 * Identical names, props and descriptions give identical prompt and schema identity everywhere.
 *
 * Rules that the official parser cannot express (it validates shallowly; evidence/r0/openui-package.md §0.4) are declared
 * here as `rules` and enforced by the trusted validator; every renderer also safe-parses its own props at render time.
 * Positional order = key order of `props`: required props first, optional props last.
 * Names are PascalCase and never collide with OpenUI builtins or reserved calls (Filter, Sort, Query, Mutation, …).
 *
 * Lane E adds journey components through `components/journeys/specs.ts` (see `JourneySpecModule` below); lane C's
 * `library-registry.ts` combines both. Nothing here grants authority: queries and actions are checked by the server.
 */
import { markReactive, tagSchemaId } from '@openuidev/lang-core';
import { z } from 'zod';

/** Bumped when a component is added, removed or changes props; libraryHash is the exact identity. */
export const LIBRARY_VERSION = 'rafii-components/1.0.0';
export const ROOT_COMPONENT = 'RafiiRoot';

/** OpenUI builtins and reserved calls (lang-core 0.3.2 BUILTINS + ACTION_NAMES + Query/Mutation). Never a component name. */
export const RESERVED_NAMES = [
  'Count', 'First', 'Last', 'Sum', 'Avg', 'Min', 'Max', 'Sort', 'Filter', 'Round', 'Abs', 'Floor', 'Ceil', 'Each',
  'Action', 'Run', 'ToAssistant', 'OpenUrl', 'Set', 'Reset', 'Query', 'Mutation',
] as const;

/**
 * Static prop rules for the trusted validator:
 *   query      the prop must be a direct reference to a top-level `Query(...)` statement (facts come from bound data);
 *   bound      the prop must be an expression over bound data (a Query result or an @Each item), never a typed literal;
 *   safe-href  a literal must be an in-app path ("/app/…"); external links must come from bound data;
 *   action-id  a string literal that names an action binding of this artifact's manifest.
 */
export type PropRule = 'query' | 'bound' | 'safe-href' | 'action-id';

export interface RafiiComponentSpec {
  name: string;
  description: string;
  props: z.ZodObject;
  rules?: Readonly<Record<string, PropRule>>;
  /** The prop that names a form field this component hosts (dirty-state protection on patches). */
  fieldNameProp?: string;
}

export interface RafiiGroupSpec {
  id: string;
  /** Prompt heading. */
  name: string;
  components: readonly string[];
  notes?: readonly string[];
}

/** Lane E's extension point (`components/journeys/specs.ts` exports `JOURNEY_SPEC_MODULE: JourneySpecModule`). */
export interface JourneySpecModule {
  consumer: { specs: readonly RafiiComponentSpec[]; groups: readonly RafiiGroupSpec[] };
  founder: { specs: readonly RafiiComponentSpec[]; groups: readonly RafiiGroupSpec[] };
  /** Component groups (C's ids and E's ids) each journey prompt includes, in heading order. */
  journeys: Readonly<Partial<Record<'J01' | 'J02' | 'J03' | 'J04' | 'J05' | 'J06' | 'J07' | 'J08' | 'J09', readonly string[]>>>;
}

function spec(definition: RafiiComponentSpec): RafiiComponentSpec {
  return definition;
}

/** A reactive prop (`$binding<T>` in the prompt): a `$variable` passed here is two-way bound. */
export function bindable<T extends z.ZodType>(schema: T): T {
  markReactive(schema);
  return schema;
}

/** Any Rafii component. Containers render these in order, keyed by statement id. */
export const componentNode = z.any();
tagSchemaId(componentNode, 'Component');

/** A reference to a `Query(...)` statement (the whole result: state, rows, as-of time and coverage). */
export const queryRef = z.record(z.string(), z.any());
tagSchemaId(queryRef, 'QueryRef');

/** A value taken from bound data, for example a row inside `@Each(rows.data, "row", …)`. */
export const boundItem = z.record(z.string(), z.any());
tagSchemaId(boundItem, 'DataItem');

/** `Action([@Set(...), @Reset(...), @ToAssistant(...), @OpenUrl(...), @Run(query)])`. */
export const actionExpression = z.any();
tagSchemaId(actionExpression, 'ActionExpression');

const nodes = () => z.array(componentNode);
const ROWS_FIELD_NOTE = ' rowsField names the list inside the result when the data is not itself a list (for example "drafts").';
const shortText = () => z.string();

export const columnSpec = z.object({
  field: z.string(),
  label: z.string(),
  kind: z.enum(['text', 'number', 'percent', 'currency', 'duration', 'date', 'datetime', 'status', 'link']).optional(),
  unit: z.string().optional(),
});
export const seriesSpec = z.object({ field: z.string(), label: z.string(), unit: z.string().optional() });
export const optionSpec = z.object({ value: z.string(), label: z.string() });
export const dateRangeValue = z.object({ start: z.string(), end: z.string() });
export const fieldRules = z.object({
  required: z.boolean().optional(),
  minLength: z.number().optional(),
  maxLength: z.number().optional(),
});

// --- layout ------------------------------------------------------------------------------------------------------------
const RafiiRoot = spec({
  name: 'RafiiRoot',
  description:
    'The one root of every view: root = RafiiRoot([...]). Children stack vertically. title is an optional short heading.',
  props: z.object({ children: nodes(), title: shortText().optional() }),
});
const Stack = spec({
  name: 'Stack',
  description: 'Groups components in a column (default) or a wrapping row. gap: sm | md | lg.',
  props: z.object({
    children: nodes(),
    direction: z.enum(['vertical', 'horizontal']).optional(),
    gap: z.enum(['sm', 'md', 'lg']).optional(),
  }),
});
const Grid = spec({
  name: 'Grid',
  description: 'Responsive grid of 1 to 4 columns that collapses to one column in narrow spaces such as the side panel.',
  props: z.object({ children: nodes(), columns: z.number().optional() }),
});
const Section = spec({
  name: 'Section',
  description: 'A titled region of the view. Use for each distinct part of a dense answer.',
  props: z.object({ title: shortText(), children: nodes(), description: z.string().optional() }),
});
const Card = spec({
  name: 'Card',
  description: 'A bordered surface for one item or one idea. tone: default | muted | highlight.',
  props: z.object({
    children: nodes(),
    title: shortText().optional(),
    description: z.string().optional(),
    tone: z.enum(['default', 'muted', 'highlight']).optional(),
  }),
});
const TabItem = spec({
  name: 'TabItem',
  description: 'One tab of Tabs. value is a stable id; it defaults to the label.',
  props: z.object({ label: shortText(), children: nodes(), value: z.string().optional() }),
});
const Tabs = spec({
  name: 'Tabs',
  description: 'Switches between TabItem panels locally. Bind value to a $variable to let other components react to the open tab.',
  props: z.object({ items: z.array(TabItem.props), value: bindable(z.string().optional()) }),
});
const AccordionItem = spec({
  name: 'AccordionItem',
  description: 'One collapsible part of an Accordion.',
  props: z.object({ title: shortText(), children: nodes(), open: z.boolean().optional() }),
});
const Accordion = spec({
  name: 'Accordion',
  description: 'Collapsible sections for secondary detail such as methods, definitions or long lists.',
  props: z.object({ items: z.array(AccordionItem.props) }),
});
const Text = spec({
  name: 'Text',
  description:
    'Plain text you write (commentary, a heading or a caption). Never type figures, record titles, statuses or sources here: show those through bound data components.',
  props: z.object({
    content: z.string(),
    variant: z.enum(['body', 'muted', 'heading', 'caption', 'emphasis']).optional(),
  }),
});
const EvidenceLink = spec({
  name: 'EvidenceLink',
  description:
    'A link to a source or record. href is an in-app path such as "/app/library", or a URL taken from bound data. Never invent a web address.',
  props: z.object({ label: z.string(), href: z.string(), source: z.string().optional(), asOf: z.string().optional() }),
  rules: { href: 'safe-href' },
});

// --- states ------------------------------------------------------------------------------------------------------------
const EmptyState = spec({
  name: 'EmptyState',
  description: 'Says that nothing matched or that no data exists yet. Use it when no binding fits the request: never invent data.',
  props: z.object({ title: shortText(), description: z.string().optional() }),
});
const LoadingState = spec({
  name: 'LoadingState',
  description: 'A quiet placeholder while something is being prepared.',
  props: z.object({ label: z.string().optional() }),
});
const ErrorState = spec({
  name: 'ErrorState',
  description: 'Explains that something could not be shown, in plain words, with what the person can do next.',
  props: z.object({ title: shortText(), description: z.string().optional() }),
});

// --- bound data --------------------------------------------------------------------------------------------------------
const ToolBoundTable = spec({
  name: 'ToolBoundTable',
  description:
    'A table of rows from a Query. columns pick fields of each row. Sorting is local. Bind cursor to the $variable used as the query cursor argument to page through results. Unknown values show as "Not available", never as zero.'+
    ROWS_FIELD_NOTE,
  props: z.object({
    source: queryRef,
    columns: z.array(columnSpec),
    cursor: bindable(z.string().optional()),
    caption: z.string().optional(),
    rowsField: z.string().optional(),
  }),
  rules: { source: 'query' },
});
const ToolBoundChart = spec({
  name: 'ToolBoundChart',
  description:
    'A line or bar chart of rows from a Query: x is the field for the horizontal axis, series are numeric fields. Missing values stay gaps, never zero. A data table alternative is always included.'+
    ROWS_FIELD_NOTE,
  props: z.object({
    source: queryRef,
    kind: z.enum(['line', 'bar']),
    x: z.string(),
    series: z.array(seriesSpec),
    title: z.string().optional(),
    unit: z.string().optional(),
    rowsField: z.string().optional(),
  }),
  rules: { source: 'query' },
});
const Metric = spec({
  name: 'Metric',
  description:
    'One server-computed figure from a field of a Query result (dots reach nested fields, for example "totals.reach"), with its unit, as-of time and coverage. Shows "Not measured" when the value is unknown.',
  props: z.object({
    source: queryRef,
    field: z.string(),
    label: shortText(),
    format: z.enum(['number', 'percent', 'currency', 'duration']).optional(),
    unit: z.string().optional(),
  }),
  rules: { source: 'query' },
});
const Timeline = spec({
  name: 'Timeline',
  description: 'Rows from a Query in time order, with dates in the person’s time zone.' + ROWS_FIELD_NOTE,
  props: z.object({
    source: queryRef,
    timeField: z.string(),
    titleField: z.string(),
    statusField: z.string().optional(),
    descriptionField: z.string().optional(),
    rowsField: z.string().optional(),
  }),
  rules: { source: 'query' },
});
const Comparison = spec({
  name: 'Comparison',
  description:
    'Side-by-side comparison of rows from a Query (for example drafts or campaigns). Bind selected to a $variable holding row ids to compare only those.' + ROWS_FIELD_NOTE,
  props: z.object({
    source: queryRef,
    labelField: z.string(),
    fields: z.array(columnSpec),
    idField: z.string().optional(),
    selected: bindable(z.array(z.string()).optional()),
    rowsField: z.string().optional(),
  }),
  rules: { source: 'query' },
});
const TaskStatus = spec({
  name: 'TaskStatus',
  description:
    'The real state of a task or record from a Query (for example preparing, needs review, saved, scheduled, published). The state shown is exactly what the data says.',
  props: z.object({ source: queryRef, labelField: z.string().optional(), statusField: z.string().optional() }),
  rules: { source: 'query' },
});
const SelectionList = spec({
  name: 'SelectionList',
  description:
    'Lets the person pick rows from a Query. value is a $variable that receives the picked row ids in the order they were picked. max limits how many.' +
    ROWS_FIELD_NOTE,
  props: z.object({
    source: queryRef,
    labelField: z.string(),
    value: bindable(z.array(z.string()).optional()),
    idField: z.string().optional(),
    descriptionField: z.string().optional(),
    max: z.number().optional(),
    label: z.string().optional(),
    rowsField: z.string().optional(),
  }),
  rules: { source: 'query' },
});
const AssetPreview = spec({
  name: 'AssetPreview',
  description:
    'A safe preview of one Library item (image, video, audio, document or link) taken from bound data, for example inside @Each over a Query result. size: row | card | detail.',
  props: z.object({ item: boundItem, size: z.enum(['row', 'card', 'detail']).optional() }),
  rules: { item: 'bound' },
});

// --- inputs and controls -----------------------------------------------------------------------------------------------
const Form = spec({
  name: 'Form',
  description: 'Groups input fields under one name. Put an ActionButton inside to submit them through a registered action.',
  props: z.object({ name: z.string(), children: nodes() }),
});
const TextField = spec({
  name: 'TextField',
  description: 'A labelled text input. Bind value to a $variable to use it in Query arguments or other components.',
  props: z.object({
    name: z.string(),
    label: shortText(),
    value: bindable(z.string().optional()),
    placeholder: z.string().optional(),
    multiline: z.boolean().optional(),
    rules: fieldRules.optional(),
  }),
  fieldNameProp: 'name',
});
const Select = spec({
  name: 'Select',
  description: 'A labelled choice from options. Bind value to a $variable to filter a Query or switch what is shown.',
  props: z.object({
    name: z.string(),
    label: shortText(),
    options: z.array(optionSpec),
    value: bindable(z.string().optional()),
    placeholder: z.string().optional(),
  }),
  fieldNameProp: 'name',
});
const DateRange = spec({
  name: 'DateRange',
  description:
    'Start and end dates (YYYY-MM-DD) in the person’s time zone, at most 366 days apart. Bind value to a $variable and pass it to a Query.',
  props: z.object({
    name: z.string(),
    label: shortText(),
    value: bindable(dateRangeValue.optional()),
  }),
  fieldNameProp: 'name',
});
const Button = spec({
  name: 'Button',
  description:
    'A local control that never changes saved data: Action([@Set($v, x)]), @Reset, @Run(query) to refresh, @ToAssistant("follow-up") or @OpenUrl("/app/…"). variant: primary | secondary | quiet.',
  props: z.object({
    label: shortText(),
    action: actionExpression.optional(),
    variant: z.enum(['primary', 'secondary', 'quiet']).optional(),
  }),
});
const ActionButton = spec({
  name: 'ActionButton',
  description:
    'Starts one registered action by its id. Its label, confirmation and result come from Rafii, never from you. Inside a Form it sends that form’s fields; inputs adds bound values such as {draftIds: $picked}.',
  props: z.object({
    actionId: z.string(),
    formName: z.string().optional(),
    inputs: z.record(z.string(), z.any()).optional(),
  }),
  rules: { actionId: 'action-id' },
});

/** Every primitive, in prompt order within its group. */
export const PRIMITIVE_SPECS: readonly RafiiComponentSpec[] = [
  RafiiRoot, Stack, Grid, Section, Card, Tabs, TabItem, Accordion, AccordionItem, Text,
  EmptyState, LoadingState, ErrorState,
  ToolBoundTable, ToolBoundChart, Metric, Timeline, Comparison, TaskStatus, EvidenceLink,
  SelectionList, AssetPreview,
  Form, TextField, Select, DateRange, Button,
  ActionButton,
];

export const PRIMITIVE_GROUPS: readonly RafiiGroupSpec[] = [
  {
    id: 'layout',
    name: 'Layout',
    components: ['RafiiRoot', 'Stack', 'Grid', 'Section', 'Card', 'Tabs', 'TabItem', 'Accordion', 'AccordionItem', 'Text'],
    notes: ['Start with root = RafiiRoot([...]). Prefer few, meaningful sections over many decorative cards.'],
  },
  { id: 'states', name: 'States', components: ['EmptyState', 'LoadingState', 'ErrorState'] },
  {
    id: 'data',
    name: 'Bound data',
    components: ['ToolBoundTable', 'ToolBoundChart', 'Metric', 'Timeline', 'Comparison', 'TaskStatus', 'EvidenceLink'],
    notes: [
      'Facts, figures, titles and statuses come only from Query results passed as source. Never type them as literals.',
      'Declare each Query once as a top-level statement with null defaults and reuse its name.',
    ],
  },
  { id: 'selection', name: 'Selection and previews', components: ['SelectionList', 'AssetPreview'] },
  {
    id: 'inputs',
    name: 'Inputs and local controls',
    components: ['Form', 'TextField', 'Select', 'DateRange', 'Button'],
    notes: ['Inputs only change this view. Bind them to $variables and use those in Query arguments.'],
  },
  {
    id: 'actions',
    name: 'Registered actions',
    components: ['ActionButton'],
    notes: ['Use only action ids listed under Rafii bindings. If none fits, explain with Text instead of adding a button.'],
  },
];

/** Groups every consumer journey prompt starts from; E's journey groups are appended per journey. */
export const CORE_GROUP_IDS: readonly string[] = ['layout', 'states', 'data', 'selection', 'inputs', 'actions'];

/** The founder library is read-only in this release: no form submission and no registered actions (D-A22). */
export const FOUNDER_PRIMITIVE_NAMES: readonly string[] = PRIMITIVE_SPECS.map((s) => s.name).filter(
  (name) => !['ActionButton', 'Form', 'AssetPreview'].includes(name),
);
export const FOUNDER_CORE_GROUP_IDS: readonly string[] = ['layout', 'states', 'data', 'selection', 'inputs'];

export function primitiveSpec(name: string): RafiiComponentSpec | undefined {
  return PRIMITIVE_SPECS.find((s) => s.name === name);
}
