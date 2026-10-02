'use client';

/**
 * The weekly opportunity brief (PRD R-BRF-01/02) inside Weekly's "This week" tab: 0–3 stored opportunities, each with
 * its source, published/retrieved times, coverage, why it is relevant, a distinct angle, an effort level and one
 * supported action (save as an idea, or accept a trend opportunity with an angle and an account), plus dismiss /
 * not relevant with a reason and restore. Hidden when the deployment has the brief off. English and Traditional
 * Chinese follow the person's language preference (D-022), errors included. Nothing here drafts, schedules or publishes.
 *
 * Focus: an action usually moves its item (into "Already handled", or back), so the card that was clicked unmounts.
 * The brief, which stays mounted, moves focus once the refreshed brief is on screen (`focusAfterAction`).
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Panel } from '@/features/workspace/rafii-parts';
import { ToneChip } from '@/features/coworker/parts';
import { useChannels } from '@/lib/api/hooks';
import { usePreferences } from '@/lib/preferences';
import { formatDate } from '@/lib/time';
import { useInlineForm } from '@/lib/growth-v2/inline-form';
import { idempotencyKey, isFeatureDisabled } from '@/lib/growth-v2/request';
import { useBrief, useBriefAction } from '@/lib/growth-v2/briefs-hooks';
import {
  actionTarget, angleOptions, briefCopy, briefElementId, briefFailure, coverageLine, coverageNote, decisionLabel, focusAfterAction, handledItems,
  itemStatus, loopLocale, optionLabel, outcomeSourceId, reasonCodes, relevanceText, safeHref, timeLine, visibleItems, wantsBrief, type LoopLocale
} from '@/lib/growth-v2/briefs-present';
import type { BriefActionInput, BriefActionKind, BriefCurrent, BriefItem, BriefReasonAction } from '@/lib/growth-v2/briefs-types';

type Copy = ReturnType<typeof briefCopy>;
type Target = { editionId?: string; materialDigest?: string };
type Done = { itemId: string; index: number; action: BriefActionKind; message: string };

export function OpportunityBrief({ canEdit }: { canEdit: boolean }) {
  const brief = useBrief();
  const { locale } = usePreferences();
  const lang = loopLocale(locale);
  const copy = briefCopy(locale);
  // Material digest → the edition an earlier action stored for it: later actions on that version name the edition.
  const stored = useRef(new Map<string, string>());
  const [done, setDone] = useState<Done | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const scrolled = useRef(false);
  const data = brief.data;

  // A brief link (`?brief=1#opportunity-brief`) lands before the brief exists, so the browser can't jump to it: scroll
  // and focus once it has loaded.
  useEffect(() => {
    if (!data || scrolled.current) return;
    scrolled.current = true;
    if (!wantsBrief(window.location.search, window.location.hash)) return;
    const panel = document.getElementById(briefElementId('panel'));
    panel?.scrollIntoView({ block: 'start' });
    panel?.focus({ preventScroll: true });
  }, [data]);

  // After an action the refreshed brief is already rendered (the mutation awaits its refetch): say where the item went
  // and move focus there.
  useEffect(() => {
    if (!done || !data) return;
    const open = visibleItems(data);
    const handled = handledItems(data);
    const inOpen = open.some((item) => item.id === done.itemId);
    const moved = !inOpen && handled.some((item) => item.id === done.itemId) ? copy.movedToHandled : inOpen && done.action === 'restore' ? copy.restored : '';
    setAnnouncement(`${done.message} ${moved}`.trim());
    document.getElementById(focusAfterAction(done, open, handled))?.focus();
    setDone(null);
  }, [done, data, copy]);

  const onDone = useCallback((next: Done) => setDone(next), []);
  const remember = useCallback((digest: string | undefined, editionId: string) => {
    if (digest) stored.current.set(digest, editionId);
  }, []);

  if (brief.isError && isFeatureDisabled(brief.error)) return null;
  if (brief.isPending) return <div lang={lang}><StateMessage kind='loading' title={copy.loading} /></div>;
  if (brief.isError || !data) {
    return (
      <div lang={lang}>
        <StateMessage kind='error' title={copy.error} description={briefFailure(brief.error as { code?: string; status?: number; message?: string } | null, copy, lang)}
                      action={<Button variant='glass' onClick={() => void brief.refetch()}>{copy.retry}</Button>} />
      </div>
    );
  }
  const items = visibleItems(data);
  const handled = handledItems(data);
  const editable = canEdit && data.canAct;
  return (
    <Panel id={briefElementId('panel')} tabIndex={-1} lang={lang} material='glass' title={copy.title} titleId='opportunity-brief-title' eyebrow={copy.items(items.length)}
           description={copy.description} className='rafii-focus scroll-mt-24'>
      <ul className='flex flex-wrap gap-2' aria-label={copy.coverage}>
        {data.coverage.map((source) => (
          <li key={source.source}>
            <ToneChip tone={source.state === 'unavailable' || source.state === 'stale' ? 'attention' : 'neutral'} icon={source.state === 'available' ? 'check' : 'info'}>
              {copy.source[source.source]}: {copy.sourceState[source.state]}
            </ToneChip>
          </li>
        ))}
      </ul>
      <p className='sr-only' role='status'>{announcement}</p>
      {items.length === 0 ? (
        <StateMessage kind={data.dataState === 'unavailable' ? 'unsupported' : 'empty'} layout='inline' title={copy.emptyTitle}
                      description={data.dataState === 'unavailable' ? copy.emptyUnavailable : copy.emptyAvailable} />
      ) : (
        <ol className='flex flex-col gap-3'>
          {items.map((item, index) => (
            <li key={item.id}>
              <BriefItemCard item={item} index={index} list='open' brief={data} lang={lang} canEdit={editable} copy={copy} onDone={onDone} remember={remember}
                             target={() => actionTarget(data.edition, stored.current)} />
            </li>
          ))}
        </ol>
      )}
      {handled.length > 0 && (
        <details className='text-sm'>
          <summary id={briefElementId('handled-summary')} className='rafii-focus min-h-11 cursor-pointer'>{copy.handled} ({handled.length})</summary>
          <p className='text-muted-foreground py-2 text-xs'>{copy.handledNote}</p>
          <ul className='flex flex-col gap-3'>
            {handled.map((item, index) => (
              <li key={item.id}>
                <BriefItemCard item={item} index={index} list='handled' brief={data} lang={lang} canEdit={editable} copy={copy} onDone={onDone} remember={remember}
                               target={() => ({ editionId: item.editionId })} />
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className='text-muted-foreground text-xs'>{copy.storedNote}{!data.canAct && ` ${copy.viewOnly}`}</p>
    </Panel>
  );
}

function BriefItemCard({ item, index, list, brief, lang, target, canEdit, copy, onDone, remember }: {
  item: BriefItem; index: number; list: 'open' | 'handled'; brief: BriefCurrent; lang: LoopLocale; target: () => Target; canEdit: boolean; copy: Copy;
  onDone: (done: Done) => void; remember: (digest: string | undefined, editionId: string) => void;
}) {
  const action = useBriefAction();
  const [mode, setMode] = useState<'idle' | BriefReasonAction | 'accept'>('idle');
  const [failure, setFailure] = useState<string | null>(null);
  // One key and one target per intent, so a retry of the same click is a replay of the same request, never a second action.
  const intents = useRef(new Map<string, { key: string; target: Target }>());
  const [focusId, setFocusId] = useState<string | null>(null);
  const status = itemStatus(item);
  const label = decisionLabel(item, copy);
  const sourceId = outcomeSourceId(item);
  const headingId = briefElementId(list, item.id);
  const prefix = useId();
  const triggerId = (name: string) => `${prefix}-${name}`;

  // Focus returns to the button that opened a picker when it is cancelled.
  useEffect(() => {
    if (!focusId) return;
    document.getElementById(focusId)?.focus();
    setFocusId(null);
  }, [focusId, mode]);

  function close(trigger: string) {
    setMode('idle');
    setFocusId(triggerId(trigger));
  }

  function intentFor(name: string) {
    if (!intents.current.has(name)) intents.current.set(name, { key: idempotencyKey('brief'), target: target() });
    return intents.current.get(name) as { key: string; target: Target };
  }

  async function run(body: Omit<BriefActionInput, 'idempotencyKey' | 'editionId' | 'materialDigest'>, name: string) {
    setFailure(null);
    const intent = intentFor(name);
    try {
      const result = await action.mutateAsync({ itemId: item.id, body: { ...body, ...intent.target, idempotencyKey: intent.key } });
      if (!result.verified) {
        setFailure(copy.unverified);
        return;
      }
      intents.current.delete(name);
      remember(intent.target.materialDigest, result.edition.id);
      const outcome = result.outcome ? copy.savedToast : copy.doneToast;
      toast.success(<span lang={lang}>{outcome}</span>);
      setMode('idle');
      onDone({ itemId: item.id, index, action: body.action, message: outcome });
    } catch (error) {
      const failed = error as { code?: string; status?: number; message?: string };
      // A refusal (4xx) recorded nothing, so the next try is a new request against the brief as it is now; after a
      // network or server failure the action may have landed, so the same key and target replay it.
      if (typeof failed?.status === 'number' && failed.status >= 400 && failed.status < 500) intents.current.delete(name);
      setFailure(briefFailure(failed, copy, lang));
    }
  }

  return (
    <article aria-labelledby={headingId} className='rafii-quiet flex min-w-0 flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <ToneChip tone='neutral' icon={item.kind === 'question' ? 'info' : 'sparkles'}>{copy.kind[item.kind]}</ToneChip>
        <ToneChip tone='neutral' icon='clock'>{copy.stored}</ToneChip>
        <span className='text-muted-foreground text-xs'>{copy.source[item.source]} · {copy.effort[item.effort]}</span>
      </div>
      <h3 id={headingId} tabIndex={-1} className='rafii-focus text-base font-medium break-words' dir='auto'>{item.title}</h3>
      <dl className='grid gap-2 text-sm'>
        <div><dt className='text-muted-foreground text-xs'>{copy.why}</dt><dd>{relevanceText(item, copy)}</dd></div>
        <div><dt className='text-muted-foreground text-xs'>{copy.angle}</dt><dd className='break-words' dir='auto'>{item.angle.text}</dd></div>
        <div><dt className='text-muted-foreground text-xs'>{copy.coverage}</dt><dd>{coverageLine(item, copy)}{coverageNote(item, copy) ? ` — ${coverageNote(item, copy)}` : ''}</dd></div>
      </dl>
      {item.excerpt && <blockquote className='text-muted-foreground border-border border-l-2 pl-3 text-sm' dir='auto'>{item.excerpt}</blockquote>}
      <details className='text-sm'>
        <summary className='rafii-focus min-h-11 cursor-pointer'>{copy.evidence}</summary>
        <ul className='text-muted-foreground flex flex-col gap-1 py-2 text-xs'>
          {item.evidence.map((evidence, position) => {
            const href = safeHref(evidence.url);
            return (
              <li key={position} className='break-words'>
                {href ? <a className='rafii-focus underline underline-offset-4' href={href} target='_blank' rel='noopener noreferrer'>{evidence.label || href}</a>
                      : <span>{evidence.label || evidence.ref}</span>}
                {' · '}{timeLine(evidence, copy, (epoch) => formatDate(epoch))}
              </li>
            );
          })}
          {item.kind === 'whitespace' && <li>{copy.gapEvidence}: {item.gapEvidence.join(', ')}</li>}
          <li>{timeLine(item, copy, (epoch) => formatDate(epoch))}</li>
          {item.limitations.map((limitation) => <li key={limitation} dir='auto'>{limitation}</li>)}
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
        <div><Button variant='quiet' disabled={action.isPending} onClick={() => void run({ action: 'restore' }, 'restore')}>{action.isPending ? copy.working : copy.restore}</Button></div>
      )}
    </article>
  );
}

function ReasonPicker({ codes, copy, pending, title, onCancel, onConfirm }: { codes: string[]; copy: Copy; pending: boolean; title: string; onCancel: () => void; onConfirm: (code: string) => void }) {
  const [code, setCode] = useState(codes[0] ?? 'other');
  const id = useId();
  const { formRef, firstRef } = useInlineForm<HTMLSelectElement>(true, onCancel);
  return (
    <form ref={formRef} className='flex min-w-0 flex-wrap items-end gap-2' aria-label={title} onSubmit={(event) => { event.preventDefault(); onConfirm(code); }}>
      <label className='grid min-w-0 gap-1 text-sm' htmlFor={id}>
        {copy.reason}
        <select id={id} ref={firstRef} className='rafii-focus rafii-quiet min-h-11 w-full max-w-full min-w-0 rounded-xl border border-border px-3 text-base' value={code} onChange={(event) => setCode(event.target.value)}>
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
  const angles = angleOptions(item, copy);
  const [angleId, setAngleId] = useState(angles[0]?.id ?? '');
  const [channelId, setChannelId] = useState('');
  const angleField = useId();
  const accountField = useId();
  const accountNote = useId();
  const chosenChannel = channelId || options[0]?.id || '';
  const chosenAngle = angles.find((angle) => angle.id === angleId);
  const { formRef, firstRef } = useInlineForm<HTMLSelectElement>(true, onCancel);
  return (
    <form ref={formRef} className='grid min-w-0 gap-3 sm:grid-cols-2' aria-label={copy.accept} onSubmit={(event) => { event.preventDefault(); if (angleId && chosenChannel) onConfirm(angleId, chosenChannel); }}>
      <div className='grid min-w-0 gap-1'>
        <label className='grid min-w-0 gap-1 text-sm' htmlFor={angleField}>
          {copy.chooseAngle}
          <select id={angleField} ref={firstRef} className='rafii-focus rafii-quiet min-h-11 w-full max-w-full min-w-0 rounded-xl border border-border px-3 text-base' value={angleId} onChange={(event) => setAngleId(event.target.value)}>
            {angles.map((angle) => <option key={angle.id} value={angle.id}>{optionLabel(angle.text)}</option>)}
          </select>
        </label>
        {chosenAngle && <p className='text-muted-foreground text-xs break-words' dir='auto'><span className='sr-only'>{copy.angleFull}: </span>{chosenAngle.text}</p>}
      </div>
      <div className='grid min-w-0 gap-1'>
        <label className='grid min-w-0 gap-1 text-sm' htmlFor={accountField}>
          {copy.chooseAccount}
          <select id={accountField} aria-describedby={accountNote} disabled={!options.length} className='rafii-focus rafii-quiet min-h-11 w-full max-w-full min-w-0 rounded-xl border border-border px-3 text-base' value={chosenChannel} onChange={(event) => setChannelId(event.target.value)}>
            {options.map((channel) => <option key={channel.id} value={channel.id}>{channel.platform} · {channel.account || channel.id}</option>)}
          </select>
        </label>
        <div id={accountNote} className='text-xs'>
          {channels.isPending ? <p className='text-muted-foreground' role='status'>{copy.accountsLoading}</p>
            : channels.isError ? (
              <p role='alert' className='text-destructive flex flex-wrap items-center gap-2'>
                {copy.accountsError}
                <Button type='button' variant='quiet' onClick={() => void channels.refetch()}>{copy.retry}</Button>
              </p>
            ) : !options.length ? (
              <p className='text-muted-foreground'>{copy.noAccounts} <Link className='rafii-focus underline underline-offset-4' href='/app/channels'>{copy.connectAccount}</Link></p>
            ) : null}
        </div>
      </div>
      <div className='flex flex-wrap gap-2 sm:col-span-2'>
        <Button type='submit' variant='glass' disabled={pending || !angleId || !chosenChannel}>{pending ? copy.working : copy.acceptConfirm}</Button>
        <Button type='button' variant='quiet' onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}
