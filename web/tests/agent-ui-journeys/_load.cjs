/**
 * Test loader for lane E's journey tests (not a test file itself): loads app TS/TSX the way the bundler would — `@/` is
 * web/src, relative imports resolve to .ts/.tsx/index files, JSON is data, packages come from web/node_modules — using
 * `typescript.transpileModule` (the repo's convention; no jsdom/vitest). One module instance per file per loader.
 *
 * `stubs` replaces specific app modules (absolute path without extension → exports) so a component can be rendered
 * with a test double of the OpenUI facade or the bridge context; everything else is the real code.
 */
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..', '..');
const SRC = path.join(WEB, 'src');
const REPO = path.join(WEB, '..');

function resolveFile(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`cannot resolve ${base}`);
}

function stripExt(file) {
  return file.replace(/\.(tsx?|json)$/, '').replace(/[\\/]index$/, '');
}

function createLoader({ stubs = {} } = {}) {
  const cache = new Map();
  const stubbed = new Map(Object.entries(stubs).map(([k, v]) => [stripExt(path.resolve(k)), v]));
  function load(file) {
    const key = stripExt(file);
    if (stubbed.has(key)) return stubbed.get(key);
    if (cache.has(file)) return cache.get(file).exports;
    const mod = { exports: {} };
    cache.set(file, mod);
    if (file.endsWith('.json')) {
      mod.exports = JSON.parse(fs.readFileSync(file, 'utf8'));
      return mod.exports;
    }
    const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      fileName: file,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    });
    const localRequire = (name) => {
      if (name.startsWith('@/')) return loadPath(path.join(SRC, name.slice(2)));
      if (name.startsWith('.')) return loadPath(path.join(path.dirname(file), name));
      return require(require.resolve(name, { paths: [WEB] }));
    };
    new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
    return mod.exports;
  }
  function loadPath(base) {
    const key = stripExt(path.resolve(base));
    if (stubbed.has(key)) return stubbed.get(key);
    return load(resolveFile(base));
  }
  return { load: (rel) => loadPath(path.isAbsolute(rel) ? rel : path.join(WEB, rel)), loadPath };
}

const pkg = (name) => require(require.resolve(name, { paths: [WEB] }));

module.exports = { WEB, SRC, REPO, createLoader, pkg };
