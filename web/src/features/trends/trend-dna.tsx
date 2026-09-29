'use client';
import { useId, useRef, useState } from 'react';
import { Surface } from '@/components/rafii';
import { Disclosure } from './disclosure';
import { Metric } from './present';
import type { Dimension } from './visual-model';
import { visualEvent } from './visual-events';
import { useDiagramMotion } from './diagram-motion';

/* oxlint-disable jsx-a11y/no-noninteractive-tabindex -- The chart is intentionally one high-level focus target; dimension details use the semantic buttons below. */

const CENTER_X = 260;
const CENTER_Y = 205;
const OUTER_RADIUS = 124;

const point = (i: number, radius: number) => [
  CENTER_X + Math.sin((i * Math.PI) / 3) * radius,
  CENTER_Y - Math.cos((i * Math.PI) / 3) * radius
];

const plottedPoint = (dimension: Dimension, index: number) =>
  dimension.radius === null ? null : point(index, dimension.radius * OUTER_RADIUS);

const axisValue = (dimension: Dimension) => {
  if (dimension.value === dimension.state) return null;
  // Full values remain in the adjacent semantic table. Long prose here would
  // clip the fixed chart viewBox and duplicate the evidence explanation.
  return dimension.value.length <= 18 ? dimension.value : null;
};

function closedPath(dimensions: Dimension[]) {
  const points = dimensions.map(plottedPoint);
  if (points.some((value) => value === null)) return null;
  return `${points
    .map((value, index) => `${index ? 'L' : 'M'}${value![0]} ${value![1]}`)
    .join(' ')} Z`;
}

function availableEdges(dimensions: Dimension[]) {
  return dimensions.flatMap((dimension, index) => {
    const next = (index + 1) % dimensions.length;
    const start = plottedPoint(dimension, index);
    const end = plottedPoint(dimensions[next], next);
    return start && end ? [`M${start[0]} ${start[1]} L${end[0]} ${end[1]}`] : [];
  });
}

type Comparison = {
  dimensions: Dimension[];
  label: string;
};

export function TrendDNA({
  dimensions,
  compact = false,
  embedded = false,
  title = 'Trend DNA',
  primaryLabel = 'Selected conversation',
  comparison
}: {
  dimensions: Dimension[];
  compact?: boolean;
  embedded?: boolean;
  title?: string;
  primaryLabel?: string;
  comparison?: Comparison;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const id = useId();
  const safeId = id.replaceAll(':', '');
  const diagram = useRef<SVGSVGElement>(null);
  const [replay, setReplay] = useState(0);
  const revision = [...dimensions, ...(comparison?.dimensions ?? [])]
    .map((dimension) => `${dimension.id}:${dimension.state}:${dimension.value}:${dimension.radius}`)
    .join('|');
  const { reduced } = useDiagramMotion(diagram, revision, replay);
  const selectedId = selected ?? (!compact ? (dimensions[0]?.id ?? null) : null);
  const detail = dimensions.find((dimension) => dimension.id === selectedId);
  const profile = dimensions.find((dimension) => dimension.profile)?.profile ?? null;
  const profileEvidenceRefs = [
    ...new Set(dimensions.flatMap((dimension) => dimension.evidenceRefs))
  ];
  const profileCount = dimensions.filter((dimension) => dimension.radius !== null).length;
  const comparisonCount =
    comparison?.dimensions.filter((dimension) => dimension.radius !== null).length ?? 0;
  const hasGeometry = profileCount > 0 || comparisonCount > 0;
  const primaryPath = closedPath(dimensions);
  const comparisonPath = comparison ? closedPath(comparison.dimensions) : null;
  const summary = dimensions
    .map(
      (dimension) =>
        `${dimension.label}: ${dimension.state}${
          dimension.value !== dimension.state ? `; ${dimension.value}` : ''
        }. ${dimension.reason}`
    )
    .join(' ');
  const labels = [
    [260, 18],
    [448, 92],
    [448, 292],
    [260, 350],
    [72, 292],
    [72, 92]
  ];

  const chooseDimension = (dimension: Dimension) => {
    setSelected(dimension.id);
    visualEvent('dna_dimension_opened');
  };

  const content = (
    <>
      <div className='vi-heading'>
        <h3 id={`${id}-title`}>{title}</h3>
        <span className='vi-dna-status'>
          {profile
            ? `Qualified profile · ${profileCount}/6 mapped`
            : `${dimensions.filter((dimension) => dimension.known).length}/6 reported · no shared scale`}
        </span>
        {!compact && (
          <button
            type='button'
            className='rafii-focus vi-replay'
            aria-label='Replay Trend DNA animation'
            disabled={reduced || !hasGeometry}
            onClick={() => setReplay((value) => value + 1)}
          >
            {reduced
              ? 'Motion reduced'
              : hasGeometry
                ? 'Replay profile'
                : 'Profile scale unavailable'}
          </button>
        )}
      </div>
      <p className='vi-note'>
        A six-part fingerprint of the opportunity. Shape appears only when a receipt-bound display
        scale is supplied.
      </p>
      <p id={`${id}-summary`} className='sr-only'>
        {summary}
      </p>
      <div
        className='rafii-focus vi-dna-figure'
        data-selected-dimension={selectedId ?? undefined}
        role='img'
        tabIndex={0}
        aria-label={comparison ? 'Two Trend DNA profiles' : 'Trend DNA profile'}
        aria-describedby={`${id}-summary ${id}-chart-note`}
      >
        <svg ref={diagram} viewBox='0 0 520 410' aria-hidden='true' focusable='false'>
          <defs>
            <linearGradient id={`${safeId}-profile`} x1='0' y1='0' x2='1' y2='1'>
              <stop offset='0' className='vi-dna-gradient-start' />
              <stop offset='1' className='vi-dna-gradient-end' />
            </linearGradient>
          </defs>
          {[OUTER_RADIUS / 3, (OUTER_RADIUS * 2) / 3, OUTER_RADIUS].map((radius) => (
            <polygon
              key={radius}
              points={dimensions.map((_, index) => point(index, radius).join(',')).join(' ')}
              className='vi-dna-grid'
            />
          ))}
          {dimensions.map((dimension, index) => {
            const [x, y] = point(index, OUTER_RADIUS);
            return (
              <path
                key={`${dimension.id}-guide`}
                d={`M${CENTER_X} ${CENTER_Y} L${x} ${y}`}
                className='vi-dna-guide'
                data-dimension={dimension.id}
                data-selected={selectedId === dimension.id}
              />
            );
          })}
          {primaryPath ? (
            <path
              d={primaryPath}
              className='vi-dna-profile vi-dna-profile-primary vi-dna-profile-fill'
              fill={`url(#${safeId}-profile)`}
              data-profile-path='primary'
              data-diagram-path
            />
          ) : (
            availableEdges(dimensions).map((path, index) => (
              <path
                key={`primary-edge-${index}`}
                d={path}
                className='vi-dna-profile vi-dna-profile-primary'
                data-profile-path='primary-partial'
                data-diagram-path
              />
            ))
          )}
          {comparison &&
            (comparisonPath ? (
              <path
                d={comparisonPath}
                className='vi-dna-profile vi-dna-profile-comparison'
                data-profile-path='comparison'
                data-diagram-path
              />
            ) : (
              availableEdges(comparison.dimensions).map((path, index) => (
                <path
                  key={`comparison-edge-${index}`}
                  d={path}
                  className='vi-dna-profile vi-dna-profile-comparison'
                  data-profile-path='comparison-partial'
                  data-diagram-path
                />
              ))
            ))}
          {dimensions.map((dimension, index) => {
            const plotted = plottedPoint(dimension, index);
            const marker = plotted ?? point(index, OUTER_RADIUS);
            const displayedValue = axisValue(dimension);
            return (
              <g
                key={dimension.id}
                data-dimension={dimension.id}
                data-selected={selectedId === dimension.id}
                data-interactive={!compact}
                className='vi-dna-axis'
                onClick={compact ? undefined : () => chooseDimension(dimension)}
              >
                <circle
                  cx={marker[0]}
                  cy={marker[1]}
                  r={selectedId === dimension.id ? 19 : 14}
                  className='vi-dna-halo'
                  aria-hidden='true'
                />
                <circle
                  cx={marker[0]}
                  cy={marker[1]}
                  r={selectedId === dimension.id ? 8 : 6}
                  className='vi-dna-node'
                  data-known={dimension.radius !== null}
                  data-profile-missing={dimension.radius === null}
                  data-diagram-node
                  strokeDasharray={dimension.radius === null ? '2 2' : undefined}
                />
                <text
                  x={labels[index][0]}
                  y={labels[index][1]}
                  textAnchor='middle'
                  className='vi-axis-label'
                >
                  {dimension.shortLabel}
                </text>
                <text
                  x={labels[index][0]}
                  y={labels[index][1] + 21}
                  textAnchor='middle'
                  className={dimension.radius !== null ? 'vi-axis-state' : 'vi-axis-unknown'}
                >
                  {dimension.state}
                </text>
                {displayedValue && (
                  <text
                    x={labels[index][0]}
                    y={labels[index][1] + 40}
                    textAnchor='middle'
                    className='vi-axis-value'
                  >
                    {displayedValue}
                  </text>
                )}
              </g>
            );
          })}
          {comparison?.dimensions.map((dimension, index) => {
            const plotted = plottedPoint(dimension, index);
            const marker = plotted ?? point(index, OUTER_RADIUS);
            return (
              <circle
                key={`${dimension.id}-comparison`}
                cx={marker[0]}
                cy={marker[1]}
                r='4.5'
                className={
                  plotted
                    ? 'vi-dna-comparison-node'
                    : 'vi-dna-comparison-node vi-dna-comparison-missing'
                }
                data-profile-missing={plotted === null}
                data-diagram-node
              />
            );
          })}
        </svg>
      </div>
      {!compact && detail && (
        <section
          id={`${id}-selection`}
          className='vi-dna-selection'
          data-dimension={detail.id}
          data-selected-summary
          aria-live='polite'
          aria-atomic='true'
        >
          <div className='vi-dna-selection-heading'>
            <span className='vi-dna-selection-eyebrow'>Selected dimension</span>
            <p>
              <strong>{detail.label}</strong>
              <span aria-hidden='true'> · </span>
              <span>{detail.state}</span>
            </p>
          </div>
          <p className='vi-dna-selection-meta'>
            <span>{detail.value}</span>
            <span aria-hidden='true'> · </span>
            <span>{detail.layer}</span>
          </p>
          <p className='vi-dna-selection-reason'>
            <strong>Why:</strong> {detail.reason}
          </p>
        </section>
      )}
      <div className='vi-chart-legend' aria-label='Trend DNA legend'>
        {hasGeometry ? (
          <>
            <span>
              <i className='vi-legend-profile' aria-hidden='true' />
              {primaryLabel}
            </span>
            {comparison && (
              <span>
                <i className='vi-legend-profile vi-legend-profile-comparison' aria-hidden='true' />
                {comparison.label}
              </span>
            )}
          </>
        ) : (
          <span>
            <i className='vi-legend-dot' aria-hidden='true' />
            Native value reported; radial position withheld
          </span>
        )}
        <span>
          <i className='vi-legend-dot vi-legend-unknown' aria-hidden='true' />
          Unknown / not scaled
        </span>
      </div>
      <p id={`${id}-chart-note`} className='vi-note vi-dna-trust'>
        {profile
          ? 'Profile geometry, not a virality score. Exact values are shown separately.'
          : 'No qualified shared scale is available. Native values are shown without radial placement.'}
      </p>
      {!compact && (
        <>
          <div className='vi-table-wrap'>
            <table className='vi-dimension-table'>
              <caption className='sr-only'>Trend DNA exact values and evidence layers</caption>
              <thead>
                <tr>
                  <th scope='col'>Dimension</th>
                  <th scope='col'>State / exact value</th>
                  <th scope='col'>Basis</th>
                </tr>
              </thead>
              <tbody>
                {dimensions.map((dimension) => (
                  <tr
                    key={dimension.id}
                    data-dimension={dimension.id}
                    data-selected={selectedId === dimension.id}
                  >
                    <th scope='row'>
                      <button
                        type='button'
                        className='rafii-focus vi-dimension-button'
                        aria-expanded={selectedId === dimension.id}
                        aria-pressed={selectedId === dimension.id}
                        aria-controls={`${id}-selection ${id}-detail`}
                        onClick={() => chooseDimension(dimension)}
                      >
                        <span className='vi-dimension-key' aria-hidden='true' />
                        <span>{dimension.label}</span>
                        {selectedId === dimension.id && (
                          <span className='vi-dimension-selected' aria-hidden='true'>
                            Selected
                          </span>
                        )}
                      </button>
                    </th>
                    <td>
                      <strong>{dimension.state}</strong>
                      {dimension.value !== dimension.state && <small>{dimension.value}</small>}
                    </td>
                    <td>{dimension.layer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div id={`${id}-detail`}>
            {detail && (
              <div className='vi-dimension-detail' data-dimension={detail.id}>
                <h4>{detail.label}</h4>
                <p>{detail.definition}</p>
                <p>{detail.reason}</p>
                {detail.metric && (
                  <dl>
                    <Metric name={detail.label} metric={detail.metric} advanced />
                  </dl>
                )}
                {detail.profile && (
                  <dl className='vi-profile-basis'>
                    <div>
                      <dt>Profile method</dt>
                      <dd>
                        {detail.profile.methodId} / {detail.profile.methodVersion}
                      </dd>
                    </div>
                    <div>
                      <dt>Reference population</dt>
                      <dd>{detail.profile.referencePopulation}</dd>
                    </div>
                    <div>
                      <dt>Profile expires</dt>
                      <dd>{detail.profile.expiresAt}</dd>
                    </div>
                  </dl>
                )}
                <p className='vi-note'>
                  Evidence reference: {detail.evidenceRefs.join(', ') || 'Not supplied'}
                </p>
              </div>
            )}
          </div>
          <Disclosure title='Profile scale & evidence'>
            {profile ? (
              <>
                <dl className='vi-profile-evidence'>
                  <div>
                    <dt>Method ID</dt>
                    <dd>{profile.methodId}</dd>
                  </div>
                  <div>
                    <dt>Method version</dt>
                    <dd>{profile.methodVersion}</dd>
                  </div>
                  <div>
                    <dt>Scale reference</dt>
                    <dd>{profile.scaleRef}</dd>
                  </div>
                  <div>
                    <dt>Reference population</dt>
                    <dd>{profile.referencePopulation}</dd>
                  </div>
                  <div>
                    <dt>Profile expires</dt>
                    <dd>
                      <time dateTime={profile.expiresAt}>{profile.expiresAt}</time>
                    </dd>
                  </div>
                  <div>
                    <dt>Limitations</dt>
                    <dd>{profile.limitations.join('; ') || 'None supplied'}</dd>
                  </div>
                  <div>
                    <dt>Evidence references</dt>
                    <dd>{profileEvidenceRefs.join(', ') || 'Not supplied'}</dd>
                  </div>
                </dl>
                <p>
                  The polygon is visual compression, not a probability or an overall rank. A vertex
                  is plotted only when the stored receipt supplies a versioned display coordinate.
                  Native units, states and evidence stay available in the table.
                </p>
                <p>
                  Unknown is missing support, never zero. It breaks the profile instead of closing
                  it.
                </p>
              </>
            ) : (
              <p>
                No qualified shared scale is available. The frame identifies dimensions only; it
                does not convert native values into radial positions or invent a polygon.
              </p>
            )}
          </Disclosure>
        </>
      )}
    </>
  );

  if (embedded)
    return (
      <section className='vi-dna vi-dna-embedded' aria-labelledby={`${id}-title`}>
        {content}
      </section>
    );
  return (
    <Surface
      as='section'
      material='glass'
      className='vi-dna vi-panel'
      aria-labelledby={`${id}-title`}
    >
      {content}
    </Surface>
  );
}
