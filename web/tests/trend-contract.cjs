/** Offline contract test and canonical JSON Schema exporter. No API/model calls. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
const { z } = require('zod');
function loadTypes() {
  const file = path.join(__dirname, '../src/lib/coworker/trend-types.ts');
  const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const output = { exports: {} };
  new Function('require', 'exports', 'module', js)(require, output.exports, output);
  return output.exports;
}
const t = loadTypes();
function exportSchema() {
  const definitions = {};
  for (const [name, schema] of Object.entries(t)) {
    if (schema instanceof z.ZodType) definitions[name] = z.toJSONSchema(schema, { io: 'input' });
  }
  for (const [name, schema] of Object.entries({
    trends: z.array(t.trendSchema),
    trend: t.trendSchema,
    receipt: t.receiptSchema,
    methodology: t.methodologySchema,
    calibration: t.calibrationSchema,
    language_patterns: z.array(t.languagePatternSchema),
    genome: t.genomeSchema,
    propagation: t.propagationSchema,
    saturation: t.saturationSchema,
    opportunities: z.array(t.opportunitySchema),
    opportunity: t.opportunitySchema,
    watches: z.array(t.watchSchema),
    watch: t.watchSchema,
    lab_run: t.labRunSchema,
    accepted_opportunity: t.acceptedOpportunitySchema
  })) {
    definitions[name + '_response'] = z.toJSONSchema(t.envelopeSchema(schema), { io: 'input' });
  }
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    title: 'Rafii Trust Trend API 1.0',
    $defs: definitions
  };
}
module.exports = { loadTypes, exportSchema };
if (require.main === module) {
  const schema = exportSchema();
  const destination = path.join(
    __dirname,
    '../../docs/design/social-trend-intelligence/api.schema.json'
  );
  if (process.argv.includes('--write-schema'))
    fs.writeFileSync(destination, JSON.stringify(schema, null, 2) + '\n');
  else
    assert.deepEqual(
      JSON.parse(fs.readFileSync(destination, 'utf8')),
      schema,
      'generated JSON Schema is current'
    );
  assert.equal(t.verificationSchema.safeParse('policy_revoked').success, true);
  assert.equal(t.verificationSchema.safeParse('revoked').success, false);
  assert.equal(
    t.labInputSchema.safeParse({
      draft_id: 'd',
      draft_revision: 1,
      opportunity_id: 'o',
      opportunity_revision: 1,
      target_platform: 'bluesky',
      idempotency_key: 'i',
      text: 'must not send draft text'
    }).success,
    false
  );
  assert.equal(
    t.evidenceSchema.safeParse({
      id: 'e',
      display_state: 'restricted',
      reason: 'policy',
      excerpt: 'forbidden',
      url: 'https://example.com'
    }).success,
    false
  );

  console.log(
    'PASS: canonical schema export, precise revocation enum, strict mutation input, restricted evidence projection'
  );
}
