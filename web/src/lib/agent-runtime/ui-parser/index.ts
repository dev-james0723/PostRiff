/**
 * Lane C — trusted OpenUI parser adapter (validate + merge) behind A's Node route
 * `web/src/app/internal/agent-ui/validate/route.ts`. Server-only (node:crypto); uses `@openuidev/lang-core` only — no
 * React, no DOM, no network, no tool execution. Frozen interface (A): `validateAndMergeUi(request)`.
 *
 * The libraries are built from `component-specs.ts` + `library-registry.ts` (the same objects the browser renders with),
 * so the library hash here is the identity of what is actually validated; the Python side additionally re-checks
 * `sourceHash == sha256(canonicalSource)` and `libraryHash` (ui_validator.py).
 */
import { createHash } from 'node:crypto';
import {
  createSpecLibrary,
  LIBRARY_DEFINITIONS,
  libraryHashInput,
  type LibraryName,
} from '@/features/agent/generative-ui/library-registry';
import {
  validateCandidate,
  type PropRuleName,
  type UiValidationResult,
  type UiValidatorPolicy,
  type UiValidatorRequest,
  type ValidatorLibrary,
} from './validate';

export type { PropRuleName, UiValidationResult, UiValidatorPolicy, UiValidatorRequest, ValidatorLibrary };

export function sha256Hex(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

const libraries = new Map<LibraryName, ValidatorLibrary>();

/** One library's validator context (parser schema, hash, positional params, prop rules), built once per process. */
export function validatorLibrary(name: LibraryName): ValidatorLibrary {
  const cached = libraries.get(name);
  if (cached) return cached;
  const library = createSpecLibrary(name);
  const schema = library.toJSONSchema();
  const definition = LIBRARY_DEFINITIONS[name];
  const params: Record<string, readonly string[]> = {};
  const rules: Record<string, Readonly<Record<string, PropRuleName>>> = {};
  for (const spec of definition.specs) {
    const def = schema.$defs?.[spec.name];
    params[spec.name] = Object.keys((def?.properties as Record<string, unknown> | undefined) ?? {});
    if (spec.rules) rules[spec.name] = { ...spec.rules } as Record<string, PropRuleName>;
  }
  const context: ValidatorLibrary = {
    name,
    root: definition.root,
    schema,
    libraryHash: sha256Hex(libraryHashInput(library.toSpec())),
    libraryVersion: definition.version,
    params,
    rules,
  };
  libraries.set(name, context);
  return context;
}

export function validateAndMergeUi(request: UiValidatorRequest): UiValidationResult {
  const name: LibraryName = request && typeof request === 'object' && request.policy && request.policy.founder ? 'founder' : 'consumer';
  return validateCandidate(request, validatorLibrary(name), sha256Hex);
}
