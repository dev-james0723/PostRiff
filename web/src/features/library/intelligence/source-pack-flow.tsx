'use client';

import { useId, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useModelChoice } from '@/features/agent/use-model';
import { ApiError } from '@/lib/api/client';
import { keys, useModels, useSnapshot } from '@/lib/api/hooks';
import type { ActionEnvelope, AssetRef, LibraryReturnTo, LibraryScope, PackChange, SourcePack, TaskContext } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import {
  PACK_LIMITS,
  allEntryKeys,
  attachEnvelope,
  buildReturnTo,
  composerTurn,
  createPackEnvelope,
  envelopeDigest,
  packEntryKey,
  packReviewProps,
  packTaskContext,
  readAttachResult,
  taskProblem,
  type AttachReading,
  type LibraryGates,
  type PackDraft
} from '@/lib/library/source-pack';
import type { SourcePackReviewProps } from '@/lib/library/openui-schemas';
import type { LibraryUrlState } from '@/lib/library/url-state';
import { countLabel } from '@/lib/library/wording';
import { useTimeZone } from '@/lib/preferences';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { LibraryTaskHostContext, SourcePackReview, type LibraryTaskHost } from './openui/components';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Where a pack was asked for: the batch bar (the selection) or one item's detail ("Use in draft"). */
export interface PackRequest {
  id: number;
  origin: 'batch' | 'detail';
  refs: AssetRef[];
  titles: string[];
  /** The Library state when the person asked: what the draft hands back (A051). */
  state: LibraryUrlState;
}

const LANGUAGES: { value: string; label: string }[] = [
  { value: '', label: 'From the goal' },
  { value: 'en', label: 'English' },
  { value: 'zh-Hant', label: '繁體中文' },
  { value: 'zh-Hans', label: '简体中文' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'es', label: 'Español' }
];

type Step = 'task' | 'review' | 'saved' | 'attached';

/** A press that didn't get an answer (network, timeout, server error): the same request may be sent again. */
function lostResponse(error: unknown) {
  return !(error instanceof ApiError) || error.status >= 500 || error.status === 0;
}

function messageOf(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Build a task source pack and hand it to a draft (implementation plan T08; A049–A051):
 *   1. the task (goal, optional audience, channels and language) over an explicit scope: the chosen items or the
 *      Library scope in view — never an implicit whole Library;
 *   2. the server's recommendation in the SourcePackReview component, evidence and style apart, each entry with its
 *      locator, reasons and rights in fixed words; the person leaves out what they don't want;
 *   3. `source_pack.create` with exactly those entries; 4. `source_pack.attach` to one draft at the pack's revision —
 *      a conflict lists what changed and offers "Refresh pack", never an automatic retry;
 *   5. the existing writer (`ideas.turn`) with the returned composer fields, reworking that same draft.
 * Every write keeps its idempotency key while its request is unchanged; a failed press becomes "Retry" with that key,
 * and an applied one is done.
 */
export function SourcePackFlow({
  request,
  onClose,
  currentScope,
  gates,
  titleOf,
  onAnnounce,
  onLeave
}: {
  request: PackRequest | null;
  onClose: () => void;
  /** The Library scope in view, offered as the alternative to the chosen items. */
  currentScope: { scope: LibraryScope; label: string };
  gates: LibraryGates;
  titleOf: (assetId: string) => string | null;
  onAnnounce: (message: string) => void;
  /** Called before leaving for the composer: the Library keeps the pack in its address so coming back restores state. */
  onLeave: (packId: string) => Promise<unknown>;
}) {
  return (
    <RafiiDialog open={request !== null} onOpenChange={(open) => (open ? undefined : onClose())}>
      {request ? <FlowBody key={request.id} request={request} onClose={onClose} currentScope={currentScope} gates={gates} titleOf={titleOf} onAnnounce={onAnnounce} onLeave={onLeave} /> : null}
    </RafiiDialog>
  );
}

function FlowBody({
  request,
  onClose,
  currentScope,
  gates,
  titleOf,
  onAnnounce,
  onLeave
}: {
  request: PackRequest;
  onClose: () => void;
  currentScope: { scope: LibraryScope; label: string };
  gates: LibraryGates;
  titleOf: (assetId: string) => string | null;
  onAnnounce: (message: string) => void;
  onLeave: (packId: string) => Promise<unknown>;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const router = useRouter();
  const snapshot = useSnapshot();
  const models = useModels();
  const choice = useModelChoice(models.data, snapshot.data?.state.writerDefaults?.model);
  const timeZone = useTimeZone();
  const id = useId();

  const [step, setStep] = useState<Step>('task');
  const [goal, setGoal] = useState('');
  const [audience, setAudience] = useState('');
  const [channels, setChannels] = useState<string[]>([]);
  const [locale, setLocale] = useState('');
  // The batch bar's items are the selection; when the Library is already scoped to it there is nothing to choose.
  const sameAsCurrent = request.origin === 'batch' && currentScope.scope.kind === 'selection';
  const [where, setWhere] = useState<'chosen' | 'current'>(request.origin === 'batch' || sameAsCurrent ? 'chosen' : 'current');
  const [pending, setPending] = useState<'recommend' | 'create' | 'attach' | 'write' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recommended, setRecommended] = useState<SourcePack | null>(null);
  const [kept, setKept] = useState<Set<string>>(new Set());
  const [saved, setSaved] = useState<SourcePack | null>(null);
  const [draftId, setDraftId] = useState('');
  const [conflict, setConflict] = useState<{ message: string; changes: string[]; raw: PackChange[] } | null>(null);
  const [attached, setAttached] = useState<Extract<AttachReading, { kind: 'applied' }> | null>(null);
  // A press whose answer was lost: the control says Retry and re-sends the same request with the same key.
  const [lost, setLost] = useState<'create' | 'attach' | 'write' | null>(null);
  const lastTask = useRef<TaskContext | null>(null);
  const createKey = useRef<{ digest: string; key: string } | null>(null);
  const attachKey = useRef<{ digest: string; key: string } | null>(null);
  const write = useRef<{ conversationId: string | null; key: string } | null>(null);

  const platforms = useMemo(() => [...new Set((snapshot.data?.state.phase2?.channels ?? []).map((channel) => channel.platform))], [snapshot.data]);
  const drafts = useMemo(
    () =>
      (snapshot.data?.state.variants ?? [])
        .filter((variant) => !variant.rejected)
        .toReversed()
        .slice(0, 20),
    [snapshot.data]
  );
  const draft = drafts.find((variant) => variant.id === draftId) ?? null;
  const tooMany = request.refs.length > PACK_LIMITS.evidence;
  const scope: LibraryScope = where === 'chosen' ? { kind: 'selection', assetRefs: request.refs } : currentScope.scope;
  const versionTitle = (versionId: string) => {
    const pack = saved ?? recommended;
    const evidence = pack?.evidenceRefs.find((entry) => entry.assetRef.versionId === versionId);
    if (evidence) return evidence.title;
    const style = pack?.styleRefs.find((entry) => entry.assetRef.versionId === versionId);
    return style ? titleOf(style.assetRef.assetId) : null;
  };

  async function recommend(task: TaskContext) {
    setPending('recommend');
    setError(null);
    try {
      const pack = await api.libraryRecommendSources(workspaceId, task, buildReturnTo(request.state) as LibraryReturnTo);
      lastTask.current = task;
      setRecommended(pack);
      setKept(new Set(allEntryKeys(pack)));
      setSaved(null);
      setConflict(null);
      setLost(null);
      createKey.current = null;
      attachKey.current = null;
      setStep('review');
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 503 ? 'Source packs aren’t available in this version yet.' : messageOf(failure, 'The source pack couldn’t be built.'));
    } finally {
      setPending(null);
    }
  }

  function findSources() {
    const problem = taskProblem({ goal, audience, locale, channels, selected: request.refs });
    if (problem) {
      setError(problem);
      return;
    }
    void recommend(packTaskContext({ goal, audience, channels, locale, scope, selected: tooMany ? [] : request.refs }) as TaskContext);
  }

  /** "Refresh pack": the same task again, without the refs the conflict named, for the person to review again. */
  function refreshPack() {
    const task = lastTask.current;
    if (!task) return;
    const changed = new Set((conflict?.raw ?? []).map((change) => change.assetRef?.assetId).filter(Boolean));
    void recommend({ ...task, selectedSourceRefs: task.selectedSourceRefs.filter((ref) => !changed.has(ref.assetRef.assetId)) });
  }

  async function savePack() {
    if (!recommended) return;
    const envelope = createPackEnvelope(recommended, kept, buildReturnTo(request.state));
    const digest = envelopeDigest(envelope);
    // The same request keeps its key (a lost answer is replayed, not applied twice); a changed one gets a new key.
    if (!createKey.current || createKey.current.digest !== digest) createKey.current = { digest, key: newIdempotencyKey('lib-pack-create', randomKey) };
    setPending('create');
    setError(null);
    try {
      const result = await api.libraryAction<SourcePack>(workspaceId, { ...envelope, idempotencyKey: createKey.current.key } as ActionEnvelope);
      setLost(null);
      if (result.status === 'applied' && result.result) {
        setSaved(result.result);
        setStep('saved');
        onAnnounce(`Source pack saved with ${countLabel(result.result.evidenceRefs.length, 'evidence source')}.`);
      } else setError(result.warnings?.[0] ?? 'The source pack wasn’t saved.');
    } catch (failure) {
      if (lostResponse(failure)) setLost('create');
      setError(messageOf(failure, 'The source pack wasn’t saved.'));
    } finally {
      setPending(null);
    }
  }

  async function attach() {
    if (!saved || !draft) return;
    const envelope = attachEnvelope(saved, draft.id);
    const digest = envelopeDigest(envelope);
    if (!attachKey.current || attachKey.current.digest !== digest) attachKey.current = { digest, key: newIdempotencyKey('lib-pack-attach', randomKey) };
    setPending('attach');
    setError(null);
    setConflict(null);
    try {
      const result = await api.libraryAction(workspaceId, { ...envelope, idempotencyKey: attachKey.current.key } as ActionEnvelope);
      setLost(null);
      const reading = readAttachResult(result, versionTitle);
      if (reading.kind === 'applied') {
        setAttached(reading);
        setStep('attached');
        onAnnounce('Source pack attached to the draft.');
        void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      } else if (reading.kind === 'conflict') {
        // Shown as it is; nothing is sent again until the person refreshes the pack.
        setConflict({ message: reading.message, changes: reading.changes, raw: ((result.result as { changes?: PackChange[] } | undefined)?.changes ?? []) as PackChange[] });
      } else setError(reading.message);
    } catch (failure) {
      if (lostResponse(failure)) setLost('attach');
      else if (failure instanceof ApiError && failure.status === 409) setConflict({ message: failure.message, changes: [], raw: [] });
      setError(failure instanceof ApiError && failure.status === 409 ? null : messageOf(failure, 'The pack wasn’t attached.'));
    } finally {
      setPending(null);
    }
  }

  async function writeWithSources() {
    const composer = attached?.composer;
    if (!composer || !draft || !saved) return;
    const target: PackDraft = { id: draft.id, platform: draft.platform, language: draft.language, ...(draft.channelId ? { channelId: draft.channelId } : {}) };
    write.current ??= { conversationId: null, key: newIdempotencyKey('lib-pack-write', randomKey) };
    const attempt = write.current;
    setPending('write');
    setError(null);
    try {
      // Kept across a Retry: the same conversation and key, so a turn that started is answered, not started twice.
      const conversationId = attempt.conversationId ?? (await api.createConversation(workspaceId, saved.taskContext.userGoal.slice(0, 60) || 'Draft from the Library')).conversationId;
      attempt.conversationId = conversationId;
      const run = await api.turn(workspaceId, conversationId, {
        ...composerTurn(composer, target, saved.taskContext.userGoal),
        ...(models.isSuccess && choice.requestFields.model ? { model: choice.requestFields.model } : {}),
        timeZone,
        idempotencyKey: attempt.key
      });
      setLost(null);
      if (run.runId) client.setQueryData(['agent-run', workspaceId, run.runId], run);
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.conversations(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.usage(workspaceId) })
      ]);
      // The Library address keeps the pack, so the way back restores the query, scope, filters and selection.
      await onLeave(saved.packId);
      router.push(`/app/agent/${encodeURIComponent(run.conversationId)}`);
    } catch (failure) {
      if (lostResponse(failure)) setLost('write');
      setError(messageOf(failure, 'The draft couldn’t be started.'));
      setPending(null);
    }
  }

  const host: LibraryTaskHost = {
    isSelected: (_ref, key) => (key ? kept.has(key) : false),
    pickable: true,
    writesEnabled: false,
    busyActionId: null,
    outcomeOf: () => undefined,
    draft: (_key, initial) => initial,
    setDraft: () => undefined
  };
  const keptEvidence = recommended ? recommended.evidenceRefs.filter((entry) => kept.has(packEntryKey(entry))).length : 0;
  const keptStyle = recommended ? recommended.styleRefs.filter((entry) => kept.has(packEntryKey(entry))).length : 0;
  const busy = pending !== null;

  return (
    <RafiiDialogContent size='lg'>
      <RafiiDialogHeader
        eyebrow={step === 'task' ? 'Step 1 of 3' : step === 'review' ? 'Step 2 of 3' : 'Step 3 of 3'}
        title={step === 'attached' ? 'Attached to your draft' : request.origin === 'detail' ? 'Use in draft' : 'Build source pack'}
        intro={
          step === 'task'
            ? `From ${request.origin === 'detail' ? `“${request.titles[0] ?? 'this item'}”` : countLabel(request.refs.length, 'selected item')}. Evidence and style samples are kept apart; nothing here approves a fact or its rights.`
            : step === 'review'
              ? 'Leave out anything you don’t want. Only what you keep is saved.'
              : undefined
        }
      />
      <RafiiDialogBody className='flex flex-col gap-4'>
        {step === 'task' ? (
          <div className='flex flex-col gap-4'>
            <label htmlFor={`${id}-goal`} className='flex flex-col gap-1.5 text-sm font-medium'>
              What are you making?
              <Input id={`${id}-goal`} value={goal} maxLength={PACK_LIMITS.goal} onChange={(event) => setGoal(event.target.value)} placeholder='A post announcing the spring recital' className='h-11 font-normal' />
            </label>
            <label htmlFor={`${id}-audience`} className='flex flex-col gap-1.5 text-sm font-medium'>
              Who is it for? (optional)
              <Input id={`${id}-audience`} value={audience} maxLength={PACK_LIMITS.audience} onChange={(event) => setAudience(event.target.value)} className='h-11 font-normal' />
            </label>
            {platforms.length ? (
              <fieldset className='flex flex-col gap-1.5'>
                <legend className='mb-1.5 text-sm font-medium'>Channels (optional)</legend>
                <div className='flex flex-wrap gap-2'>
                  {platforms.map((platform) => {
                    const on = channels.includes(platform);
                    return (
                      <Button key={platform} type='button' variant={on ? 'action' : 'glass'} size='control' className='h-11' aria-pressed={on} onClick={() => setChannels(on ? channels.filter((value) => value !== platform) : [...channels, platform])}>
                        {on ? <Icons.check aria-hidden /> : null}
                        {platform}
                      </Button>
                    );
                  })}
                </div>
              </fieldset>
            ) : null}
            <label htmlFor={`${id}-locale`} className='flex flex-col gap-1.5 text-sm font-medium'>
              Language
              <select id={`${id}-locale`} value={locale} onChange={(event) => setLocale(event.target.value)} className='rafii-field rafii-focus h-11 rounded-[var(--rafii-radius-control)] px-3 text-base font-normal md:text-sm'>
                {LANGUAGES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            {!sameAsCurrent ? (
              <fieldset className='flex flex-col gap-1.5'>
                <legend className='mb-1.5 text-sm font-medium'>Where Rafii may look</legend>
                {(
                  [
                    ['chosen', request.origin === 'detail' ? 'Only this item' : `Only the ${countLabel(request.refs.length, 'selected item')}`],
                    ['current', `${currentScope.label}, starting from ${request.origin === 'detail' ? 'this item' : 'your selection'}`]
                  ] as const
                ).map(([value, label]) => (
                  <label key={value} className='flex min-h-11 items-center gap-2 text-sm'>
                    <input type='radio' name={`${id}-where`} value={value} checked={where === value} onChange={() => setWhere(value)} className='size-4' />
                    {label}
                  </label>
                ))}
              </fieldset>
            ) : null}
            {tooMany ? <p className='text-muted-foreground text-xs'>More than {PACK_LIMITS.evidence} items are selected, so Rafii picks the best matches among them.</p> : null}
            {gates.recommendations.reason ? <p className='text-muted-foreground text-xs'>{gates.recommendations.reason}</p> : null}
            {gates.voice.reason ? <p className='text-muted-foreground text-xs'>{gates.voice.reason}</p> : null}
          </div>
        ) : null}

        {step === 'review' && recommended ? (
          <div className='flex flex-col gap-3'>
            <LibraryTaskHostContext.Provider value={host}>
              <SourcePackReview
                {...(packReviewProps(recommended, titleOf) as unknown as SourcePackReviewProps)}
                onAction={(actionId, inputs) => {
                  if (actionId !== 'library.select' || typeof inputs.key !== 'string') return;
                  const entryKey = inputs.key;
                  setKept((current) => {
                    const next = new Set(current);
                    if (inputs.selected === false) next.delete(entryKey);
                    else next.add(entryKey);
                    return next;
                  });
                }}
              />
            </LibraryTaskHostContext.Provider>
            {recommended.rationale.length ? (
              <details className='rafii-quiet rounded-[var(--rafii-radius-card)] px-3 text-sm'>
                <summary className='rafii-focus flex min-h-11 cursor-pointer items-center font-medium'>How Rafii chose these</summary>
                <ul className='flex list-disc flex-col gap-1 pb-3 pl-5'>
                  {recommended.rationale.map((line) => (
                    <li key={line.code}>{line.message}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            {(recommended.warnings ?? []).map((warning) => (
              <p key={warning} className='text-muted-foreground text-xs'>
                {warning}
              </p>
            ))}
            <p className='text-sm' aria-live='polite'>
              Keeping {countLabel(keptEvidence, 'evidence source')} and {countLabel(keptStyle, 'style sample')}.
            </p>
          </div>
        ) : null}

        {step === 'saved' && saved ? (
          <div className='flex flex-col gap-4'>
            <p className='text-sm'>
              Saved: {countLabel(saved.evidenceRefs.length, 'evidence source')} and {countLabel(saved.styleRefs.length, 'style sample')}.
            </p>
            {saved.gaps.length ? (
              <div className='flex flex-col gap-1'>
                <p className='rafii-eyebrow'>Still missing</p>
                <ul className='flex list-disc flex-col gap-1 pl-5 text-sm'>
                  {saved.gaps.map((gap) => (
                    <li key={`${gap.code}-${gap.message}`}>{gap.message}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {saved.rightsWarnings.length ? (
              <div className='flex flex-col gap-1'>
                <p className='rafii-eyebrow'>Rights to check</p>
                <ul className='flex list-disc flex-col gap-1 pl-5 text-sm'>
                  {saved.rightsWarnings.map((note) => (
                    <li key={`${note.code}-${note.message}`}>{note.message}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {drafts.length ? (
              <fieldset className='flex flex-col gap-1'>
                <legend className='mb-1.5 text-sm font-medium'>Attach to which draft?</legend>
                {drafts.map((variant) => (
                  <label key={variant.id} className='rafii-quiet flex min-h-11 items-start gap-2 rounded-[var(--rafii-radius-control)] p-2 text-sm'>
                    <input
                      type='radio'
                      name={`${id}-draft`}
                      value={variant.id}
                      checked={draftId === variant.id}
                      onChange={() => {
                        setDraftId(variant.id);
                        setConflict(null);
                      }}
                      className='mt-1 size-4'
                    />
                    <span className='flex min-w-0 flex-col'>
                      <span className='font-medium'>
                        {variant.platform} · {variant.language}
                      </span>
                      <span className='text-muted-foreground line-clamp-2 text-xs'>{variant.text || 'Empty draft'}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            ) : (
              <div className='flex flex-col gap-2 text-sm'>
                <p>There’s no draft to attach this pack to yet. Write one from Home or Ideas, then come back: the pack stays saved.</p>
                <Link href='/app/ideas' className={cn('self-start', buttonVariants({ variant: 'glass', size: 'control' }))}>
                  Open Ideas
                </Link>
              </div>
            )}
            {conflict ? (
              <div role='alert' className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3 text-sm'>
                <p className='flex items-center gap-1.5 font-medium'>
                  <Icons.warning className='size-4' aria-hidden />
                  {conflict.message}
                </p>
                {conflict.changes.length ? (
                  <ul className='flex list-disc flex-col gap-1 pl-5'>
                    {conflict.changes.map((change) => (
                      <li key={change}>{change}</li>
                    ))}
                  </ul>
                ) : null}
                <p className='text-muted-foreground text-xs'>Nothing was attached. Refresh the pack to review what’s still allowed.</p>
              </div>
            ) : null}
          </div>
        ) : null}

        {step === 'attached' && attached && saved ? (
          <div className='flex flex-col gap-3 text-sm'>
            <p>
              {attached.alreadyAttached ? 'This pack was already attached to' : 'Attached to'} your {draft ? `${draft.platform} draft` : 'draft'}.
              {attached.composer ? ` ${countLabel(attached.composer.sourceIds.length, 'Library source')} go to the writer as reviewable sources.` : ''}
            </p>
            {attached.composer ? <p className='text-muted-foreground text-xs'>Voice: {attached.composer.voiceMode === 'personalized' ? 'writing like you, from your approved examples' : 'neutral'}.</p> : null}
            {attached.warnings.map((warning) => (
              <p key={warning} className='text-muted-foreground text-xs'>
                {warning}
              </p>
            ))}
            <p className='text-muted-foreground text-xs'>{gates.artifacts.enabled ? 'When you accept the draft, it’s saved to your Library with a link to this pack.' : gates.artifacts.reason}</p>
            {attached.composer ? (
              <p className='text-muted-foreground text-xs'>
                Writing uses {models.isLoading ? '…' : models.isError ? 'the workspace’s default writer' : choice.label} and counts like any draft. Coming back to the Library returns you to where you were.
              </p>
            ) : (
              <p className='text-muted-foreground text-xs'>Open the draft from Drafts to keep writing with these sources.</p>
            )}
          </div>
        ) : null}

        {error ? (
          <p role='alert' className='text-destructive text-sm'>
            {error}
          </p>
        ) : null}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row flex-wrap justify-end'>
        <Button variant='glass' size='control' onClick={onClose}>
          {step === 'attached' ? 'Done' : 'Close'}
        </Button>
        {step === 'task' ? (
          <Button variant='action' size='control' disabled={busy || !goal.trim()} onClick={findSources}>
            {pending === 'recommend' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            Find sources
          </Button>
        ) : null}
        {step === 'review' ? (
          <>
            <Button variant='quiet' size='control' disabled={busy} onClick={() => setStep('task')}>
              Back
            </Button>
            <Button variant='action' size='control' disabled={busy || keptEvidence === 0} onClick={() => void savePack()}>
              {pending === 'create' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              {lost === 'create' ? 'Retry' : 'Save source pack'}
            </Button>
          </>
        ) : null}
        {step === 'saved' ? (
          conflict ? (
            <Button variant='action' size='control' disabled={busy} onClick={refreshPack}>
              {pending === 'recommend' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              Refresh pack
            </Button>
          ) : (
            <Button variant='action' size='control' disabled={busy || !draft} onClick={() => void attach()}>
              {pending === 'attach' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              {lost === 'attach' ? 'Retry' : 'Attach to draft'}
            </Button>
          )
        ) : null}
        {step === 'attached' && attached?.composer ? (
          <Button variant='action' size='control' disabled={busy} onClick={() => void writeWithSources()}>
            {pending === 'write' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            {lost === 'write' ? 'Retry' : 'Rework this draft with these sources'}
          </Button>
        ) : null}
      </RafiiDialogFooter>
    </RafiiDialogContent>
  );
}
