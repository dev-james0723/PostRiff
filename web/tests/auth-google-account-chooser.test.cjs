/** Every Google sign-in asks Google to show its account chooser, so a person signed in to one Google account in the
 *  browser can still pick another after signing out of Rafii (consumer form and founder sign-in alike). */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.resolve(__dirname, '../src');
const FILES = ['components/auth/auth-form.tsx', 'lib/founder/sign-in.ts'];

function googleOAuthCalls(relative) {
  const file = path.join(SRC, relative);
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.ES2022, true,
    relative.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const calls = [];
  const visit = (node) => {
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'signInWithOAuth') {
      const arg = node.arguments[0];
      const props = arg && ts.isObjectLiteralExpression(arg) ? arg.properties : [];
      const prop = (list, name) => list.find((p) => ts.isPropertyAssignment(p) && p.name.getText(source) === name);
      const provider = prop(props, 'provider');
      if (provider && provider.initializer.getText(source).replace(/['"]/g, '') === 'google') {
        const options = prop(props, 'options');
        const query = options && ts.isObjectLiteralExpression(options.initializer) ? prop(options.initializer.properties, 'queryParams') : null;
        const prompt = query && ts.isObjectLiteralExpression(query.initializer) ? prop(query.initializer.properties, 'prompt') : null;
        calls.push(prompt ? prompt.initializer.getText(source).replace(/['"]/g, '') : null);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return calls;
}

for (const relative of FILES) {
  test(`${relative}: Google sign-in shows the account chooser`, () => {
    const prompts = googleOAuthCalls(relative);
    assert.ok(prompts.length > 0, `${relative} has a Google signInWithOAuth call`);
    for (const prompt of prompts) assert.ok(prompt && prompt.split(/\s+/).includes('select_account'), `prompt is '${prompt}'`);
  });
}
