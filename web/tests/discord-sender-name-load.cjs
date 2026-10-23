/**
 * Loads the app's TypeScript and TSX sources into a node test without a bundler: `.ts` and `.tsx` are transpiled on
 * require, `@/…` resolves to `src/…`, and JSON imports work. Used by the sender-name tests only; node runs each test
 * file in its own process, so the hooks cannot leak into other suites.
 */
const Module = require('node:module');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const root = path.resolve(__dirname, '..');
let installed = false;

function transpile(filename) {
  return ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true
    },
    fileName: filename
  }).outputText;
}

function install() {
  if (installed) return;
  installed = true;
  const resolveFilename = Module._resolveFilename;
  Module._resolveFilename = function (request, parent, ...rest) {
    const mapped = request.startsWith('@/') ? path.join(root, 'src', request.slice(2)) : request;
    return resolveFilename.call(this, mapped, parent, ...rest);
  };
  for (const extension of ['.ts', '.tsx']) {
    Module._extensions[extension] = (loaded, filename) => loaded._compile(transpile(filename), filename);
  }
}

/** `relative` is a path under `web/`, for example `src/lib/channels/discord-sender-name.ts`. */
function load(relative) {
  install();
  return require(path.join(root, relative));
}

module.exports = { load, root };
