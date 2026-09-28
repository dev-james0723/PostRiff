'use client';

import { useId, useState } from 'react';
import { ApiError } from '@/lib/api/client';
import {
  forecastResponseSchema,
  whitespaceResponseSchema,
  type Trend,
  type TrendEnvelope,
  type TrendFlags,
  type TrendForecast,
  type TrendWhitespace
} from '@/lib/coworker/trend-types';
import type { TrendApi } from './api';
import { useExpired, useTrendContext, useTrendQuery } from './hooks';
import { DemoNotice, words } from './present';

export type VisualAnalysisProps = { trend: Trend; platform: string };
const READ_FRESHNESS_MS = 30_000; // Matches stored-query polling; hidden tabs lose old claims.
const cell = 'border-b border-border px-2 py-2 text-left align-top break-words';
const currentTrend = (trend: Trend, now: number) =>
  Boolean(trend.trust_receipt_id) &&
  trend.verification_state === 'verified' &&
  Date.parse(trend.expires_at) > now &&
  !['rights_blocked', 'retracted', 'stale'].includes(trend.inferred.data_state);
export function analysisEnabled(flags: TrendFlags, kind: 'WHITESPACE' | 'FORECASTS') {
  return (
    flags.RAFII_TREND_INTELLIGENCE_ENABLED === true &&
    flags.RAFII_TREND_RADAR_ENABLED === true &&
    flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED === true &&
    flags[`RAFII_TREND_${kind}_ENABLED`] === true
  );
}
function currentRead<T>(response: TrendEnvelope<T>, now: number) {
  return (
    ['stored_result', 'partial'].includes(response.execution_state) &&
    Date.parse(response.as_of) <= now &&
    now - Date.parse(response.as_of) < READ_FRESHNESS_MS &&
    (!response.coverage.freshness_deadline ||
      Date.parse(response.coverage.freshness_deadline) > now)
  );
}
function firstExpiry(...dates: (string | null | undefined)[]) {
  const times = dates.filter((v): v is string => Boolean(v)).map(Date.parse);
  return times.length && times.every(Number.isFinite)
    ? new Date(Math.min(...times)).toISOString()
    : null;
}
function readDeadline<T>(response?: TrendEnvelope<T>) {
  return response ? new Date(Date.parse(response.as_of) + READ_FRESHNESS_MS).toISOString() : null;
}
export function selectWhitespace(
  raw: unknown,
  trend: Trend,
  workspace: string,
  platform: string,
  now = Date.now()
) {
  const result = whitespaceResponseSchema.safeParse(raw);
  if (!result.success || !currentTrend(trend, now) || !currentRead(result.data, now)) return null;
  const matches = result.data.data.filter(
    (row) =>
      row.workspace_id === workspace &&
      row.trend_id === trend.id &&
      row.trust_receipt_id === trend.trust_receipt_id &&
      Date.parse(row.expires_at) > now &&
      Date.parse(row.computed_at) <= Date.parse(result.data.as_of)
  );
  // Ambiguous duplicates are not resolved by guessing which assessment is authoritative.
  if (matches.length !== 1) return null;
  const entry = matches[0];
  const gaps = entry.gaps.filter((gap) => !platform || gap.platform === platform);
  return gaps.length ? { entry, gaps, response: result.data } : null;
}

export type BoundForecast = {
  response: TrendEnvelope<TrendForecast>;
  // Client read proof from actual stored detail responses, not invented wire fields.
  binding: {
    workspace_id: string;
    trend_id: string;
    trust_receipt_id: string;
    checked_before: string;
    checked_after: string;
    expires_at: string;
  };
};
/** The endpoint replays current rights/admission. Sandwich reads detect receipt changes
 * because its numeric response intentionally does not repeat trend/receipt IDs. */
const forecastReadError = () =>
  new ApiError('The current forecast receipt could not be verified.', 409, 'revision_conflict');
export async function readBoundForecast(
  api: TrendApi,
  workspace: string,
  trend: Trend,
  signal: AbortSignal
): Promise<BoundForecast> {
  const matches = (value: TrendEnvelope<Trend>) =>
    value.data.id === trend.id &&
    value.data.trust_receipt_id === trend.trust_receipt_id &&
    currentTrend(value.data, Date.now()) &&
    currentRead(value, Date.now());
  const before = await api.detail(workspace, trend.id, signal);
  if (!matches(before)) throw forecastReadError();
  const response = await api.forecast(workspace, trend.id, signal);
  const after = await api.detail(workspace, trend.id, signal);
  if (
    !matches(after) ||
    response.data.scope_key !== `workspace:${workspace}` ||
    !currentRead(response, Date.now()) ||
    Date.parse(before.as_of) > Date.parse(response.as_of) ||
    Date.parse(response.as_of) > Date.parse(after.as_of) ||
    [before, after].some(
      (r) =>
        r.coverage.scope_ref !== response.coverage.scope_ref ||
        r.coverage.coverage_epoch !== response.coverage.coverage_epoch
    )
  )
    throw forecastReadError();
  return {
    response,
    binding: {
      workspace_id: workspace,
      trend_id: after.data.id,
      trust_receipt_id: after.data.trust_receipt_id!,
      checked_before: before.as_of,
      checked_after: after.as_of,
      expires_at: firstExpiry(
        before.data.expires_at,
        after.data.expires_at,
        response.data.expires_at
      )!
    }
  };
}
export function selectForecast(
  read: BoundForecast | undefined,
  trend: Trend,
  workspace: string,
  platform: string,
  now = Date.now()
) {
  if (!read || platform || !currentTrend(trend, now)) return null;
  const parsed = forecastResponseSchema.safeParse(read.response);
  const b = read.binding;
  if (
    !parsed.success ||
    !currentRead(parsed.data, now) ||
    b.workspace_id !== workspace ||
    b.trend_id !== trend.id ||
    b.trust_receipt_id !== trend.trust_receipt_id ||
    !(
      Date.parse(b.checked_before) <= Date.parse(parsed.data.as_of) &&
      Date.parse(parsed.data.as_of) <= Date.parse(b.checked_after) &&
      Date.parse(b.checked_after) <= now &&
      Date.parse(b.expires_at) > now
    )
  )
    return null;
  const f = parsed.data.data;
  return f.scope_key === `workspace:${workspace}` &&
    Date.parse(f.issued_at) <= Date.parse(parsed.data.as_of) &&
    Date.parse(f.expires_at) > now &&
    Date.parse(f.horizon_end) > now
    ? f
    : null;
}
function Time({ value }: { value: string }) {
  // Retain offset and precision instead of silently presenting the source cutoff as "now".
  return (
    <time dateTime={value} className='break-all'>
      {value}
    </time>
  );
}
function Unknown({ children }: { children: React.ReactNode }) {
  return (
    <p className='vi-empty' role='status'>
      <strong>Unknown.</strong> {children}
    </p>
  );
}
function Limits({ values }: { values: string[] }) {
  return values.length ? (
    <details className='mt-3 min-w-0'>
      <summary className='rafii-focus cursor-pointer rounded-sm text-sm'>
        Limits and evidence scope
      </summary>
      <ul className='mt-2 list-disc space-y-1 pl-5 text-sm break-words'>
        {values.map((v, i) => (
          <li key={i}>{v}</li>
        ))}
      </ul>
    </details>
  ) : null;
}
function Gap({
  entry,
  gap,
  readAt
}: {
  entry: TrendWhitespace;
  gap: TrendWhitespace['gaps'][number];
  readAt: string;
}) {
  const opportunity = entry.opportunities.find((o) => o.candidate_id === gap.candidate_id);
  const s = opportunity?.supply_search_scope;
  return (
    <article
      className='min-w-0 space-y-2 rounded-xl border border-border p-3 break-words'
      data-whitespace-state={gap.state}
    >
      <div className='flex flex-wrap items-center gap-2 text-sm'>
        <strong className={opportunity ? 'text-foreground' : 'text-[var(--muted-foreground)]'}>
          {opportunity ? 'Supported in this sample' : 'Proposed · review required'}
        </strong>
        <span>
          {gap.platform} · {gap.language}
        </span>
      </div>
      <p lang={gap.language}>{gap.summary}</p>
      {opportunity && s && (
        <>
          <h5 className='font-semibold'>Proposed contribution</h5>
          <p>{opportunity.proposed_contribution}</p>
        </>
      )}
      <details className='min-w-0 text-sm'>
        <summary className='rafii-focus cursor-pointer rounded-sm'>
          Evidence and comparison details
        </summary>
        <p className='vi-note'>
          Observed comparison sample only. Global supply and semantic qualification remain unknown.
        </p>
        <dl className='mt-2 grid grid-cols-2 gap-2 text-sm'>
          <div>
            <dt>Observed original posts</dt>
            <dd>{gap.observed_original_count.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Known creators</dt>
            <dd>{gap.known_creator_count.toLocaleString()}</dd>
          </div>
        </dl>
        {opportunity && s ? (
          <>
            <div
              className='mt-3 min-w-0 break-words'
              role='region'
              aria-label='Observed comparison sample table'
            >
              <table className='w-full table-fixed text-sm'>
                <caption className='pb-2 text-left'>
                  Observed comparison sample · {s.frame_id}
                </caption>
                <thead>
                  <tr>
                    <th className={cell} scope='col'>
                      Measure
                    </th>
                    <th className={cell} scope='col'>
                      Observed value
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    [
                      'Retained / expected comparison units',
                      `${s.observed_units} / ${s.expected_units}`
                    ],
                    [
                      'Sample retrieval coverage',
                      `${(s.retrieval_coverage * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
                    ],
                    [
                      'Supporting / opposing supply',
                      `${opportunity.angle_occupancy.supporting_count} / ${opportunity.angle_occupancy.opposing_count}`
                    ],
                    [
                      'Reply context',
                      s.context_complete
                        ? 'Complete within sample'
                        : 'Incomplete; unanswered status unknown'
                    ]
                  ].map(([label, value]) => (
                    <tr key={label}>
                      <th scope='row' className={cell}>
                        {label}
                      </th>
                      <td className={cell}>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h5 className='mt-3 font-semibold'>Support, risks and disconfirming evidence</h5>
            <p className='mt-2'>Demand references: {opportunity.demand_evidence_refs.join(', ')}</p>
            <p>
              Supporting supply:{' '}
              {opportunity.supporting_supply_refs.join(', ') || 'None in this sample'}
            </p>
            <p>
              Opposing supply:{' '}
              {opportunity.opposing_supply_refs.join(', ') || 'None in this sample'}
            </p>
            <p>
              Approved workspace fact references:{' '}
              {opportunity.credibility.approved_fact_refs.join(', ')}
            </p>
            <p>Risks: {opportunity.risks.join(' · ') || 'No risk notes supplied'}</p>
            <p>
              Disconfirming evidence:{' '}
              {opportunity.disconfirming_evidence.join(' · ') ||
                'None supplied; absence is not proof'}
            </p>
          </>
        ) : (
          <p className='vi-note'>Review needed: {gap.reasons.map(words).join(' · ')}.</p>
        )}
        <h5 className='mt-3 font-semibold'>Source and analysis times</h5>
        <dl className='mt-2 space-y-1 text-xs text-muted-foreground'>
          <div>
            <dt>Source decision cutoff</dt>
            <dd>
              <Time value={entry.source_decision_cutoff} />
            </dd>
          </div>
          <div>
            <dt>Analysis computed</dt>
            <dd>
              <Time value={entry.computed_at} />
            </dd>
          </div>
          <div>
            <dt>Current stored read</dt>
            <dd>
              <Time value={readAt} />
            </dd>
          </div>
          <div>
            <dt>Evidence expires</dt>
            <dd>
              <Time value={entry.expires_at} />
            </dd>
          </div>
        </dl>
      </details>
    </article>
  );
}
export function WhitespacePanel({ trend, platform }: VisualAnalysisProps) {
  const context = useTrendContext();
  const trendExpired = useExpired(trend.expires_at);
  const enabled =
    context.enabled &&
    analysisEnabled(context.flags, 'WHITESPACE') &&
    !trendExpired &&
    currentTrend(trend, Date.now());
  const query = useTrendQuery(
    ['visual-whitespace', trend.id, trend.trust_receipt_id, platform],
    (api, w, signal) => api.whitespace(w, signal),
    enabled,
    'RAFII_TREND_WHITESPACE_ENABLED'
  );
  const selected = selectWhitespace(query.data, trend, context.w, platform);
  const expired = useExpired(
    firstExpiry(
      trend.expires_at,
      selected?.entry.expires_at,
      readDeadline(query.data),
      query.data?.coverage.freshness_deadline
    )
  );
  let reason = '';
  if (!enabled) reason = 'Current verified evidence and enabled whitespace access are required.';
  else if (query.isError)
    reason =
      'The stored assessment could not be verified. Previously shown claims have been removed.';
  else if (query.isFetching || !query.data) reason = 'Checking the current stored assessment…';
  else if (expired || !selected)
    reason =
      'No current stored assessment matches this trend, receipt and platform. This does not establish a gap.';
  return (
    <div
      role='region'
      className='min-w-0 space-y-3'
      aria-label='Creative whitespace'
      aria-busy={enabled && query.isFetching}
    >
      <DemoNotice
        limitations={[
          ...trend.limitations,
          ...(query.data?.limitations ?? []),
          ...(selected?.entry.limitations ?? [])
        ]}
      />
      {reason || !selected ? (
        <Unknown>{reason}</Unknown>
      ) : (
        <>
          <p className='vi-note'>Based on the posts observed in this sample.</p>
          {selected.gaps.map((gap) => (
            <Gap
              key={gap.candidate_id}
              entry={selected.entry}
              gap={gap}
              readAt={selected.response.as_of}
            />
          ))}
          {(selected.entry.truncated ||
            selected.response.next_cursor ||
            selected.response.execution_state === 'partial') && (
            <p className='vi-note'>
              Partial coverage. The returned candidates are not an exhaustive catalogue.
            </p>
          )}
          <Limits values={[...selected.entry.limitations, ...selected.response.limitations]} />
          <p className='vi-note'>
            An admitted contribution is still a proposal. Ideas, FactPack review and publishing
            approval remain separate.
          </p>
        </>
      )}
    </div>
  );
}
// Preserve the stored number; do not round a small observed value down to zero.
const formatForecastNumber = (n: number) => String(n);
function ForecastTable({ forecast }: { forecast: TrendForecast }) {
  const p = forecast.predictions[0],
    q = forecast.qualification;
  return (
    <>
      <p className='vi-note'>
        A forecast for the named observed cohort. Target platform is unspecified; no platform-wide
        conclusion is supported.
      </p>
      <div className='min-w-0 break-words' role='region' aria-label='Stored forecast values'>
        <table className='w-full table-fixed text-sm'>
          <caption className='pb-2 text-left'>
            Forecast · {forecast.target.metric_definition} · {forecast.target.cohort}
          </caption>
          <thead>
            <tr>
              <th scope='col' className={cell}>
                Quantity
              </th>
              <th scope='col' className={cell}>
                Forecast value
              </th>
            </tr>
          </thead>
          <tbody>
            {[
              ['Point estimate', formatForecastNumber(p.point)],
              [
                'Predictive interval · lower (10th percentile)',
                formatForecastNumber(p.quantiles['0.1'])
              ],
              ['Median (50th percentile)', formatForecastNumber(p.quantiles['0.5'])],
              [
                'Predictive interval · upper (90th percentile)',
                formatForecastNumber(p.quantiles['0.9'])
              ]
            ].map(([label, value]) => (
              <tr key={label}>
                <th scope='row' className={cell}>
                  {label}
                </th>
                <td className={cell}>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className='mt-3 space-y-2 text-sm break-words'>
        <div>
          <dt>Forecast target window</dt>
          <dd>
            <Time value={forecast.target_start} /> – <Time value={forecast.horizon_end} /> (
            {forecast.target.horizon_steps} × {forecast.target.bin_hours} hours)
          </dd>
        </div>
      </dl>
      <details className='mt-3 text-sm'>
        <summary className='rafii-focus cursor-pointer rounded-sm'>
          Calibration and qualification
        </summary>
        <dl className='mt-3 space-y-2 text-sm break-words'>
          <div>
            <dt>Observed-sample frame</dt>
            <dd>{forecast.target.frame_id}</dd>
          </div>
          <div>
            <dt>Source training cutoff</dt>
            <dd>
              <Time value={forecast.training_cutoff} />
            </dd>
          </div>
          <div>
            <dt>Forecast issued</dt>
            <dd>
              <Time value={forecast.issued_at} />
            </dd>
          </div>
          <div>
            <dt>Evidence expires</dt>
            <dd>
              <Time value={forecast.expires_at} />
            </dd>
          </div>
          <div>
            <dt>Method / feature version</dt>
            <dd>
              {forecast.method_bundle.version} / {forecast.method_bundle.feature_version}
            </dd>
          </div>
          <div>
            <dt>Admission version</dt>
            <dd>{forecast.method.version}</dd>
          </div>
        </dl>
        <p className='mt-2'>
          {q.paired_count} paired predictions across {q.episode_count} episodes; evaluation cutoff{' '}
          <Time value={q.evaluation_cutoff} />.
        </p>
        <p>
          Observed interval coverage:{' '}
          {formatForecastNumber(q.metrics.local_linear_count.interval_coverage * 100)}%; nominal
          coverage: 80%. Coverage tolerance: {formatForecastNumber(q.gate.coverage_tolerance * 100)}{' '}
          percentage points.
        </p>
        <p>
          MAE: {formatForecastNumber(q.metrics.local_linear_count.mae)}. Better simple baseline:{' '}
          {words(q.better_simple_baseline)}.
        </p>
        <p>
          Paired improvement interval: {formatForecastNumber(q.improvement_interval.lower)}–
          {formatForecastNumber(q.improvement_interval.upper)} (95% episode block bootstrap;{' '}
          {q.improvement_interval.draws} draws).
        </p>
        <p className='break-all'>Qualification digest: {q.qualification_digest}</p>
      </details>
    </>
  );
}
function ForecastSession({
  trend,
  platform,
  workspace
}: VisualAnalysisProps & { workspace: string }) {
  const [requested, setRequested] = useState(false);
  const toggle = useId();
  const context = useTrendContext();
  const trendExpired = useExpired(trend.expires_at);
  const access =
    context.enabled &&
    analysisEnabled(context.flags, 'FORECASTS') &&
    !trendExpired &&
    currentTrend(trend, Date.now());
  const query = useTrendQuery(
    ['visual-forecast', trend.id, trend.trust_receipt_id, platform],
    (api, w, signal) => readBoundForecast(api, w, trend, signal),
    access && requested && !platform,
    'RAFII_TREND_FORECASTS_ENABLED'
  );
  const forecast = selectForecast(query.data, trend, workspace, platform);
  const response = query.data?.response;
  const expired = useExpired(
    firstExpiry(
      trend.expires_at,
      query.data?.binding.expires_at,
      forecast?.expires_at,
      readDeadline(response),
      response?.coverage.freshness_deadline
    )
  );
  let reason = '';
  if (!access) reason = 'Forecasts are disabled or current verified evidence is unavailable.';
  else if (!requested)
    reason = 'Turn on the stored forecast to check current support. No forecast has been loaded.';
  else if (platform)
    reason =
      'The current forecast contract does not identify a target platform. A platform-specific forecast cannot be shown.';
  else if (query.isError)
    reason =
      'No qualified current forecast could be verified. Expired, changed or unsupported results are withheld.';
  else if (query.isFetching || !query.data)
    reason = 'Checking the stored forecast, current receipt and rights…';
  else if (expired || !forecast)
    reason = 'No qualified forecast matches the current receipt, target and retention window.';
  return (
    <section
      className='mt-3 min-w-0 rounded-xl border border-border p-4'
      aria-label='Optional stored forecast'
      aria-busy={access && requested && query.isFetching}
    >
      <h4 className='font-semibold'>Optional forecast</h4>
      <label
        htmlFor={toggle}
        className='rafii-focus mt-2 flex min-h-11 cursor-pointer items-center gap-3 rounded-sm text-sm'
      >
        <input
          id={toggle}
          type='checkbox'
          aria-label='Show stored forecast'
          className='rafii-focus size-5 shrink-0'
          checked={requested}
          disabled={!access}
          onChange={(event) => setRequested(event.target.checked)}
        />
        Show stored forecast
      </label>
      <DemoNotice limitations={[...trend.limitations, ...(response?.limitations ?? [])]} />
      {reason || !forecast ? (
        <Unknown>{reason}</Unknown>
      ) : (
        <>
          <ForecastTable forecast={forecast} />
          <details className='mt-3 text-sm'>
            <summary className='rafii-focus cursor-pointer rounded-sm'>
              Current read and receipt details
            </summary>
            <p className='vi-note'>
              Current analysis and rights read: <Time value={response!.as_of} />. Receipt confirmed:{' '}
              <Time value={query.data!.binding.checked_after} />.
            </p>
          </details>
          {response!.execution_state === 'partial' && (
            <p className='vi-note'>
              Source coverage is partial; the forecast applies only to its declared observed cohort.
            </p>
          )}
          <Limits values={response!.limitations} />
        </>
      )}
    </section>
  );
}
export function ForecastPanel(props: VisualAnalysisProps) {
  const context = useTrendContext();
  // Consent is reset on receipt, platform, workspace, expiry or access changes.
  const key = JSON.stringify([
    context.w,
    props.trend.id,
    props.trend.trust_receipt_id,
    props.trend.expires_at,
    props.platform,
    analysisEnabled(context.flags, 'FORECASTS')
  ]);
  return <ForecastSession key={key} {...props} workspace={context.w} />;
}
