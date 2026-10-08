/**
 * Which components make up each Rafii Generative UI library and which component groups each journey prompt uses.
 *
 * React-free (the asset generator and the trusted Node validator load it). Two libraries, never mixed:
 *   consumer  J01–J08: C's primitives + E's consumer journey components;
 *   founder   J09: a read-only primitive subset + E's founder components, in its own chunk, prompt and schema.
 *
 * Lane E plugs in by exporting `JOURNEY_SPEC_MODULE: JourneySpecModule` from `components/journeys/specs.ts` (React-free)
 * and `JOURNEY_RENDERERS` from `components/journeys/renderers.tsx`; `JOURNEYS_MODULE` below is the one import that
 * points at them. The validator, prompts and hashes then include them automatically.
 */
import { createLibrary, defineComponent, type Library, type LibrarySpec } from '@openuidev/lang-core';
import { CONTRACT_VERSION, JOURNEYS, type JourneyId } from '@/lib/agent-runtime/ui-contracts';
import {
  CORE_GROUP_IDS,
  FOUNDER_CORE_GROUP_IDS,
  FOUNDER_PRIMITIVE_NAMES,
  LIBRARY_VERSION,
  PRIMITIVE_GROUPS,
  PRIMITIVE_SPECS,
  RESERVED_NAMES,
  ROOT_COMPONENT,
  type JourneySpecModule,
  type RafiiComponentSpec,
  type RafiiGroupSpec,
} from './component-specs';
import { JOURNEYS_MODULE } from './core/journey-module';

export type LibraryName = 'consumer' | 'founder';

export interface LibraryDefinition {
  name: LibraryName;
  id: string;
  root: string;
  version: string;
  specs: readonly RafiiComponentSpec[];
  groups: readonly RafiiGroupSpec[];
}

export interface JourneyLibrary {
  library: LibraryName;
  groups: readonly string[];
}

const journeys: JourneySpecModule = JOURNEYS_MODULE;

function definition(name: LibraryName): LibraryDefinition {
  if (name === 'consumer') {
    return {
      name,
      id: 'rafii-consumer',
      root: ROOT_COMPONENT,
      version: LIBRARY_VERSION,
      specs: [...PRIMITIVE_SPECS, ...journeys.consumer.specs],
      groups: [...PRIMITIVE_GROUPS, ...journeys.consumer.groups],
    };
  }
  const allowed = new Set(FOUNDER_PRIMITIVE_NAMES);
  return {
    name,
    id: 'rafii-founder',
    root: ROOT_COMPONENT,
    version: LIBRARY_VERSION,
    specs: [...PRIMITIVE_SPECS.filter((s) => allowed.has(s.name)), ...journeys.founder.specs],
    groups: [
      ...PRIMITIVE_GROUPS.filter((g) => FOUNDER_CORE_GROUP_IDS.includes(g.id)).map((g) => ({
        ...g,
        components: g.components.filter((c) => allowed.has(c)),
      })),
      ...journeys.founder.groups,
    ],
  };
}

export const LIBRARY_DEFINITIONS: Readonly<Record<LibraryName, LibraryDefinition>> = {
  consumer: definition('consumer'),
  founder: definition('founder'),
};

/**
 * Earlier library hashes this build still renders faithfully (additive changes only). An artifact whose libraryHash is
 * neither current nor listed here shows its stored native fallback instead of being re-generated or re-charged.
 */
export const COMPATIBLE_LIBRARY_HASHES: Readonly<Record<LibraryName, readonly string[]>> = { consumer: [], founder: [] };

/** Journey → library and prompt groups. J09 is the founder journey; every other journey uses the consumer library. */
export const JOURNEY_LIBRARIES: Readonly<Record<JourneyId, JourneyLibrary>> = Object.fromEntries(
  JOURNEYS.map((journey) => {
    const library: LibraryName = journey === 'J09' ? 'founder' : 'consumer';
    const core = library === 'founder' ? FOUNDER_CORE_GROUP_IDS : CORE_GROUP_IDS;
    const extra = journeys.journeys[journey] ?? [];
    const known = new Set(LIBRARY_DEFINITIONS[library].groups.map((g) => g.id));
    const groups = [...core, ...extra.filter((g) => !core.includes(g))].filter((g) => known.has(g));
    return [journey, { library, groups }];
  }),
) as unknown as Record<JourneyId, JourneyLibrary>;

/** Component names of the given groups (in group order, de-duplicated). */
export function groupComponents(library: LibraryName, groupIds: readonly string[]): string[] {
  const out: string[] = [];
  for (const id of groupIds) {
    const group = LIBRARY_DEFINITIONS[library].groups.find((g) => g.id === id);
    for (const name of group?.components ?? []) if (!out.includes(name)) out.push(name);
  }
  return out;
}

/** Structural problems of the registry itself (names, groups, root). Empty means sound; tests and the generator assert it. */
export function registryProblems(): string[] {
  const problems: string[] = [];
  const reserved = new Set<string>(RESERVED_NAMES);
  for (const lib of Object.values(LIBRARY_DEFINITIONS)) {
    const names = new Set<string>();
    for (const s of lib.specs) {
      if (!/^[A-Z][A-Za-z0-9]{1,47}$/.test(s.name)) problems.push(`${lib.name}:name_not_pascal:${s.name}`);
      if (reserved.has(s.name)) problems.push(`${lib.name}:name_reserved:${s.name}`);
      if (names.has(s.name)) problems.push(`${lib.name}:name_duplicate:${s.name}`);
      names.add(s.name);
      if (!s.description || s.description.length > 400) problems.push(`${lib.name}:description:${s.name}`);
      for (const prop of Object.keys(s.rules ?? {})) if (!(prop in s.props.shape)) problems.push(`${lib.name}:rule_prop:${s.name}.${prop}`);
    }
    if (!names.has(lib.root)) problems.push(`${lib.name}:root_missing`);
    const groupIds = new Set<string>();
    for (const g of lib.groups) {
      if (groupIds.has(g.id)) problems.push(`${lib.name}:group_duplicate:${g.id}`);
      groupIds.add(g.id);
      for (const c of g.components) if (!names.has(c)) problems.push(`${lib.name}:group_unknown_component:${g.id}.${c}`);
    }
  }
  const consumer = new Set(LIBRARY_DEFINITIONS.consumer.specs.map((s) => s.name));
  for (const s of LIBRARY_DEFINITIONS.founder.specs) {
    if (s.name === 'ActionButton' || s.name === 'Form') problems.push(`founder:write_control:${s.name}`);
  }
  for (const s of journeys.founder.specs) if (consumer.has(s.name)) problems.push(`founder_component_in_consumer:${s.name}`);
  return problems;
}

/** A lang-core library with no renderers: identical prompt/schema identity to the React library built from the same specs. */
export function createSpecLibrary(name: LibraryName): Library<null> {
  const lib = LIBRARY_DEFINITIONS[name];
  return createLibrary<null>({
    id: lib.id,
    root: lib.root,
    components: lib.specs.map((s) => defineComponent({ name: s.name, description: s.description, props: s.props, component: null })),
    componentGroups: lib.groups.map((g) => ({ name: g.name, components: [...g.components], ...(g.notes ? { notes: [...g.notes] } : {}) })),
  });
}

/** Deterministic JSON: object keys sorted at every depth, arrays in order, `undefined` dropped (JSON semantics). */
export function stableJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null';
  if (Array.isArray(value)) return `[${value.map((v) => (v === undefined ? 'null' : stableJson(v))).join(',')}]`;
  const entries = Object.keys(value as Record<string, unknown>)
    .sort()
    .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
    .map((k) => `${JSON.stringify(k)}:${stableJson((value as Record<string, unknown>)[k])}`);
  return `{${entries.join(',')}}`;
}

/** The text a library hash is computed over: canonical `toSpec()` plus the contract version (D-A30). */
export function libraryHashInput(spec: LibrarySpec): string {
  return `${stableJson(spec)}\n${CONTRACT_VERSION}`;
}

/** Restrict a library spec to some components (OpenUI has no native subset parameter; openui-package §2.2). */
export function subsetSpec(full: LibrarySpec, allowed: ReadonlySet<string>): LibrarySpec {
  return {
    ...(full.id !== undefined ? { id: full.id } : {}),
    ...(full.root !== undefined ? { root: full.root } : {}),
    components: Object.fromEntries(Object.entries(full.components).filter(([name]) => allowed.has(name))),
    componentGroups: (full.componentGroups ?? [])
      .map((g) => ({ ...g, components: g.components.filter((c) => allowed.has(c)) }))
      .filter((g) => g.components.length > 0),
  };
}
