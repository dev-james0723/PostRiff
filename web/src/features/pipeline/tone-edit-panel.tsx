'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useModelChoice } from '@/features/agent/use-model';
import { eligibleVoiceSources, manualVoiceAvailable } from '@/features/agent/voice-consent';
import { compareWording } from '@/features/workspace/brand/brain-diff';
import { ApiError } from '@/lib/api/client';
import { createDraftEditsApi, draftEditsDisabled, type DraftEditResult } from '@/lib/api/draft-edits';
import { keys, useAct, useMemory, useModels, useSnapshot } from '@/lib/api/hooks';
import type { Snapshot, SnapshotVariant } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAuth } from '@/lib/auth/session';
import { isImeEvent } from '@/lib/ime';
import { textAttributes } from '@/lib/locales';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import {
  INSTRUCTION_MAX,
  PRESET_TONE_IDS,
  TONE_COPY,
  baseLabel,
  choiceName,
  codePointLength,
  contextHead,
  contextTail,
  draftEditsEnabled,
  editMatches,
  editVoiceMode,
  editRequest,
  fidelityMessage,
  pendingEdit,
  previousRevision,
  relocateSelection,
  requestSignature,
  rewritingText,
  snapSelection,
  toCodePointRange,
  tooLongToEdit,
  violationValues,
  type EditChoice,
  type EditOutcome,
  type PendingEdit,
  type TextRange,
  type ToneCopy,
  type ToneLocale
} from './tone-edit-contract';

/** 44 px targets on the dialog's dense surface. A waiting button stays focusable, so focus never drops to the page. */
const CONTROL = 'h-11 px-4 aria-disabled:pointer-events-none aria-disabled:opacity-50';
/** Unchanged text shown on each side of a change; the rest is identical in both versions. */
const CONTEXT = 90;
/** Long enough to read the toast and reach its Undo. */
const UNDO_MS = 10_000;
/** 409s that mean "what you were looking at is no longer current"; any other 409 keeps the server's own words. */
const STALE = new Set(['workspace_revision_conflict', 'draft_revision_conflict', 'draft_update_unavailable', 'conflict']);

export interface ToneEditPanelProps {
  variant: SnapshotVariant;
  /** The editor's text right now; it differs from the saved draft while there are unsaved changes. */
  text: string;
  /** The editor's selection as UTF-16 offsets into `text`; null when nothing is selected. */
  selection: TextRange | null;
  /** Saves the editor's text and keeps the dialog open; resolves with the saved draft and the workspace revision. */
  save: () => Promise<{ variant: SnapshotVariant; revision: number }>;
  /** Replaces the editor's text. The updater form lets an undo keep what the person typed since. */
  onText: Dispatch<SetStateAction<string>>;
  /** The editor dialog is English-only today; pass a locale to switch every string of this control. */
  locale?: ToneLocale;
}

type Busy = { step: 'saving' | 'writing'; choice: EditChoice } | { step: 'accepting' | 'discarding' | 'undoing' };
/** Where focus goes once the draft is at `revision`: named for a revision so the view of an older one never takes it. */
interface FocusRequest {
  target: 'applied' | 'controls' | 'custom';
  revision: number;
  control?: string;
}
interface Session {
  copy: ToneCopy;
  locale: ToneLocale;
  busy: Busy | null;
  /** What is happening or what just arrived, for the status line and for screen readers. */
  announcement: string;
  problem: string | null;
  notice: string | null;
  /** The passage the next click rewrites; null for the whole draft. */
  passage: TextRange | null;
  tooLong: boolean;
  unsaved: boolean;
  /** A candidate waiting on the draft, unless it changes nothing. */
  candidate: PendingEdit | null;
  /** The server's answer for that candidate (voice, base, check), when this editor asked for it. */
  answer: Partial<DraftEditResult> | null;
  /** A candidate identical to the draft is still in the slot: nothing to compare, only to clear. */
  idle: boolean;
  /** The revision an inline Undo restores, while the draft is exactly the last accepted edit. */
  undoable: number | null;
  instruction: string;
  setInstruction: (value: string) => void;
  focus: FocusRequest | null;
  focused: () => void;
  request: (choice: EditChoice) => void;
  accept: () => void;
  discard: () => void;
  undo: () => void;
}

/**
 * Everything that must outlive a draft revision. Saving unsaved text before an edit bumps the revision, and the
 * view below is keyed by it, so the request in flight, its answer and the custom tone live here instead.
 */
function useToneEdit({ variant, text, selection, save, onText, locale }: Required<ToneEditPanelProps>): Session | null {
  const copy = TONE_COPY[locale];
  const client = useQueryClient();
  const { workspaceId } = useWorkspaceApi();
  const { getToken } = useAuth();
  const edits = useMemo(() => createDraftEditsApi(getToken), [getToken]);
  const snapshot = useSnapshot();
  const act = useAct();
  const models = useModels();
  const access = useWorkspaceAccess();
  const state = snapshot.data?.state;
  // The same writer and voice rules as every other drafting surface: a pinned writer is named, Auto is left to the
  // server, and the approved voice is used only when this writer may read a sample the person approved for it.
  const writer = useModelChoice(models.data, state?.writerDefaults?.model);
  const pinned = models.isSuccess ? writer.requestFields.model : undefined;
  // The voice the draft was written in carries over (`editVoiceMode`): samples this writer may read, or an approved
  // profile without samples for a draft written in it, under the same cloud memory consent as the composer.
  const memory = useMemory();
  const voiceMode = editVoiceMode({
    eligibleSamples: eligibleVoiceSources(state?.sources ?? [], writer.option).length,
    writtenInApprovedVoice: variant.memoryReceipt?.effectiveVoiceMode === 'approved',
    profileUsable: manualVoiceAvailable(state?.speaker, writer.option, memory.data?.egress?.cloud === true && !memory.isRefetchError)
  });

  const [busy, setBusy] = useState<Busy | null>(null);
  const [result, setResult] = useState<{ draftId: string; outcome: EditOutcome } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [instruction, setInstruction] = useState('');
  const [focus, setFocus] = useState<FocusRequest | null>(null);
  const [off, setOff] = useState(false);
  const focused = useCallback(() => setFocus(null), []);
  // One action at a time, also across the re-render a state update needs.
  const working = useRef(false);
  // Keep the key after a lost answer: choosing the same option again picks up that run instead of buying another.
  const inFlight = useRef(new Map<string, string>());

  const passage = selection ? snapSelection(text, selection.start, selection.end) : null;
  const tooLong = tooLongToEdit(text, passage);
  const unsaved = text !== variant.text;
  const pending = pendingEdit(variant);
  const same = pending !== null && (pending.noChange === true || pending.text === variant.text);
  const own = result && result.draftId === variant.id ? result.outcome : null;
  const matched = own && editMatches(own, variant) ? own.edit : null;
  const current = own !== null && own.revision === variant.revision;
  const elsewhere = current && own.edit.status === 'candidate' && own.edit.variantId !== variant.id;
  const gone = current && own.edit.status === 'candidate' && own.edit.variantId === variant.id && !pending;
  const failure = matched?.status === 'failed' ? matched.message || copy.failed : null;
  const settled = same || matched?.status === 'no_change' ? copy.noChange : elsewhere ? copy.newDraft : gone ? copy.gone : null;
  const undoable = variant.editBase?.acceptedRevision === variant.revision ? previousRevision(variant) : null;

  const refetch = () => void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });

  /** The workspace as the edit left it. Never puts an older snapshot over a newer one. */
  function adopt(next: Snapshot | undefined) {
    if (!next || typeof next.revision !== 'number' || !next.state) return refetch();
    client.setQueryData<Snapshot>(keys.snapshot(workspaceId), (held) => (!held || next.revision >= held.revision ? next : held));
    void client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
  }

  /** The server's own words, except for a stale draft: then the latest is loaded and the person is told to choose again. */
  function explain(error: unknown, fallback: string): string {
    if (error instanceof ApiError && error.status === 409) {
      refetch();
      return STALE.has(error.code ?? '') || !error.message ? copy.conflict : error.message;
    }
    return error instanceof ApiError && error.message ? error.message : fallback;
  }

  async function request(choice: EditChoice) {
    const held = snapshot.data;
    if (working.current || !held) return;
    if (choice.mode === 'tone' && choice.tone === 'custom' && !instruction.trim()) {
      setProblem(copy.customMissing);
      setFocus({ target: 'custom', revision: variant.revision });
      return;
    }
    if (tooLong) {
      setProblem(copy.tooLong);
      return;
    }
    working.current = true;
    setProblem(null);
    setNotice(null);
    try {
      let draft = variant;
      let range = passage;
      let workspaceRevision = held.revision;
      if (unsaved) {
        // One click still starts the edit: the unsaved text is saved first, then rewritten.
        setBusy({ step: 'saving', choice });
        try {
          const saved = await save();
          draft = saved.variant;
          workspaceRevision = saved.revision;
        } catch (error) {
          const reason = explain(error, '');
          setProblem(reason ? `${copy.saveFailed} ${reason}` : copy.saveFailed);
          return;
        }
        if (range) {
          // Saving trims the ends of the text; the selection follows its passage or is asked for again.
          range = relocateSelection(text, range, draft.text);
          if (!range) {
            setNotice(copy.selectionLost);
            return;
          }
        }
      }
      const body = editRequest({
        choice,
        instruction,
        variantRevision: draft.revision,
        expectedRevision: workspaceRevision,
        selection: range ? toCodePointRange(draft.text, range.start, range.end) : null,
        voiceMode,
        model: pinned,
        idempotencyKey: ''
      });
      const signature = requestSignature(draft.id, body);
      body.idempotencyKey = inFlight.current.get(signature) ?? crypto.randomUUID();
      inFlight.current.set(signature, body.idempotencyKey);
      setBusy({ step: 'writing', choice });
      try {
        const reply = await edits.request(workspaceId, draft.id, body);
        inFlight.current.delete(signature);
        if (!reply?.edit) {
          refetch();
          setProblem(copy.failed);
          return;
        }
        adopt(reply.snapshot);
        setResult({ draftId: draft.id, outcome: { revision: draft.revision, edit: reply.edit } });
      } catch (error) {
        if (draftEditsDisabled(error)) {
          // Switched off on the server since the catalogue was read: hide the control and read the catalogue again.
          setOff(true);
          void client.invalidateQueries({ queryKey: keys.models });
        } else if (error instanceof ApiError) {
          inFlight.current.delete(signature);
          setProblem(error.code === 'draft_too_long_for_edit' ? copy.tooLong : explain(error, copy.failed));
        } else {
          // No answer (offline, or past the timeout): the writer may still finish, so the draft is read again.
          refetch();
          setProblem(copy.lost);
        }
      }
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  /** Back to an earlier revision as a new one (`variant_restore`). Also runs from the toast after this editor closed. */
  async function restore(variantId: string, variantRevision: number, restoreRevision: number, replaced: string) {
    const held = client.getQueryData<Snapshot>(keys.snapshot(workspaceId));
    if (working.current || !held) return;
    working.current = true;
    setProblem(null);
    setBusy({ step: 'undoing' });
    try {
      const next = await act.mutateAsync({ revision: held.revision, action: 'variant_restore', payload: { variantId, variantRevision, restoreRevision } });
      const restored = next.state.variants?.find((item) => item.id === variantId);
      if (restored) {
        // Only the text the edit put there is replaced; anything typed since stays in the editor.
        onText((typed) => (typed === replaced ? restored.text : typed));
        setFocus({ target: 'controls', revision: restored.revision });
      }
      setResult(null);
      toast.success(copy.restored);
    } catch (error) {
      let reason: string | undefined;
      if (error instanceof ApiError && error.status === 409) {
        refetch();
        reason = error.code === 'draft_revision_conflict' ? copy.restoreStale : copy.sheet.changed;
      } else if (error instanceof ApiError) {
        reason = error.message;
      }
      toast.error(copy.restoreFailed, { description: reason });
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  async function accept() {
    const held = snapshot.data;
    if (working.current || !held || !pending || same || unsaved) return;
    working.current = true;
    setProblem(null);
    setNotice(null);
    setBusy({ step: 'accepting' });
    const before = variant.revision;
    const name = choiceName(pending.edit, locale);
    try {
      const next = await act.mutateAsync({ revision: held.revision, action: 'accept_update', payload: { variantId: variant.id } });
      const saved = next.state.variants?.find((item) => item.id === variant.id);
      setResult(null);
      if (!saved) return;
      onText(saved.text);
      setFocus({ target: 'applied', revision: saved.revision });
      toast.success(copy.applied(name), {
        duration: UNDO_MS,
        action: { label: copy.undo, onClick: () => void restore(variant.id, saved.revision, before, saved.text) }
      });
    } catch (error) {
      setProblem(explain(error, copy.acceptFailed));
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  async function discard() {
    const held = snapshot.data;
    if (working.current || !held || !pending) return;
    working.current = true;
    setProblem(null);
    setBusy({ step: 'discarding' });
    try {
      await act.mutateAsync({ revision: held.revision, action: 'discard_update', payload: { variantId: variant.id } });
      setResult(null);
      setFocus({ target: 'controls', revision: variant.revision, control: pending.edit.mode === 'polish' ? 'polish' : (pending.edit.tone ?? undefined) });
    } catch (error) {
      setProblem(explain(error, copy.discardFailed));
    } finally {
      working.current = false;
      setBusy(null);
    }
  }

  // Server-driven: no catalogue entry, no control. Editors only, and never in the read-only sample workspace.
  if (!draftEditsEnabled(models.data) || off || !checkAccess(access, { permission: 'edit' }) || state?.workspace?.sample === true) return null;

  const announcement = busy
    ? busy.step === 'saving'
      ? copy.saving
      : busy.step === 'writing'
        ? rewritingText(busy.choice, locale)
        : busy.step === 'accepting'
          ? copy.accepting
          : busy.step === 'discarding'
            ? copy.discarding
            : copy.undoing
    : pending && !same
      ? copy.ready(choiceName(pending.edit, locale))
      : (settled ?? notice ?? '');

  return {
    copy,
    locale,
    busy,
    announcement,
    problem: problem ?? failure,
    notice: busy ? null : (settled ?? notice),
    passage,
    tooLong,
    unsaved,
    candidate: pending && !same ? pending : null,
    answer: pending && matched?.status === 'candidate' ? matched : null,
    idle: same,
    undoable,
    instruction,
    setInstruction,
    focus,
    focused,
    request: (choice) => void request(choice),
    accept: () => void accept(),
    discard: () => void discard(),
    undo: () => {
      if (undoable !== null) void restore(variant.id, variant.revision, undoable, variant.text);
    }
  };
}

/**
 * One-click tone and polish edits beside the draft editor. A click asks the writer for a candidate (unsaved text is
 * saved first); the candidate is compared with the current text and replaces it only on "Use this", which can be
 * undone. Hidden entirely while the server has the feature off.
 */
export function ToneEditPanel({ locale = 'en', ...props }: ToneEditPanelProps) {
  const session = useToneEdit({ ...props, locale });
  const titleId = useId();
  if (!session) return null;
  const { variant } = props;
  return (
    <Surface as='section' material='quiet' padding='sm' aria-labelledby={titleId} data-testid='tone-edit' className='relative flex flex-col gap-4'>
      <div>
        <h3 id={titleId} className='font-medium'>
          {session.copy.title}
        </h3>
        <p className='text-muted-foreground text-sm'>{session.copy.intro}</p>
      </div>
      {/* Kept across revisions, so "saving", "rewriting" and "ready" are announced as one sequence. */}
      <p role='status' aria-live='polite' className='sr-only' data-testid='tone-edit-status'>
        {session.announcement}
      </p>
      <ToneEditView key={`${variant.id}:${variant.revision}`} session={session} variant={variant} text={props.text} titleId={titleId} />
    </Surface>
  );
}

function Wording({ label, attributes, children }: { label: string; attributes: ReturnType<typeof textAttributes>; children: ReactNode }) {
  return (
    <div role='group' aria-label={label} className='flex min-w-0 flex-col gap-1'>
      <span aria-hidden className='text-muted-foreground text-xs font-medium'>
        {label}
      </span>
      <p {...attributes} className='rafii-paper rounded-xl p-3 text-sm leading-relaxed break-words whitespace-pre-wrap'>
        {children}
      </p>
    </div>
  );
}

/** Everything that belongs to one revision of the draft; a new revision starts it afresh. */
function ToneEditView({ session, variant, text, titleId }: { session: Session; variant: SnapshotVariant; text: string; titleId: string }) {
  const { copy, locale, busy, passage, candidate, answer, focus, focused } = session;
  const root = useRef<HTMLDivElement>(null);
  const scopeId = useId();
  const limitId = useId();
  const customId = useId();
  const appliedId = useId();
  const candidateId = useId();
  const unsavedId = useId();
  const authored = textAttributes(variant.language);
  const blocked = Boolean(busy) || session.tooLong;

  // Focus follows what just happened: the note with Undo after "Use this", the tone buttons after a discard or an
  // undo, the field when a custom tone is missing. The button that was pressed is gone by then.
  useEffect(() => {
    if (!focus || focus.revision !== variant.revision) return;
    const within = (selector: string) => root.current?.querySelector<HTMLElement>(selector) ?? null;
    const control = focus.control ? within(`[data-tone-control="${CSS.escape(focus.control)}"]`) : null;
    const target = (focus.target === 'applied' ? within('[data-tone-focus="applied"]') : focus.target === 'custom' ? within('[data-tone-focus="custom"]') : control) ?? within('[data-tone-control]');
    target?.focus();
    focused();
  }, [focus, focused, variant.revision]);

  const selected = passage ? text.slice(passage.start, passage.end) : '';
  const diff = candidate ? compareWording(variant.text, candidate.text) : null;
  const violations = (answer?.fidelity ?? candidate?.fidelity)?.violations ?? [];
  const checked = (answer?.fidelity ?? candidate?.fidelity)?.checked;
  const base = answer?.base ?? (candidate?.edit.baseKind ? { kind: candidate.edit.baseKind, revision: candidate.edit.baseRevision } : null);
  const voice = answer?.voice?.effective;

  return (
    <div ref={root} className='flex flex-col gap-4'>
      {session.undoable !== null && (
        <div
          role='group'
          aria-labelledby={appliedId}
          tabIndex={-1}
          data-tone-focus='applied'
          className='rafii-paper focus-visible:ring-ring/50 flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2 text-sm outline-none focus-visible:ring-3'
        >
          <span id={appliedId}>{copy.appliedNote}</span>
          <Button type='button' variant='quiet' className={CONTROL} disabled={Boolean(busy)} focusableWhenDisabled onClick={session.undo}>
            <Icons.history data-icon='inline-start' />
            {copy.undo}
          </Button>
        </div>
      )}

      <div className='flex flex-col gap-1'>
        <p id={scopeId} className='text-sm'>
          <span className='text-muted-foreground'>{copy.scopeLabel} </span>
          <span className='font-medium'>{passage ? copy.scopeSelection : copy.scopeDraft}</span>
          {passage && <span className='text-muted-foreground'> · {copy.characters(codePointLength(selected))}</span>}
        </p>
        {session.tooLong ? (
          <p id={limitId} className='text-sm'>
            {copy.tooLong}
          </p>
        ) : passage ? (
          <blockquote {...authored} className='text-muted-foreground line-clamp-2 border-s-2 ps-3 text-xs break-words'>
            {contextHead(selected.replace(/\s+/g, ' '), 140)}
          </blockquote>
        ) : (
          <p className='text-muted-foreground text-xs'>{copy.scopeHint}</p>
        )}
      </div>

      <div role='group' aria-labelledby={titleId} aria-describedby={session.tooLong ? `${scopeId} ${limitId}` : scopeId} className='flex flex-wrap gap-2'>
        {PRESET_TONE_IDS.map((tone) => (
          <Button key={tone} type='button' variant='glass' className={CONTROL} data-tone-control={tone} disabled={blocked} focusableWhenDisabled onClick={() => session.request({ mode: 'tone', tone })}>
            {copy.tones[tone]}
          </Button>
        ))}
        <Button type='button' variant='glass' className={CONTROL} data-tone-control='polish' disabled={blocked} focusableWhenDisabled onClick={() => session.request({ mode: 'polish' })}>
          <Icons.sparkles data-icon='inline-start' />
          {copy.polish}
        </Button>
      </div>

      <div className='flex flex-col gap-2 sm:flex-row sm:items-end'>
        <label htmlFor={customId} className='flex min-w-0 flex-1 flex-col gap-2 text-sm'>
          {copy.customLabel}
          <Input
            id={customId}
            data-tone-focus='custom'
            dir='auto'
            value={session.instruction}
            maxLength={INSTRUCTION_MAX}
            placeholder={copy.customPlaceholder}
            className='h-11'
            onChange={(event) => session.setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' || isImeEvent(event)) return;
              event.preventDefault();
              if (!blocked) session.request({ mode: 'tone', tone: 'custom' });
            }}
          />
        </label>
        <Button type='button' variant='glass' className={CONTROL} data-tone-control='custom' disabled={blocked} focusableWhenDisabled onClick={() => session.request({ mode: 'tone', tone: 'custom' })}>
          {copy.customApply}
        </Button>
      </div>

      {busy && (
        <div className='flex items-start gap-2 text-sm'>
          <Icons.spinner aria-hidden className='text-muted-foreground mt-0.5 size-4 shrink-0 animate-spin motion-reduce:animate-none' />
          <p className='min-w-0'>
            {session.announcement}
            {(busy.step === 'saving' || busy.step === 'writing') && <span className='text-muted-foreground block text-xs'>{copy.untouched}</span>}
          </p>
        </div>
      )}
      {session.problem && (
        <p role='alert' className='text-destructive text-sm'>
          {session.problem}
        </p>
      )}
      {session.notice && <p className='text-sm'>{session.notice}</p>}
      {session.idle && !busy && (
        <Button type='button' variant='glass' className={`${CONTROL} self-start`} focusableWhenDisabled onClick={session.discard}>
          {copy.discard}
        </Button>
      )}

      {candidate && diff && (
        <section aria-labelledby={candidateId} data-testid='tone-candidate' className='flex flex-col gap-3'>
          <h4 id={candidateId} className='font-medium'>
            {copy.suggestionTitle}
            <span className='text-muted-foreground font-normal'>
              {' '}
              · {choiceName(candidate.edit, locale)} · {candidate.edit.scope === 'selection' || candidate.edit.selection ? copy.scopeSelection : copy.scopeDraft}
            </span>
          </h4>
          {/* Side by side from the dialog's full width; one above the other on a phone. */}
          <div className='grid gap-3 sm:grid-cols-2'>
            <Wording label={copy.current} attributes={authored}>
              {contextTail(diff.prefix, CONTEXT)}
              {diff.removed && (
                <del className='decoration-muted-foreground/70 text-muted-foreground'>
                  <span className='sr-only'>{copy.removedPrefix}</span>
                  {diff.removed}
                </del>
              )}
              {contextHead(diff.suffix, CONTEXT)}
            </Wording>
            <Wording label={copy.suggested} attributes={authored}>
              {contextTail(diff.prefix, CONTEXT)}
              {diff.changed && (
                <mark className='bg-primary/15 text-foreground decoration-primary/50 rounded underline underline-offset-4'>
                  <span className='sr-only'>{copy.changedPrefix}</span>
                  {diff.changed}
                </mark>
              )}
              {contextHead(diff.suffix, CONTEXT)}
            </Wording>
          </div>
          {violations.length > 0 ? (
            <div className='rafii-paper rounded-xl p-3 text-sm'>
              <h5 className='font-medium'>{copy.fidelityTitle}</h5>
              <ul className='mt-1 flex list-disc flex-col gap-1 ps-5'>
                {violations.map((item, index) => {
                  const values = violationValues(item.detail);
                  return (
                    <li key={`${item.code}-${index}`}>
                      {fidelityMessage(item.code, locale)}
                      {values.length > 0 && (
                        <span dir='auto' className='text-muted-foreground'>
                          {locale === 'zh-Hant' ? `（${values.join('、')}）` : ` (${values.join(', ')})`}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            (answer?.fidelity ?? candidate.fidelity) && checked?.length !== 0 && <p className='text-muted-foreground text-xs'>{copy.fidelityClear}</p>
          )}
          {(voice || base) && (
            <div className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
              {voice && <p>{voice === 'personalized' ? copy.voicePersonalized : copy.voiceNeutral}</p>}
              {base && <p>{copy.basedOn(baseLabel(base, locale))}</p>}
            </div>
          )}
          {session.unsaved && (
            <p id={unsavedId} className='text-sm'>
              {copy.unsavedNote}
            </p>
          )}
          <div className='flex flex-wrap gap-2'>
            <Button type='button' variant='action' className={CONTROL} disabled={Boolean(busy) || session.unsaved} focusableWhenDisabled aria-describedby={session.unsaved ? unsavedId : undefined} onClick={session.accept}>
              {copy.use}
            </Button>
            <Button type='button' variant='glass' className={CONTROL} disabled={Boolean(busy)} focusableWhenDisabled onClick={session.discard}>
              {copy.discard}
            </Button>
          </div>
          <p className='text-muted-foreground text-xs'>{copy.tryAnother}</p>
        </section>
      )}
    </div>
  );
}
