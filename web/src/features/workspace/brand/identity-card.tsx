'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import type { BrandMode, SnapshotState } from '@/lib/api/types';
import { ExpandableText, Field, NotSet, SectionUnavailable, type Refetchable } from './brand-parts';
import { MODE_LABELS } from './voice-model';

function Text({ value }: { value: string | undefined | null }) {
  const text = typeof value === 'string' ? value.trim() : '';
  return text ? <ExpandableText text={text} lines={3} /> : <NotSet />;
}

/** Who speaks, for whom and what for: the brand context behind IDENTITY.md and BRAND.md. Read-only here. */
export function IdentityCard({ state, query }: { state: SnapshotState | undefined; query: Refetchable }) {
  const hub = state?.brandHub;
  const speaker = state?.speaker;
  const you = state?.you as { identitySentence?: unknown } | undefined;
  const mode = hub?.mode ? (hub.mode as BrandMode) : null;
  const sentence = typeof you?.identitySentence === 'string' ? you.identitySentence : '';
  const layers = Array.isArray(hub?.layers) ? hub.layers.filter((layer) => typeof layer === 'string' && layer !== mode) : [];

  return (
    <Card data-tour='brand-identity' className='min-w-0'>
      <CardHeader>
        <CardTitle>Identity</CardTitle>
        <CardDescription>What you are building and for whom. Writing routes receive it as IDENTITY.md.</CardDescription>
      </CardHeader>
      <CardContent>
        {!hub ? (
          <SectionUnavailable message='The brand context could not be read from this workspace.' query={query} />
        ) : (
          <dl className='flex flex-col gap-3'>
            <Field label='Building'>
              {mode ? (
                <span className='flex flex-wrap items-center gap-1.5'>
                  {MODE_LABELS[mode] ?? mode}
                  {layers.map((layer) => (
                    <Badge key={layer} variant='outline'>
                      {layer}
                    </Badge>
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
      </CardContent>
      <CardFooter>
        <p className='text-muted-foreground text-xs'>What you are building, purpose, audience and speaker come from voice setup. Changing them after approval is not available on this page yet.</p>
      </CardFooter>
    </Card>
  );
}
