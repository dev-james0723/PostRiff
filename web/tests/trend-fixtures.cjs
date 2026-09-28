/** Explicit synthetic intercepted browser fixtures. Never imported by production code. */
const { loadTypes } = require('./trend-contract.cjs');
const types = loadTypes();
function fixtures({ longContent = false } = {}) {
  const now = Date.now(),
    iso = (delta) => new Date(now + delta).toISOString();
  const coverage = {
    availability: 'available',
    representation: 'sampled_posts',
    completeness: 'complete_within_scope',
    breadth: 'unknown',
    scope_ref: 'synthetic-scope',
    coverage_epoch: 'synthetic-epoch',
    scope: 'Synthetic permitted sample, not the whole platform',
    latest_successful_read: iso(-60000),
    freshness_deadline: iso(3600000),
    sources: [
      { platform: 'bluesky', availability: 'available', reason: null },
      { platform: 'tiktok', availability: 'unavailable', reason: 'No authorized source' }
    ]
  };
  const metric = (value) => ({
    value,
    unit: 'posts/hour',
    definition_id: 'synthetic-rate',
    definition_version: '1',
    window: { start: iso(-3600000), end: iso(0) },
    baseline_ref: 'synthetic-baseline',
    denominator: 'Eligible original posts in one observed hour',
    null_reason: value === null ? 'Insufficient observations' : null
  });
  const dimension = {
    assessment: 'supported',
    reason: 'Synthetic evidence supports a practical contribution.',
    evidence_refs: ['synthetic-evidence']
  };
  const fit = {
    reason: 'Your teaching practice can add a concrete example.',
    sufficient: true,
    ...Object.fromEntries(
      ['trend_relevance', 'brand', 'audience', 'timing', 'originality', 'risk', 'confidence'].map(
        (k) => [k, { ...dimension }]
      )
    )
  };
  const inferred = {
    stage: 'rising',
    data_state: 'qualified',
    explanation: 'Two comparable observed windows increased; platform-wide prevalence unknown.',
    confidence: 'qualified',
    calibration_state: 'unknown',
    evidence_refs: ['synthetic-evidence']
  };
  const trend = {
    id: 'synthetic-trend',
    canonical_topic: 'Synthetic fixture · 練琴唔係鬥快',
    observed: {
      summary: 'A sampled conversation about deliberate practice changed in the observed window.',
      first_detected: iso(-7200000),
      latest_observed: iso(-60000),
      metrics: {
        original_posts: { ...metric(150), unit: 'posts' },
        independent_creators: { ...metric(null), unit: 'creators' }
      },
      timeline: [
        { at: iso(-7200000), value: 60, unit: 'posts/hour', state: 'complete', reason: null },
        {
          at: iso(-3600000),
          value: null,
          unit: 'posts/hour',
          state: 'gap',
          reason: 'Collector unavailable'
        },
        {
          at: iso(0),
          value: 150,
          unit: 'posts/hour',
          state: 'provisional',
          reason: 'Window still settling'
        }
      ]
    },
    calculated: {
      velocity: { ...metric(60), unit: 'posts/hour^2' },
      acceleration: { ...metric(30), unit: 'posts/hour^3' }
    },
    inferred,
    interpretation: {
      summary: '慢慢嚟，先練準。Practice before speed.',
      language: 'yue',
      phrases: ['練琴唔係鬥快'],
      alternatives: ['A recurring teaching conversation'],
      evidence_refs: ['synthetic-evidence']
    },
    unverified_claims: ['No evidence establishes the earliest cultural origin.'],
    coverage,
    limitations: ['Demo data: Synthetic fixture only; no live provider or model was called.'],
    trust_receipt_id: 'synthetic-receipt',
    verification_state: 'verified',
    expires_at: iso(3600000),
    platform_states: [
      { platform: 'bluesky', inferred, coverage },
      {
        platform: 'tiktok',
        inferred: { ...inferred, stage: null, data_state: 'insufficient' },
        coverage: { ...coverage, availability: 'unavailable' }
      }
    ],
    evidence: [
      {
        id: 'synthetic-evidence',
        display_state: 'displayable',
        platform: 'bluesky',
        language: 'yue',
        excerpt:
          '慢練係為咗聽清楚每粒音。🎹' +
          (longContent
            ? '\n' + '聽清楚呼吸、觸鍵同樂句，再慢慢調整；唔好用速度代替聆聽。 '.repeat(12)
            : ''),
        url: 'https://example.com/synthetic-conversation',
        observed_at: iso(-60000),
        expires_at: iso(3600000),
        policy_ref: 'synthetic-policy'
      },
      { id: 'restricted', display_state: 'restricted', reason: 'Display not permitted' }
    ],
    workspace_fit: fit
  };
  const receipt = {
    ...trend,
    receipt_id: 'synthetic-receipt',
    method: {
      id: 'synthetic-method',
      version: '2',
      formula: 'Eligible originals / hours; velocity = change in comparable rate.',
      calibration_cohort: null,
      snapshot_refs: ['synthetic-snapshot-1', 'synthetic-snapshot-2']
    }
  };
  const opportunity = {
    id: 'synthetic-opportunity',
    revision: 1,
    trend_id: trend.id,
    trust_receipt_id: trend.trust_receipt_id,
    state: 'ready',
    platform_targets: ['LinkedIn', 'bluesky'],
    context_digest: 'synthetic-context',
    context_revision: 'synthetic-context',
    verification_state: 'verified',
    expires_at: iso(3600000),
    title: 'A useful practice demonstration',
    contribution: 'Show one passage at two practice speeds using your own playing.',
    uncertainty: 'The audience response is unknown.',
    workspace_fit: fit,
    source_id: null,
    draft_id: null,
    angles: [
      {
        id: 'synthetic-angle',
        title: 'Listen before speeding up',
        contribution: 'Demonstrate a listening checklist.',
        factual_requirements: [
          'Use your own performance; do not claim a result you have not measured.'
        ],
        format_reason: 'A short demonstration can make the listening task concrete.'
      }
    ]
  };
  const run = {
    id: 'synthetic-run',
    state: 'completed',
    draft_id: 'synthetic-draft',
    draft_revision: 1,
    opportunity_id: opportunity.id,
    opportunity_revision: 1,
    context_revision: opportunity.context_revision,
    trust_receipt_id: trend.trust_receipt_id,
    expires_at: iso(3600000),
    failure_reason: null,
    diagnostics: [
      {
        dimension: 'originality',
        assessment: 'mixed',
        claim: 'A concrete listening instruction would make the opening more useful.',
        evidence_refs: ['synthetic-receipt'],
        comparison_frame: 'Synthetic owned writing comparison; no causal performance claim',
        uncertainty: 'Audience response is unknown.',
        requires_user_fact: false,
        suggested_edit: {
          id: 'synthetic-edit',
          before: 'A small idea worth a closer look.',
          after: 'Listen to one phrase before increasing the tempo.',
          reason: 'Make the action observable.'
        }
      },
      {
        dimension: 'personal_experience',
        assessment: 'unknown',
        claim: 'A claimed improvement needs your own evidence.',
        evidence_refs: [],
        comparison_frame: 'No owned measurement',
        uncertainty: 'Your results are unknown.',
        requires_user_fact: true,
        suggested_edit: {
          id: 'synthetic-fact-edit',
          before: 'A small idea worth a closer look.',
          after: 'I doubled my speed in a week.',
          reason: 'Needs a verified user fact; never auto-apply.'
        }
      }
    ]
  };
  const envelope = (data, execution_state = 'stored_result') => ({
    schema_version: '1.0',
    request_id: 'synthetic-request',
    as_of: iso(0),
    data,
    coverage,
    limitations: trend.limitations,
    execution_state,
    next_cursor: null
  });
  const methodology = {
    method_id: 'synthetic-method',
    version: '2',
    summary: 'Explicit synthetic measurement fixture.',
    definitions: [
      { id: 'rate', version: '1', unit: 'posts/hour', formula: 'eligible count / observed hours' }
    ],
    blind_spots: ['No platform-wide denominator']
  };
  const calibration = {
    state: 'insufficient',
    cohort: 'Synthetic practice cohort',
    evaluated: 4,
    unknown_outcomes: 3,
    metrics: { precision: { ...metric(99), unit: 'percent' } },
    limitations: ['Not enough comparable history']
  };
  const genome = {
    version: '1',
    dimensions: [
      {
        dimension: 'Narrative',
        finding: 'Practice as listening',
        uncertainty: 'Limited sample',
        evidence_refs: ['synthetic-evidence']
      }
    ],
    narrative_variants: ['Slower practice as deliberate listening']
  };
  const propagation = {
    version: '1',
    scope: coverage.scope,
    nodes: [
      { id: 'a', label: 'Original post', first_seen: iso(-1000) },
      { id: 'b', label: 'A reply', first_seen: iso(0) }
    ],
    edges: [
      {
        id: 'ab',
        from: 'a',
        to: 'b',
        relation: 'reply',
        basis: 'observed',
        evidence_refs: ['synthetic-evidence'],
        limitation: 'No causal origin established'
      },
      {
        id: 'ba',
        from: 'b',
        to: 'a',
        relation: 'adaptation',
        basis: 'hypothesized',
        evidence_refs: ['synthetic-evidence'],
        limitation: 'Not an observed transmission'
      }
    ],
    truncated: false
  };
  const saturation = {
    dimensions: ['topic', 'narrative', 'hook', 'format', 'creator'].map((d) => ({
      dimension: d,
      assessment: null,
      frame: coverage.scope,
      eligible: 100,
      classified: 80,
      metric: { ...metric(25), unit: 'percent', denominator: '80 classified posts' },
      interval: null,
      method: 'synthetic-classifier/1',
      uncertainty: 'Crowding label unqualified'
    }))
  };
  const languages = [
    {
      id: 'synthetic-language',
      expression: '練琴唔係鬥快',
      language: 'yue',
      context: 'Synthetic Cantonese teaching conversation',
      meaning: 'Practice is not a race.',
      uncertainty: 'Origin not established',
      evidence: trend.evidence
    }
  ];
  if (longContent) {
    trend.canonical_topic += ' · 聆聽、節奏與觸鍵：在真實練習中逐步探索自己的音樂語言';
    receipt.canonical_topic = trend.canonical_topic;
    trend.observed.summary +=
      ' ' +
      'This deliberately long synthetic observation preserves uncertainty and original language across narrow screens. '.repeat(
        4
      );
    opportunity.title += ' · explore one musical phrase without claiming a measured outcome';
    opportunity.contribution +=
      ' ' +
      'Use your own performance and retain the limits of this sampled conversation. '.repeat(4);
    run.diagnostics[0].claim +=
      ' ' +
      'A long diagnostic must stay readable without hiding its evidence or inventing personal experience. '.repeat(
        4
      );
  }
  types.trendSchema.parse(trend);
  types.receiptSchema.parse(receipt);
  types.opportunitySchema.parse(opportunity);
  types.labRunSchema.parse(run);
  return {
    trend,
    receipt,
    opportunity,
    run,
    coverage,
    metric,
    envelope,
    methodology,
    calibration,
    genome,
    propagation,
    saturation,
    languages,
    flags: Object.fromEntries(types.TREND_FLAGS.map((k) => [k, true]))
  };
}
module.exports = { fixtures };
