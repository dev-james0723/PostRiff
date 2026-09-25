'use client';

import type { SurfaceMaterial } from '@/components/rafii';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import type { SnapshotState, VoiceProfile } from '@/lib/api/types';
import { ApprovedDate, Caption, ExpandableText, SectionUnavailable, type Refetchable } from './brand-parts';
import { TONE_LABELS, toneLabel, voiceStatus } from './voice-model';

function strings(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '') : [];
}

/**
 * The parts of a stored voice profile, as VOICE.md carries them: tone, observations, the sample and unknowns.
 * Shared by the active revision and a proposal waiting for approval. Generated inference is labelled as such.
 */
export function ProfileDetails({ profile, observationsLabel }: { profile: VoiceProfile; observationsLabel: string }) {
  const observations = strings(profile.observations);
  const unknowns = strings(profile.unknowns);
  const sample = typeof profile.writingExample === 'string' ? profile.writingExample.trim() : '';
  const tone = profile.tone ? TONE_LABELS[profile.tone] : undefined;
  const dimensions = Array.isArray(profile.dimensions) ? profile.dimensions : [];

  return (
    <>
      <div className='flex flex-col gap-1.5'>
        {profile.analysisMethod && (
          <StatusChip icon={profile.analysisMethod === 'ai' ? 'sparkles' : 'ruler'} className='h-auto min-h-7 w-fit max-w-full py-1 whitespace-normal'>
            {profile.analysisMethod === 'ai' ? `AI analysis · ${profile.analysisModel ?? 'managed model'} · needs your review` : 'Local writing statistics (no AI)'}
          </StatusChip>
        )}
        <Caption>Tone</Caption>
        <div className='flex flex-wrap items-center gap-2'>
          <StatusChip icon={null}>{toneLabel(profile.tone) ?? 'Not set'}</StatusChip>
          {tone && <span className='text-muted-foreground text-xs'>{tone.note}</span>}
        </div>
      </div>

      <div className='flex flex-col gap-1.5'>
        <Caption>{observationsLabel}</Caption>
        {observations.length ? (
          <ul className='flex list-disc flex-col gap-1.5 pl-5'>
            {observations.map((item, index) => (
              <li key={index} className='min-w-0'>
                <ExpandableText text={item} lines={4} />
              </li>
            ))}
          </ul>
        ) : (
          <p className='text-muted-foreground'>None recorded.</p>
        )}
      </div>

      {dimensions.length > 0 && (
        <div className='flex flex-col gap-2'>
          <Caption>Evidence</Caption>
          <ul className='flex flex-col gap-2'>
            {dimensions.map((item) => (
              <li key={item.id} className='rafii-quiet rounded-[var(--rafii-radius-control)] p-3'>
                <div className='flex flex-wrap items-center gap-2'>
                  <span className='text-foreground font-medium'>{item.id.replaceAll('_', ' ')}</span>
                  <StatusChip icon={item.evidenceLevel === 'conflicting' ? 'warning' : null} tone={item.evidenceLevel === 'conflicting' ? 'attention' : 'neutral'}>
                    {item.evidenceLevel}
                  </StatusChip>
                </div>
                <p className='mt-1'>{item.observation}</p>
                {item.quotes?.map((quote, index) => (
                  <blockquote key={`${quote.sourceId}-${index}`} className='text-muted-foreground border-foreground/20 mt-2 border-l-2 pl-2 text-xs'>
                    “{quote.text}” <span className='break-all'>— sample {quote.sourceId}</span>
                  </blockquote>
                ))}
                <p className='text-muted-foreground mt-1 text-xs'>
                  {item.support.length} supporting sample{item.support.length === 1 ? '' : 's'}
                  {item.counterEvidence.length ? ` · ${item.counterEvidence.length} conflicting sample${item.counterEvidence.length === 1 ? '' : 's'}` : ''}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className='flex flex-col gap-1.5'>
        <Caption>Your sample</Caption>
        {sample ? (
          <>
            <ExpandableText as='blockquote' text={sample} lines={6} className='border-foreground/20 border-l-2 pl-3' />
            {/* memory.py puts the sample in VOICE.md, so every writing route reads it; analysis-only samples never land here. */}
            <span className='text-muted-foreground text-xs leading-snug'>Every draft reads this sample.</span>
          </>
        ) : (
          <p className='text-muted-foreground'>No sample supplied.</p>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <Caption>Unknowns</Caption>
        {unknowns.length ? (
          <ul className='text-muted-foreground flex list-disc flex-col gap-1 pl-5 text-xs'>
            {unknowns.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className='text-muted-foreground text-xs'>None listed.</p>
        )}
      </div>
    </>
  );
}

/** How the workspace sounds: the active revision behind VOICE.md. Read-only here; a waiting proposal has its own card. */
export function VoiceCard({ state, query, material, className }: { state: SnapshotState | undefined; query: Refetchable; isOwner: boolean; material?: SurfaceMaterial; className?: string }) {
  const status = voiceStatus(state);
  const record = status.kind === 'active' ? status.record : null;
  const profile = record?.profile;

  return (
    <Panel
      data-tour='brand-voice'
      title='Voice'
      titleId='brand-voice-heading'
      description={
        record ? (
          <>
            Revision {record.revision} · approved <ApprovedDate iso={record.approvedAt} />
          </>
        ) : undefined
      }
      material={material}
      className={className}
      bodyClassName='gap-5 text-sm'
    >
      {!profile ? (
        <SectionUnavailable message='Couldn’t load the active voice.' query={query} />
      ) : (
        <ProfileDetails profile={profile} observationsLabel='Observations' />
      )}
    </Panel>
  );
}
