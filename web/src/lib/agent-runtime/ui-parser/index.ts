/**
 * Lane C — trusted OpenUI parser adapter (validate + merge). Uses `@openuidev/lang-core` only (no React, no DOM, no I/O).
 * Frozen interface (A): the route `web/src/app/internal/agent-ui/validate/route.ts` calls `validateAndMergeUi(request)`.
 * Implementation rules: evidence/r0/openui-package.md §4.5 and §5 (root must be RafiiRoot, no Mutation statements, Query
 * tool names must be literal read bindings from the policy, null defaults, literal refresh >= 30 s, component/action
 * allowlists, bounds, unexplained-deletion guard in patch mode). C replaces this stub.
 */
export interface UiValidatorPolicy {
  rootName: string;
  allowedComponents: string[];
  readBindings: string[];
  actionIds: string[];
  founder?: boolean;
}

export interface UiValidatorRequest {
  v: 'v1';
  contractVersion: string;
  mode: 'generate' | 'patch';
  baseSource: string | null;
  candidateSource: string;
  libraryHash: string;
  policy: UiValidatorPolicy;
  scope: { workspaceId: string; artifactId: string; attemptId: string };
}

export interface UiValidationResult {
  accepted: boolean;
  canonicalSource: string | null;
  sourceHash: string | null;
  statementCount: number;
  queryNames: string[];
  actionIds: string[];
  componentNames: string[];
  errors: string[];
  libraryHash: string | null;
  libraryVersion: string | null;
}

export function validateAndMergeUi(_request: UiValidatorRequest): UiValidationResult {
  return {
    accepted: false,
    canonicalSource: null,
    sourceHash: null,
    statementCount: 0,
    queryNames: [],
    actionIds: [],
    componentNames: [],
    errors: ['validation_unavailable'],
    libraryHash: null,
    libraryVersion: null,
  };
}
