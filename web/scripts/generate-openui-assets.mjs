#!/usr/bin/env node
/**
 * Rafii Generative UI asset generator (lane C; A-DECISIONS D-A30). Cloud CI only — never run heavy work on a dev Mac.
 *
 *   node web/scripts/generate-openui-assets.mjs --write   regenerate every asset from the component specs
 *   node web/scripts/generate-openui-assets.mjs --check   exit 1 when the committed assets differ (drift check in CI)
 *
 * Inputs (single source): web/src/features/agent/generative-ui/component-specs.ts + library-registry.ts (+ lane E's
 * journey specs through core/journey-module.ts), core/prompt-text.ts, and lane E's journey examples
 * src/postriff_phase2/agent_runtime_v2/generated/journey-examples/<J0x>-*.openui.
 *
 * Outputs:
 *   src/postriff_phase2/agent_runtime_v2/generated/openui-assets.json
 *   src/postriff_phase2/agent_runtime_v2/generated/prompts/<library>-<J0x|all>-<generate|patch>.txt
 *   src/postriff_phase2/agent_runtime_v2/generated/<library>.schema.json
 *   web/src/features/agent/generative-ui/generated/{openui-assets.json,<library>.schema.json}   (browser copy)
 *
 * TypeScript sources are loaded with `typescript.transpileModule` (the repo's web test loader pattern), so `@/` aliases and
 * extensionless imports resolve the way the bundler resolves them. Nothing here talks to the network.
 */
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

process.env.OPENUI_TELEMETRY_DISABLED = '1';
process.env.DO_NOT_TRACK = '1';

const WEB = fileURLToPath(new URL('..', import.meta.url));
const ROOT = path.join(WEB, '..');
const SRC = path.join(WEB, 'src');
const PY_GENERATED = path.join(ROOT, 'src', 'postriff_phase2', 'agent_runtime_v2', 'generated');
const WEB_GENERATED = path.join(SRC, 'features', 'agent', 'generative-ui', 'generated');
const EXAMPLES_DIR = path.join(PY_GENERATED, 'journey-examples');
const requireWeb = createRequire(path.join(WEB, 'package.json'));
const ts = requireWeb('typescript');

const cache = new Map();
function resolveFile(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`cannot resolve ${path.relative(ROOT, base)}`);
}
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} };
  cache.set(file, mod);
  if (file.endsWith('.json')) {
    mod.exports = JSON.parse(readFileSync(file, 'utf8'));
    return mod.exports;
  }
  const { outputText } = ts.transpileModule(readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  });
  const localRequire = (name) => {
    if (name.startsWith('@/')) return load(resolveFile(path.join(SRC, name.slice(2))));
    if (name.startsWith('.')) return load(resolveFile(path.join(path.dirname(file), name)));
    return requireWeb(name);
  };
  // Trusted repository source only (build step), compiled the way the web unit tests load TypeScript.
  vm.compileFunction(outputText, ['require', 'module', 'exports'], { filename: file })(localRequire, mod, mod.exports);
  return mod.exports;
}

const sha256 = (text) => createHash('sha256').update(text, 'utf8').digest('hex');
const json = (value) => `${JSON.stringify(value, null, 2)}\n`;
const packageVersion = (name) => JSON.parse(readFileSync(path.join(WEB, 'node_modules', ...name.split('/'), 'package.json'), 'utf8')).version;

const registry = load(path.join(SRC, 'features/agent/generative-ui/library-registry.ts'));
const prompts = load(path.join(SRC, 'features/agent/generative-ui/core/prompt-text.ts'));
const contracts = load(path.join(SRC, 'lib/agent-runtime/ui-contracts.ts'));
const langCore = requireWeb('@openuidev/lang-core');

function journeyExamples() {
  const byJourney = {};
  if (!existsSync(EXAMPLES_DIR)) return byJourney;
  for (const name of readdirSync(EXAMPLES_DIR).sort()) {
    const match = /^(J0[1-9])-[A-Za-z0-9_-]+\.openui$/.exec(name);
    if (!match) continue;
    (byJourney[match[1]] ??= []).push({ name, source: readFileSync(path.join(EXAMPLES_DIR, name), 'utf8').trim() });
  }
  return byJourney;
}

/** Structural check of an example against its library (the full manifest policy is applied at run time). */
function exampleProblems(library, source, allowed) {
  const parser = langCore.createParser(library.toJSONSchema(), 'RafiiRoot');
  const result = parser.parse(source);
  const problems = [];
  if (!result.root || result.root.statementId !== 'root' || result.root.typeName !== 'RafiiRoot') problems.push('root_invalid');
  if (result.meta.incomplete) problems.push('incomplete');
  for (const e of result.meta.errors) problems.push(`${e.code}:${e.statementId ?? ''}`);
  for (const u of result.meta.unresolved) problems.push(`unresolved:${u}`);
  if (result.mutationStatements.length) problems.push('mutation');
  for (const q of result.queryStatements) {
    if (q.toolAST?.k !== 'Str') problems.push(`query_name:${q.statementId}`);
    if (q.defaultsAST && q.defaultsAST.k !== 'Null') problems.push(`query_defaults:${q.statementId}`);
  }
  const { text } = langCore.autoClose(source);
  for (const stmt of langCore.split(langCore.tokenize(text))) {
    langCore.walkAST(langCore.parseExpression(stmt.tokens), (node) => {
      if (node.k === 'Comp' && !langCore.isBuiltin(node.name) && node.name !== 'Query' && !allowed.has(node.name)) {
        problems.push(`component_outside_journey:${node.name}`);
      }
    });
  }
  return problems;
}

function build() {
  const problems = registry.registryProblems();
  const files = new Map(); // absolute path → text
  const examples = journeyExamples();
  const libraries = {};
  const promptIndex = {};
  const specLibraries = {};
  for (const name of ['consumer', 'founder']) {
    const library = registry.createSpecLibrary(name);
    specLibraries[name] = library;
    const definition = registry.LIBRARY_DEFINITIONS[name];
    const spec = library.toSpec();
    const schema = library.toJSONSchema();
    const schemaFile = `${name}.schema.json`;
    files.set(path.join(PY_GENERATED, schemaFile), json(schema));
    files.set(path.join(WEB_GENERATED, schemaFile), json(schema));
    const fieldHosts = {};
    const rules = {};
    for (const s of definition.specs) {
      if (s.fieldNameProp) fieldHosts[s.name] = s.fieldNameProp;
      if (s.rules) rules[s.name] = { ...s.rules };
    }
    libraries[name] = {
      id: definition.id,
      libraryHash: sha256(registry.libraryHashInput(spec)),
      compatibleLibraryHashes: [...(registry.COMPATIBLE_LIBRARY_HASHES?.[name] ?? [])],
      root: definition.root,
      components: definition.specs.map((s) => s.name),
      groups: Object.fromEntries(definition.groups.map((g) => [g.id, [...g.components]])),
      fieldHosts,
      rules,
      schemaFile,
    };
    // Reference closure: a component whose props reference another component (Tabs → TabItem) needs it in the same prompt.
    const refs = {};
    for (const [component, def] of Object.entries(schema.$defs ?? {})) {
      const found = new Set();
      JSON.stringify(def, (key, value) => {
        if (key === '$ref' && typeof value === 'string') found.add(value.split('/').pop());
        return value;
      });
      refs[component] = [...found].filter((r) => r !== component);
    }
    libraries[name].references = refs;
  }

  const journeys = {};
  for (const journey of contracts.JOURNEYS) {
    const entry = registry.JOURNEY_LIBRARIES[journey];
    journeys[journey] = { library: entry.library, groups: [...entry.groups] };
  }

  const preambleFor = (mode) => (mode === 'patch' ? `${prompts.PRESENTER_PREAMBLE}\n${prompts.PATCH_RULES.join('\n')}` : prompts.PRESENTER_PREAMBLE);
  const targets = [];
  for (const name of ['consumer', 'founder']) {
    const ids = contracts.JOURNEYS.filter((j) => journeys[j].library === name);
    targets.push({ library: name, journey: 'all', groups: registry.LIBRARY_DEFINITIONS[name].groups.map((g) => g.id), journeysCovered: ids });
    for (const journey of ids) targets.push({ library: name, journey, groups: journeys[journey].groups, journeysCovered: [journey] });
  }
  for (const target of targets) {
    const library = specLibraries[target.library];
    const allowed = new Set(registry.groupComponents(target.library, target.groups));
    for (const component of [...allowed]) {
      for (const ref of libraries[target.library].references[component] ?? []) {
        if (!allowed.has(ref)) problems.push(`prompt_closure:${target.library}:${target.journey}:${component}->${ref}`);
      }
    }
    const exampleTexts = [];
    for (const journey of target.journeysCovered) {
      for (const example of examples[journey] ?? []) {
        const issues = exampleProblems(library, example.source, allowed);
        if (issues.length) problems.push(`example:${example.name}:${issues.slice(0, 5).join(',')}`);
        exampleTexts.push(example.source);
      }
    }
    const coreExamples = prompts.CORE_EXAMPLES.filter((source) => !exampleProblems(library, source, allowed).length);
    if (target.library === 'consumer' && target.journey === 'all') {
      prompts.CORE_EXAMPLES.forEach((source, index) => {
        const issues = exampleProblems(library, source, allowed);
        if (issues.length) problems.push(`core_example_${index}:${issues.slice(0, 5).join(',')}`);
      });
    }
    for (const mode of ['generate', 'patch']) {
      const text = langCore.generateSystemPrompt({
        library: registry.subsetSpec(library.toSpec(), allowed),
        promptOptions: {
          toolCalls: false,
          bindings: true,
          editMode: mode === 'patch',
          preamble: preambleFor(mode),
          examples: [...coreExamples, ...exampleTexts.slice(0, 6)],
          additionalRules: prompts.rulesFor(target.library),
        },
      });
      if (/mock data/i.test(text)) problems.push(`prompt_mock_data:${target.library}:${target.journey}:${mode}`);
      if (/\bMutation\(/.test(text.replace(/Never write Mutation/g, ''))) problems.push(`prompt_mutation_section:${target.library}:${target.journey}:${mode}`);
      const file = `prompts/${target.library}-${target.journey}-${mode}.txt`;
      files.set(path.join(PY_GENERATED, file), text.endsWith('\n') ? text : `${text}\n`);
      promptIndex[`${target.library}:${target.journey}:${mode}`] = {
        file,
        promptHash: sha256(text.endsWith('\n') ? text : `${text}\n`),
        components: [...allowed],
      };
    }
  }

  const assets = {
    contractVersion: contracts.CONTRACT_VERSION,
    language: contracts.LANGUAGE,
    languageVersion: packageVersion('@openuidev/lang-core'),
    libraryVersion: registry.LIBRARY_DEFINITIONS.consumer.version,
    packages: {
      '@openuidev/lang-core': packageVersion('@openuidev/lang-core'),
      '@openuidev/react-lang': packageVersion('@openuidev/react-lang'),
    },
    libraryHashAlgorithm: 'sha256(stableJson(library.toSpec()) + "\\n" + contractVersion)',
    promptHashAlgorithm: 'sha256(prompt file text); B records sha256(final prompt) after appending the Rafii bindings section',
    libraries,
    journeys,
    prompts: promptIndex,
  };
  files.set(path.join(PY_GENERATED, 'openui-assets.json'), json(assets));
  files.set(path.join(WEB_GENERATED, 'openui-assets.json'), json(assets));
  return { files, problems };
}

function existing(dir) {
  const out = [];
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name !== 'journey-examples') out.push(...existing(full));
    } else if (/\.(json|txt)$/.test(name)) out.push(full);
  }
  return out;
}

const mode = process.argv.includes('--write') ? 'write' : process.argv.includes('--check') ? 'check' : null;
if (!mode) {
  console.error('usage: generate-openui-assets.mjs --write | --check');
  process.exit(64);
}
const { files, problems } = build();
if (problems.length) {
  for (const problem of problems) console.error(`problem: ${problem}`);
  process.exit(1);
}
const stale = [...existing(PY_GENERATED), ...existing(WEB_GENERATED)].filter((file) => !files.has(file));
if (mode === 'write') {
  for (const [file, text] of files) {
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, text);
  }
  for (const file of stale) rmSync(file);
  console.log(`wrote ${files.size} files, removed ${stale.length} stale`);
} else {
  const drift = [];
  for (const [file, text] of files) {
    if (!existsSync(file)) drift.push(`missing ${path.relative(ROOT, file)}`);
    else if (readFileSync(file, 'utf8') !== text) drift.push(`changed ${path.relative(ROOT, file)}`);
  }
  for (const file of stale) drift.push(`stale ${path.relative(ROOT, file)}`);
  if (drift.length) {
    for (const line of drift) console.error(line);
    console.error(`OpenUI assets drifted from the component specs (${drift.length}); push a commit tagged [agent-ui-assets] and commit the generated files.`);
    process.exit(1);
  }
  console.log(`OpenUI assets match the component specs (${files.size} files)`);
}
