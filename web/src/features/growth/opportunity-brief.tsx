'use client';

/**
 * The weekly opportunity brief (PRD R-BRF-01/02) inside Weekly's "This week" tab: 0–3 stored opportunities, each with
 * its source, published/retrieved times, coverage, why it is relevant, a distinct angle, an effort level and one
 * supported action (save as an idea, or accept a trend opportunity with an angle and an account), plus dismiss /
 * not relevant with a reason and restore. Hidden when the deployment has the brief off. English and Traditional
 * Chinese follow the person's language preference. Nothing here drafts, schedules or publishes.
 */
import { useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Panel } from '@/features/workspace/rafii-parts';
import { ToneChip } from '@/features/coworker/parts';
import { useChannels } from '@/lib/api/hooks';
import { usePreferences } from '@/lib/preferences';
import { formatDate } from '@/lib/time';
import { errorCode, errorMessage, idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { useBrief, useBriefAction } from '@/lib/growth-v2/briefs-hooks';
import { actionTarget, briefCopy, coverageLine, coverageNote, decisionLabel, itemStatus, outcomeSourceId, reasonCodes, relevanceText, safeHref, timeLine, visibleItems } from '@/lib/growth-v2/briefs-present';
import type { BriefActionInput, BriefCurrent, BriefItem, BriefReasonAction } from '@/lib/growth-v2/briefs-types';

type Copy = ReturnType<typeof briefCopy>;

export function OpportunityBrief({ canEdit }: { canEdit: boolean }) {
  const brief = useBrief();
  const copy = briefCopy(usePreferences().locale);
  if (brief.isError && isFeatureDisabled(brief.error)) return null;
  if (brief.isPending) return <StateMessage kind='loading' title={copy.loading} />;
  if (brief.isError) {
    return <StateMessage kind='error' title={copy.error} description={errorMessage(brief.error)}
                         action={<Button variant='glass' onClick={() => void brief.refetch()}>{copy.retry}</Button>} />;
  }
  const data = brief.data;
  const items = visibleItems(data);
  return (
    <Panel id='opportunity-brief' material='glass' title={copy.title} titleId='opportunity-brief-title' eyebrow={copy.items(items.length)} description={copy.description}>
      <ul className='flex flex-wrap gap-2' aria-label={copy.coverage}>
        {data.coverage.map((source) => (
          <li key={source.source}>
            <ToneChip tone={source.state === 'unavailable' || source.state === 'stale' ? 'attention' : 'neutral'} icon={source.state === 'available' ? 'check' : 'info'}>
              {copy.source[source.source]}: {copy.sourceState[source.state]}
            </ToneChip>
          </li>
        ))}
      </ul>
      {items.length === 0 ? (
        <StateMessage kind={data.dataState === 'unavailable' ? 'unsupported' : 'empty'} layout='inline' title={copy.emptyTitle}
                      description={data.dataState === 'unavailable' ? copy.emptyUnavailable : copy.emptyAvailable} />
      ) : (
        <ol className='flex flex-col gap-3'>
          {items.map((item) => <li key={item.id}><BriefItemCard item={item} brief={data} canEdit={canEdit && data.canAct} copy={copy} /></li>)}
        </ol>
      )}
      <p className='text-muted-foreground text-xs'>{copy.storedNote}{!data.canAct && ` ${copy.viewOnly}`}</p>
    </Panel>
  );
}

function BriefItemCard({ item, brief, canEdit, copy }: { item: BriefItem; brief: BriefCurrent; canEdit: boolean; copy: Copy }) {
  const action = useBriefAction();
  const [mode, setMode] = useState<'idle' | BriefReasonAction | 'accept'>('idle');
  const [failure, setFailure] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());
  const [focusId, setFocusId] = useState<string | null>(null);
  const status = itemStatus(item);
  const label = decisionLabel(item, copy);
  const sourceId = outcomeSourceId(item);
  const headingId = useId();
  const triggerId = (name: string) => `${headingId}-${name}`;

  // Focus follows the work: back to the button that opened a picker on cancel, to the item's heading after a change
  // removed the buttons (the status line announces the outcome).
  useEffect(() => {
    if (!focusId) return;
    document.getElementById(focusId)?.focus();
    setFocusId(null);
  }, [focusId, mode, status]);

  function close(trigger: string) {
    setMode('idle');
    setFocusId(triggerId(trigger));
  }

  function keyFor(intent: string) {
    // One key per intent, so a retry of the same click is a replay, never a second action.
    if (!keys.current.has(intent)) keys.current.set(intent, idempotencyKey('brief'));
    return keys.current.get(intent) as string;
  }

  async function run(body: Omit<BriefActionInput, 'idempotencyKey' | 'editionId' | 'materialDigest'>, intent: string) {
    setFailure(null);
    try {
      const result = await action.mutateAsync({ itemId: item.id, body: { ...body, ...actionTarget(brief.edition), idempotencyKey: keyFor(intent) } });
      if (!result.verified) throw new Error(copy.unverified);
      keys.current.delete(intent);
      setMode('idle');
      setFocusId(headingId);
      toast.success(result.outcome ? copy.savedToast : copy.doneToast);
    } catch (error) {
      const message = errorCode(error) === 'revision_conflict' ? copy.changed : errorMessage(error, copy.unverified);
      setFailure(message);
    }
  }

  return (
    <article aria-labelledby={headingId} className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <ToneChip tone='neutral' icon={item.kind === 'question' ? 'info' : 'sparkles'}>{copy.kind[item.kind]}</ToneChip>
        <ToneChip tone='neutral' icon='clock'>{copy.stored}</ToneChip>
        <span className='text-muted-foreground text-xs'>{copy.source[item.source]} · {copy.effort[item.effort]}</span>
      </div>
      <h3 id={headingId} tabIndex={-1} className='rafii-focus text-base font-medium' dir='auto'>{item.title}</h3>
      <dl className='grid gap-2 text-sm'>
        <div><dt className='text-muted-foreground text-xs'>{copy.why}</dt><dd>{relevanceText(item, copy)}</dd></div>
        <div><dt className='text-muted-foreground text-xs'>{copy.angle}</dt><dd dir='auto'>{item.angle.text}</dd></div>
        <div><dt className='text-muted-foreground text-xs'>{copy.coverage}</dt><dd>{coverageLine(item, copy)}{coverageNote(item, copy) ? ` — ${coverageNote(item, copy)}` : ''}</dd></div>
      </dl>
      {item.excerpt && <blockquote className='text-muted-foreground border-border border-l-2 pl-3 text-sm' dir='auto'>{item.excerpt}</blockquote>}
      <details className='text-sm'>
        <summary className='rafii-focus min-h-11 cursor-pointer'>{copy.evidence}</summary>
        <ul className='text-muted-foreground flex flex-col gap-1 py-2 text-xs'>
          {item.evidence.map((evidence, index) => {
            const href = safeHref(evidence.url);
            return (
              <li key={index}>
                {href ? <a className='rafii-focus underline underline-offset-4' href={href} target='_blank' rel='noopener noreferrer'>{evidence.label || href}</a>
                      : <span>{evidence.label || evidence.ref}</span>}
                {' · '}{timeLine(evidence, copy, (epoch) => formatDate(epoch))}
              </li>
            );
          })}
          {item.kind === 'whitespace' && <li>{copy.gapEvidence}: {item.gapEvidence.join(', ')}</li>}
          <li>{timeLine(item, copy, (epoch) => formatDate(epoch))}</li>
          {item.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
        </ul>
      </details>
      {label && (
        <p className='text-sm' role='status'>
          {label}
          {sourceId && <> · <Link className='rafii-focus underline underline-offset-4' href={`/app/ideas?source=${encodeURIComponent(sourceId)}`}>{copy.openIdea}</Link></>}
        </p>
      )}
      {failure && <p role='alert' className='text-destructive text-sm'>{failure}</p>}
      {canEdit && status === 'open' && mode === 'idle' && (
        <div className='flex flex-wrap gap-2'>
          {item.action.kind === 'save_idea' ? (
            <Button id={triggerId('save')} variant='glass' disabled={action.isPending} onClick={() => void run({ action: 'save_idea' }, 'save_idea')}>{action.isPending ? copy.working : copy.saveIdea}</Button>
          ) : (
            <Button id={triggerId('accept')} variant='glass' onClick={() => setMode('accept')}>{copy.accept}</Button>
          )}
          <Button id={triggerId('dismiss')} variant='quiet' onClick={() => setMode('dismiss')}>{copy.dismiss}</Button>
          <Button id={triggerId('not_relevant')} variant='quiet' onClick={() => setMode('not_relevant')}>{copy.notRelevant}</Button>
        </div>
      )}
      {canEdit && (mode === 'dismiss' || mode === 'not_relevant') && (
        <ReasonPicker codes={reasonCodes(brief, mode)} copy={copy} pending={action.isPending} title={mode === 'dismiss' ? copy.dismiss : copy.notRelevant}
                      onCancel={() => close(mode)}
                      onConfirm={(reasonCode) => void run({ action: mode, reasonCode }, `${mode}:${reasonCode}`)} />
      )}
      {canEdit && mode === 'accept' && (
        <AcceptForm item={item} copy={copy} pending={action.isPending} onCancel={() => close('accept')}
                    onConfirm={(angleId, channelId) => void run({ action: 'accept', angleId, channelId }, `accept:${angleId}:${channelId}`)} />
      )}
      {canEdit && status === 'set_aside' && (
        <div><Button variant='quiet' disabled={action.isPending} onClick={() => void run({ action: 'restore' }, 'restore')}>{copy.restore}</Button></div>
      )}
    </article>
  );
}

function ReasonPicker({ codes, copy, pending, title, onCancel, onConfirm }: { codes: string[]; copy: Copy; pending: boolean; title: string; onCancel: () => void; onConfirm: (code: string) => void }) {
  const [code, setCode] = useState(codes[0] ?? 'other');
  const id = useId();
  return (
    <form className='flex flex-wrap items-end gap-2' aria-label={title} onSubmit={(event) => { event.preventDefault(); onConfirm(code); }}
          onKeyDown={(event) => { if (event.key === 'Escape') onCancel(); }}>
      <label className='grid gap-1 text-sm' htmlFor={id}>
        {copy.reason}
        <select id={id} autoFocus className='rafii-focus rafii-quiet min-h-11 rounded-xl border border-border px-3 text-base' value={code} onChange={(event) => setCode(event.target.value)}>
          {codes.map((value) => <option key={value} value={value}>{copy.reasons[value] ?? value}</option>)}
        </select>
      </label>
      <Button type='submit' variant='glass' disabled={pending}>{pending ? copy.working : copy.confirm}</Button>
      <Button type='button' variant='quiet' onClick={onCancel}>{copy.cancel}</Button>
    </form>
  );
}

function AcceptForm({ item, copy, pending, onCancel, onConfirm }: { item: BriefItem; copy: Copy; pending: boolean; onCancel: () => void; onConfirm: (angleId: string, channelId: string) => void }) {
  const channels = useChannels();
  const platforms = new Set((item.action.platforms ?? []).map((p) => p.toLowerCase()));
  const options = (channels.data?.channels ?? []).filter((c) => !platforms.size || platforms.has(c.platform.toLowerCase()));
  const angles = item.action.angleIds ?? [];
  const [angleId, setAngleId] = useState(angles[0] ?? '');
  const [channelId, setChannelId] = useState('');
  const angleField = useId();
  const accountField = useId();
  const chosenChannel = channelId || options[0]?.id || '';
  return (
    <form className='grid gap-3 sm:grid-cols-2' aria-label={copy.accept} onSubmit={(event) => { event.preventDefault(); if (angleId && chosenChannel) onConfirm(angleId, chosenChannel); }}
          onKeyDown={(event) => { if (event.key === 'Escape') onCancel(); }}>
      <label className='grid gap-1 text-sm' htmlFor={angleField}>
        {copy.chooseAngle}
        <select id={angleField} autoFocus className='rafii-focus rafii-quiet min-h-11 rounded-xl border border-border px-3 text-base' value={angleId} onChange={(event) => setAngleId(event.target.value)}>
          {angles.map((value, index) => <option key={value} value={value}>{index === 0 ? item.angle.text : value}</option>)}
        </select>
      </label>
      <label className='grid gap-1 text-sm' htmlFor={accountField}>
        {copy.chooseAccount}
        <select id={accountField} className='rafii-focus rafii-quiet min-h-11 rounded-xl border border-border px-3 text-base' value={chosenChannel} onChange={(event) => setChannelId(event.target.value)}>
          {options.map((channel) => <option key={channel.id} value={channel.id}>{channel.platform} · {channel.account || channel.id}</option>)}
        </select>
      </label>
      <div className='flex flex-wrap gap-2 sm:col-span-2'>
        <Button type='submit' variant='glass' disabled={pending || !angleId || !chosenChannel}>{pending ? copy.working : copy.acceptConfirm}</Button>
        <Button type='button' variant='quiet' onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}
