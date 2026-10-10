const test = require('node:test');
const assert = require('node:assert/strict');
const { makeEnvironment, render, textOf, envelope } = require('./_harness.cjs');
const fixture = require('./fixtures/J06-analytics.json');

const evidence = (overrides = {}) => ({
  schema: 'rafii.evidence.v1', workspaceId: 'workspace-a', classification: 'observed', availability: 'available',
  source: { platform: 'Threads', provider: 'threads', entityType: 'provider_post', entityId: 'native-post', connectionId: 'account-a', document: null, href: null },
  collectionPeriod: { start: '2026-10-08T01:00:00Z', end: '2026-10-08T02:00:00Z', basis: 'provider_reading' },
  lastSuccessfulSync: '2026-10-08T02:00:03Z',
  definition: { name: 'views', version: '2026-09', description: 'Native provider views; not unique reach.', unit: 'count' },
  uncertainty: ['The provider reading does not establish causality.'], ...overrides,
});
function metrics() {
  const data = structuredClone(fixture.analytics_posts.partial);
  data.data.workspaceId = 'workspace-a';
  const first = data.data.posts[0];
  first.metrics.views.evidence = evidence();
  first.metrics.likes = { value: null, availability: 'not_supported', evidence: evidence({ availability: 'not_supported', lastSuccessfulSync: null, collectionPeriod: { start: null, end: null, basis: 'provider_reading' } }) };
  return data;
}

test('native metric evidence shows entity, collection period, successful sync, definition and workspace', () => {
  const env = makeEnvironment();
  const { MetricTable } = env.load('components/journeys/analytics');
  const html = render(env, MetricTable, { data: metrics(), metrics: ['views', 'likes'] });
  const text = textOf(html);
  for (const expected of ['Evidence', 'Observed', 'Collection period', 'Last successful sync', 'native-post', 'account-a', 'workspace-a', '2026-09', 'not_supported', 'Not recorded']) assert.ok(text.includes(expected), expected);
  assert.equal((html.match(/data-evidence-mode="v1"/g) || []).length, 2);
  assert.match(html, /dateTime="2026-10-08T02:00:03Z"/i);
  assert.match(text, /Asia\/Hong_Kong/);
  assert.equal(env.requests.length, 0);
});

test('foreign workspace envelope and malformed provenance cannot render', () => {
  const env = makeEnvironment();
  const { MetricTable } = env.load('components/journeys/analytics');
  const data = metrics();
  data.data.posts[0].metrics.views.evidence = evidence({ workspaceId: 'founder-private', source: { ...evidence().source, entityId: 'SECRET-ENTITY' } });
  let html = render(env, MetricTable, { data, metrics: ['views'] });
  assert.doesNotMatch(html, /SECRET-ENTITY|founder-private|data-evidence-mode/);
  data.data.posts[0].metrics.views.evidence.lastSuccessfulSync = 'invented-time';
  html = render(env, MetricTable, { data, metrics: ['views'] });
  assert.doesNotMatch(html, /SECRET-ENTITY|invented-time/);
});

test('FactPack evidence keeps disputed/unverified attribution and reuses safe EvidenceLink', () => {
  const env = makeEnvironment();
  const { DraftEvidence } = env.load('components/journeys/drafts');
  const source = evidence({ availability: 'disputed', source: { ...evidence().source, entityType: 'source_claim', entityId: 'claim-a', document: 'Publisher report', href: 'javascript:alert(1)' }, lastSuccessfulSync: null });
  const data = envelope('available', { workspaceId: 'workspace-a', claimsTruncated: true, draftId: 'draft-a', edges: [], sources: [{ sourceId: 'source-a', available: true, title: 'Publisher report', evidence: source, claims: [{ claimId: 'claim-b', relation: 'supports', evidence: { ...source, availability: 'unverified' } }] }] });
  const html = render(env, DraftEvidence, { data });
  assert.match(textOf(html), /Publisher report/);
  assert.match(textOf(html), /first 30 evidence relationships/);
  assert.match(textOf(html), /disputed/);
  assert.match(textOf(html), /unverified/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.equal(env.requests.length, 0);
});

test('classification is not silently promoted and missing envelope stays absent for older responses', () => {
  const env = makeEnvironment();
  const { scopedEvidence } = env.load('../../../lib/agent-runtime/evidence');
  for (const classification of ['observed', 'inferred', 'recommended']) assert.equal(scopedEvidence(evidence({ classification }), 'workspace-a').classification, classification);
  assert.equal(scopedEvidence(evidence(), null), null);
  assert.equal(scopedEvidence(evidence({ classification: 'proven' }), 'workspace-a'), null);
  const { MetricTable } = env.load('components/journeys/analytics');
  assert.doesNotMatch(render(env, MetricTable, { data: fixture.analytics_posts.partial }), /data-evidence-mode/);
});
