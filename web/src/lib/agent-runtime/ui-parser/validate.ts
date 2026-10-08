/**
 * Trusted OpenUI validation and merge (D-A11), pure: no I/O, no rendering, no tool execution, no evaluation.
 *
 * Uses `@openuidev/lang-core` 0.3.2 only (createParser, mergeStatements, tokenize/split/autoClose/parseExpression,
 * walkAST). Rafii rules the official parser does not express are applied on top of its result and of the statement ASTs:
 * root `RafiiRoot`, zero `Mutation`, literal read-binding `Query` names with null defaults, literal refresh >= 30 s,
 * literal/$variable query arguments, component/action allowlists, bounds, duplicate ids, prop rules from
 * `component-specs.ts`, and in patch mode the unexplained-deletion guard (a malformed `x = )` parses to Null and would
 * delete `x`; openui-package.md §5). Error strings are stable codes plus identifiers, never source text.
 */
import {
  autoClose,
  createParser,
  isBuiltin,
  mergeStatements,
  parseExpression,
  split,
  tokenize,
  walkAST,
  type ASTNode,
  type ElementNode,
  type LibraryJSONSchema,
  type ParseResult,
  type Parser,
} from '@openuidev/lang-core';
import { BOUNDS } from '@/lib/agent-runtime/ui-contracts';
import { hasFence, maxBracketDepth, stripLineComments, utf8Bytes } from './source-scan';

export type PropRuleName = 'query' | 'bound' | 'safe-href' | 'action-id';

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
  /** Optional: sha256 of the base the edit was requested against; a mismatch is a revision conflict. */
  baseSourceHash?: string | null;
}

export interface UiValidationResult {
  accepted: boolean;
  canonicalSource: string | null;
  sourceHash: string | null;
  statementCount: number;
  queryNames: string[];
  actionIds: string[];
  componentNames: string[];
  /** D-A42: every declared reactive `$variable` of the canonical source (persistable state keys), at most 200. */
  stateNames: string[];
  /** D-A42: every Form name of the canonical source (persistable form keys), at most 100. */
  formNames: string[];
  errors: string[];
  libraryHash: string | null;
  libraryVersion: string | null;
  /** Patch mode: statements of the base that the merge removed (explicitly or because their parent was re-declared). */
  removedStatementIds?: string[];
  /** Patch mode: statements of the base that the patch re-declared. */
  replacedStatementIds?: string[];
}

/** Everything the validator needs about one library, built once from the registry (see index.ts). */
export interface ValidatorLibrary {
  name: 'consumer' | 'founder';
  root: string;
  schema: LibraryJSONSchema;
  libraryHash: string;
  libraryVersion: string;
  /** component → positional prop names, in the parser's order (JSON Schema property order). */
  params: Readonly<Record<string, readonly string[]>>;
  /** component → prop → rule. */
  rules: Readonly<Record<string, Readonly<Record<string, PropRuleName>>>>;
}

export type Sha256 = (text: string) => string;

/** The recursive parser is protected by a bracket pre-scan before any parse. */
export const MAX_BRACKET_DEPTH = 64;
const MAX_ERRORS = 20;
const MAX_POLICY_ITEMS = 500;
const MAX_STATE_NAMES = 200;
const MAX_FORM_NAMES = 100;
/** `$` + identifier, at most 64 characters in all. */
const STATE_NAME = /^\$[A-Za-z_][A-Za-z0-9_]{0,62}$/;
/** A Form name is a literal identifier (it becomes a persisted state key), at most 64 characters. */
const FORM_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

interface Stmt {
  id: string;
  tokenCount: number;
  explicitNull: boolean;
  ast: ASTNode;
}

const parsers = new WeakMap<LibraryJSONSchema, Parser>();
function parserFor(lib: ValidatorLibrary): Parser {
  let parser = parsers.get(lib.schema);
  if (!parser) {
    parser = createParser(lib.schema, lib.root);
    parsers.set(lib.schema, parser);
  }
  return parser;
}

function rejected(errors: string[], lib?: ValidatorLibrary | null): UiValidationResult {
  const unique = [...new Set(errors.map((e) => e.slice(0, 120)))].slice(0, MAX_ERRORS);
  return {
    accepted: false,
    canonicalSource: null,
    sourceHash: null,
    statementCount: 0,
    queryNames: [],
    actionIds: [],
    componentNames: [],
    stateNames: [],
    formNames: [],
    errors: unique.length ? unique : ['parse_rejected'],
    libraryHash: lib?.libraryHash ?? null,
    libraryVersion: lib?.libraryVersion ?? null,
  };
}

function ident(value: string): string {
  return /^[$A-Za-z_][A-Za-z0-9_]{0,63}$/.test(value) ? value : 'invalid';
}

/** Statements as the parser splits them (`autoClose` → `tokenize` → `split` → `parseExpression`). */
export function statementsOf(text: string): Stmt[] {
  const { text: closed } = autoClose(text);
  return split(tokenize(closed)).map((raw) => ({
    id: raw.id,
    tokenCount: raw.tokens.length,
    // Only the literal `null` (token type 12) is an intended deletion; a malformed right-hand side also parses to Null.
    explicitNull: raw.tokens.length === 1 && (raw.tokens[0].t as number) === 12,
    ast: parseExpression(raw.tokens),
  }));
}

function refsOf(node: ASTNode): Set<string> {
  const out = new Set<string>();
  walkAST(node, (current) => {
    if (current.k === 'Ref' || current.k === 'RuntimeRef') out.add(current.n);
  });
  return out;
}

function isLiteral(node: ASTNode): boolean {
  switch (node.k) {
    case 'Str':
    case 'Num':
    case 'Bool':
    case 'Null':
      return true;
    case 'UnaryOp':
      return node.op === '-' && node.operand.k === 'Num';
    case 'Arr':
      return node.els.every(isLiteral);
    case 'Obj':
      return node.entries.every(([, value]) => isLiteral(value));
    default:
      return false;
  }
}

/** Query arguments: an object of literals and `$variables` only (no query→query dependencies; openui-package §6.3). */
function literalOrState(node: ASTNode): boolean {
  if (node.k === 'StateRef') return true;
  if (node.k === 'Arr') return node.els.every(literalOrState);
  if (node.k === 'Obj') return node.entries.every(([, value]) => literalOrState(value));
  return isLiteral(node);
}

function isInternalPath(value: string): boolean {
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return false;
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code < 0x20 || code === 0x7f) return false;
  }
  return true;
}

function elementDepth(node: unknown, depth = 1, seen = 0): number {
  if (seen > 10_000) return depth;
  if (node === null || typeof node !== 'object') return depth - 1;
  if (Array.isArray(node)) return node.reduce<number>((max, item) => Math.max(max, elementDepth(item, depth, seen + 1)), depth - 1);
  const record = node as Record<string, unknown>;
  if (record.type === 'element' && typeof record.typeName === 'string') {
    const props = (record as unknown as ElementNode).props ?? {};
    return Object.values(props).reduce<number>((max, value) => Math.max(max, elementDepth(value, depth + 1, seen + 1)), depth);
  }
  if (typeof record.k === 'string') return depth - 1 + astComponentDepth(record as unknown as ASTNode);
  return Object.values(record).reduce<number>((max, value) => Math.max(max, elementDepth(value, depth, seen + 1)), depth - 1);
}

/** Component nesting inside an expression (for example an @Each template). */
function astComponentDepth(node: ASTNode): number {
  const visit = (current: ASTNode): number => {
    const childDepth = (children: ASTNode[]) => children.reduce((max, child) => Math.max(max, visit(child)), 0);
    switch (current.k) {
      case 'Comp':
        return (isBuiltin(current.name) ? 0 : 1) + childDepth(current.args);
      case 'Arr':
        return childDepth(current.els);
      case 'Obj':
        return childDepth(current.entries.map(([, value]) => value));
      case 'Ternary':
        return childDepth([current.cond, current.then, current.else]);
      case 'BinOp':
        return childDepth([current.left, current.right]);
      case 'Member':
        return visit(current.obj);
      case 'Index':
        return childDepth([current.obj, current.index]);
      default:
        return 0;
    }
  };
  return visit(node);
}

function validRequest(request: UiValidatorRequest): string | null {
  if (!request || typeof request !== 'object') return 'bad_request';
  if (request.mode !== 'generate' && request.mode !== 'patch') return 'bad_request';
  if (typeof request.candidateSource !== 'string') return 'bad_request';
  if (request.baseSource !== null && request.baseSource !== undefined && typeof request.baseSource !== 'string') return 'bad_request';
  if (typeof request.libraryHash !== 'string') return 'bad_request';
  const policy = request.policy;
  if (!policy || typeof policy !== 'object' || typeof policy.rootName !== 'string') return 'bad_request';
  for (const list of [policy.allowedComponents, policy.readBindings, policy.actionIds]) {
    if (!Array.isArray(list) || list.length > MAX_POLICY_ITEMS || !list.every((item) => typeof item === 'string')) return 'bad_request';
  }
  return null;
}

/**
 * Validate (and in patch mode merge) one candidate against one library and one manifest policy. `sha256` is injected so
 * the module stays free of Node-only imports.
 */
export function validateCandidate(request: UiValidatorRequest, lib: ValidatorLibrary, sha256: Sha256): UiValidationResult {
  const invalid = validRequest(request);
  if (invalid) return rejected([invalid], lib);
  if (request.libraryHash !== lib.libraryHash) return rejected(['library_unsupported'], lib);
  const { policy } = request;
  if (policy.rootName !== lib.root) return rejected(['root_invalid'], lib);
  const patch = request.mode === 'patch';
  const founder = lib.name === 'founder';
  const candidate = request.candidateSource;
  const limit = patch ? (founder ? BOUNDS.founderPatchBytes : BOUNDS.patchBytes) : BOUNDS.sourceBytes;
  if (utf8Bytes(candidate) > limit) return rejected(['source_too_large'], lib);
  const base = request.baseSource ?? null;
  if (patch) {
    if (!base) return rejected(['missing_base'], lib);
    if (utf8Bytes(base) > BOUNDS.sourceBytes) return rejected(['source_too_large'], lib);
    if (request.baseSourceHash && sha256(base) !== request.baseSourceHash) return rejected(['revision_conflict'], lib);
  }
  if (maxBracketDepth(candidate) > MAX_BRACKET_DEPTH || (base && maxBracketDepth(base) > MAX_BRACKET_DEPTH)) {
    return rejected(['nesting_too_deep'], lib);
  }

  const cleanCandidate = stripLineComments(candidate);
  const cleanBase = base ? stripLineComments(base) : '';
  let merged: string;
  try {
    merged = (patch ? mergeStatements(cleanBase, cleanCandidate, 'root') : mergeStatements('', cleanCandidate, 'root')).trim();
  } catch {
    return rejected(['parse_exception'], lib);
  }
  if (!merged) return rejected(['root_invalid'], lib);
  if (hasFence(merged)) return rejected(['fence_in_source'], lib);
  if (utf8Bytes(merged) > BOUNDS.sourceBytes) return rejected(['source_too_large'], lib);
  if (maxBracketDepth(merged) > MAX_BRACKET_DEPTH) return rejected(['nesting_too_deep'], lib);

  let result: ParseResult;
  try {
    result = parserFor(lib).parse(merged);
  } catch {
    return rejected(['parse_exception'], lib);
  }

  const errors: string[] = [];
  const root = result.root;
  if (!root || root.statementId !== 'root' || root.typeName !== lib.root) errors.push('root_invalid');
  if (result.meta.incomplete) errors.push('incomplete');
  for (const error of result.meta.errors) errors.push(`${error.code}:${ident(error.statementId ?? '')}`);
  for (const name of result.meta.unresolved) errors.push(`unresolved_ref:${ident(name)}`);
  if (result.meta.statementCount > BOUNDS.statements) errors.push('bounds_statements');
  if (root && elementDepth(root) > BOUNDS.treeDepth) errors.push('bounds_depth');
  if (result.mutationStatements.length) errors.push('mutation_forbidden');

  const readBindings = new Set(policy.readBindings);
  const queryNames: string[] = [];
  for (const query of result.queryStatements) {
    const id = ident(query.statementId);
    const tool = query.toolAST;
    if (!tool || tool.k !== 'Str' || !readBindings.has(tool.v)) errors.push(`query_binding_denied:${id}`);
    else if (!queryNames.includes(tool.v)) queryNames.push(tool.v);
    if (query.defaultsAST && query.defaultsAST.k !== 'Null') errors.push(`query_defaults_forbidden:${id}`);
    const refresh = query.refreshAST;
    if (refresh && !(refresh.k === 'Num' && Number.isFinite(refresh.v) && refresh.v >= BOUNDS.refreshMinSeconds)) {
      errors.push(`refresh_invalid:${id}`);
    }
    if (query.argsAST && !(query.argsAST.k === 'Obj' && literalOrState(query.argsAST))) errors.push(`query_args_shape:${id}`);
  }

  // Statement-level walk: sees orphans and @Each templates too, which the materialized tree does not.
  const statements = statementsOf(merged);
  if (statements.length > BOUNDS.statements) errors.push('bounds_statements');
  const kinds = new Map<string, 'query' | 'mutation' | 'state' | 'value'>();
  const asts = new Map<string, ASTNode>();
  for (const stmt of statements) {
    const top = stmt.ast;
    const kind = top.k === 'Comp' && top.name === 'Query' ? 'query' : top.k === 'Comp' && top.name === 'Mutation' ? 'mutation' : stmt.id.startsWith('$') ? 'state' : 'value';
    kinds.set(stmt.id, kind);
    asts.set(stmt.id, top);
  }
  const duplicates = (list: Stmt[]) => {
    const seen = new Set<string>();
    for (const stmt of list) {
      if (seen.has(stmt.id)) errors.push(`duplicate_statement:${ident(stmt.id)}`);
      seen.add(stmt.id);
    }
  };
  const candidateStatements = statementsOf(cleanCandidate);
  duplicates(patch ? candidateStatements : statements);

  const isBound = (node: ASTNode, depth = 0): boolean => {
    if (depth > 32) return false;
    switch (node.k) {
      case 'RuntimeRef':
        return node.refType === 'query';
      case 'Ref': {
        const kind = kinds.get(node.n);
        if (kind === 'query') return true;
        if (kind === 'value') return isBound(asts.get(node.n) as ASTNode, depth + 1);
        if (kind === 'state' || kind === 'mutation') return false;
        return true; // an @Each iterator variable: bound when its collection is
      }
      case 'Member':
        return isBound(node.obj, depth + 1);
      case 'Index':
        return isBound(node.obj, depth + 1);
      case 'Ternary':
        return isBound(node.then, depth + 1) && isBound(node.else, depth + 1);
      case 'Comp':
        return isBuiltin(node.name) && node.args.some((arg) => isBound(arg, depth + 1));
      default:
        return false;
    }
  };
  const hrefOk = (node: ASTNode): boolean => {
    if (node.k === 'Str') return isInternalPath(node.v);
    if (node.k === 'BinOp' && node.op === '+') {
      let left: ASTNode = node;
      while (left.k === 'BinOp' && left.op === '+') left = left.left;
      if (left.k === 'Str') return isInternalPath(left.v);
    }
    return isBound(node);
  };

  const components = new Set<string>();
  const actionIds: string[] = [];
  const formNames: string[] = [];
  const allowedActions = new Set(policy.actionIds);
  for (const stmt of statements) {
    const id = ident(stmt.id);
    const top = stmt.ast;
    if (top.k === 'Comp' && top.name === 'Query' && top.args.length > 4) errors.push(`query_args_count:${id}`);
    walkAST(top, (node) => {
      if (node.k !== 'Comp') return;
      if (node.name === 'Mutation') {
        errors.push('mutation_forbidden');
        return;
      }
      if (node.name === 'Query') {
        if (node !== top) errors.push(`query_inline:${id}`);
        return;
      }
      if (isBuiltin(node.name)) return;
      components.add(node.name);
      const params = lib.params[node.name];
      if (!params) {
        errors.push(`unknown_component:${ident(node.name)}`);
        return;
      }
      if (node.args.length > params.length) errors.push(`excess_args:${id}`);
      if (node.name === 'Form') {
        const formName = node.args[0];
        if (!formName || formName.k !== 'Str' || !FORM_NAME.test(formName.v)) errors.push(`form_name_invalid:${id}`);
        else if (!formNames.includes(formName.v)) formNames.push(formName.v);
      }
      const rules = lib.rules[node.name] ?? {};
      for (const [prop, rule] of Object.entries(rules)) {
        const arg = node.args[params.indexOf(prop)];
        if (!arg || arg.k === 'Null') continue; // a missing required prop is the parser's error
        if (rule === 'query' && !(arg.k === 'Ref' && kinds.get(arg.n) === 'query')) errors.push(`source_not_query:${id}`);
        if (rule === 'bound' && !isBound(arg)) errors.push(`bound_literal:${id}`);
        if (rule === 'safe-href' && !hrefOk(arg)) errors.push(`href_not_allowed:${id}`);
        if (rule === 'action-id') {
          if (arg.k !== 'Str') errors.push(`action_id_not_literal:${id}`);
          else if (!allowedActions.has(arg.v)) errors.push(`action_denied:${ident(arg.v)}`);
          else if (!actionIds.includes(arg.v)) actionIds.push(arg.v);
        }
      }
    });
  }
  if (formNames.length > MAX_FORM_NAMES) errors.push('bounds_forms');
  const stateNames = Object.keys(result.stateDeclarations ?? {}).sort();
  for (const name of stateNames) if (!STATE_NAME.test(name)) errors.push(`state_name_invalid:${ident(name)}`);
  if (stateNames.length > MAX_STATE_NAMES) errors.push('bounds_state');
  const allowed = new Set(policy.allowedComponents);
  for (const name of components) if (!allowed.has(name)) errors.push(`component_denied:${ident(name)}`);

  let removed: string[] | undefined;
  let replaced: string[] | undefined;
  if (patch) {
    const baseStatements = statementsOf(cleanBase);
    const baseAst = new Map(baseStatements.map((s) => [s.id, s.ast] as const));
    const mergedIds = new Set(statements.map((s) => s.id));
    const deleted = new Set(baseStatements.map((s) => s.id).filter((sid) => !mergedIds.has(sid)));
    const explicit = new Set(candidateStatements.filter((s) => s.explicitNull).map((s) => s.id));
    const redeclared = new Map(candidateStatements.filter((s) => !s.explicitNull && baseAst.has(s.id)).map((s) => [s.id, s.ast] as const));
    const explained = new Set([...deleted].filter((sid) => explicit.has(sid)));
    let changed = true;
    while (changed) {
      changed = false;
      for (const sid of deleted) {
        if (explained.has(sid)) continue;
        for (const [parent, ast] of baseAst) {
          if (!refsOf(ast).has(sid)) continue;
          const now = redeclared.get(parent);
          if ((now && !refsOf(now).has(sid)) || explained.has(parent)) {
            explained.add(sid);
            changed = true;
            break;
          }
        }
      }
    }
    for (const sid of deleted) if (!explained.has(sid)) errors.push(`unexplained_deletion:${ident(sid)}`);
    removed = [...deleted];
    replaced = [...redeclared.keys()];
  }

  if (errors.length) return { ...rejected(errors, lib), ...(removed ? { removedStatementIds: removed, replacedStatementIds: replaced } : {}) };
  return {
    accepted: true,
    canonicalSource: merged,
    sourceHash: sha256(merged),
    statementCount: result.meta.statementCount,
    queryNames,
    actionIds,
    componentNames: [...components].sort(),
    stateNames,
    formNames: [...formNames].sort(),
    errors: [],
    libraryHash: lib.libraryHash,
    libraryVersion: lib.libraryVersion,
    ...(removed ? { removedStatementIds: removed, replacedStatementIds: replaced } : {}),
  };
}
