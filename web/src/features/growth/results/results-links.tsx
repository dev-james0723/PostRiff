'use client';

import { useId, useRef, useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogClose, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Band, FIELD_CLASS, StatusChip } from '@/features/workspace/rafii-parts';
import { errorCode, errorMessage, idempotencyKey } from '@/lib/growth-v2/request';
import { useCreateLink, useLinkAction, useTrackingLinks } from '@/lib/growth-v2/results-hooks';
import type { TrackingLink } from '@/lib/growth-v2/results-types';
import { linkResultsText, type Lang, type ResultsCopy } from './present';
import { useResultsCopy } from './use-results-copy';

type LinkField = 'destination' | 'label' | 'campaign';
const CAMPAIGN = /^[A-Za-z0-9_:-]{1,80}$/;

/** Which field a refusal is about, so only that field is marked invalid. */
function refusedField(code: string | undefined): LinkField | null {
  if (code === 'result_campaign_invalid') return 'campaign';
  if (code === 'result_label_invalid') return 'label';
  if (code === 'link_destination_invalid' || code === 'link_destination_unsafe') return 'destination';
  return null;
}

export function linkUrl(link: TrackingLink): string {
  return link.url ?? (typeof window !== 'undefined' ? window.location.origin + link.path : link.path);
}

function shortDestination(destination: string): string {
  try {
    const url = new URL(destination);
    const path = url.pathname === '/' ? '' : decodeURI(url.pathname);
    return url.hostname + (path.length > 40 ? `${path.slice(0, 39)}…` : path);
  } catch {
    return destination;
  }
}

/** Tracking links: server-made links to the person's own public pages; clicks are clicks, not people. */
export function TrackingLinksView() {
  const { copy, lang } = useResultsCopy();
  const query = useTrackingLinks();
  const [creating, setCreating] = useState(false);
  const pages = query.data?.pages ?? [];
  const items = pages.flatMap((page) => page.items);
  const canEdit = pages[0]?.canEdit ?? false;
  const windowDays = pages[0]?.windowDays ?? 30;
  const copyLink = (link: TrackingLink) =>
    void navigator.clipboard.writeText(linkUrl(link)).then(
      () => toast.success(<span lang={lang}>{copy.links.copied}</span>),
      () => toast.error(<span lang={lang}>{copy.links.copyFailed}</span>)
    );

  return (
    <>
      {canEdit && (
        <div className='flex justify-end'>
          <Button variant='action' size='control' onClick={() => setCreating(true)}>
            <Icons.link /> {copy.links.create}
          </Button>
        </div>
      )}
      {query.isPending ? (
        <StateMessage kind='loading' layout='inline' title={copy.ledger.loading} />
      ) : query.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={copy.unavailableTitle}
          description={errorMessage(query.error)}
          action={
            <Button variant='glass' onClick={() => void query.refetch()}>
              <Icons.refresh /> {copy.retry}
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title={copy.links.empty} description={copy.links.emptyDescription} />
      ) : (
        <ul className='flex flex-col gap-2' aria-label={copy.tabs.links}>
          {items.map((link) => (
            <LinkRow key={link.id} link={link} copy={copy} canEdit={canEdit} onCopy={() => copyLink(link)} />
          ))}
        </ul>
      )}
      {query.hasNextPage && (
        <Button variant='glass' className='self-start' onClick={() => void query.fetchNextPage()} disabled={query.isFetchingNextPage} aria-busy={query.isFetchingNextPage || undefined}>
          {copy.loadMore}
        </Button>
      )}
      <p className='text-muted-foreground text-xs leading-relaxed text-pretty'>
        {copy.links.note} {copy.links.windowNote(windowDays)}
      </p>
      <RafiiDialog open={creating} onOpenChange={setCreating}>
        <RafiiDialogContent size='sm' lang={lang}>{creating && <CreateLink onCopy={copyLink} lang={lang} />}</RafiiDialogContent>
      </RafiiDialog>
    </>
  );
}

function LinkRow({ link, copy, canEdit, onCopy }: { link: TrackingLink; copy: ResultsCopy; canEdit: boolean; onCopy: () => void }) {
  const act = useLinkAction();
  const [problem, setProblem] = useState('');
  // One part per source, never added together (a declared and a reported result are different kinds of evidence).
  const results = linkResultsText(link.associatedResults, copy);

  async function toggle() {
    setProblem('');
    const action = link.status === 'active' ? 'disable' : 'enable';
    try {
      await act.mutateAsync({ id: link.id, action, idempotencyKey: idempotencyKey(`tracking-link-${action}`), expectedRevision: link.revision });
    } catch (error) {
      setProblem(errorMessage(error));
    }
  }

  return (
    <li>
      <Band className='gap-2'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div className='flex min-w-0 flex-wrap items-center gap-2'>
            <span className='text-foreground text-sm font-medium'>{link.label}</span>
            <StatusChip status={link.status === 'active' ? 'success' : 'neutral'}>{link.status === 'active' ? copy.links.on : copy.links.off}</StatusChip>
          </div>
          <div className='flex flex-wrap gap-2'>
            <Button variant='glass' onClick={onCopy} disabled={link.status !== 'active'}>
              <Icons.copy /> {copy.links.copy}
            </Button>
            {canEdit && (
              <Button variant='quiet' onClick={() => void toggle()} disabled={act.isPending} aria-busy={act.isPending || undefined}>
                {link.status === 'active' ? copy.links.turnOff : copy.links.turnOn}
              </Button>
            )}
          </div>
        </div>
        <p className='text-muted-foreground min-w-0 truncate text-xs' title={link.destination}>
          {shortDestination(link.destination)}
          {link.campaignRef ? ` · ${copy.item.campaign}: ${link.campaignRef}` : ''}
        </p>
        <p className='text-foreground text-xs tabular-nums'>
          {copy.links.clicks(link.clicks.counted)}
          <span className='text-muted-foreground'>
            {' · '}
            {copy.links.bots(link.clicks.likelyBot)}
            {results ? ` · ${results}` : ''}
          </span>
        </p>
        {problem && (
          <p role='alert' lang='en' className='text-destructive text-sm'>
            {problem}
          </p>
        )}
      </Band>
    </li>
  );
}

function CreateLink({ onCopy, lang }: { onCopy: (link: TrackingLink) => void; lang: Lang }) {
  const { copy } = useResultsCopy();
  const id = useId();
  const create = useCreateLink();
  const [destination, setDestination] = useState('');
  const [label, setLabel] = useState('');
  const [campaign, setCampaign] = useState('');
  // Our own checks speak the person's language; the server's refusals are English (marked so for assistive technology).
  const [problem, setProblem] = useState<{ field: LinkField | null; message: string; lang: Lang } | null>(null);
  const [made, setMade] = useState<TrackingLink | null>(null);
  const intent = useRef(idempotencyKey('tracking-link-create'));
  // Only the field a refusal is about is marked invalid, and described by the message.
  const invalid = (field: LinkField) => (problem?.field === field ? { 'aria-invalid': true as const, 'aria-errormessage': `${id}-problem` } : {});

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem(null);
    if (campaign.trim() && !CAMPAIGN.test(campaign.trim())) {
      setProblem({ field: 'campaign', message: copy.form.campaignInvalid, lang });
      return;
    }
    try {
      const result = await create.mutateAsync({ destination: destination.trim(), label: label.trim() || null, campaignRef: campaign.trim() || null, idempotencyKey: intent.current });
      setMade(result.link);
    } catch (error) {
      setProblem({ field: refusedField(errorCode(error)), message: errorMessage(error), lang: 'en' });
    }
  }

  if (made) {
    return (
      <>
        <RafiiDialogHeader title={copy.links.created} intro={copy.links.note} closeLabel={copy.secret.done} />
        <RafiiDialogBody className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-made`}>{made.label}</Label>
          <Input id={`${id}-made`} readOnly value={linkUrl(made)} onFocus={(event) => event.currentTarget.select()} className={`${FIELD_CLASS} font-mono text-xs md:text-xs`} />
        </RafiiDialogBody>
        <RafiiDialogFooter className='flex-row justify-end'>
          <Button variant='glass' size='control' onClick={() => onCopy(made)}>
            <Icons.copy /> {copy.links.copy}
          </Button>
          <RafiiDialogClose render={<Button type='button' variant='action' size='control' />}>{copy.secret.done}</RafiiDialogClose>
        </RafiiDialogFooter>
      </>
    );
  }
  return (
    <form onSubmit={(event) => void submit(event)} className='flex min-h-0 flex-1 flex-col'>
      <RafiiDialogHeader title={copy.links.createTitle} intro={copy.links.createIntro} closeLabel={copy.form.cancel} />
      <RafiiDialogBody className='flex flex-col gap-4'>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-destination`}>{copy.links.destination}</Label>
          <Input
            id={`${id}-destination`}
            type='url'
            inputMode='url'
            required
            maxLength={2048}
            placeholder='https://'
            value={destination}
            onChange={(event) => setDestination(event.target.value)}
            className={FIELD_CLASS}
            aria-describedby={`${id}-destination-hint`}
            {...invalid('destination')}
          />
          <p id={`${id}-destination-hint`} className='text-muted-foreground text-xs'>
            {copy.links.destinationHint}
          </p>
        </div>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-label`}>{copy.links.label}</Label>
          <Input id={`${id}-label`} maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} className={FIELD_CLASS} {...invalid('label')} />
        </div>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-campaign`}>{copy.links.campaign}</Label>
          <Input id={`${id}-campaign`} maxLength={80} autoComplete='off' value={campaign} onChange={(event) => setCampaign(event.target.value)} className={FIELD_CLASS} aria-describedby={`${id}-campaign-hint`} {...invalid('campaign')} />
          <p id={`${id}-campaign-hint`} className='text-muted-foreground text-xs'>
            {copy.links.campaignHint}
          </p>
        </div>
        {problem && (
          <p id={`${id}-problem`} role='alert' lang={problem.lang} className='text-destructive text-sm'>
            {problem.message}
          </p>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row justify-end'>
        <RafiiDialogClose render={<Button type='button' variant='quiet' size='control' disabled={create.isPending} />}>{copy.form.cancel}</RafiiDialogClose>
        <Button type='submit' variant='action' size='control' disabled={create.isPending || !destination.trim()} aria-busy={create.isPending || undefined}>
          {create.isPending ? copy.links.creating : copy.links.createButton}
        </Button>
      </RafiiDialogFooter>
    </form>
  );
}
