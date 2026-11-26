/**
 * Loads a TypeScript module from web/src inside a node:test file. Node strips the types itself; the hook only adds
 * the `.ts` that the app's bundler resolves for relative imports, so a module split across files loads without a build.
 */
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';

registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (error) {
      if (!/^\.{1,2}\//.test(specifier) || /\.(?:[cm]?[jt]sx?|json)$/.test(specifier)) throw error;
      return nextResolve(`${specifier}.ts`, context);
    }
  }
});

const SRC = new URL('../../../src/', import.meta.url);
const FIXTURES = new URL('./', import.meta.url);

export const loadTs = (path) => import(new URL(path, SRC).href);

/** A fixture as the browser hands it to the parsers: its path inside the export (the platform folder dropped) and its text. */
export function fixture(path) {
  return { name: path.split('/').slice(1).join('/'), text: readFileSync(new URL(path, FIXTURES), 'utf8') };
}
