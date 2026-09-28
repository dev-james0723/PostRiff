'use client';
import { useEffect, useState } from 'react';
import { StateMessage, SegmentedControl, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription
} from '@/components/ui/sheet';
import { ApiError } from '@/lib/api/client';
import { blockedVerification, publicStage } from './trust-contract';
export { blockedVerification, publicStage } from './trust-contract';
import type { Trend, TrendFlags, TrendReceipt } from '@/lib/coworker/trend-types';
import { useExpired, useTrendContext, useTrendQuery } from './hooks';
import {
  CoverageDetails,
  DemoNotice,
  EvidenceList,
  Metric,
  QueryContent,
  date,
  words
} from './present';
import { Disclosure } from './disclosure';
import { FitDetails } from './fit-details';
import { creatorStage, platformLabel } from './creator-language';
import { SignalSummary, SourcesSummary } from './signal-summary';

export function TrendTimeline({ trend }: { trend: Trend }) {
  return (
    <section aria-label='Observation timeline'>
      <h3 className='mb-2 font-medium'>How it changed over time</h3>
      {trend.observed.timeline.length ? (
        <ol className='trend-timeline text-sm'>
          {trend.observed.timeline.map((point, i) => (
            <li key={i} className='trend-timeline-point'>
              <time dateTime={point.at}>{date(point.at)}</time>
              <span>
                {point.state === 'gap' || point.value === null
                  ? `Gap — ${point.reason ?? 'No observation'}`
                  : `${point.value.toLocaleString()} ${point.unit} · ${point.state}`}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p>No comparable timeline is available. History has not been filled in.</p>
      )}
    </section>
  );
}
function AdvancedProjection({
  id,
  tab
}: {
  id: string;
  tab: 'genome' | 'propagation' | 'saturation';
}) {
  const genome = useTrendQuery(
    ['genome', id],
    (api, w, s) => api.genome(w, id, s),
    tab === 'genome',
    'RAFII_TREND_GRAPH_GENOME_ENABLED'
  );
  const graph = useTrendQuery(
    ['propagation', id],
    (api, w, s) => api.propagation(w, id, s),
    tab === 'propagation',
    'RAFII_TREND_GRAPH_GENOME_ENABLED'
  );
  const saturation = useTrendQuery(
    ['saturation', id],
    (api, w, s) => api.saturation(w, id, s),
    tab === 'saturation',
    'RAFII_TREND_SATURATION_ENABLED'
  );
  if (tab === 'genome')
    return (
      <QueryContent query={genome}>
        {(data) => (
          <div className='space-y-4'>
            <h3>Genome · {data.version}</h3>
            <dl className='space-y-4'>
              {data.dimensions.map((d) => (
                <div key={d.dimension}>
                  <dt className='font-medium'>{d.dimension}</dt>
                  <dd>
                    {d.finding ?? 'Unknown'}
                    <p>{d.uncertainty}</p>
                    <p>Evidence: {d.evidence_refs.join(', ') || 'None'}</p>
                  </dd>
                </div>
              ))}
            </dl>
            <h3>Narrative variants</h3>
            <ul className='list-inside list-disc'>
              {data.narrative_variants.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </QueryContent>
    );
  if (tab === 'propagation')
    return (
      <QueryContent query={graph}>
        {(data) => (
          <section aria-label='Propagation graph equivalent list' className='space-y-3'>
            <h3 className='font-medium'>Spread relationships</h3>
            <p>{data.scope}</p>
            <p>First seen in the observed sample does not establish an origin or cause.</p>
            {data.truncated && <p>Only a bounded subset is available.</p>}
            <ul className='space-y-3'>
              {data.edges.map((e) => (
                <li key={e.id} className='trend-relation'>
                  <strong>
                    {data.nodes.find((n) => n.id === e.from)?.label ?? e.from} →{' '}
                    {data.nodes.find((n) => n.id === e.to)?.label ?? e.to}
                  </strong>
                  <p>
                    {e.basis === 'observed'
                      ? 'Directly observed relation'
                      : 'Hypothesized adaptation'}{' '}
                    · {e.relation}
                  </p>
                  <p>{e.limitation}</p>
                  <p>Evidence: {e.evidence_refs.join(', ') || 'Unknown'}</p>
                </li>
              ))}
            </ul>
            {!data.edges.length && <p>No supported relationships are available.</p>}
            <Disclosure title='First-seen observations'>
              <ul>
                {data.nodes.map((n) => (
                  <li key={n.id}>
                    {n.label}: {date(n.first_seen)}
                  </li>
                ))}
              </ul>
            </Disclosure>
          </section>
        )}
      </QueryContent>
    );
  return (
    <QueryContent query={saturation}>
      {(data) => (
        <section className='space-y-4'>
          <h3 className='font-medium'>Creative crowding</h3>
          <p>
            Each dimension has its own comparison frame. This does not predict audience fatigue.
          </p>
          {data.dimensions.map((d) => (
            <Surface key={d.dimension} material='quiet' className='trend-crowding space-y-3'>
              <h4 className='font-medium'>
                {words(d.dimension)} · {d.assessment ?? 'Unknown'}
              </h4>
              <p>{d.frame}</p>
              <p>
                {d.classified} classified / {d.eligible} eligible observations
              </p>
              <dl>
                <Metric name='Classified share' metric={d.metric} advanced />
              </dl>
              <p>
                Interval: {d.interval ?? 'Unknown'} · Method: {d.method}
              </p>
              <p>{d.uncertainty}</p>
            </Surface>
          ))}
        </section>
      )}
    </QueryContent>
  );
}
function TrustContent({ trend, flags }: { trend: Trend | TrendReceipt; flags: TrendFlags }) {
  const [tab, setTab] = useState('evidence');
  const expired = useExpired(trend.expires_at);
  if (expired || blockedVerification(trend.verification_state))
    return (
      <StateMessage
        kind='stale'
        title='Evidence revoked or no longer current'
        description={`Claims removed: ${words(trend.verification_state)}. Recheck before using this evidence.`}
      />
    );
  const options = [
    { value: 'evidence', label: 'Evidence' },
    { value: 'timeline', label: 'Timeline' },
    ...(flags.RAFII_TREND_GRAPH_GENOME_ENABLED
      ? [
          { value: 'genome', label: 'Genome & narratives' },
          { value: 'propagation', label: 'Graph / list' }
        ]
      : []),
    ...(flags.RAFII_TREND_SATURATION_ENABLED ? [{ value: 'saturation', label: 'Crowding' }] : [])
  ];
  const active = options.some((o) => o.value === tab) ? tab : 'evidence';
  return (
    <div className='space-y-5'>
      <p>
        <strong>{creatorStage(trend, flags)}</strong>
      </p>
      <DemoNotice limitations={trend.limitations} />
      <Disclosure className='trend-scope-summary' title='Sources and what’s missing'>
        <SourcesSummary coverage={trend.coverage} />
      </Disclosure>
      <SegmentedControl
        label='Trust views'
        pattern='tabs'
        widths='content'
        value={active}
        onChange={setTab}
        options={options}
        panelIds={
          options.map((o) => (o.value === active ? 'trend-trust-panel' : undefined)) as string[]
        }
      />
      <div
        id='trend-trust-panel'
        role='tabpanel'
        aria-label={options.find((o) => o.value === active)?.label}
        className='space-y-5'
      >
        {active === 'timeline' ? (
          <TrendTimeline trend={trend} />
        ) : ['genome', 'propagation', 'saturation'].includes(active) ? (
          <AdvancedProjection
            id={trend.id}
            tab={active as 'genome' | 'propagation' | 'saturation'}
          />
        ) : (
          <>
            <section className='trend-trust-layer space-y-4'>
              <h3 className='text-base font-semibold'>1. What we saw</h3>
              <p>{trend.observed.summary}</p>
              <p>
                First detected: {date(trend.observed.first_detected)}
                <br />
                Latest observed: {date(trend.observed.latest_observed)}
              </p>
              <EvidenceList evidence={trend.evidence} />
            </section>
            <section className='trend-trust-layer space-y-4'>
              <h3 className='text-base font-semibold'>2. How the conversation is changing</h3>
              <SignalSummary trend={trend} />
            </section>
            <section className='trend-trust-layer space-y-3'>
              <h3 className='text-base font-semibold'>3. How Rafii reads the pattern</h3>
              <p>{trend.inferred.explanation}</p>

              <ul>
                {trend.platform_states.map((s) => (
                  <li key={s.platform}>
                    {platformLabel(s.platform)}:{' '}
                    {s.coverage.availability === 'unavailable'
                      ? 'Data isn’t available'
                      : creatorStage({ ...trend, inferred: s.inferred }, flags)}{' '}
                    — {s.inferred.explanation}
                  </li>
                ))}
              </ul>
            </section>
            <section className='trend-trust-layer space-y-3'>
              <h3 className='text-base font-semibold'>4. What it might mean</h3>
              <p>A possible reading of the conversation. This doesn’t tell us how popular it is.</p>
              {flags.RAFII_TREND_MODEL_ENRICHMENT_ENABLED && trend.interpretation ? (
                <>
                  <p lang={trend.interpretation.language} dir='auto'>
                    {trend.interpretation.summary}
                  </p>
                  <ul>
                    {trend.interpretation.phrases.map((p, i) => (
                      <li key={i} lang={trend.interpretation!.language} dir='auto'>
                        {p}
                      </li>
                    ))}
                  </ul>
                  <p>
                    Alternative explanations:{' '}
                    {trend.interpretation.alternatives.join('; ') || 'Not established'}
                  </p>
                </>
              ) : (
                <p>
                  There isn’t a supported interpretation yet. You can still explore the evidence.
                </p>
              )}
            </section>
            {trend.workspace_fit && (
              <FitDetails fit={trend.workspace_fit} title='Workspace fit, timing and risk' />
            )}
            <section className='trend-trust-layer'>
              <h3 className='text-base font-semibold'>What we don’t know yet</h3>
              {trend.unverified_claims.length ? (
                <ul className='list-inside list-disc'>
                  {trend.unverified_claims.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              ) : (
                <p>No additional claims supplied.</p>
              )}
            </section>
            <Disclosure className='trend-methodology' title='Measurement details and methodology'>
              <p>
                Verification: {words(trend.verification_state)} · Lifecycle:{' '}
                {publicStage(trend, flags) ?? 'Not qualified for display'}
              </p>
              <p>
                Data state: {words(trend.inferred.data_state)} · Measurement support:{' '}
                {words(trend.inferred.confidence)} · Calibration:{' '}
                {words(trend.inferred.calibration_state)}
              </p>
              <p>
                Lifecycle claims require a current verified receipt, qualified evidence and
                calibration, with both receipt and stage flags enabled.
              </p>
              <CoverageDetails coverage={trend.coverage} limitations={trend.limitations} />
              <Disclosure title='Platform measurement details'>
                {trend.platform_states.map((state) => (
                  <div key={state.platform}>
                    <h4>{platformLabel(state.platform)}</h4>
                    <p>
                      Data state: {words(state.inferred.data_state)} · Measurement support:{' '}
                      {words(state.inferred.confidence)} · Calibration:{' '}
                      {words(state.inferred.calibration_state)}
                    </p>
                    <CoverageDetails coverage={state.coverage} />
                  </div>
                ))}
              </Disclosure>
              {'method' in trend ? (
                <div className='space-y-2'>
                  <p>
                    Method: {trend.method.id} / {trend.method.version}
                  </p>
                  <p>{trend.method.formula}</p>
                  <p>Calibration cohort: {trend.method.calibration_cohort ?? 'Unknown'}</p>
                  <p className='break-words'>
                    Source snapshots: {trend.method.snapshot_refs.join(', ')}
                  </p>
                  <p>Receipt: {trend.receipt_id}</p>
                </div>
              ) : (
                <p>Trust receipts are not enabled or available.</p>
              )}
              <dl className='trend-metrics-grid mt-4'>
                {[
                  ...Object.entries(trend.observed.metrics).map(
                    ([key, value]) => [`Observed: ${key}`, value] as const
                  ),
                  ...Object.entries(trend.calculated).map(
                    ([key, value]) => [`Calculated: ${key}`, value] as const
                  )
                ].map(([key, value]) => (
                  <Metric key={key} name={key} metric={value} advanced />
                ))}
              </dl>
            </Disclosure>
          </>
        )}
      </div>
    </div>
  );
}
export function TrustDrawer({ trend, onRevoked }: { trend: Trend; onRevoked: () => void }) {
  const [open, setOpen] = useState(false);
  const { flags } = useTrendContext();
  const receipts =
    flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED === true && Boolean(trend.trust_receipt_id);
  const query = useTrendQuery(
    ['trust', trend.id, trend.trust_receipt_id, receipts],
    (api, w, s) =>
      receipts ? api.receipt(w, trend.id, trend.trust_receipt_id!, s) : api.detail(w, trend.id, s),
    open
  );
  useEffect(() => {
    if (
      (query.error instanceof ApiError && [401, 403, 404, 410].includes(query.error.status)) ||
      (query.data && blockedVerification(query.data.data.verification_state))
    )
      onRevoked();
  }, [query.error, query.data, onRevoked]);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger render={<Button variant='glass' size='control' />}>
        Why should I trust this?
      </SheetTrigger>
      <SheetContent
        className='trend-drawer overflow-y-auto overscroll-contain break-words p-5 sm:p-7'
        finalFocus={true}
      >
        <SheetHeader className='p-0 pr-10'>
          <SheetTitle>
            {blockedVerification(trend.verification_state) ||
            Date.parse(trend.expires_at) <= Date.now() ||
            (query.error instanceof ApiError && [401, 403, 404, 410].includes(query.error.status))
              ? 'Trend evidence unavailable'
              : trend.canonical_topic}
          </SheetTitle>
          <SheetDescription>
            See the conversations behind this idea, what’s missing, and how Rafii reached its view.
          </SheetDescription>
        </SheetHeader>
        {open && (
          <QueryContent query={query}>
            {(data) => <TrustContent trend={data} flags={flags} />}
          </QueryContent>
        )}
      </SheetContent>
    </Sheet>
  );
}
