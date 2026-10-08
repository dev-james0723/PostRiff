/**
 * Lane C test loader (not a test file itself): loads web/src TypeScript/TSX the way the bundler resolves it, using
 * `typescript.transpileModule` (the repo's node --test pattern; no jsdom, no bundler). `@/` maps to web/src, relative
 * imports resolve extensionless/index files, packages come from web/node_modules. Modules load in this realm, so
 * `instanceof`, WeakMaps and React contexts behave exactly as in the app. `stubs` replaces modules by request string or
 * by repo-relative path (for example the D bridges or `next/navigation`).
 */
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

process.env.OPENUI_TELEMETRY_DISABLED = '1';
process.env.DO_NOT_TRACK = '1';

const WEB = path.join(__dirname, '..');
const SRC = path.join(WEB, 'src');
const requireWeb = Module.createRequire(path.join(WEB, 'package.json'));

function resolveFile(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`cannot resolve ${path.relative(WEB, base)}`);
}

function createLoader({ stubs = {} } = {}) {
  const cache = new Map();
  const stubFor = (request, file) => {
    if (Object.prototype.hasOwnProperty.call(stubs, request)) return { hit: true, value: stubs[request] };
    if (file) {
      const rel = path.relative(WEB, file).split(path.sep).join('/');
      const noExt = rel.replace(/\.(tsx?|cjs|mjs|js)$/, '');
      for (const key of [rel, noExt]) if (Object.prototype.hasOwnProperty.call(stubs, key)) return { hit: true, value: stubs[key] };
    }
    return { hit: false };
  };
  function load(file) {
    const stub = stubFor(null, file);
    if (stub.hit) return stub.value;
    if (cache.has(file)) return cache.get(file).exports;
    const mod = { exports: {} };
    cache.set(file, mod);
    if (file.endsWith('.json')) {
      mod.exports = JSON.parse(fs.readFileSync(file, 'utf8'));
      return mod.exports;
    }
    const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
      fileName: file,
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
        esModuleInterop: true,
      },
    });
    const localRequire = (request) => {
      const direct = stubFor(request, null);
      if (direct.hit) return direct.value;
      if (request.startsWith('@/')) return load(resolveFile(path.join(SRC, request.slice(2))));
      if (request.startsWith('.')) return load(resolveFile(path.join(path.dirname(file), request)));
      if (/\.css$/.test(request)) return {};
      return requireWeb(request);
    };
    const fn = new Function('require', 'module', 'exports', '__filename', '__dirname', outputText);
    fn(localRequire, mod, mod.exports, file, path.dirname(file));
    return mod.exports;
  }
  return {
    load: (rel) => load(resolveFile(path.join(WEB, rel))),
    requireWeb,
  };
}

module.exports = { createLoader, WEB, SRC, requireWeb };
