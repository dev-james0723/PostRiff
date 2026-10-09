const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function upgradeInput() {
  const file = path.resolve(__dirname, '../src/features/youtube/creator-view.tsx');
  const text = fs.readFileSync(file, 'utf8');
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const declaration = source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'creatorOAuthInput');
  assert.ok(declaration, 'Execute the production OAuth upgrade input resolver.');
  const printed = ts.createPrinter().printNode(ts.EmitHint.Unspecified, declaration, source);
  const { outputText } = ts.transpileModule(`${printed}\nmodule.exports = creatorOAuthInput;`, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('module', 'exports', outputText)(mod, mod.exports);
  return { resolve: mod.exports, source: text };
}

test('agentic Analytics upgrade preserves the exact selected connection and lane only with explicit consent', () => {
  const { resolve } = upgradeInput();
  const agentic = Object.freeze({ id: 'same-channel-agentic-connection', authorizationLane: 'agentic' });
  assert.throws(() => resolve(agentic, 'analytics', false), /Explicitly approve/);
  assert.deepEqual(resolve(agentic, 'analytics', true), {
    connectionId: agentic.id, authorizationLane: 'agentic', agenticConsent: true
  });
  assert.throws(() => resolve(agentic, 'monetary_analytics', true, true), /Other agentic permissions require their own consent flow/);
  assert.throws(() => resolve(undefined, 'analytics', true), /Select an available/);
  assert.throws(() => resolve({ id: 'unknown', authorizationLane: 'other' }, 'analytics', true), /Reconnect/);
});

test('ordinary Analytics and sensitive upgrades retain their existing client and permission semantics', () => {
  const { resolve, source } = upgradeInput();
  for (const authorizationLane of [undefined, 'standard']) {
    const connection = { id: 'manual-connection', authorizationLane };
    assert.deepEqual(resolve(connection, 'analytics', false), {
      connectionId: connection.id, authorizationLane: 'standard'
    });
    assert.deepEqual(resolve(connection, 'monetary_analytics', false, true), {
      connectionId: connection.id, authorizationLane: 'standard', enableSensitive: true
    });
  }
  assert.match(source, /creatorOAuthInput\(yt.find\(\(c\) => c.id === channel\), feature, agenticAnalyticsConsent, sensitive\)/);
  assert.match(source, /api.oauthStart\(workspaceId, 'youtube', feature, input\)/);
  assert.match(source, /setAgenticAnalyticsConsent\(false\)/);
  assert.match(source, /add read-only YouTube Analytics access to this selected autopilot authorization/);
});
