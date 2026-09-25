'use client';

import type { SurfaceMaterial } from '@/components/rafii';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import type { BrandMode, SnapshotState } from '@/lib/api/types';
import { ExpandableText, Field, NotSet, SectionUnavailable, type Refetchable } from './brand-parts';
import { MODE_LABELS } from './voice-model';

function Text({ value }: { value: string | undefined | null }) {
  const text = typeof value === 'string' ? value.trim() : '';
  return text ? <ExpandableText text={text} lines={3} /> : <NotSet />;
}

/** Who speaks, for whom and what for: the brand context behind IDENTITY.md and BRAND.md. Read-only here; it comes from voice setup. */
export function IdentityCard({ state, query, material, className }: { state: SnapshotState | undefined; query: Refetchable; material?: SurfaceMaterial; className?: string }) {
  const hub = state?.brandHub;
  const speaker = state?.speaker;
  const you = state?.you;
  const mode = hub?.mode ? (hub.mode as BrandMode) : null;
  const sentence = typeof you?.identitySentence === 'string' ? you.identitySentence : '';
  const layers = Array.isArray(hub?.layers) ? hub.layers.filter((layer) => typeof layer === 'string' && layer !== mode) : [];

  return (
    <Panel
      data-tour='brand-identity'
      title='Identity'
      titleId='brand-identity-heading'
      material={material}
      className={className}
    >
      {!hub ? (
        <SectionUnavailable message='Couldn’t load your brand details.' query={query} />
      ) : (
        <dl className='flex flex-col gap-3'>
          <Field label='Building'>
            {mode ? (
              <span className='flex flex-wrap items-center gap-1.5'>
                {MODE_LABELS[mode] ?? mode}
                {layers.map((layer) => (
                  <StatusChip key={layer} icon={null}>
                    {layer}
                  </StatusChip>
                ))}
              </span>
            ) : (
              <NotSet />
            )}
          </Field>
          <Field label='Purpose'>
            <Text value={hub.purpose} />
          </Field>
          <Field label='Audience'>
            <Text value={hub.audience} />
          </Field>
          {(mode !== 'personal' || hub.subject) && (
            <Field label={mode === 'business' ? 'Business' : 'Subject'}>
              <Text value={hub.subject} />
            </Field>
          )}
          <Field label='Speaker'>{speaker ? <Text value={speaker.label} /> : <NotSet>Unavailable</NotSet>}</Field>
          <Field label='Identity sentence'>
            <Text value={sentence} />
          </Field>
        </dl>
      )}
    </Panel>
  );
}
