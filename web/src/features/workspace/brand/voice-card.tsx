'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import type { SnapshotState, VoiceProfile } from '@/lib/api/types';
import { ApprovedDate, ExpandableText, SectionUnavailable, type Refetchable } from './brand-parts';
import { TONE_LABELS, toneLabel, voiceStatus } from './voice-model';

function strings(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '') : [];
}

/**
 * The parts of a stored voice profile, as VOICE.md carries them: tone, observations, the sample and unknowns.
 * Shared by the active revision and a proposal waiting for approval.
 */
export function ProfileDetails({ profile, observationsLabel }: { profile: VoiceProfile; observationsLabel: string }) {
  const observations = strings(profile.observations);
  const unknowns = strings(profile.unknowns);
  const sample = typeof profile.writingExample === 'string' ? profile.writingExample.trim() : '';
  const tone = profile.tone ? TONE_LABELS[profile.tone] : undefined;

  return (
    <>
      <div className='flex flex-col gap-1'>
        <span className='text-muted-foreground text-xs'>Starting tone</span>
        <div className='flex flex-wrap items-center gap-2'>
          <Badge variant='secondary'>{toneLabel(profile.tone) ?? 'Not set'}</Badge>
          {tone && <span className='text-muted-foreground text-xs'>{tone.note}</span>}
        </div>
      </div>

      <div className='flex flex-col gap-1.5'>
        <span className='text-muted-foreground text-xs'>{observationsLabel}</span>
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

      <div className='flex flex-col gap-1.5'>
        <span className='text-muted-foreground text-xs'>Your sample</span>
        {sample ? (
          <>
            <ExpandableText as='blockquote' text={sample} lines={6} className='border-l-2 pl-3' />
            {/* memory.py puts the sample in VOICE.md, so every writing route reads it; PostRiff itself never analyses it. */}
            <span className='text-muted-foreground text-[11px] leading-snug'>
              Writing routes read it in VOICE.md as an example of how you write. PostRiff does not analyse it to set the tone or observations.
            </span>
          </>
        ) : (
          <p className='text-muted-foreground'>No sample supplied.</p>
        )}
      </div>

      <div className='flex flex-col gap-1.5'>
        <span className='text-muted-foreground text-xs'>Unknowns kept explicit</span>
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

/** How the workspace sounds: the active revision behind VOICE.md. Read-only here. */
export function VoiceCard({ state, query, isOwner }: { state: SnapshotState | undefined; query: Refetchable; isOwner: boolean }) {
  const status = voiceStatus(state);
  const record = status.kind === 'active' ? status.record : null;
  const profile = record?.profile;

  return (
    <Card data-tour='brand-voice' className='min-w-0'>
      <CardHeader>
        <CardTitle>Voice</CardTitle>
        <CardDescription>
          {record ? (
            <>
              Revision {record.revision} · approved <ApprovedDate iso={record.approvedAt} />. Writing routes receive it as VOICE.md.
            </>
          ) : (
            'How drafts sound. Writing routes receive it as VOICE.md.'
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-5 text-sm'>
        {!profile ? (
          <SectionUnavailable message='The active voice revision could not be read from this workspace.' query={query} />
        ) : (
          <>
            {status.kind === 'active' && status.waiting && (
              <Badge variant='outline' className='w-fit'>
                {isOwner ? 'A proposed revision is waiting for your approval' : 'A proposed revision is waiting for an owner'}
              </Badge>
            )}
            <ProfileDetails profile={profile} observationsLabel='Observations approved with this revision' />
          </>
        )}
      </CardContent>
      <CardFooter>
        <p className='text-muted-foreground text-xs'>Proposing a new revision is not available on this page yet. Every approved revision stays listed under Revisions.</p>
      </CardFooter>
    </Card>
  );
}
