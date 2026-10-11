# R0 evidence — OpenUI package API map (lanes C / A)

**Prepared:** 2026-10-08 · read-only reader for role A (R0 baseline)
**Worktree:** `/Users/ouxianxing/Documents/.agent-worktrees/rafii-openui-a-integration-20261008` at `3da806f0` (branch `claude/rafii-openui-production-20261008`)
**Packages inspected (unpacked tarballs, not installed):**

| Package | Version | Path (`$P` below = `/Users/ouxianxing/Documents/.agent-worktrees/openui-probe-20261008`) |
|---|---|---|
| `@openuidev/react-lang` | 0.3.2 | `$P/openuidev-react-lang-0.3.2/package` |
| `@openuidev/lang-core` | 0.3.2 | `$P/openuidev-lang-core-0.3.2/package` |
| `@openuidev/observability` | 0.0.4 | `$P/openuidev-observability-0.0.4/package` |
| `@openuidev/devtools` | 0.2.2 | `$P/openuidev-devtools-0.2.2/package` |

**Method:** read `dist/*.d.mts` and the implementation in `dist/*.mjs`, the `postinstall` scripts and the READMEs. Fetched the official docs pages for queries-mutations, defining-components, incremental-editing, telemetry, renderer and reactive-state. Nothing was installed, built or executed.

**Evidence labels:**
- **[CODE]** means I read it in the pinned dist source at the cited file and line.
- **[DOC]** means the official docs or the README say it. Where docs and code disagree, the code wins and I flag the drift.
- **[INF]** means an inference that has not been run. Each one says how to verify it.

File shorthands used below:
- `RL/exp.mjs` = `$P/openuidev-react-lang-0.3.2/package/dist/exports-Cab8UG5o.mjs` (the whole React runtime, 888 lines)
- `RL/exp.d.mts` = `$P/openuidev-react-lang-0.3.2/package/dist/exports-CqIWw0ev.d.mts`
- `RL/index.mjs` = `$P/openuidev-react-lang-0.3.2/package/dist/index.mjs`
- `LC/index.mjs` = `$P/openuidev-lang-core-0.3.2/package/dist/index.mjs` (4499 lines)
- `LC/index.d.mts` = `$P/openuidev-lang-core-0.3.2/package/dist/index.d.mts`
- `LC/shared.mjs` = `$P/openuidev-lang-core-0.3.2/package/dist/shared-Dzgc28Wo.mjs`
- `LC/postinstall.mjs` = `$P/openuidev-lang-core-0.3.2/package/dist/postinstall.mjs`

---

## 0. Headline facts (read this first)

1. **One `toolProvider` serves both `Query()` and `Mutation()`.** It receives only `(toolName, args)`. It gets no effect class, no caller kind (query or mutation), no user-gesture flag, no AbortSignal and no activation context. [CODE] `RL/exp.mjs:754-765`, `LC/index.mjs:4020`, `LC/index.mjs:4190`. **Native Mutation therefore cannot be safely intercepted in 0.3.2.** Any write tool reachable through `toolProvider` can also be called by a generated `Query("writeName")` on mount.
2. **Queries auto-execute** as soon as `isStreaming === false`, on mount and on replay of an old message. They re-fetch whenever their `$var` args change. [CODE] `RL/exp.mjs:390-412`, `LC/index.mjs:4113`. **Mutations never auto-execute.** They are only *registered* (`LC/index.mjs:4157-4178`). They fire only from `triggerAction()` with an `ActionPlan` step `{type:"run", refType:"mutation"}` (`RL/exp.mjs:495-499`). `triggerAction` is only ever called by component code.
3. **Refresh interval** is the 4th positional `Query` arg, in seconds. It is evaluated at runtime, so it can be an expression, and it has **no minimum**. It becomes a raw `setInterval(n*1000)` with no hidden-tab suspension and no backoff. [CODE] `RL/exp.mjs:400`, `LC/index.mjs:4114-4125`.
4. **Parser validation is JSON-Schema-shallow.** It checks types, enums, required fields, array items and object properties only. Zod refinements (`min`, `max`, `regex`, `url`) are **not enforced**. Runtime-evaluated props (from `$vars`, Query data or expressions) are **never validated**. [CODE] `LC/index.mjs:2067-2314`; AST values are skipped at `:2299`. Every Rafii component must `safeParse` its own props.
5. **The root type is not enforced.** Entry selection prefers statement id `root`, whatever component it is. [CODE] `LC/index.mjs:2790-2796`. Rafii's validator must assert `root.typeName === "RafiiRoot"`.
6. **`mergeStatements` deletes explicitly.** A patch statement whose expression parses to `Null` deletes that statement. A *malformed* RHS such as `x = )` also parses to `Null`, so it deletes too. [CODE] `LC/index.mjs:3259-3265`; the Null fallback is at `:1581-1582`. This differs from the docs, which say "direct deletion isn't performed".
7. **Observability leaks raw source by default.** Every `<Renderer>` publishes full raw `response` text and errors to a **global** in-page bus (`Symbol.for("openui.observability")`) unless `publishObservability={false}`. The default is `publish = true`. [CODE] `RL/exp.mjs:280-316`, `$P/openuidev-observability-0.0.4/package/dist/index.mjs:56-58`.
8. **Devtools in dev loads unpinned remote JS.** Under `next dev` (NODE_ENV=development), react-lang auto-mounts devtools, which `import()`s remote JS from `https://cdn.jsdelivr.net/npm/@openuidev/devtools@0/dist/devtools.browser.js?t=…`. [CODE] `RL/index.mjs:16-42`, `$P/openuidev-devtools-0.2.2/package/dist/index.mjs:21-27,45-71`. Production builds dead-code-eliminate this (dot-form `process.env.NODE_ENV`).
9. **Install telemetry is ON by default** (`postinstall` sends to PostHog). Disable with `OPENUI_TELEMETRY_DISABLED=1` or `DO_NOT_TRACK=1` (value `"1"` or case-insensitive `"true"`). Runtime telemetry is **off** unless `OPENUI_RUNTIME_TELEMETRY_ENABLED` is truthy, and the disable flags override it. Runtime telemetry is server-side only. [CODE] `LC/shared.mjs:9-18`, `LC/postinstall.mjs:40-92`, `LC/index.mjs:199-293`.
10. **There is no `"use client"` directive in react-lang.** It uses `createContext`, `useSyncExternalStore` and `useInsertionEffect` at module level. Every importer must be a Client Component. `@openuidev/lang-core` has no React and is safe for the server-side parser adapter. [CODE] grep finds `"use client"` only in `devtools/dist/index.mjs:1`.

---

## 1. Package graph, peers, install facts

[CODE] package.json files:

- `@openuidev/react-lang@0.3.2`
  - Dependencies: `@openuidev/lang-core ^0.3.2`, `@openuidev/observability ^0.0.4` (a caret on 0.0.x is effectively exact), `@openuidev/devtools ^0.2.2`. Devtools is a **runtime dependency**, not a devDependency.
  - Peers: `react *`, `react-dom *` (optional), `zod ^3.25.0 || ^4.0.0`, `@modelcontextprotocol/sdk >=1.0.0` (optional).
  - `sideEffects: ["./dist/index.mjs","./dist/index.cjs",…]` keeps the devtools bootstrap side effect.
  - Exports: an `import` and a `require` (CJS) build, plus a `react-native` condition. The CJS build means the repo's `node --test *.test.cjs` style tests can `require()` it.
- `@openuidev/lang-core@0.3.2`
  - Dependency: `ci-info ^4.4.0`, used by postinstall and runtime telemetry.
  - Peers: `zod ^3.25 || ^4`, `@modelcontextprotocol/sdk` (optional).
  - `scripts.postinstall: "node ./postinstall.cjs"`.
  - Subpath `./cloud` provides `artifactTool()`, which is OpenUI Cloud only. **Do not use it.**
- `@openuidev/observability@0.0.4`: no dependencies. An in-memory event bus.
- `@openuidev/devtools@0.2.2`
  - Dependency: `lucide-react ^0.575.0`. Rafii does not currently depend on lucide-react; it uses `@tabler/icons-react`, so this adds a package to the lockfile.
  - Peers: `@openuidev/observability >=0.0.4 <0.1.0`, `@openuidev/react-lang >=0.3.0 <0.4.0` (optional), react `^18.3.1 || ^19`, react-dom.

Rafii side, from `web/package.json` and `web/package-lock.json` in the worktree:
- next `16.3.8`, react/react-dom `19.2.4`, zod range `^4.3.6`, which the lockfile resolves to **zod 4.6.5** (`web/package-lock.json:6775-6777`).
- Node `24.x`, npm `11.12.1`.
- `@modelcontextprotocol/sdk` is not present. **Do not add it.**
- No existing `@openuidev/*` usage under `web/src`.

Zod compatibility:
- [CODE] react-lang types import `z` from `"zod/v4"` and `$ZodObject` from `"zod/v4/core"` (`RL/exp.d.mts:4-5`). lang-core imports `object` from `"zod/v4"` and `* as z` from `"zod/v4/core"` (`LC/index.mjs:2-3`).
- `assertV4Schema` throws for Zod 3 schemas (`LC/index.mjs:1138-1140`).
- **Zod v4 is required.** Rafii's `import { z } from "zod"` (v4 classic) is correct. [INF] zod 4.6.5 still ships the `zod/v4` and `zod/v4/core` subpaths. Verify with `node -e "require.resolve('zod/v4/core')"` in the cloud install job.

**Pinning recommendation (A owns lockfile):**
- Add exact `"@openuidev/react-lang": "0.3.2"` and `"@openuidev/lang-core": "0.3.2"` as direct dependencies. lang-core is needed directly by the Node parser adapter, and pinning it forces dedupe to 0.3.2.
- If npm resolves another 0.3.x of lang-core, add an npm `overrides` entry. Two lang-core copies would break the module-scoped `WeakMap` schema tags (`LC/index.mjs:1129`) and the reactive `WeakSet` (`:1118`) that react-lang relies on.
- Install with `OPENUI_TELEMETRY_DISABLED=1` set in the environment (see §11).

---

## 2. Component definition API

### 2.1 Signatures

[CODE] `RL/exp.d.mts:13-19` (React wrapper):

```ts
declare function defineComponent<T extends $ZodObject>(config: {
  name: string; props: T; description: string;
  component: ComponentRenderer<z.infer<T>>;          // React.FC<{ props, renderNode, statementId? }>
}): DefinedComponent<T>;
declare function createLibrary(input: LibraryDefinition): Library;
// LibraryDefinition = { components: DefinedComponent[]; componentGroups?: {name, components: string[], notes?: string[]}[]; root?: string; id?: string }
```

Implementation:
- [CODE] `RL/exp.mjs:37-44`. react-lang's `createLibrary` calls lang-core's `createLibrary`. When `process.env["NODE_ENV"] !== "production"` it then calls `publishLibrary()`, which stores the live library on `globalThis[Symbol.for("openui.devtools.libraries")]` and emits `observability.info({kind:"react-lang:library", components:[names]})`.
- [CODE] lang-core `defineComponent` (`LC/index.mjs:1146-1153`): asserts Zod v4, then `schemaIdTags.set(props, name)`. It returns `{...config, ref: config.props}`, so **`.ref` is the same Zod object** as `props`.
- [CODE] lang-core `createLibrary` (`LC/index.mjs:1285-1334`):
  - Registers each component's `props` in a `z.registry()` with `{id: name}`.
  - Throws if `root` is not a component name.
  - Returns `{components, componentGroups, root, id, __libraryId (random UUID), prompt(opts), toSpec(), toJSONSchema()}`.
  - `toJSONSchema()` is `z.toJSONSchema(object({Name: props,…}), {metadata: reg})`, with each `$defs[Name].description` set to the component description (`:1324-1332`).

`ComponentRenderProps`:
- [CODE] `LC/index.d.mts:474-479` gives `{ props: P; renderNode: (value) => ReactNode; statementId?: string }`.
- **README drift:** the react-lang README example destructures `({ name, mood })` directly. That is wrong for 0.3.2. Use `({ props })`.

### 2.2 Positional props, groups, subsets

- **Positional order = Zod object key order.**
  - [CODE] `buildSignature` uses `Object.entries(shape)` (`LC/index.mjs:1253-1266`).
  - The parser maps args by `Object.keys(def.properties)` of the JSON Schema (`:3069-3086`), then by index (`:2515-2522`).
  - Excess args produce `excess-args` (`:2523-2527`).
  - Optional means a Zod `optional`, `default` or `nullable` wrapper (`:1160-1163`).
  - A JSON-Schema `default` is substituted when a param is missing or null (`:2531-2536`).
  - [DOC] "Required props first, optional props last."
- **Component names must start with A–Z** and be ASCII `[A-Za-z_][A-Za-z0-9_]*`. A lowercase-initial word lexes as an `Ident`, which becomes a reference, not a call. [CODE] `LC/index.mjs:2028-2049`, `:2044`.
- **Component names must not collide with builtins or reserved calls:** `Count, First, Last, Sum, Avg, Min, Max, Sort, Filter, Round, Abs, Floor, Ceil, Each, Action, Run, ToAssistant, OpenUrl, Set, Reset, Query, Mutation`.
  - [CODE] `LC/index.mjs:316-471`.
  - In `parsePrefix`, a PascalCase name that `isBuiltin` (other than `Action`) followed by `(` is **not** parsed as a component (`:1535-1543`).
  - So a component called `Filter` or `Sort` silently breaks. Use names like `FilterBar` and `SortControl`.
- **`componentGroups` only organize prompt headings.** The `### <group>` headings list member signatures followed by `notes` lines. Components not in any group are listed under `### Other`. [CODE] `LC/index.mjs:987-1007`. **There is no subset parameter.** Every component in the passed spec is printed.
  - To prompt a per-journey subset, filter `library.toSpec()` (`components` and `componentGroups[].components`) before calling `generateSystemPrompt` (§3).
  - Or create a separate library per group.
  - Either way, children referenced via `.ref` must be included. Otherwise `z.toJSONSchema` inlines them and the parser reports `unknown-component`. A build-time closure check is required [INF].
- **Child composition:** `z.array(Child.ref)` produces `$ref: "#/$defs/Child"`. Unions of refs produce `anyOf`, which the parser treats as component slots. [CODE] `LC/index.mjs:2196-2204`. [DOC] same idiom.

### 2.3 Action props and reactive props

- **Action props:** tag a `z.any()` with `tagSchemaId(schema, "ActionExpression")`. The prompt then shows `action?: ActionExpression` and includes the Action section. [CODE] `LC/index.mjs:1021`, `:975-984`. [DOC] defining-components.
  - At parse time the `Action([...])` argument is an AST node, so schema validation skips it (`LC/index.mjs:2299`).
  - At render time it evaluates to `ActionPlan {steps: ActionStep[]}` (`:3605-3610`).
- **Reactive props:** `reactive(z.string().optional())` marks the schema in a WeakSet (`RL/exp.mjs:803-806`, `LC/index.mjs:1118-1126`).
  - The prompt shows `$binding<string>` (`LC/index.mjs:1206-1211`).
  - At render, a `$var` passed to a reactive prop becomes `ReactiveAssign {__reactive:"assign", target:"$var", expr:$value}` (`LC/index.mjs:3457-3464`, `:3780-3787`).
  - `useStateField(name, props.value)` turns it into `{value, setValue, isReactive:true}`, and `setValue` writes the store (`LC/index.mjs:4281-4296`).
  - A non-reactive prop given a `$var` receives the current value (`:3465`, `:3791`).

---

## 3. Prompt generation

[CODE] Signatures:
- `generateSystemPrompt(spec: {library: LibrarySpec, promptOptions?: SystemPromptOptions, cloud?: false} | {cloud: true, …})`. A deprecated overload accepts a `PromptSpec` (`LC/index.d.mts:435-448`).
- `LibrarySpec = {id?, root?, components: Record<name,{signature, description?}>, componentGroups?, schema?}`. It is what `library.toSpec()` returns.
- `generatePrompt(spec)` is deprecated, but `library.prompt(opts)` uses it.
- Implementation at `LC/index.mjs:1094-1108`. **`cloud: true` emits a `]]>openui:config` block for OpenUI Cloud. Never use it** (`:588-621`).

Exact output order (`LC/index.mjs:1015-1093`), with flag defaults `toolCalls = spec.toolCalls ?? !!tools.length`, `bindings = spec.bindings ?? toolCalls`, `supportsExpressions = toolCalls || bindings`:

1. `preamble`. The default `PREAMBLE` says: "You are an AI assistant that responds using openui-lang … Your ENTIRE response must be valid openui-lang code — no markdown" (`:668`).
2. `## Syntax Rules` (`:669-686`): one statement per line `identifier = Expression`; `root = <Root>(...)` required; positional args only ("colon syntax … silently breaks"); every non-root var must be referenced. With bindings: `$var` declaration rule. With expressions: concat, member access (array pluck), index, arithmetic, comparison, logical and ternary rules.
3. `## Component Signatures` (`:969-1013`), grouped as in §2.2. Adds the ActionExpression and `$binding<type>` explanations when relevant.
4. `## Built-in Functions` if expressions are on (`:687-704`): `@Count @First @Last @Sum @Avg @Min @Max @Sort @Filter @Round @Abs @Floor @Ceil @Each`.
5. If `toolCalls`: `## Query — Live Data Fetching` (`:705-722`) and `## Mutation — Write Operations` (`:723-739`).
6. If any signature uses ActionExpression: `## Action — Button Behavior` (`:740-769`). Steps: `@Run` only if toolCalls; `@ToAssistant`, `@OpenUrl`; `@Set` and `@Reset` if bindings. It also says "Buttons without an explicit Action prop automatically send their label to the assistant."
7. If toolCalls && bindings: `## Interactive Filters` + `## Forms` (`:770-811`). This references Select/FormControl/Input from OpenUI's own UI kit, which Rafii does not use.
8. If toolCalls: `## Data Workflow` (`:884-914`). It says: "FIRST: Call the most relevant tool to inspect the real data shape before generating code". The Rafii Presenter has no tools, so this does not apply.
9. If `tools` given: `## Available Tools` (`:942-968`). It includes default-shape hints and the sentence **"…If the user asks for functionality that doesn't match any available tool, use realistic mock data instead of fabricating a tool call."** (`:966`). **This contradicts Rafii grounding rules.**
10. `## Hoisting & Streaming (CRITICAL)` (`:836-857`): root first, then `$vars`, then Queries, then components, then data.
11. `## Examples` from `examples + toolExamples`.
12. `## Edit Mode` if `editMode` (`:812-835`): "same name = replace, new name = append"; delete by re-declaring the parent; patch size guide.
13. `## Inline Mode` if `inlineMode` (`:858-883`). Not wanted for Rafii.
14. `## Important Rules` / `## Final Verification` (`:915-926`).
15. `additionalRules`, each emitted as `- <rule>` (`:1088-1091`).

Runtime telemetry hook: `recordSystemPromptGeneration` returns immediately unless the server env opts in (`:199-211`).

**Recommended Rafii prompt assembly** (decision D3). Build it at asset-generation time in Node:

```ts
import { generateSystemPrompt, type LibrarySpec } from '@openuidev/lang-core';

function subsetSpec(full: LibrarySpec, allowed: ReadonlySet<string>): LibrarySpec {
  return {
    id: full.id, root: full.root,
    components: Object.fromEntries(Object.entries(full.components).filter(([n]) => allowed.has(n))),
    componentGroups: full.componentGroups
      ?.map((g) => ({ ...g, components: g.components.filter((c) => allowed.has(c)) }))
      .filter((g) => g.components.length > 0),
  };
}

const base = generateSystemPrompt({
  library: subsetSpec(consumerSpec, journeyComponents.J06),
  promptOptions: {
    toolCalls: false,           // suppress OpenUI's Query/Mutation/Data-Workflow/mock-data text
    bindings: true,             // keep $vars, expressions, builtins, @Set/@Reset docs
    editMode: mode === 'patch',
    preamble: RAFII_PRESENTER_PREAMBLE,
    examples: JOURNEY_EXAMPLES.J06,
  },
});
const prompt = `${base}\n\n${RAFII_BINDINGS_SECTION}`; // Rafii-authored: exact read-binding names + arg schema,
// `name = Query("<binding>", {k: $var|literal}, null)`, optional literal refresh >= 30,
// `@Run(queryRef)` for manual refresh, NO Mutation, ActionButton(actionId) for writes,
// "if no binding fits, render EmptyState — never invent or mock data".
// promptHash = sha256(prompt)
```

The parser and runtime support Query and `@Run` regardless of prompt flags; the flags only change the prompt text. [CODE] `parse()` takes no flags (`LC/index.mjs:2946`).

---

## 4. Parser API

### 4.1 Signatures

[CODE] `LC/index.d.mts:559-595`; implementation at `LC/index.mjs:2679-3117`:

```ts
createParser(schema: LibraryJSONSchema, rootName?: string): { parse(input: string): ParseResult }
createStreamingParser(schema: LibraryJSONSchema, rootName?: string): {
  push(chunk: string): ParseResult;     // append
  set(fullText: string): ParseResult;   // diff vs buffer; resets if not a prefix-extension (LC/index.mjs:3060-3065)
  getResult(): ParseResult;
}
parse(input: string, cat: ParamMap, rootName?: string): ParseResult   // low-level; ParamMap builder (compileSchema) is NOT exported
```

- **README drift:** the react-lang README says `createParser(library)`. The real argument is `library.toJSONSchema()`. The README also mentions an error `type: "validation"` discriminant that does not exist in 0.3.2.
- Telemetry: `createParser().parse` has a sampled runtime-telemetry hook that is off unless opted in (`LC/index.mjs:3097-3110`). The low-level `parse()` and the streaming parser have none.
- Low-level helpers are also exported: `tokenize`, `split`, `autoClose`, `parseExpression`, `walkAST`, `isASTNode`, `evaluate`, `evaluateElementProps`, `createStore`, `createQueryManager`, `jsonToOpenUI`, `mergeStatements`, `enrichErrors` (deprecated), `BUILTINS`, `ACTION_STEPS`, `isBuiltin` (`LC/index.d.mts:1032`).

### 4.2 `ParseResult` shape

[CODE] `LC/index.d.mts:348-368`:

```ts
{ root: ElementNode | null;                               // {type:"element", statementId?, typeName, props, partial, hasDynamicProps?}
  meta: { incomplete: boolean; unresolved: string[]; orphaned: string[]; statementCount: number; errors: ValidationError[] };
  stateDeclarations: Record<"$name", unknown>;            // materialized defaults; auto-declared $vars → null
  queryStatements: QueryStatementInfo[];                  // {statementId, toolAST, argsAST, defaultsAST, refreshAST, deps?: string[], complete}
  mutationStatements: MutationStatementInfo[] }           // {statementId, toolAST, argsAST}
```

`ValidationError = {code, component, path (JSON pointer), message, statementId?}`.

Error codes:
- `ValidationErrorCode = "missing-required" | "null-required" | "unknown-component" | "inline-reserved" | "excess-args" | "type-mismatch"` (`LC/index.d.mts:203`).
- Runtime `OpenUIErrorCode` adds `"runtime-error" | "render-error" | "parse-exception" | "parse-failed" | "tool-not-found" | "tool-error" | "mcp-error"` (`:232`).
- `OpenUIError = {source: "parser"|"runtime"|"query"|"mutation", code, message, statementId?, component?, path?, toolName?, hint?}` (`:241-258`).

### 4.3 Pipeline semantics

[CODE] `parse()` at `LC/index.mjs:2946-2960`:

1. `preprocess` = `stripComments(stripFences(trim))` (`:2936`).
   - `stripFences` extracts the contents of ``` fences if any exist, dropping text outside them (`:2851-2910`). It is aware of double-quoted strings only.
   - `stripComments` removes `//` and `#` to end of line outside `"` or `'` strings (`:2912-2934`).
2. `autoClose` closes unbalanced strings and brackets and sets `wasIncomplete` (`:2573-2614`).
3. `tokenize`:
   - Strings: double-quoted strings go through `JSON.parse`, so escapes and `\u` work and CJK and emoji are fine. Single-quoted strings are also supported.
   - `$name` is a StateVar; `@Name` is a BuiltinCall (`:1793-2065`).
   - Unknown characters are skipped silently (`:2061`).
4. `split` turns the token stream into `id = expr` statements. Lines without `=` or without an identifier on the left are **silently skipped** (`:2626-2677`).
5. `parseExpression` is a Pratt parser. An unknown prefix token yields `{k:"Null"}` (`:1581-1582`). Object keys use `key: value`.
6. `classifyStatement` (`:2711-2744`):
   - `Query(...)` becomes kind `query`, with deps = the StateRefs inside the 2nd arg.
   - `Mutation(...)` becomes kind `mutation`.
   - `$id = …` becomes kind `state`.
   - Anything else becomes kind `value`.
   - **Duplicate ids: last definition wins** (`Map.set`, `:2955-2956`).
7. **Root detection** (`pickEntryId`, `:2790-2796`), in order:
   1. A statement named `root`.
   2. A statement named `rootName`.
   3. The first component statement whose component is `rootName`.
   4. The first component statement.
   5. The first statement.

   It does **not** require the root's component type to be the library root.
8. `materializeValue` (`:2474-2566`):
   - Resolves refs and detects cycles; cycles and undefined names become `unresolved`.
   - Maps positional args to props and validates them against the JSON Schema (§0.4).
   - **Drops a component (null) when a required param is missing or null and has no default.** This happens even while streaming (`:2528-2544`), which is what makes progressive reveal work.
   - Unknown component: error plus null (`:2546-2551`).
   - `Query` or `Mutation` used inline: `inline-reserved` plus null (`:2507-2510`).
   - A ref to a Query or Mutation statement becomes `RuntimeRef{refType}` (`:2349-2353`).
   - Array elements that are unresolved or dropped components are removed (`:2482-2490`).
9. `meta.orphaned` = value statements not reachable from root. State, Query and Mutation statements are excluded (`:2804-2809`).
10. **Incomplete handling:**
    - `meta.incomplete = wasIncomplete`, meaning `autoClose` had to close something.
    - In the streaming parser, completed lines (split at newlines at depth 0) are cached. Only the trailing pending statement is re-tokenized each push (`:2961-3046`).
    - While partial, enum checks and required *object keys* are deferred (`:2223`, `:2271`).
    - **`QueryStatementInfo.complete` is hard-coded `true` in 0.3.2** (`:2765`), so the runtime's `!node.complete` guard (`:4091`) is moot.

### 4.4 Cost model

Each streaming `push`/`set` rebuilds the full result, re-materializing the whole tree, so total work is O(n²) over a stream. [CODE] `:3025-3046`. [INF] This should be fine at the 128 KiB / 512-statement caps, but G17 must measure it.

### 4.5 Server validator recipe (C owns, A wires; `validate_and_merge_ui`)

Uses lang-core only, with no React import:

```ts
import { createParser, mergeStatements, tokenize, split, autoClose, walkAST, type ElementNode, type ParseResult } from '@openuidev/lang-core';
import consumerSchema from './generated/consumer.schema.json' with { type: 'json' };
const parser = createParser(consumerSchema, 'RafiiRoot');

export function validateAndMergeUi(base: string | null, candidate: string, mode: 'generate' | 'patch', policy: UiPolicy) {
  const limit = mode === 'patch' ? 32 * 1024 : 128 * 1024;
  if (Buffer.byteLength(candidate, 'utf8') > limit) return reject('source_too_large');
  if (maxBracketDepth(candidate) > 64) return reject('nesting_too_deep');            // parser is recursive; pre-scan before parse
  if (mode === 'patch' && !base) return reject('missing_base');
  let merged: string, result: ParseResult;
  try {
    merged = mode === 'patch' ? mergeStatements(base!, candidate, 'root') : mergeStatements('', candidate, 'root');
    if (Buffer.byteLength(merged, 'utf8') > 128 * 1024) return reject('source_too_large');
    result = parser.parse(merged);
  } catch { return reject('parse_exception'); }
  const errs: string[] = [];
  if (!result.root || result.root.statementId !== 'root' || result.root.typeName !== 'RafiiRoot') errs.push('root_invalid');
  if (result.meta.incomplete) errs.push('incomplete');
  if (result.meta.errors.length) errs.push(...result.meta.errors.map((e) => `${e.code}:${e.statementId ?? ''}`));
  if (result.meta.unresolved.length) errs.push('unresolved_ref');
  if (result.meta.statementCount > 512 || elementDepth(result.root) > 24) errs.push('bounds');
  if (result.mutationStatements.length) errs.push('mutation_forbidden');               // writes only via ActionButton
  for (const q of result.queryStatements) {
    if (q.toolAST?.k !== 'Str' || !policy.readBindings.has(q.toolAST.v)) errs.push(`query_binding_denied:${q.statementId}`);
    if (q.defaultsAST && q.defaultsAST.k !== 'Null') errs.push(`query_defaults_forbidden:${q.statementId}`);
    if (q.refreshAST && !(q.refreshAST.k === 'Num' && q.refreshAST.v >= 30)) errs.push(`refresh_invalid:${q.statementId}`);
    if (q.argsAST && !argsAreLiteralsOrStateRefs(q.argsAST)) errs.push(`query_args_shape:${q.statementId}`); // no query→query deps (see §6.3)
  }
  for (const typeName of collectTypeNames(result.root)) if (!policy.allowedComponents.has(typeName)) errs.push(`component_denied:${typeName}`);
  for (const id of collectActionIds(result.root)) if (!policy.actionBindings.has(id)) errs.push(`action_denied:${id}`);
  if (mode === 'generate' && hasDuplicateIds(candidate)) errs.push('duplicate_statement');   // split(tokenize(autoClose(x).text))
  if (mode === 'patch') errs.push(...checkDeletions(base!, candidate, merged));             // see §5
  return errs.length ? { accepted: false, errors: errs.slice(0, 20) }
    : { accepted: true, canonicalSource: merged, sourceHash: sha256(merged), statementCount: result.meta.statementCount,
        queryNames: result.queryStatements.map((q) => (q.toolAST as any).v), actionIds: [...collectActionIds(result.root)] };
}
```

Validator notes:
- `ToolBound*` and `ActionButton` must carry their binding and action ids as literal string props so `collectActionIds` can read them statically.
- The client renders exactly `canonicalSource` after `ui.ready`.
- The parser performs **no I/O and no tool execution**. [CODE] parser and materialize contain no `fetch` or callTool. Telemetry I/O happens only when `OPENUI_RUNTIME_TELEMETRY_ENABLED` is truthy, and `OPENUI_TELEMETRY_DISABLED=1` hard-overrides it.

---

## 5. Incremental editing — `mergeStatements`

[CODE] `mergeStatements(existing: string, patch: string, rootId = "root"): string` (`LC/index.d.mts:616`, `LC/index.mjs:3245-3272`).

Behavior:
- Statements are split at newlines at bracket depth 0 (`:3153-3188`).
- The **patch goes through `stripFences`, but neither side has comments stripped** (`:3246-3247`).
- If `existing` has no statements, the result is the patch statements' raw text joined by `\n`. Duplicates are **not** de-duplicated, and the later one wins at parse.
- If the patch has no statements, the result is `existing` unchanged.
- Same name: the patch raw text **replaces the old text in its original position**. A new name is **appended** (`:3258-3269`).
- **`name = null`, or any RHS that parses to `Null`, deletes `name`** (`:3259-3265`). This includes malformed RHS such as `x = )`.
- After merging it **garbage-collects** statements unreachable from `rootId`, by walking `Ref` and `RuntimeRef` from root. `$state` statements are always kept (`:3218-3238`). If no `root` statement exists, GC is skipped.
- Output is raw statement text joined by `\n`. It is **not** library-validated. Always re-parse (§4.5).
- [DOC] "Same name → replace; New name → added; Missing from patch → kept." The docs say deletion is only by unreachability, but the code also deletes on `= null`.

Required Rafii guards for G10:
- `checkDeletions`: for every id in `ids(base) − ids(merged)`, require one of two things:
  - the patch line's tokens are exactly `[Null]`, meaning an intentional delete, or
  - the id became unreachable because its parent was re-declared.

  Flag any deleted statement that hosts dirty form fields so the native warning path runs.
- Reject or repair a patch that adds Query bindings or ActionButton ids outside the manifest. The post-merge checks in §4.5 already cover this.
- `baseSourceHash` must equal `sha256(base)` of the stored canonical source before merging (CAS is owned by F).

Runtime side of a patch (React, same `<Renderer>` instance):
- [CODE] `response` changes, so `sp.set()` resets because the new text is not a prefix and re-parses (`RL/exp.mjs:342-358`).
- The **store persists**. It is created once per Renderer (`:359`).
- The query manager **keeps cache entries with unchanged `cacheKey`, so unchanged queries are not refetched** (`LC/index.mjs:4110-4113`). Removed queries are dropped and their timers cleared (`:4083-4089`).
- **Hazard [CODE + INF]: re-initialization can revert dirty state.**
  - The state-init effect re-runs whenever `JSON(stateDeclarations)` or `JSON(initialState)` changes (`RL/exp.mjs:365-379`).
  - On re-run it **re-applies `initialState`**. Non-`$` keys go through `store.set`; `$` keys are applied as "persisted" over the current values.
  - So if `initialState` still holds the load-time snapshot when a patch adds a `$var`, the user's typed values are reverted.
  - **Mitigation:** keep `initialState` referentially stable between revisions. At the moment an accepted revision is swapped in, pass `initialState = latestSnapshotFromOnStateUpdate`.
  - Must be verified by a C test: type into a field, apply a patch that adds a `$var`, and assert the value is kept.

---

## 6. React runtime — `<Renderer>` and hooks

### 6.1 `RendererProps`

[CODE] `RL/exp.d.mts:22-60`; implementation `RL/exp.mjs:746-794`.

| Prop | Exact semantics (code) | Rafii usage |
|---|---|---|
| `response: string \| null` | Re-parsed on every change through the streaming parser's `set()` (`RL/exp.mjs:344-358`). A parser exception becomes `parse-exception` and the result becomes null. | Pass candidate source while streaming, then exactly `canonicalSource` after `ui.ready`. Enforce the 128 KiB bound before passing. |
| `library` | `useMemo` keys the parser on library identity (`:342`). | Use a **module-level constant**. Use separate consumer and founder libraries. |
| `isStreaming?` | While true: queries are not evaluated (`:391`), mutations are not registered (`:414`), `onError` is held and reset (`:155-162`), and `useSetDefaultValue` is a no-op. It does **not** disable controls by itself. | Pass `generationState !== 'ready'`, so `validating` is also treated as streaming. Components disable actions using `useIsStreaming()`. |
| `onAction?(ActionEvent)` | Receives the custom `{type, params}` path, `continue_conversation` (from `@ToAssistant` or a button without an action), and `open_url` (`:475-549`). | Handle only `continue_conversation` and `open_url`; see §7.3. Ignore any other type. |
| `onStateUpdate?(snapshot)` | Store-subscription callback on every change after init (`:437-445`). Also called from `setFieldValue` when `shouldTriggerSaveCallback` is set, which is the default (`:452-467`). Can fire twice per change. | Debounce 500 ms, whitelist declared fields, 16 KiB cap, then `persist_ui_state`. |
| `initialState?` | Shape `{formName: {field: {value, componentType}}, $var: value}`. `$`-keys become persisted bindings; other keys are set directly (`:365-379`). | Use the persisted `safeState`. See the §5 hazard. |
| `onParseResult?` | Effect on every parse, including during streaming (`:777-779`). | Track `statementCount` and incompleteness; show a native skeleton while `root == null`. |
| `toolProvider?` | A function map or an object with `callTool({name, arguments})` (MCP-like). Normalized into a **stable** wrapper; the ref updates every render (`:752-765`). `null` disables fetches. Switching null↔non-null creates a **new QueryManager**, which re-fetches and resets mutation state (`:360`, `:773`). | Pass the read-only provider (§7.2) **only when `validationState==='accepted'`**. Otherwise pass `null`. |
| `queryLoader?` | `queryLoader ?? <DefaultQueryLoader/>` (`:785`). **Passing `null` still shows the default spinner.** The default has no ARIA. | Pass an accessible Rafii status element. |
| `onError?(OpenUIError[])` | Fires only after streaming, de-duplicated by JSON key, and called with `[]` once errors are resolved. Without it, the renderer `console.warn`s each error (`RL/exp.mjs:148-198`). | Record metrics only. **Do not trigger a paid repair from the client.** Repair is decided server-side. |
| `publishObservability?` | Default publish is true and sends raw `response` and errors to the global bus (`:280-316`). | **Always `false`.** |

Render details [CODE]:
- Returns `null` until a root exists (`:780`).
- Wraps output in `<div style="position:relative">`, with an inner div that dims to opacity .7 while **any** query loads (`:781-793`).
- Injects a `<style>` with `@keyframes openui-spin` into `document.head` (`:726-733`).
- Each element is wrapped in `ElementErrorBoundary`, which shows the **last good children** on render error and reports `render-error` (`:652-681`, `:701-713`).
- `renderDeep(array)` keys children **by index** (`:691`). For stable identity, Rafii containers must map children themselves with `key={child.statementId ?? i}`.
- Strings are rendered as React text, so there is no raw-HTML path.

### 6.2 Hooks

All of these throw outside `<Renderer>`, except `useFormName` and `useFormValidation`. [CODE] `RL/exp.d.mts:79-178`, `RL/exp.mjs:47-145,809-885`.

- `useTriggerAction(): (userMessage, formName?, action?: ActionPlan | {type?, params?}) => void | Promise<void>`
- `useIsStreaming(): boolean`
- `useIsQueryLoading(): boolean`. This is **global**: true if *any* query is loading. There is no per-query hook.
- `useRenderNode(): (value) => ReactNode`
- `useStateField<T>(name, value?) → {name, value, setValue, isReactive}` (`RL/exp.mjs:809-813`)
- `useGetFieldValue(): (formName|undefined, name) => any`
- `useSetFieldValue(): (formName, componentType, name, value, shouldTriggerSaveCallback = true) => void`
- `FormNameContext`, `useFormName()`. Rafii's `Form` component must provide `FormNameContext`.
- `useSetDefaultValue({formName, componentType, name, existingValue, defaultValue, shouldTriggerSaveCallback = false})` writes the default only after streaming and only if unset.
- `FormValidationContext`, `useFormValidation()`, `useCreateFormValidation()` provide `{errors, getFieldError, validateField, registerField, unregisterField, validateForm, clearFieldError}`.
- Validator utilities: `validate`, `builtInValidators`, `parseRules` (`"min:8"` style) and `parseStructuredRules` (`{required:true, minLength:5}`).
- Other exports: `reactive`, `tagSchemaId`, `mergeStatements`, `createParser`, `createStreamingParser`, `generatePrompt`, `generateSystemPrompt`, `extractToolResult`, `ToolNotFoundError`, `BuiltinActionType {ContinueConversation="continue_conversation", OpenUrl="open_url"}`, `ACTION_STEPS {Run:"run", ToAssistant:"continue_conversation", OpenUrl:"open_url", Set:"set", Reset:"reset"}`, `isReactiveAssign`.
- **Not re-exported by react-lang** (import from `@openuidev/lang-core` if needed): `createQueryManager`, `createStore`, `evaluate`, `jsonToOpenUI`, `walkAST`, `tokenize`, `split`, `autoClose`. The `RL/index.mjs:44` export list confirms this.

### 6.3 Query runtime

`createQueryManager` [CODE] `LC/index.mjs:3950-4278`:

- **Cache key** = `toolName::stableStringify(args)::deps` (`:3946-3949`). De-duplication is **per Renderer instance only**.
- **Fetch triggers:**
  - Mount after streaming.
  - Any store change that changes evaluated args. The effect depends on `storeSnapshot` (`RL/exp.mjs:406-412`).
  - `@Run(queryRef)`, which goes through `invalidate` (`:4147-4156`).
  - The refresh interval.

  The effect does **not** depend on `querySnapshot`. So **a Query whose args reference another Query's data is not re-evaluated when the first query resolves.** Forbid query→query arg dependencies.
- **Defaults.** Before data arrives, `getResult()` returns `defaults` (3rd arg). During a refetch it returns the previous cacheKey's data (`:4129-4139`). Model-supplied defaults would therefore be displayed as real data. Rafii must require `defaults = null`; see the §4.5 validator.
- **Errors:**
  - `ToolNotFoundError` becomes `tool-not-found`, with a hint listing available tools (`:4037-4045`).
  - `McpToolError` becomes `mcp-error`.
  - Anything else becomes `tool-error` with `err.message`.
  - Every failure is also `console.error`ed (`:4062`). Sentry breadcrumbs may capture that console output [INF]. **Throw only sanitized messages.**
- **No cancellation.** `callTool` receives no signal. `dispose()` bumps `generation` and ignores late results (`:4249-4263`). Superseded fetches are ignored by the cacheKey check (`:4023-4026`).
- **No min interval, no visibility pause, no backoff, no concurrency cap.** All of these must be adapters.
- **Mutation runtime:**
  - `fireMutation` refuses a mutation already `loading` (a local double-click guard only) and calls `toolProvider.callTool(m.toolName, evaluatedArgs)` (`:4179-4235`).
  - `result.status` is `idle`, `loading`, `success` or `error`.
  - The plan halts if a mutation fails (`RL/exp.mjs:499`).

### 6.4 Builtins and the "unknown is not zero" rule

[CODE] `LC/index.mjs:307-433`, `:3495-3509`:
- `toNumber(non-numeric) = 0`.
- `@Avg([]) = 0`.
- `@Sum` coerces nulls to 0.
- `/0` and `%0` return 0.
- `@Filter` uses loose `==`.

**These semantics violate "unknown is not zero"** for analytics (J06/J09). Rule: metrics come pre-computed from D's bounded query results, carrying units, coverage and as-of. Builtins are used only for presentational counts of present rows. Metric components take a binding ref plus a field name and do their own null-aware math.

### 6.5 Expression safety

[CODE]:
- Member and index access read arbitrary keys, including `constructor` and `__proto__` (`:3517-3532`). This is read-only. `Object.fromEntries` creates own properties, and functions render as null.
- There is no write path to prototypes. The store uses a `Map` (`:4307-4361`).
- `@OpenUrl(url)` only produces an `open_url` ActionEvent (`RL/exp.mjs:511-519`). The host must validate the URL.
- `@ToAssistant(message, context)` produces model-authored text (`LC/index.mjs:3621-3629`). Treat it as untrusted.

---

## 7. Safe mutation design and the mandatory negatives (D/C)

### 7.1 Why native Mutation is unusable for writes in 0.3.2

[CODE]:
- `toolProvider.callTool(toolName, args)` is identical for Query and Mutation (`LC/index.mjs:4020` vs `:4190`).
- A Query fires on mount and replay with whatever literal or expression tool name the model wrote (`RL/exp.mjs:397`).
- There is no hook to attach an activation id or a trusted-event check between the click and `callTool`. `triggerAction` is `async` and awaits each step.
- So exposing any write in `toolProvider` would let `w = Query("schedule_apply", {...}, null)` write on mount.

**Decision:** keep native `Mutation` disabled. The validator rejects `mutationStatements.length > 0`, and `toolProvider` contains reads only. This is the "equivalent user-triggered form via Rafii-owned components" path allowed by spec §6.3. Document it as an adapter.

### 7.2 Read-only `toolProvider`

C owns the wrapper; D owns the HTTP bridge to `POST /api/workspaces/{workspaceId}/agent/ui/queries`.

```ts
'use client';
import { ToolNotFoundError, type McpClientLike } from '@/features/agent/generative-ui/core/openui';
export function createReadOnlyToolProvider(ctx: QueryCtx): McpClientLike {
  return {
    async callTool({ name, arguments: args = {} }) {
      const binding = Object.hasOwn(ctx.readBindings, name) ? ctx.readBindings[name] : undefined;   // own-key only
      if (!binding || binding.effectClass !== 'read') throw new ToolNotFoundError(name, Object.keys(ctx.readBindings));
      const key = `${binding.bindingId}:${stableHash(args)}`;
      if (ctx.signal.aborted || !ctx.isVisible()) return wrap(ctx.cache.last(key) ?? staleEnvelope());    // hidden → no network
      await ctx.limiter.admit(binding, key);              // 4 concurrent / 60 per min / 30s min refresh / 300ms search debounce; supersede → AbortError
      const result: UiQueryResultV1 = await ctx.queryUiBinding(
        { artifactId: ctx.artifactId, artifactRevision: ctx.revision, bindingId: binding.bindingId, inputs: args }, ctx.signal);
      ctx.cache.put(key, result); ctx.status.set(binding.bindingId, result.state);   // per-binding status for ToolBound* (no native per-query hook)
      return wrap(result);                                 // denial/unavailable → state:'denied'|'unavailable', NOT thrown (not LLM-fixable)
    },
  };
}
const wrap = (structuredContent: unknown) => ({ content: [], structuredContent });   // extractToolResult prefers structuredContent (LC/index.mjs:3899)
```

Key points:
- Use own-key lookup or the MCP-like shape. A plain object-literal map does `map[toolName]` with prototype lookup (`RL/exp.mjs:762`): `"constructor"` resolves to `Object(args)` and `"toString"` to the prototype function. If a function map is used anyway, create it with `Object.create(null)`.
- Abort on workspace switch, logout or unmount by remounting `<Renderer key={scopeKey+artifactId}>`.

### 7.3 Writes: `ActionButton` → Rafii bridge (not `toolProvider`, not raw `onAction`)

```tsx
const ActionButton = defineComponent({
  name: 'ActionButton',
  description: 'Prepares one server-registered action by id. Shows a native confirmation; never runs on render.',
  props: z.object({ actionId: z.string(), formName: z.string().optional() }),
  component: ({ props, statementId }) => {
    const bridge = useRafiiActionBridge();          // Rafii React context from RafiiGenerativeMessage (outside OpenUI)
    const streaming = useIsStreaming();
    const getField = useGetFieldValue();
    const binding = bridge.binding(props.actionId); // label/effect summary come from the SERVER manifest, not model text
    if (!binding) return <ActionUnavailable />;
    return (
      <button type="button" disabled={streaming || !bridge.writesEnabled /* accepted revision + current binding */}
        onClick={(e) => { if (!e.isTrusted) return;
          bridge.request({ actionId: binding.actionId, controlId: statementId,
                           inputs: bridge.collectDeclaredInputs(binding, props.formName, getField) }); }}>
        {binding.label}
      </button>);
  },
});
// bridge.request → native confirmation sheet (outside generated subtree) → POST …/actions/activate (input_digest)
//   → POST …/actions {idempotencyKey, activationId} → native receipt from executor + re-read (verified only server-side)
```

Generic, non-write buttons forward only sanitized plans:

```tsx
const SAFE = new Set(['set', 'reset', 'continue_conversation', 'open_url']);
function sanitizePlan(a: unknown): ActionPlan {
  const steps = (a && typeof a === 'object' && Array.isArray((a as ActionPlan).steps)) ? (a as ActionPlan).steps : [];
  return { steps: steps.filter((s) => SAFE.has(s.type) || (s.type === 'run' && s.refType === 'query')) };
}
// onClick: triggerAction(label, formName, sanitizePlan(props.action))  — never forward a model-built {type, params} object
```

Why writes do not go through `onAction` (decision D4):
- Any component that forwards a model-supplied object `{type:"rafii.x", params}` to `triggerAction` would reach `onAction` as a custom event (`RL/exp.mjs:478-491`).
- The host's `onAction` should therefore handle only `continue_conversation` and `open_url`:
  - `continue_conversation`: put the model-written `humanFriendlyMessage` into the composer, or send it as a labeled follow-up through the existing chat path. Drop `params.context` unless whitelisted.
  - `open_url`: same-origin allowlist only; reject `javascript:` and `data:`.
- `ActionEvent.formState` is the **entire store snapshot** when no `formName` is given (`RL/exp.mjs:468-474`). Never forward it to the model unfiltered.

### 7.4 Mandatory negative tests (G06)

Fixtures for each:
1. `root = RafiiRoot([t])`, `t = ToolBoundTable(w)`, `w = Query("<write action name>", {}, null)`. The server validator rejects it with `query_binding_denied`. Force-render it client-side anyway: `ToolNotFoundError` is thrown, and the assertion is **zero** requests to `/actions*` and an unchanged DB/audit count.
2. `m = Mutation("schedule_apply", {...})` plus `x = @Run(m)` at top level, plus `root = RafiiRoot([...], Action([@Run(m)]))`. Expect rejection (`mutation_forbidden`). When force-rendered: zero writes on mount, replay and refresh. `@Run` outside a click only *evaluates* to a step object (`LC/index.mjs:3611-3620`).
3. `Query("x" + "_apply", …)` or `Query($tool, …)`. Expect `query_binding_denied` because the tool name is not a literal.
4. Refresh `0.01`, refresh `$fast`, defaults `{total: 0}`. Expect `refresh_invalid` / `query_defaults_forbidden`.
5. Stream truncated mid-Query. The artifact never becomes `accepted`, `toolProvider` stays `null`, and there are zero query calls.
6. A malformed patch `chart = )`. The deletion is flagged and rejected unless intended.

---

## 8. Reactive state, forms and persistence

Store [CODE] `LC/index.mjs:4307-4361`:
- A `Map` with keys `$var` (raw value), `formName` (`{field: {value, componentType}}`) or a bare field name when there is no form.
- `set` skips the update when `Object.is` or shallow-equal holds.
- `initialize(defaults, persisted)`: persisted values are always set; defaults only if absent.

Native mechanics:
- `@Set($v, expr)` and `@Reset($a, $b)` run locally in `triggerAction` (`RL/exp.mjs:520-533`).
- `$var` changes re-run dependent Queries (deps at `LC/index.mjs:2699-2722`).
- Undeclared `$vars` are auto-declared with a null default (`:2776-2779`).
- **No LLM call happens for any of this.** That is native C03.

Form example (Rafii primitive):

```tsx
const TextField = defineComponent({
  name: 'TextField',
  description: 'Single-line input. Bind value to a $variable to use it in queries or other components.',
  props: z.object({ name: z.string(), label: z.string(), rules: z.any().optional(), value: reactive(z.string().optional()) }),
  component: ({ props }) => {
    const field = useStateField<string>(props.name, props.value as any);
    const v = useFormValidation(); const rules = parseStructuredRules(props.rules);
    useEffect(() => v?.registerField(props.name, rules, () => field.value), [v, props.name, rules, field.value]);
    return <label>{safeText(props.label)}<input value={field.value ?? ''} aria-invalid={!!v?.getFieldError(props.name)}
             onChange={(e) => field.setValue(e.target.value)} onBlur={() => v?.validateField(props.name, field.value, rules)} /></label>;
  },
});
```

Rafii's `Form` provides `FormNameContext` plus `FormValidationContext` (from `useCreateFormValidation()`) and calls `validateForm()` before `bridge.request`. Client validation is a UX aid only; D re-validates against the binding's input schema.

---

## 9. Observability and devtools runtime behavior

**`@openuidev/observability`** [CODE] `$P/openuidev-observability-0.0.4/package/dist/index.mjs`:
- A global bus at `globalThis[Symbol.for("openui.observability")]`.
- API: `observability(level, detail)`, `.info`, `.warn`, `.error`, `.listen(levels, fn)`, `.listenAll(fn)`, `toErrorInfo()`.
- **No network and no storage.** Events reach whatever listener registers, including any third-party script on the page.

react-lang emits:
- `react-lang:library` when `createLibrary` runs and `process.env["NODE_ENV"] !== "production"` (`RL/exp.mjs:42`). This uses **bracket** access. [INF] Next/Turbopack may not inline bracket-form env reads in the client bundle; if not, the branch also runs in production. That is harmless (component names only, no network) but should be verified by grepping the built chunk.
- `react-lang:stream` streaming and settled events **with the full `response` text and errors** (`RL/exp.mjs:288-316`), unless `publishObservability={false}`.

**`@openuidev/devtools`** [CODE] `$P/openuidev-devtools-0.2.2/package/dist/index.mjs`:
- `OpenUIDevtools` fetches `https://cdn.jsdelivr.net/npm/@openuidev/devtools@<tag>/dist/devtools.browser.js`. The tag is `0` for auto-mount, with a cache-buster query string. The script is mounted into `document.body` with the host's React (`:21-71`).
- It is gated by `enabled ?? NODE_ENV !== "production"`.
- Auto-mount comes from `RL/index.mjs:16-42`. It is guarded by dot-form `process.env.NODE_ENV === "development"`, so it is dead in production builds, and by `globalThis[Symbol.for("openui.devtools.autoMount")]`.
- The local copy of the browser bundle (183 KB) contains no `fetch(` calls, only docs links and `localStorage` settings. The CDN `@0` copy is unpinned and may differ.
- Rafii has no global CSP; vercel.json sets one only for `/sw.js`. So the dev import would succeed.

**Required:**
- `publishObservability={false}` on every Renderer.
- A single facade module that sets the auto-mount opt-out flag *before* importing react-lang:

```ts
// web/src/features/agent/generative-ui/core/openui-optout.ts
(globalThis as Record<symbol, unknown>)[Symbol.for('openui.devtools.autoMount')] = true;
// web/src/features/agent/generative-ui/core/openui.ts  ('use client'; the ONLY file that imports @openuidev/react-lang)
import './openui-optout';            // ESM evaluates imports in order → flag set before react-lang's top-level check
export * from '@openuidev/react-lang';
```

- An oxlint or CI rule banning direct `@openuidev/react-lang` imports elsewhere.
- A production-bundle grep showing `cdn.jsdelivr.net/npm/@openuidev/devtools` is absent.
- Optionally (A-owned shared config): `turbopack.resolveAlias` mapping `@openuidev/devtools` to an empty stub.

---

## 10. SSR / client boundary and Next 16 notes

- [CODE] react-lang has no `"use client"`, and its module top level calls `createContext` (`RL/exp.mjs:47`, `:111`, `:816`). Every importing file (library, renderer, components) must be a `'use client'` module. The existing chat files already are; for example `web/src/features/agent/conversation-view.tsx:1`.
- The parser adapter, prompt generator and asset build use **`@openuidev/lang-core` only**, which has no React and no DOM.
  - `detectRuntime` treats Node, Edge, Bun and Deno as servers (`LC/index.mjs:60-86`).
  - Do not put the Node adapter under `/api/*`, because `vercel.json` routes `/api/*` to Python. A must choose a precise authenticated Next route (decision D6).
- Single source of truth (decision D2):
  - `component-specs.ts` holds names, descriptions and Zod props, with no React and only erasable TS syntax, so Node 24 can strip types natively.
  - The generator script uses lang-core `defineComponent`/`createLibrary` with `component: null` to emit `consumer.schema.json`, `consumer.spec.json`, the per-journey prompts and the hashes.
  - `library.tsx` attaches React renderers to the *same* spec objects. Prompt and schema identity is the same as long as names, props and descriptions are identical.
  - The founder library is a separate module and chunk.
- `compiler.removeConsole` is on in production builds (`web/next.config.ts`), so the OpenUI `console.warn`/`console.error` calls are likely stripped in app code. [INF] Whether this applies to `node_modules` is unverified; do not rely on it.

---

## 11. Telemetry: install and runtime

[CODE] `LC/shared.mjs:1-18`, `LC/postinstall.mjs`, `$P/openuidev-lang-core-0.3.2/package/postinstall.cjs`:

- **Install (postinstall), default ON.**
  - Sends to PostHog. The default host is a CloudFront domain; override with `OPENUI_POSTHOG_HOST`. A public project key is hard-coded; override with `OPENUI_POSTHOG_KEY`.
  - Payload: a random distinct id, a salted SHA-256 project id derived from the git origin / `REPOSITORY_URL` / install root, plus lang-core, Node, OS, architecture, package-manager, CI and Docker info.
  - It writes `$XDG_CONFIG_HOME or ~/.config/openui/telemetry.json` (mode 0600) and prints a stderr notice.
  - It runs `git config --get remote.origin.url`.
  - **`isTelemetryDisabled` is checked first** (`LC/postinstall.mjs:42`). When disabled, there is no file, no git call and no network.
  - Disable names: **`OPENUI_TELEMETRY_DISABLED`** or **`DO_NOT_TRACK`**, with value `"1"` or `"true"` (case-insensitive).
  - `OPENUI_TELEMETRY_DEBUG=1` prints the payload instead of sending, but only when telemetry is not disabled.
- **Runtime, default OFF.**
  - Requires `OPENUI_RUNTIME_TELEMETRY_ENABLED` truthy *and* not disabled (`LC/shared.mjs:16-18`).
  - Server-only. Browsers and workers return early (`LC/index.mjs:60-61,79`).
  - 10% sampled events from `generateSystemPrompt` and `createParser().parse`, carrying counts and hashes only.
  - [DOC] "Browser calls never send runtime telemetry."
- **A must set `OPENUI_TELEMETRY_DISABLED=1`** in:
  - the local install command,
  - every CI and JCB/Depot install job env,
  - the Vercel project env for Production and Preview, at both build time (Vercel runs `npm install` and therefore postinstall) and runtime, as defense in depth for the Node adapter.

  **Never set** `OPENUI_RUNTIME_TELEMETRY_ENABLED`.
- G14 evidence:
  - The install log has no "OpenUI Lang Core sends pseudonymous installation telemetry" notice.
  - `~/.config/openui/telemetry.json` is absent on the runner.
  - The network allowlist shows no request to the PostHog/CloudFront capture host.

---

## 12. Capability matrix C01–C10: native vs Rafii adapter

| ID | Native in 0.3.2 [CODE] | Rafii adapter required |
|---|---|---|
| C01 Dynamic composition | `defineComponent`/`createLibrary`, `generateSystemPrompt`, parser, `Renderer` | Per-journey prompt subsets (no native subset), Rafii prompt section, server validator (root type, allowlists, bounds), consumer/founder library split, hashes and drift CI |
| C02 Progressive rendering | Streaming parser with auto-close; components missing required props are dropped until complete; `ElementErrorBoundary` last-good display | Real SSE transport and UTF-8 `TextDecoder` (B/F); native skeleton while `root == null`; containers keyed by `statementId` (native keys by index); deduplicated aria-live announcements; client size watchdog |
| C03 Reactive state | `$vars`, `reactive()`, `useStateField`, `@Set`/`@Reset`, Query re-fetch on `$var` deps; no model calls | Persistence via `onStateUpdate`/`initialState` (F), whitelist, 16 KiB cap, CAS; patch-time `initialState` hazard (§5) |
| C04 Live queries | `Query()` plus `toolProvider`, per-renderer cache/dedupe, manual `@Run(query)`, refresh interval | Auth/scope through D's `/queries` bridge; read-only allowlist; AbortController; minimum 30 s refresh; hidden/inactive suspension; backoff; concurrency and rate caps; search debounce; per-binding status (no per-query hook); null defaults; no query→query args; as-of envelope; historical-message snapshot mode |
| C05 Forms and mutations | Form validation hooks and validators. `Mutation` exists but **cannot be safely intercepted** | `ActionButton`/`Form` via Rafii bridge, native confirmation, `/actions/activate` + `/actions`, idempotency, re-read receipts (D); native Mutation forbidden by the validator |
| C06 Incremental editing | `mergeStatements` (replace by name, append, `= null` delete, GC); `editMode` prompt; unchanged queries keep cache at runtime | Server merge + validate + CAS (F/A); deletion audit; dirty-state warning; stale-hash conflict; no query/action expansion |
| C07 Rich grounded views | **None.** react-lang ships no UI components. Builtins exist but zero-coerce | All Rafii components (C/E) on Recharts and TanStack Table; null-aware metric math; source/as-of display; prop `safeParse` in every component |
| C08 Persistence and recovery | `initialState`/`onStateUpdate` only | Artifact store, revisions, replay/resume, revoked-source checks, version fallback (F) |
| C09 Surface continuity | None | Same artifact across chat, panel, expanded, mobile and voice (F/C); `speakableSummary` |
| C10 Reliability and operations | Structured `onError` (after-stream, deduped); render error boundary; observability bus | Server-decided bounded repair (B); native fallback; sanitized metrics into existing Sentry; kill switch; `publishObservability=false`; devtools opt-out; telemetry disabled |

---

## 13. Risks and gaps

1. **Native Mutation cannot be intercepted.** It is replaced by `ActionButton` and the bridge. This must be documented honestly as an adapter (spec §6.3 permits it).
2. **The built-in prompt text conflicts with Rafii rules.** The "use realistic mock data", "call the tool first" and Mutation sections conflict with grounding. Use `toolCalls:false` plus a Rafii-authored bindings section and record `promptHash`.
3. **Unvalidated runtime props.** Zod refinements are not enforced and runtime props are never validated. Without component-level `safeParse`, malformed data or XSS-adjacent URL props reach renderers. Validate `href`/`src` schemes in components.
4. **Builtins zero-coerce unknowns.** Violates "unknown is not zero" if used for metrics.
5. **Malformed-RHS deletion** in `mergeStatements` (`x = )` deletes `x`).
6. **Index-keyed children** in `renderDeep` lose focus and selection on insertions unless Rafii containers key by `statementId`.
7. **`initialState` re-apply on declaration change** can revert dirty `$vars` and forms during patches [INF]. A test is required.
8. **No cancellation or visibility logic in QueryManager.** `setInterval` keeps ticking while hidden. To satisfy G18 "no active polling", either unmount Renderers for hidden or collapsed artifacts, or short-circuit in the provider. Network logs are the evidence.
9. **Global query-loading dimming.** Any query dims the whole artifact to opacity .7. This is built-in and cannot be configured, so it affects the reading experience.
10. **Default spinner without ARIA**, and `queryLoader={null}` does not disable it.
11. **Devtools CDN code in dev** and the global observability bus carrying raw DSL: opt out and set `publishObservability={false}`.
12. **Install telemetry** on every `npm install` and every Vercel build unless the env is set.
13. **Possible duplicate lang-core copies** break WeakMap/WeakSet schema tagging. Pin exact versions and dedupe.
14. **`lucide-react@^0.575` added** through devtools. It is install weight only (dead in production).
15. **Docs/README drift** (createParser argument, component props destructuring, error `type`, deletion semantics). Code against this map, not the README.
16. **O(n²) re-parse while streaming and full-tree re-evaluation on every store change** (`RL/exp.mjs:582-615` depends on `storeSnapshot` and `querySnapshot`). G17 local-interaction p95 ≤ 200 ms needs measurement at the 512-statement cap.
17. **`QueryStatementInfo.complete` is always true.** A truncated stream ending with a Query could fire partial args once `isStreaming` is false. Mitigated by passing `toolProvider` only for accepted revisions.

---

## 14. Verification checklist for C's R0 feature probe (cloud job, not the Mac)

Each item is an executable assertion against the installed 0.3.2:

- [ ] `require('@openuidev/lang-core').createParser(schema,'RafiiRoot').parse(src)` returns the documented `ParseResult` keys. Error codes match §4.2.
- [ ] `root = Card(...)` parses with `root.typeName === 'Card'`, proving the validator must check the root type.
- [ ] A component named `Filter` fails to parse as a component.
- [ ] `mergeStatements(base, 'chart = null')` and `mergeStatements(base, 'chart = )')` both remove `chart`. A GC'd orphan is removed. `$x` is kept.
- [ ] A jsdom Renderer test: a `Query` with a write tool name, a throwing `ToolNotFoundError` provider, and `isStreaming` toggling show zero provider calls while streaming and exactly one call after it ends. `Mutation` is never called without a click.
- [ ] The refresh arg `0.5` produces about 2 calls per second (proves the native gap). The provider throttle reduces this to at most 1 per 30 s.
- [ ] `publishObservability` default: a `listenAll` listener receives `detail.response`. With `false`, it receives nothing.
- [ ] Patch preservation: type into a `$var`-bound field, swap `response` to a merged source that adds `$y`, and assert the typed value survives with the §5 mitigation.
- [ ] Re-ordering `Stack` children keeps the focused input when keyed by `statementId`.
- [ ] The install log with `OPENUI_TELEMETRY_DISABLED=1` has no notice and no `~/.config/openui/telemetry.json`.
- [ ] The production `next build` chunk grep finds no `cdn.jsdelivr.net/npm/@openuidev/devtools` and records whether `react-lang:library` code remains.


## 2026-10-09 exact lockfile re-review after PR #137

This addendum reviews the current production OpenUI dependency addition from `a522482e` to `94ca0dbd`; the historical R0 map above remains dated evidence. Current lock SHA256 is `1b300aacc1220cf05699ea08bd92986ebff7c4068fad447be9a0866084f3f0c5`, replacing the pre-OpenUI reviewed hash `c347e642ee841cdcc2ca1a8450c4acc09cd391ea6962735c7b1f31fe6c551504`.

Official npm metadata and independently calculated tarball SHA512 match all six lock entries: direct `@openuidev/lang-core@0.3.2` / `@openuidev/react-lang@0.3.2`; transitive `@openuidev/devtools@0.2.2`, `@openuidev/observability@0.0.4`, `ci-info@4.4.0`, `lucide-react@0.575.0`. No existing package entry changed or was removed. React/React DOM 19.2.4 and Zod 4.6.5 satisfy the peer requirements; the optional MCP SDK is not installed. Registry source metadata: `https://registry.npmjs.org/<package>/<version>` for these exact packages; OpenUI upstream: <https://github.com/thesysdev/openui>.

Fresh inspection of the exact published hashed modules confirms the install-telemetry opt-out, opt-in runtime telemetry, development devtools auto-mount/CDN risk and raw renderer observability described above. Current CI/Depot environment disables installation telemetry before npm ci. App controls are implemented: `core/openui.ts` imports the global devtools opt-out first, `renderer.tsx` passes `publishObservability={false}`, and the trusted validator rejects native Mutation and restricts bounded Query calls to read bindings. Production Vercel environment values were not inspected in this review; no prior production install-telemetry claim is made.

`scripts/cloud-dependency-security.py` retains every prior validator and adds these exact package versions to its locked/installed graph, exact direct OpenUI pins and a required CI telemetry opt-out. The review used bounded Python HTTPS/archive inspection, JSON/Git comparison and AST checks; no dependency installation or local Node execution occurred. JCB `x3kgl2347m` failed at the inherited old hash before source tests. A subsequent shared cloud run must validate the repaired gate, a fresh zero-finding advisory result, native image/worker/formatter checks and application tests. Full byte-verification and source-control review receipt: external task artifact `gates-20261009/dependency-review/REVIEW.md` with `REGISTRY-INTEGRITY.json` and `OPENUI-SOURCE-INTEGRITY.json`.
