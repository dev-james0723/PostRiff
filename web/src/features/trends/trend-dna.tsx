'use client';
import { useId, useState } from 'react';
import { Surface } from '@/components/rafii';
import { Disclosure } from './disclosure';
import { Metric } from './present';
import type { Dimension } from './visual-model';
import { visualEvent } from './visual-events';

const point = (i: number, radius: number) => [
  260 + Math.sin((i * Math.PI) / 3) * radius,
  192 - Math.cos((i * Math.PI) / 3) * radius
];

export function TrendDNA({
  dimensions,
  compact = false
}: {
  dimensions: Dimension[];
  compact?: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const id = useId();
  const detail = dimensions.find((d) => d.id === selected);

  const labels = [
    [260, 29],
    [447, 94],
    [447, 283],
    [260, 356],
    [73, 283],
    [73, 94]
  ];
  return (
    <Surface
      as='section'
      material='glass'
      className='vi-dna vi-panel'
      aria-labelledby={`${id}-title`}
    >
      <div className='vi-heading'>
        <h3 id={`${id}-title`}>Trend DNA</h3>
        <span>Six dimensions</span>
      </div>
      <p className='vi-note'>
        A profile of this opportunity. Every dimension keeps its own evidence.
      </p>
      <button
        type='button'
        className='rafii-focus vi-dna-figure'
        onClick={() => {
          setSelected(dimensions[0].id);
          visualEvent('dna_dimension_opened');
        }}
        aria-label='Trend DNA overview. Six dimensions with exact values and Unknown states in the table below.'
      >
        <svg viewBox='0 0 520 380' aria-hidden='true' focusable='false'>
          {[40, 80, 122].map((r) => (
            <polygon
              key={r}
              points={dimensions.map((_, i) => point(i, r).join(',')).join(' ')}
              className='vi-dna-grid'
            />
          ))}
          {dimensions.map((d, i) => {
            const [x, y] = point(i, 122);
            return (
              <g key={d.id}>
                <path d={`M260 192 L${x} ${y}`} className='vi-dna-grid' />
                <circle
                  cx={x}
                  cy={y}
                  r='6'
                  className='vi-dna-node'
                  strokeDasharray={d.known ? undefined : '2 2'}
                />
                <text
                  x={labels[i][0]}
                  y={labels[i][1]}
                  textAnchor='middle'
                  className='vi-axis-label'
                >
                  {d.shortLabel}
                </text>
                <text
                  x={labels[i][0]}
                  y={labels[i][1] + 23}
                  textAnchor='middle'
                  className={d.known ? 'vi-axis-value' : 'vi-axis-unknown'}
                >
                  {d.value}
                </text>
              </g>
            );
          })}
          <text x='260' y='189' textAnchor='middle' className='vi-center-label'>
            PROFILE
          </text>
          <text x='260' y='208' textAnchor='middle' className='vi-center-note'>
            not a score
          </text>
        </svg>
      </button>
      <p className='vi-note'>
        No shared numerical scale is supplied. The spokes identify dimensions; their length does not
        encode a value. No polygon or missing value is inferred.
      </p>
      {!compact && (
        <>
          <div className='vi-table-wrap'>
            <table className='vi-dimension-table'>
              <caption className='sr-only'>Trend DNA exact values and evidence layers</caption>
              <thead>
                <tr>
                  <th scope='col'>Dimension</th>
                  <th scope='col'>Value / state</th>
                  <th scope='col'>Basis</th>
                </tr>
              </thead>
              <tbody>
                {dimensions.map((d) => (
                  <tr key={d.id}>
                    <th scope='row'>
                      <button
                        type='button'
                        className='rafii-focus vi-dimension-button'
                        aria-expanded={selected === d.id}
                        aria-controls={`${id}-detail`}
                        onClick={() => {
                          setSelected(selected === d.id ? null : d.id);
                          visualEvent('dna_dimension_opened');
                        }}
                      >
                        {d.label}
                      </button>
                    </th>
                    <td>{d.value}</td>
                    <td>{d.layer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div id={`${id}-detail`} aria-live='polite'>
            {detail && (
              <div className='vi-dimension-detail'>
                <h4>{detail.label}</h4>
                <p>{detail.definition}</p>
                <p>{detail.reason}</p>
                {detail.metric && (
                  <dl>
                    <Metric name={detail.label} metric={detail.metric} advanced />
                  </dl>
                )}
                <p className='vi-note'>
                  Evidence reference: {detail.evidenceRefs.join(', ') || 'Not supplied'}
                </p>
              </div>
            )}
          </div>
          <Disclosure title='How Trend DNA works'>
            <p>
              The dimensions describe different kinds of evidence. Raw measured units and model
              assessments cannot be combined into a probability or ranked by polygon area. Unknown
              is an absent measurement, never zero.
            </p>
          </Disclosure>
        </>
      )}
    </Surface>
  );
}
