'use client';
import { useId, useRef, useState } from 'react';
import { Surface } from '@/components/rafii';
import type { Trend } from '@/lib/coworker/trend-types';
import { timelineData } from './visual-model';
import { date, fieldClass } from './present';
import { Disclosure } from './disclosure';
import { visualEvent } from './visual-events';
import { useDiagramMotion } from './diagram-motion';

export function MomentumCurve({ trend, platform }: { trend: Trend; platform: string }) {
  const units = [...new Set(trend.observed.timeline.map((p) => p.unit))];
  const [selectedUnit, setUnit] = useState(units[0] ?? '');
  const unit = units.includes(selectedUnit) ? selectedUnit : (units[0] ?? '');
  const [hours, setHours] = useState(168);
  const id = useId();
  const points = timelineData(trend, unit, hours, platform);
  const diagram = useRef<SVGSVGElement>(null);
  const [replay, setReplay] = useState(0);
  const { reduced } = useDiagramMotion(diagram, JSON.stringify(points), replay);
  const values = points.flatMap((p) => (p.value === null ? [] : [p.value]));
  const times = points.map((p) => Date.parse(p.at));
  const minTime = Math.min(...times),
    maxTime = Math.max(...times);
  const min = Math.min(0, ...values),
    max = Math.max(0, ...values);
  const x = (at: string) =>
    maxTime === minTime ? 300 : 60 + ((Date.parse(at) - minTime) / (maxTime - minTime)) * 500;
  const y = (value: number) => (max === min ? 130 : 235 - ((value - min) / (max - min)) * 205);
  const segments: string[] = [];
  let segment = '';
  for (const p of points) {
    if (p.value === null) {
      if (segment) segments.push(segment);
      segment = '';
    } else segment += `${segment ? ' L' : 'M'}${x(p.at)} ${y(p.value)}`;
  }
  if (segment) segments.push(segment);
  return (
    <Surface
      as='section'
      material='glass'
      className='vi-momentum vi-panel'
      aria-labelledby={`${id}-title`}
    >
      <div className='vi-heading'>
        <h3 id={`${id}-title`}>Momentum Curve</h3>
        <button
          type='button'
          className='rafii-focus vi-replay'
          aria-label='Replay Momentum animation'
          disabled={reduced || !values.length}
          onClick={() => setReplay((n) => n + 1)}
        >
          {reduced ? 'Motion reduced' : 'Replay animation'}
        </button>
      </div>
      <p className='vi-note'>
        {platform
          ? `${platform}: no platform-specific series is supplied. The combined series is not relabelled as this platform.`
          : 'Actual observation times. Missing windows remain gaps.'}
      </p>
      <div className='vi-chart-controls'>
        <label>
          Measurement
          <select
            className={fieldClass}
            value={unit}
            disabled={!units.length || Boolean(platform)}
            onChange={(e) => {
              setUnit(e.target.value);
              visualEvent('timeline_metric_changed');
            }}
          >
            {units.length ? (
              units.map((u) => (
                <option key={u} value={u}>
                  {u} · reported series
                </option>
              ))
            ) : (
              <option value=''>Unavailable</option>
            )}
          </select>
        </label>
        <label>
          Observed range
          <select
            className={fieldClass}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            <option value={24}>Last 24 hours</option>
            <option value={168}>Last 7 days</option>
          </select>
        </label>
      </div>
      {points.length ? (
        <>
          <svg
            ref={diagram}
            viewBox='0 0 600 290'
            role='img'
            aria-labelledby={`${id}-chart-title ${id}-chart-description`}
            className='vi-timeline-svg'
          >
            <title id={`${id}-chart-title`}>Observed {unit} over actual time</title>
            <desc id={`${id}-chart-description`}>
              {values.length} available readings from {date(points[0].at)} to{' '}
              {date(points.at(-1)!.at)}. {points.length - values.length} gaps. Exact readings and
              provisional states follow in the table. No forecast is shown.
            </desc>
            {[0, 0.5, 1].map((f) => (
              <g key={f}>
                <line
                  x1='60'
                  x2='560'
                  y1={30 + f * 205}
                  y2={30 + f * 205}
                  className='vi-dna-grid'
                />
                <text x='50' y={35 + f * 205} textAnchor='end' className='vi-axis-label'>
                  {Number((max - (max - min) * f).toPrecision(4))}
                </text>
              </g>
            ))}
            {segments.map((d, i) => (
              <path
                key={i}
                d={d}
                className='vi-timeline-line'
                data-observed-segment
                data-diagram-path
              />
            ))}
            {points.map((p, i) =>
              p.value === null ? (
                <g key={i}>
                  <line x1={x(p.at)} x2={x(p.at)} y1='30' y2='235' className='vi-gap-line' />
                  <text x={x(p.at)} y='20' textAnchor='middle' className='vi-axis-label'>
                    Gap
                  </text>
                </g>
              ) : (
                <circle
                  key={i}
                  cx={x(p.at)}
                  cy={y(p.value)}
                  r='6'
                  data-diagram-node
                  className={
                    p.state === 'provisional' ? 'vi-provisional-point' : 'vi-observed-point'
                  }
                />
              )
            )}
            {[points[0], ...(points.length > 1 ? [points.at(-1)!] : [])].map((p, i) => (
              <text
                key={i}
                x={x(p.at)}
                y='267'
                textAnchor={i ? 'end' : 'start'}
                className='vi-axis-label'
              >
                {new Date(p.at).toLocaleString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit'
                })}
              </text>
            ))}
          </svg>
          <div className='vi-chart-legend' aria-label='Momentum legend'>
            <span>
              <i className='vi-legend-dot vi-legend-observed' aria-hidden='true' />
              Observed
            </span>
            <span>
              <i className='vi-legend-dot vi-legend-provisional' aria-hidden='true' />
              Provisional
            </span>
            <span>
              <i className='vi-legend-gap' aria-hidden='true' />
              Missing window
            </span>
          </div>
          <p className='vi-note'>
            {unit} · Observed history only. No qualified forecast is available.
          </p>
          <Disclosure title='Exact timeline readings'>
            <div className='vi-table-wrap'>
              <table>
                <caption>Observed values and missing windows</caption>
                <thead>
                  <tr>
                    <th scope='col'>Time</th>
                    <th scope='col'>Reading</th>
                    <th scope='col'>State / limitation</th>
                  </tr>
                </thead>
                <tbody>
                  {points.map((p, i) => (
                    <tr key={i}>
                      <th scope='row'>
                        <time dateTime={p.at}>{date(p.at)}</time>
                      </th>
                      <td>
                        {p.value === null ? 'Unknown' : `${p.value.toLocaleString()} ${p.unit}`}
                      </td>
                      <td>
                        {p.state} · {p.reason || 'No additional limitation supplied'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Disclosure>
        </>
      ) : (
        <p className='vi-empty'>
          No comparable history in this selection. No curve has been invented.
        </p>
      )}
    </Surface>
  );
}
