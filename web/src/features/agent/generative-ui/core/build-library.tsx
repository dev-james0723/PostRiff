'use client';
/**
 * Builds an OpenUI React library from the registry specs plus renderers (lane C primitives + lane E journeys).
 *
 * The React library uses the very same spec objects (names, Zod props, descriptions, groups) as the trusted validator
 * and the asset generator, so its prompt/schema identity is the generated `libraryHash`. A spec without a renderer gets
 * a quiet "can't be shown" renderer (and fails `agent-ui-library.test.cjs`), so a missing journey renderer never crashes
 * a message.
 */
import { LIBRARY_DEFINITIONS, type LibraryName } from '../library-registry';
import type { JourneyRenderers, RafiiComponentRenderer } from './component-types';
import { createLibrary, defineComponent, type Library } from './openui';

function missingRenderer(name: string): RafiiComponentRenderer {
  const Missing: RafiiComponentRenderer = () => (
    <p className="text-xs text-muted-foreground" data-genui-missing={name}>
      {'—'}
    </p>
  );
  Missing.displayName = `Missing(${name})`;
  return Missing;
}

export function missingRenderers(name: LibraryName, renderers: JourneyRenderers): string[] {
  return LIBRARY_DEFINITIONS[name].specs.map((s) => s.name).filter((component) => !Object.prototype.hasOwnProperty.call(renderers, component));
}

export function buildReactLibrary(name: LibraryName, renderers: JourneyRenderers): Library {
  const definition = LIBRARY_DEFINITIONS[name];
  return createLibrary({
    id: definition.id,
    root: definition.root,
    components: definition.specs.map((spec) =>
      defineComponent({
        name: spec.name,
        description: spec.description,
        props: spec.props,
        component: Object.prototype.hasOwnProperty.call(renderers, spec.name) ? renderers[spec.name] : missingRenderer(spec.name),
      }),
    ),
    componentGroups: definition.groups.map((g) => ({ name: g.name, components: [...g.components], ...(g.notes ? { notes: [...g.notes] } : {}) })),
  });
}
