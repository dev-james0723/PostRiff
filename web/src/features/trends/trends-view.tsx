'use client';
import { useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { StateMessage, SegmentedControl, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useTrendContext, useTrendQuery } from './hooks';
import {
  CoverageDetails,
  DemoNotice,
  EvidenceList,
  Metric,
  QueryContent,
  TrendError,
  date,
  fieldClass
} from './present';
import { Watchlist } from './watches';
import { VisualCollection } from './visual-intelligence';
import { exposurePage } from './opportunity-exposure';
import { Disclosure } from './disclosure';
import { SourcesSummary } from './signal-summary';
import './trends.css';
const tabs = [
  { value: 'for_you', label: 'For You' },
  { value: 'rising', label: 'Picking up' },
  { value: 'breaking', label: 'Breaking out' },
  { value: 'hot', label: 'Active now' },
  { value: 'niche', label: 'Niche' },
  { value: 'platforms', label: 'Platforms' },
  { value: 'language', label: 'Language & Slang' },
  { value: 'watchlist', label: 'Watchlist' }
];
function Quality() {
  const { flags } = useTrendContext();
  const method = useTrendQuery(['methodology'], (a, w, s) => a.methodology(w, s));
  const calibration = useTrendQuery(
    ['calibration'],
    (a, w, s) => a.calibration(w, s),
    true,
    'RAFII_TREND_CALIBRATION_ENABLED'
  );
  return (
    <Surface as='section' className='trend-quality space-y-6' aria-label='Quality and methodology'>
      <h2 className='text-lg font-medium'>How this works</h2>
      <QueryContent query={method}>
        {(data) => (
          <>
            <DemoNotice limitations={method.data?.limitations ?? []} />
            <p>
              Current method: {data.method_id} / {data.version}
            </p>
            <p>{data.summary}</p>
            <h3>Known blind spots</h3>
            <ul>
              {data.blind_spots.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
            <details>
              <summary className='rafii-focus min-h-11 cursor-pointer'>Metric definitions</summary>
              <dl>
                {data.definitions.map((d) => (
                  <div key={d.id}>
                    <dt>
                      {d.id} / {d.version}
                    </dt>
                    <dd>
                      {d.formula} · {d.unit}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          </>
        )}
      </QueryContent>
      {flags.RAFII_TREND_CALIBRATION_ENABLED ? (
        <QueryContent query={calibration}>
          {(data) => (
            <>
              <h3>Calibration · {data.cohort ?? 'Unknown cohort'}</h3>
              {data.state === 'qualified' ? (
                <>
                  <p>
                    {data.evaluated} evaluated predictions · {data.unknown_outcomes} unknown
                    outcomes
                  </p>
                  <dl className='space-y-3'>
                    {Object.entries(data.metrics).map(([k, v]) => (
                      <Metric key={k} name={k} metric={v} advanced />
                    ))}
                  </dl>
                </>
              ) : (
                <p>
                  Not enough comparable history. Calibration is unknown; no accuracy percentage is
                  available.
                </p>
              )}
              <ul>
                {data.limitations.map((l, i) => (
                  <li key={i}>{l}</li>
                ))}
              </ul>
            </>
          )}
        </QueryContent>
      ) : (
        <p>Calibration is not enabled. No overall AI accuracy claim is available.</p>
      )}
    </Surface>
  );
}
function Languages() {
  const { flags } = useTrendContext();
  const query = useTrendQuery(
    ['languages'],
    (a, w, s) => a.languages(w, s),
    true,
    'RAFII_TREND_MODEL_ENRICHMENT_ENABLED'
  );
  if (!flags.RAFII_TREND_MODEL_ENRICHMENT_ENABLED)
    return (
      <StateMessage
        kind='unsupported'
        title='Language interpretation is unavailable'
        description='Source measurements remain available in the other views.'
      />
    );
  return (
    <QueryContent query={query}>
      {(data) =>
        data.length ? (
          <div className='space-y-4'>
            <DemoNotice limitations={query.data?.limitations ?? []} />
            {data.map((p) => (
              <Surface key={p.id} className='trend-language space-y-4'>
                <h2 lang={p.language} dir='auto' className='text-xl'>
                  {p.expression}
                </h2>
                <p>{p.context}</p>
                <p>{p.meaning}</p>
                <p>Uncertainty: {p.uncertainty}</p>
                <EvidenceList evidence={p.evidence} />
              </Surface>
            ))}
          </div>
        ) : (
          <StateMessage kind='empty' title='No language patterns in the available scope' />
        )
      }
    </QueryContent>
  );
}
function RadarResults({ acquisition }: { acquisition: 'none' | 'unverified' | 'active' | 'degraded' }) {
  const [tab, setTab] = useState('for_you');
  const [quality, setQuality] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState({
    query: '',
    platform: '',
    language: '',
    region: '',
    niche: '',
    since: new Date(Date.now() - 7 * 86400000).toISOString()
  });
  const [cursor, setCursor] = useState<string | null>(null);
  const isList = !['language', 'watchlist'].includes(tab) && !quality;
  const trends = useTrendQuery(
    ['list', tab, filters, cursor],
    (a, w, s) => a.list(w, { view: tab, ...filters, ...(cursor ? { cursor } : {}) }, s),
    isList
  );
  const opportunities = useTrendQuery(
    ['opportunities'],
    (a, w, s) => a.opportunities(w, s),
    tab === 'for_you' && !quality
  );
  // The signed page binds the complete server-ordered candidate set, before any visual filtering.
  const page = exposurePage(opportunities.data?.exposure_token, opportunities.data?.data ?? []);
  const changeFilter = (key: keyof typeof filters, value: string) => {
    setCursor(null);
    setFilters((old) => ({ ...old, [key]: value }));
  };
  return (
    <div className='trend-workspace space-y-5'>
      <div className='trend-section-bar'>
        <SegmentedControl
          label='Trend sections'
          pattern='tabs'
          widths='content'
          value={tab}
          onChange={(v) => {
            setTab(v);
            if (v === 'niche') setFilterOpen(true);
            setCursor(null);
            setQuality(false);
          }}
          options={tabs}
          panelIds={
            tabs.map((t) => (t.value === tab && !quality ? 'trends-panel' : undefined)) as string[]
          }
        />
        <Button variant='quiet' aria-expanded={quality} onClick={() => setQuality(!quality)}>
          How this works
        </Button>
      </div>
      {quality ? (
        <Quality />
      ) : (
        <section
          id='trends-panel'
          role='tabpanel'
          aria-label={tabs.find((t) => t.value === tab)?.label}
          className='space-y-5'
        >
          {isList ? (
            <>
              <Surface
                as='form'
                material='canvas'
                padding='none'
                className='trend-filter-bar'
                onSubmit={(e) => {
                  e.preventDefault();
                  changeFilter('query', search.trim());
                }}
              >
                <label className='trend-search'>
                  <span className='sr-only'>Search trends</span>
                  <input
                    aria-label='Search trends'
                    className={fieldClass}
                    placeholder='Search trends…'
                    maxLength={200}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
                <Button type='submit' variant='glass'>
                  Search
                </Button>
                <Button
                  type='button'
                  variant='quiet'
                  aria-expanded={filterOpen}
                  aria-controls='trend-filters'
                  onClick={() => setFilterOpen(!filterOpen)}
                >
                  Filters
                  {[filters.platform, filters.language, filters.niche].filter(Boolean).length
                    ? ` · ${[filters.platform, filters.language, filters.niche].filter(Boolean).length}`
                    : ''}
                </Button>
                <div id='trend-filters' className='trend-filter-fields' hidden={!filterOpen}>
                  <label>
                    Platform
                    <select
                      className={fieldClass}
                      value={filters.platform}
                      onChange={(e) => changeFilter('platform', e.target.value)}
                    >
                      <option value=''>All available platforms</option>
                      {[
                        'bluesky',
                        'mastodon',
                        'reddit',
                        'x',
                        'threads',
                        'tiktok',
                        'instagram',
                        'youtube'
                      ].map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Language
                    <select
                      className={fieldClass}
                      value={filters.language}
                      onChange={(e) => changeFilter('language', e.target.value)}
                    >
                      <option value=''>All available languages</option>
                      <option value='en'>English</option>
                      <option value='zh-Hant'>Traditional Chinese</option>
                      <option value='yue'>Cantonese</option>
                      <option value='mixed'>Mixed language</option>
                    </select>
                  </label>
                  {tab === 'niche' && (
                    <label>
                      Niche
                      <input
                        aria-label='Niche'
                        className={fieldClass}
                        maxLength={100}
                        value={filters.niche}
                        onChange={(e) => changeFilter('niche', e.target.value)}
                      />
                    </label>
                  )}
                  <label>
                    Time range
                    <select
                      className={fieldClass}
                      value={
                        Math.round((Date.now() - Date.parse(filters.since)) / 86400000) > 2
                          ? '7'
                          : '1'
                      }
                      onChange={(e) =>
                        changeFilter(
                          'since',
                          new Date(Date.now() - Number(e.target.value) * 86400000).toISOString()
                        )
                      }
                    >
                      <option value='1'>Last 24 hours</option>
                      <option value='7'>Last 7 days</option>
                    </select>
                  </label>
                </div>
              </Surface>
              <QueryContent query={trends}>
                {(data) => (
                  <>
                    <p className='trend-stored-line'>As of {date(trends.data!.as_of)}</p>
                    <Disclosure className='trend-scope-summary' title='Sources and what’s missing'>
                      <SourcesSummary coverage={trends.data!.coverage} />
                      <Disclosure title='Source details and limits'>
                        <p>Stored results only. No paid refresh has been started.</p>
                        <CoverageDetails
                          coverage={trends.data!.coverage}
                          limitations={trends.data!.limitations}
                        />
                      </Disclosure>
                    </Disclosure>
                    {data.length ? (
                      <VisualCollection
                        trends={data}
                        page={page}
                        opportunities={
                          tab === 'for_you' && !opportunities.isError
                            ? (opportunities.data?.data ?? [])
                            : []
                        }
                      />
                    ) : (
                      <StateMessage
                        kind='empty'
                        title='No matches in the available scope'
                        description={`${acquisition === 'active' ? 'The live Bluesky sample was collected, but no current Trend matches these filters. ' : ''}Filters: ${filters.query || 'any topic'}; ${filters.platform || 'available platforms'}; ${filters.language || 'available languages'}; ${filters.niche || 'all niches'}. Since ${date(filters.since)}. This does not imply platform-wide absence.`}
                      />
                    )}
                    {opportunities.isError && tab === 'for_you' && (
                      <StateMessage
                        kind='partial'
                        title='Workspace opportunities are unavailable'
                        description='The trend evidence above is still available.'
                      />
                    )}
                    <div className='flex flex-wrap gap-3'>
                      {cursor && (
                        <Button variant='glass' onClick={() => setCursor(null)}>
                          Back to first page
                        </Button>
                      )}
                      {trends.data!.next_cursor && (
                        <Button variant='glass' onClick={() => setCursor(trends.data!.next_cursor)}>
                          Next page
                        </Button>
                      )}
                    </div>
                  </>
                )}
              </QueryContent>
            </>
          ) : tab === 'language' ? (
            <Languages />
          ) : (
            <Watchlist />
          )}
        </section>
      )}
    </div>
  );
}
export function TrendsView() {
  const { w, status, beta, enabled } = useTrendContext();
  return (
    <PageContainer
      pageTitle='Social Trends Intel'
      pageDescription='Spot a conversation. Find your next idea.'
      className='trend-radar'
    >
      {status.isError ? (
        <TrendError error={status.error} retry={() => void status.refetch()} />
      ) : status.isPending ? (
        <StateMessage kind='loading' title='Checking trend availability…' />
      ) : !enabled ? (
        <StateMessage
          kind='unsupported'
          title={beta?.state === 'workspace_not_allowlisted' ? 'This workspace is outside the Trend Beta' :
            beta?.state === 'feature_off' ? 'Trend Beta is off' : 'Trend availability could not be verified'}
          description={beta?.state === 'workspace_not_allowlisted'
            ? 'Stored conversations are available only to explicitly admitted workspaces.'
            : beta?.state === 'feature_off' ? 'Conversations will appear here when the feature is enabled.'
              : 'Try again later. No live discovery has been started.'}
        />
      ) : (
        <>
          <p className='text-muted-foreground mb-4 text-sm' data-trend-beta-status>
            {beta?.acquisition === 'active'
              ? 'Beta · A recent bounded Bluesky sample was collected. Source coverage remains limited.'
              : beta?.acquisition === 'degraded'
                ? 'Beta · The Bluesky source is paused or degraded. Stored results remain available.'
                : beta?.acquisition === 'unverified'
                  ? 'Beta · Live Bluesky acquisition is admitted, awaiting a verified collection.'
                  : 'Beta · Stored conversations. Live source acquisition is off.'}
          </p>
          <RadarResults key={w} acquisition={beta?.acquisition ?? 'none'} />
        </>
      )}
    </PageContainer>
  );
}
