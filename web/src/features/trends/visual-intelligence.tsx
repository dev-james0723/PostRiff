'use client';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { useSnapshot } from '@/lib/api/hooks';
import type { ExposurePage } from './opportunity-exposure';
import { WhitespacePanel, ForecastPanel } from './visual-analysis-panels';
import { motion } from 'motion/react';
import { Surface, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { RAFII_EASE, RAFII_TIME, useMotionPreference } from '@/lib/rafii/motion';
import type { Trend, TrendOpportunity } from '@/lib/coworker/trend-types';
import { useExpired, useTrendContext, useTrendQuery } from './hooks';
import { TrustDrawer, blockedVerification, CrowdingSampleDetails } from './trust-drawer';
import { OpportunityCard } from './opportunity-card';
import { WatchForm } from './watches';
import { Disclosure } from './disclosure';
import {
  CoverageDetails,
  DemoNotice,
  EvidenceList,
  Metric,
  QueryContent,
  date,
  fieldClass,
  words
} from './present';
import { creatorStage, platformLabel } from './creator-language';
import {
  trendDimensions,
  currentEvidence,
  movementState,
  usableOpportunity,
  displayableOpportunity,
  compareDimensions,
  comparableDnaProfiles,
  formatValue
} from './visual-model';
import { TrendDNA } from './trend-dna';
import { MomentumCurve } from './momentum-curve';
import { visualEvent } from './visual-events';
import './visual-intelligence.css';

function Crowding({ trend, platform }: { trend: Trend; platform: string }) {
  const { flags } = useTrendContext();
  const query = useTrendQuery(
    ['saturation', trend.id],
    (api, w, s) => api.saturation(w, trend.id, s),
    !platform && currentEvidence(trend),
    'RAFII_TREND_SATURATION_ENABLED'
  );
  if (platform || !flags.RAFII_TREND_SATURATION_ENABLED || !currentEvidence(trend))
    return (
      <p className='vi-empty'>
        Crowding is Unknown for this selection. A current verified receipt and a comparison sample
        are required.
      </p>
    );
  return (
    <QueryContent query={query}>
      {(data) => (
        <>
          <DemoNotice limitations={query.data?.limitations ?? []} />
          <div className='vi-crowding-grid'>
            {(['topic', 'narrative', 'hook', 'format', 'creator'] as const).map((name) => {
              const d = data.dimensions.find((item) => item.dimension === name);
              return (
                <div key={name}>
                  <h5>{words(name)}</h5>
                  <strong>{d?.assessment ?? 'Unknown'}</strong>
                  {d && (
                    <Disclosure title={`${words(name)} comparison evidence`}>
                      <p>{d.frame}</p>
                      <p>
                        {d.classified} classified / {d.eligible} eligible observations
                      </p>
                      <dl>
                        <Metric name='Reported sample measure' metric={d.metric} advanced />
                      </dl>
                      <p>{d.uncertainty}</p>
                      <CrowdingSampleDetails details={d.sample_details} dimension={d.dimension} />
                      <p>
                        Interval: {d.interval ?? 'Unknown'} · Method: {d.method}
                      </p>
                    </Disclosure>
                  )}
                </div>
              );
            })}
          </div>
          <p className='vi-note'>
            Each is a separate sample description. Topic momentum does not establish creative
            crowding or audience fatigue.
          </p>
        </>
      )}
    </QueryContent>
  );
}

export function VisualIntelligence({
  trend,
  opportunities,
  candidates,
  page
}: {
  trend: Trend;
  opportunities: TrendOpportunity[];
  candidates: Trend[];
  page: ExposurePage;
}) {
  const { flags } = useTrendContext();
  const expired = useExpired(trend.expires_at);
  const [revoked, setRevoked] = useState(false);
  const revoke = useCallback(() => setRevoked(true), []);
  const [platform, setPlatform] = useState('');
  const [compare, setCompare] = useState('');
  const [opportunityId, setOpportunityId] = useState('');
  const { reduced } = useMotionPreference();
  const creativeRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const snapshot = useSnapshot();
  const deliveredIds = useRef(new Set<string>());
  const focused = useRef<HTMLElement | null>(null);
  useEffect(() => {
    for (const op of opportunities) deliveredIds.current.add(op.id);
    if (
      focused.current &&
      !focused.current.isConnected &&
      document.activeElement === document.body
    ) {
      creativeRef.current?.focus({ preventScroll: true });
      focused.current = null;
    }
  }, [opportunities]);
  const savedSources = snapshot.isError
    ? []
    : (snapshot.data?.state.sources ?? []).filter((source) => {
        const origin = source.origin;
        if (!source.active || origin?.kind !== 'trend_opportunity' || !('trendLineage' in origin))
          return false;
        const lineage = origin.trendLineage;
        return (
          lineage !== null &&
          typeof lineage === 'object' &&
          'opportunity_id' in lineage &&
          typeof lineage.opportunity_id === 'string' &&
          deliveredIds.current.has(lineage.opportunity_id) &&
          !opportunities.some((op) => op.id === lineage.opportunity_id)
        );
      });
  const blocked = expired || revoked || blockedVerification(trend.verification_state);
  const validated = currentEvidence(trend);
  const dimensions = trendDimensions(trend, flags);
  const selectedPlatform = trend.platform_states.find((p) => p.platform === platform);
  const visibleEvidence = trend.evidence.filter(
    (e) =>
      !platform ||
      (e.display_state === 'displayable' && e.platform.toLowerCase() === platform.toLowerCase())
  );
  const visibleOpportunities = opportunities.filter(
    (op) =>
      displayableOpportunity(op, trend) &&
      (!platform || op.platform_targets.some((p) => p.toLowerCase() === platform.toLowerCase()))
  );
  const chosenOpportunity =
    visibleOpportunities.find((op) => op.id === opportunityId) ?? visibleOpportunities[0];
  const canCreate = visibleOpportunities.some((op) => usableOpportunity(op, trend));
  const platformInsight =
    selectedPlatform && movementState(selectedPlatform, trend, flags).stage
      ? selectedPlatform.inferred.explanation
      : null;
  const other = candidates.find((t) => t.id === compare && t.id !== trend.id && currentEvidence(t));
  const interpretation =
    validated && flags.RAFII_TREND_MODEL_ENRICHMENT_ENABLED && !platform
      ? trend.interpretation
      : null;
  const fit =
    validated && flags.RAFII_TREND_MODEL_ENRICHMENT_ENABLED
      ? (chosenOpportunity?.workspace_fit ?? trend.workspace_fit)
      : null;
  const otherDimensions = other ? trendDimensions(other, flags) : [];
  const comparison = other ? compareDimensions(dimensions, otherDimensions) : [];
  const canOverlayProfiles = other ? comparableDnaProfiles(dimensions, otherDimensions) : false;
  useExpired(other?.expires_at);
  const nextExpiry = visibleOpportunities.map((o) => o.expires_at).toSorted()[0];
  useExpired(nextExpiry);
  const focusCreative = () => {
    creativeRef.current?.scrollIntoView({
      behavior: reduced ? 'instant' : 'smooth',
      block: 'start'
    });
    creativeRef.current?.focus({ preventScroll: true });
    visualEvent('create_post_started');
  };
  return (
    <article
      data-trend-card
      className='vi-cockpit'
      aria-label={blocked ? 'Trend evidence unavailable' : trend.canonical_topic}
    >
      <header className='vi-identity'>
        <div>
          <p className='vi-eyebrow'>Selected conversation</p>
          <h2 dir='auto'>{blocked ? 'Trend evidence unavailable' : trend.canonical_topic}</h2>
        </div>
        <span className='vi-state'>
          {blocked
            ? 'Needs another look'
            : creatorStage(
                selectedPlatform ? { ...trend, inferred: selectedPlatform.inferred } : trend,
                flags
              )}
        </span>
      </header>
      {blocked && (
        <StateMessage
          kind='stale'
          title='Evidence revoked or expired'
          description='Claims and examples have been removed. Recheck before using this conversation.'
        />
      )}
      {!blocked && <DemoNotice limitations={trend.limitations} />}
      <div className='vi-layout' data-blocked={blocked}>
        {!blocked && (
          <>
            <Surface
              as='section'
              material='glass'
              className='vi-insight vi-panel'
              aria-labelledby={`${id}-insight`}
            >
              <div className='vi-heading'>
                <h3 id={`${id}-insight`}>Key Insight</h3>
                <span>
                  {interpretation
                    ? 'Model interpretation'
                    : platform
                      ? 'Calculated inference'
                      : 'Observed evidence'}
                </span>
              </div>
              <p className='vi-insight-text' dir='auto' lang={interpretation?.language}>
                {interpretation?.summary ||
                  (platform
                    ? platformInsight ||
                      'Platform activity is not established in the available evidence.'
                    : trend.observed.summary)}
              </p>
              {!interpretation && (
                <p className='vi-note'>
                  {platform
                    ? 'Platform-specific cultural interpretation is not supplied.'
                    : 'Interpretation is unavailable. You can still inspect the measurements.'}
                </p>
              )}
              <p className='vi-note'>
                Evidence as of {date(trend.observed.latest_observed)}. Check again at{' '}
                {date(trend.expires_at)}.
              </p>
              <Disclosure title='Why it may fit'>
                <p>{fit?.reason ?? 'Audience and brand relevance are not established.'}</p>
                <p>{fit?.audience.reason ?? 'Your audience history has not been supplied.'}</p>
              </Disclosure>
            </Surface>
            <div className='vi-primary'>
              <Button variant='glass' onClick={focusCreative} disabled={!canCreate}>
                Create original post
              </Button>
              <p className='vi-note'>
                {canCreate
                  ? 'Choose an original angle, then review the source in Ideas.'
                  : 'A current, supported opportunity is needed before creating from this trend.'}
              </p>
            </div>
            <TrendDNA dimensions={dimensions} />
            <Surface
              as='section'
              material='glass'
              className='vi-actions vi-panel'
              aria-label='What To Do Now'
            >
              <div className='vi-heading'>
                <h3>What To Do Now</h3>
                <span>Three next steps</span>
              </div>
              <ol className='vi-next-actions'>
                <li>
                  <span>01</span>
                  <div>
                    <h4>Recheck before posting</h4>
                    <p>
                      Evidence expires at {date(trend.expires_at)}. This is a freshness deadline,
                      not a predicted peak.
                    </p>
                  </div>
                </li>
                <li>
                  <span>02</span>
                  <div>
                    <h4>
                      {visibleOpportunities.length
                        ? 'Choose your contribution'
                        : 'Find evidence for a distinct angle'}
                    </h4>
                    <p>
                      {chosenOpportunity?.contribution ||
                        'No qualified whitespace is supplied. Review the conversation before claiming a gap.'}
                    </p>
                  </div>
                </li>
                <li>
                  <span>03</span>
                  <div>
                    <h4>Bring your own facts</h4>
                    <p>
                      Personal tests and client results must come from you. Keep factual
                      verification in FactPack.
                    </p>
                  </div>
                </li>
              </ol>
              <Disclosure title='Action basis and uncertainty'>
                <p>
                  Timing uses the current receipt expiry. Creative direction uses the selected
                  opportunity and its workspace-fit evidence. First-hand requirements are supplied
                  with each angle below. These suggestions do not authorize publishing.
                </p>
                <p>Receipt: {trend.trust_receipt_id ?? 'Unavailable'}</p>
                <p>
                  Evidence:{' '}
                  {chosenOpportunity?.workspace_fit.originality.evidence_refs.join(', ') ||
                    'No angle-specific evidence supplied'}
                </p>
              </Disclosure>
            </Surface>
            <div className='vi-momentum-stack'>
              <MomentumCurve trend={trend} platform={platform} />
              <ForecastPanel trend={trend} platform={platform} />
            </div>
            <Surface
              as='section'
              material='glass'
              className='vi-platforms vi-panel'
              aria-label="Where It's Moving"
            >
              <div className='vi-heading'>
                <h3>Where It’s Moving</h3>
                <span>Within available scope</span>
              </div>
              <button
                className='rafii-focus vi-platform-reset'
                type='button'
                aria-pressed={!platform}
                onClick={() => {
                  setPlatform('');
                  visualEvent('platform_filtered');
                }}
              >
                All available evidence
              </button>
              <div className='vi-platform-list'>
                {trend.platform_states.map((row) => {
                  const state = movementState(row, trend, flags);
                  return (
                    <button
                      type='button'
                      key={row.platform}
                      className='rafii-focus vi-platform-row'
                      aria-pressed={platform === row.platform}
                      onClick={() => {
                        setPlatform(platform === row.platform ? '' : row.platform);
                        visualEvent('platform_filtered');
                      }}
                    >
                      <span className='vi-platform-title'>
                        {platformLabel(row.platform)}
                        <strong>{state.activity}</strong>
                      </span>
                      <span className='vi-platform-meta'>
                        {state.representation} · {state.completeness}
                      </span>
                      <span className='vi-note'>
                        Latest read: {date(row.coverage.latest_successful_read)}
                      </span>
                    </button>
                  );
                })}
              </div>
              {!trend.platform_states.length && (
                <p className='vi-empty'>No platform-specific state is available.</p>
              )}
              <p className='vi-note'>
                Low activity and “not observed” require explicit measurements. Missing access is
                neither. Aggregate-only and partial coverage describe different limits.
              </p>
              {selectedPlatform && (
                <Disclosure title='Selected platform scope'>
                  <CoverageDetails coverage={selectedPlatform.coverage} />
                  <p>{selectedPlatform.inferred.explanation}</p>
                </Disclosure>
              )}
            </Surface>
            <Surface
              as='section'
              material='glass'
              className='vi-creative vi-panel'
              aria-labelledby={`${id}-creative`}
              onFocusCapture={(event) => {
                focused.current = event.target as HTMLElement;
              }}
              onBlurCapture={(event) => {
                if (
                  event.relatedTarget &&
                  !event.currentTarget.contains(event.relatedTarget as Node)
                )
                  focused.current = null;
              }}
            >
              <div ref={creativeRef} tabIndex={-1} className='rafii-focus vi-creative-anchor'>
                <p className='vi-eyebrow'>From understanding to an original contribution</p>
                <h3 id={`${id}-creative`}>Creative Opportunity</h3>
              </div>
              <div className='vi-creative-intro'>
                <div>
                  <h4>Why this matters to you</h4>
                  <p>
                    {fit?.reason ??
                      'Workspace relevance is Unknown. Your audience and brand context need support.'}
                  </p>
                </div>
                <div>
                  <h4>Where there may be whitespace</h4>
                  <WhitespacePanel trend={trend} platform={platform} />
                </div>
              </div>
              <h4>What’s crowded</h4>
              <Crowding trend={trend} platform={platform} />
              <h4>Original contribution angles</h4>
              {savedSources.map((source) => (
                <p key={source.id} role='status'>
                  Saved to Ideas.{' '}
                  <Link
                    className='rafii-focus inline-flex min-h-11 items-center underline'
                    href={`/app/ideas?source=${encodeURIComponent(source.id)}`}
                  >
                    Review source and create original post
                  </Link>
                </p>
              ))}
              {visibleOpportunities.length > 1 && (
                <label className='vi-opportunity-select'>
                  Choose an opportunity
                  <select
                    className={fieldClass}
                    value={chosenOpportunity?.id ?? ''}
                    onChange={(e) => setOpportunityId(e.target.value)}
                  >
                    {visibleOpportunities.map((op) => (
                      <option key={op.id} value={op.id}>
                        {op.title}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {chosenOpportunity ? (
                [chosenOpportunity].map((op) => (
                  <div key={`${op.id}:${op.revision}`} className='vi-opportunity'>
                    <p className='vi-note'>
                      Suitable platforms: {op.platform_targets.map(platformLabel).join(', ')}.
                      Platform choice continues with your connected account in Ideas.
                    </p>
                    <Disclosure title='Why this direction is different and what supports it'>
                      <p>{op.workspace_fit.originality.reason}</p>
                      <p>User relevance: {op.workspace_fit.audience.reason}</p>
                      <p>
                        Evidence:{' '}
                        {op.workspace_fit.originality.evidence_refs.join(', ') || 'Unknown'}
                      </p>
                      <p>
                        These are opportunity-level reasons. Independent angle-level evidence and
                        supply comparisons are not supplied.
                      </p>
                      <p>Risk: {op.workspace_fit.risk.reason}</p>
                      <p>
                        Do not copy observed wording, hooks or personal experiences. Supply the
                        factual requirements below from your own work.
                      </p>
                      <p>
                        Source revision: {op.revision} · Receipt: {op.trust_receipt_id} ·
                        Brand/voice context: {op.context_revision}
                      </p>
                    </Disclosure>
                    <OpportunityCard opportunity={op} exposurePage={page} />
                  </div>
                ))
              ) : (
                <StateMessage
                  kind='partial'
                  title='Original angles are not available for this selection'
                  description='A current receipt, supported workspace fit and an eligible original contribution are needed. No replacement angles have been invented.'
                />
              )}
            </Surface>
          </>
        )}
        <Surface
          as='section'
          material='glass'
          className='vi-trust vi-panel'
          aria-label='Evidence and Coverage'
        >
          {!blocked && (
            <>
              <div className='vi-heading'>
                <h3>Evidence & Coverage</h3>
                <span>{validated ? 'Receipt verified' : 'Receipt not verified'}</span>
              </div>
              <p>
                Measurement quality: <strong>Not separately supplied</strong>
              </p>
              <dl className='vi-trust-facts'>
                <div>
                  <dt>Qualifying observations</dt>
                  <dd>
                    {validated ? formatValue(trend.observed.metrics.original_posts) : 'Unknown'}
                  </dd>
                </div>
                <div>
                  <dt>Independent creators</dt>
                  <dd>
                    {validated
                      ? formatValue(trend.observed.metrics.independent_creators)
                      : 'Unknown'}
                  </dd>
                </div>
                <div>
                  <dt>Coverage</dt>
                  <dd>{words(trend.coverage.completeness)}</dd>
                </div>
                <div>
                  <dt>Lifecycle calibration</dt>
                  <dd>{words(trend.inferred.calibration_state)}</dd>
                </div>
              </dl>
              <p className='vi-note'>
                Coverage, sample sufficiency, diversity, corroboration and freshness remain
                separate. No generic confidence percentage.
              </p>
            </>
          )}
          <TrustDrawer trend={trend} onRevoked={revoke} />
          {!blocked && (
            <>
              <Disclosure title='Sources and what’s missing'>
                <CoverageDetails coverage={trend.coverage} limitations={trend.limitations} />
                <p>
                  Sample sufficiency: Unknown · Creator diversity:{' '}
                  {validated ? formatValue(trend.calculated.creator_diversity) : 'Unknown'} ·
                  Corroboration: {dimensions[2].value}
                </p>
              </Disclosure>
              <Disclosure title='Timeline and original conversations'>
                <p>Evidence selection: {platformLabel(platform) || 'All available platforms'}</p>
                <EvidenceList evidence={visibleEvidence} />
                {interpretation && (
                  <div>
                    <h4>Native cultural context · model interpretation</h4>
                    <p lang={interpretation.language} dir='auto'>
                      {interpretation.phrases.join(' · ')}
                    </p>
                    <p>Other readings: {interpretation.alternatives.join('; ') || 'Unknown'}</p>
                  </div>
                )}
                <Disclosure title='All observed and calculated measurements'>
                  <dl className='trend-metrics-grid'>
                    {Object.entries(trend.observed.metrics).map(([key, value]) => (
                      <Metric key={key} name={`Observed: ${key}`} metric={value} advanced />
                    ))}
                    {validated &&
                      Object.entries(trend.calculated).map(([key, value]) => (
                        <Metric key={key} name={`Calculated: ${key}`} metric={value} advanced />
                      ))}
                  </dl>
                </Disclosure>
              </Disclosure>
              <WatchForm trend={trend} />
            </>
          )}
        </Surface>
        {!blocked && (
          <Surface
            as='section'
            material='glass'
            className='vi-compare vi-panel'
            aria-label='Compare Trend DNA'
          >
            <div className='vi-heading'>
              <h3>Compare Trend DNA</h3>
              <span>Two profiles, no overall winner</span>
            </div>
            <label>
              Compare with
              <select
                className={fieldClass}
                value={other?.id ?? ''}
                onChange={(e) => {
                  setCompare(e.target.value);
                  visualEvent('compare_started');
                }}
              >
                <option value=''>Choose another conversation</option>
                {candidates
                  .filter((t) => t.id !== trend.id && currentEvidence(t))
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.canonical_topic}
                    </option>
                  ))}
              </select>
            </label>
            {other ? (
              <>
                <DemoNotice limitations={other.limitations} />
                <p className='vi-note'>
                  Both use the same six dimensions. Unknown values stay Unknown; differences in
                  scope and methods remain visible.
                </p>
                {canOverlayProfiles ? (
                  <TrendDNA
                    dimensions={dimensions}
                    compact
                    embedded
                    title='Profile overlay'
                    primaryLabel={trend.canonical_topic}
                    comparison={{ dimensions: otherDimensions, label: other.canonical_topic }}
                  />
                ) : (
                  <p className='vi-empty'>
                    A visual overlay needs matching method, scale and reference-population
                    contracts. Exact native values remain available below.
                  </p>
                )}
                <div className='vi-table-wrap'>
                  <table>
                    <caption>Exact dimension comparison</caption>
                    <thead>
                      <tr>
                        <th scope='col'>Dimension</th>
                        <th scope='col'>{trend.canonical_topic}</th>
                        <th scope='col'>{other.canonical_topic}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.map((row) => (
                        <tr key={row.label}>
                          <th scope='row'>{row.label}</th>
                          <td>
                            <strong>{row.leftState}</strong>
                            <small>{row.left}</small>
                          </td>
                          <td>
                            <strong>{row.rightState}</strong>
                            <small>{row.right}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Disclosure title='Comparison context and differences'>
                  <ul>
                    {comparison.map((row) => (
                      <li key={row.label}>
                        {row.label}: {row.difference}
                      </li>
                    ))}
                  </ul>
                  <p>Current scope: {trend.coverage.scope}</p>
                  <p>Comparison scope: {other.coverage.scope}</p>
                  <p>
                    Comparison as of {date(other.observed.latest_observed)} · Receipt{' '}
                    {other.trust_receipt_id}
                  </p>
                </Disclosure>
              </>
            ) : (
              <p className='vi-note'>
                Choose a second current trend from this result set. Native units cannot be overlaid
                on a shared radar scale, so exact values are compared in a table.
              </p>
            )}
          </Surface>
        )}
      </div>
    </article>
  );
}

export function VisualCollection({
  trends,
  opportunities,
  page
}: {
  trends: Trend[];
  opportunities: TrendOpportunity[];
  page: ExposurePage;
}) {
  const [selected, setSelected] = useState(trends[0]?.id ?? '');
  const current = trends.find((t) => t.id === selected) ?? trends[0];
  const { reduced } = useMotionPreference();
  if (!current) return null;
  return (
    <div className='vi-collection'>
      {trends.length > 1 && (
        <label className='vi-trend-select'>
          Explore a conversation
          <select
            className={fieldClass}
            value={current.id}
            onChange={(e) => {
              setSelected(e.target.value);
              visualEvent('trend_selected');
            }}
          >
            {trends.map((t) => (
              <option key={t.id} value={t.id}>
                {blockedVerification(t.verification_state) || Date.parse(t.expires_at) <= Date.now()
                  ? 'Evidence unavailable'
                  : t.canonical_topic}
              </option>
            ))}
          </select>
        </label>
      )}
      <motion.div
        key={`${current.id}:${current.trust_receipt_id}`}
        initial={false}
        animate={{ opacity: 1 }}
        transition={{ duration: reduced ? 0 : RAFII_TIME.feedback / 1000, ease: RAFII_EASE.ui }}
      >
        <VisualIntelligence
          trend={current}
          page={page}
          candidates={trends}
          opportunities={opportunities.filter((o) => o.trend_id === current.id)}
        />
      </motion.div>
    </div>
  );
}
