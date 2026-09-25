'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Band, Panel, SelectField, TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { errorMessage, isFeatureDisabled } from '@/lib/coworker/api';
import { useCoworkerApi, useCoworkerFlag, useDecideHypothesis, useOverlayStatus, useOverlays, usePerformance, useResetOverlays, useSaveNote } from '@/lib/coworker/hooks';
import type { OverlayItem, OverlayScope, StrategyHypothesis } from '@/lib/coworker/types';
import { downloadBlob } from '@/lib/download';
import { languageLabel } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { humanize } from '../present';
import { formatDate, OriginBadge, QueryProblem, ScopeChips, ToneChip, WhyRafiiExplainer } from '../parts';

const PLATFORMS = ['LinkedIn', 'Instagram', 'Threads', 'X', 'Facebook', 'TikTok', 'YouTube', 'Bluesky', 'Pinterest', 'Xiaohongshu'];
const LANGUAGES = ['en', 'en-GB', 'en-US', 'zh-Hant-HK', 'zh-Hant', 'zh-Hans', 'yue', 'ja', 'ko'];

const infoContent = {
  title: 'How personalization works',
  sections: [
    { title: 'Three kinds of memory', description: 'Voice is how you write. Brand is who you are and what you may claim. Strategy is what seems to work on one account — a hypothesis, never a rule.' },
    { title: 'Explicit beats inferred', description: 'A note you write always outranks something Rafii noticed. Noticed patterns carry a confidence and expire unless new evidence supports them.' },
    { title: 'Reversible', description: 'Disable, retire or reset anything here. Global writing rules, approvals and publishing safety are never changed by these notes.' }
  ]
};

function statusLabel(status: OverlayItem['status']): { label: string; tone: 'neutral' | 'attention' | 'success'; icon: string } {
  switch (status) {
    case 'active':
      return { label: 'In use', tone: 'success', icon: 'check' };
    case 'disabled':
    case 'paused':
      return { label: 'Off', tone: 'neutral', icon: 'pause' };
    case 'retired':
      return { label: 'Retired', tone: 'neutral', icon: 'slash' };
    case 'expired':
      return { label: 'Expired', tone: 'attention', icon: 'clock' };
    default:
      return { label: humanize(status), tone: 'neutral', icon: 'circle' };
  }
}

/**
 * Personalization controls (coworker spec §9, §19): inspect, add, edit, disable, retire, reset and export what
 * shapes Rafii's drafts — Voice, Brand and Strategy — with where each item came from, where it applies, how
 * sure Rafii is and when it expires. Strategy items are hypotheses with sample sizes, never proof.
 */
export function PersonalizationView() {
  const access = useWorkspaceAccess();
  const isOwner = checkAccess(access, { permission: 'owner' });
  const overlays = useOverlays();
  const performanceOn = useCoworkerFlag('RAFII_PERFORMANCE_LEARNING_ENABLED') === true;
  const performance = usePerformance(performanceOn);
  const { api, w } = useCoworkerApi();
  const [exporting, setExporting] = useState(false);
  const [resetScope, setResetScope] = useState<'notes' | 'learned' | null>(null);
  const reset = useResetOverlays();

  async function exportJson() {
    setExporting(true);
    try {
      const data = await api.exportOverlays(w);
      downloadBlob(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }), `rafii-personalization-${new Date().toISOString().slice(0, 10)}.json`);
      toast.success('Exported. The file lists every note, learned item and hypothesis with its evidence ids.');
    } catch (err) {
      toast.error(errorMessage(err, 'The export failed.'));
    } finally {
      setExporting(false);
    }
  }

  async function confirmReset() {
    if (!resetScope) return;
    try {
      const result = await reset.mutateAsync(resetScope);
      if (!result.verified) toast.warning(`Reset finished with ${result.remaining} item${result.remaining === 1 ? '' : 's'} still listed. Refresh and try again.`);
      else toast.success(resetScope === 'notes' ? 'Your notes are cleared. Learned items are unchanged.' : 'Learned preferences are forgotten. Your notes are unchanged.');
    } catch (err) {
      toast.error(errorMessage(err, 'The reset failed.'));
    } finally {
      setResetScope(null);
    }
  }

  if (overlays.isError && isFeatureDisabled(overlays.error)) {
    return (
      <PageContainer pageTitle='Personalization' width='reading'>
        <StateMessage kind='unsupported' title='Personalization controls are not turned on for this workspace yet.' description='Your voice, brand and learned preferences in Memory and Brand still apply.' />
      </PageContainer>
    );
  }

  const hypotheses = mergeHypotheses(overlays.data?.strategy ?? [], performance.data?.hypotheses ?? []);

  return (
    <PageContainer
      pageTitle='Personalization'
      pageDescription='What shapes Rafii’s drafts for this workspace, where each item came from, and how to change it.'
      infoContent={infoContent}
      width='reading'
      pageHeaderAction={
        <Button variant='glass' size='control' disabled={exporting || !overlays.data} onClick={() => void exportJson()}>
          <Icons.download className='size-4' aria-hidden /> {exporting ? 'Exporting…' : 'Export JSON'}
        </Button>
      }
    >
      <div className='flex flex-col gap-5'>
        <WhyRafiiExplainer />
        {!isOwner && <p className='text-muted-foreground text-sm'>Only an owner can add, change or reset these. You can read and export them.</p>}
        {overlays.isPending ? (
          <StateMessage kind='loading' title='Loading personalization…' />
        ) : overlays.isError ? (
          <QueryProblem error={overlays.error} onRetry={() => void overlays.refetch()} what='Personalization' />
        ) : (
          <>
            <OverlaySection kind='voice' title='Voice' description='How you tend to write: length, openings, tone, what you never say.' items={overlays.data.voice} isOwner={isOwner} />
            <OverlaySection kind='brand' title='Brand' description='Who the brand is: audience, products, approved claims and vocabulary.' items={overlays.data.brand} isOwner={isOwner} />
            <StrategySection hypotheses={hypotheses} isOwner={isOwner} performanceNote={performance.data?.rules.note} measured={performance.data ? { posts: performance.data.posts, measured: performance.data.measured, unavailable: performance.data.unavailable } : null} />
            {isOwner && (
              <Panel title='Reset' titleId='reset-heading' description='Start over without touching Rafii’s global writing rules, approvals or anything already scheduled.'>
                <div className='flex flex-wrap gap-2'>
                  <Button variant='glass' size='control' onClick={() => setResetScope('notes')}>
                    Reset my notes…
                  </Button>
                  <Button variant='glass' size='control' onClick={() => setResetScope('learned')}>
                    Reset what Rafii learned…
                  </Button>
                </div>
              </Panel>
            )}
          </>
        )}
      </div>

      <AlertDialog open={resetScope !== null} onOpenChange={(open) => !open && setResetScope(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{resetScope === 'notes' ? 'Reset your notes?' : 'Reset what Rafii learned?'}</AlertDialogTitle>
            <AlertDialogDescription>
              {resetScope === 'notes'
                ? 'Every voice and brand note written in this workspace is removed. Learned preferences stay. This cannot be undone; export first if you want a copy.'
                : 'Every learned preference, proposal and edit history is forgotten. Your notes stay. This cannot be undone; export first if you want a copy.'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep everything</AlertDialogCancel>
            <AlertDialogAction variant='destructive' disabled={reset.isPending} onClick={() => void confirmReset()}>
              {reset.isPending ? 'Resetting…' : resetScope === 'notes' ? 'Reset notes' : 'Reset learned'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  );
}

function mergeHypotheses(fromOverlays: StrategyHypothesis[], fromPerformance: StrategyHypothesis[]): StrategyHypothesis[] {
  const byId = new Map<string, StrategyHypothesis>();
  for (const h of fromOverlays) byId.set(h.id, h);
  for (const h of fromPerformance) byId.set(h.id, { ...byId.get(h.id), ...h });
  return [...byId.values()].filter((h) => ['candidate', 'experiment', 'supported'].includes(h.status));
}

function samplesOf(h: StrategyHypothesis): [number, number] {
  return Array.isArray(h.samples) ? [h.samples[0] ?? 0, h.samples[1] ?? 0] : [h.samples?.a ?? 0, h.samples?.b ?? 0];
}

/** "may … not proven": a hypothesis statement never reads as a fact. */
function hedged(statement: string): string {
  return /\b(may|might|could|appears?|seems?)\b/i.test(statement) ? statement : `This may hold: ${statement}`;
}

function OverlaySection({ kind, title, description, items, isOwner }: { kind: 'voice' | 'brand'; title: string; description: string; items: OverlayItem[]; isOwner: boolean }) {
  const live = items.filter((i) => i.status !== 'retired');
  const retired = items.filter((i) => i.status === 'retired');
  const [adding, setAdding] = useState(false);
  const addRef = useRef<HTMLButtonElement>(null);
  return (
    <Panel
      title={title}
      titleId={`${kind}-heading`}
      description={description}
      actions={
        isOwner && !adding ? (
          <Button ref={addRef} variant='glass' size='control' onClick={() => setAdding(true)}>
            <Icons.add className='size-4' aria-hidden /> Add a {kind} note
          </Button>
        ) : undefined
      }
    >
      {adding && <NoteForm kind={kind} onDone={() => { setAdding(false); requestAnimationFrame(() => addRef.current?.focus()); }} />}
      {live.length === 0 && !adding ? (
        <StateMessage kind='empty' layout='inline' title={`No ${kind} notes or learned items yet.`} description={isOwner ? `Add a note, for example: ${kind === 'voice' ? 'Short sentences; no exclamation marks.' : 'Say “members”, never “customers”.'}` : undefined} />
      ) : (
        <ul className='flex flex-col gap-2' aria-labelledby={`${kind}-heading`}>
          {live.map((item) => (
            <OverlayRow key={item.id} item={item} isOwner={isOwner} />
          ))}
        </ul>
      )}
      {retired.length > 0 && (
        <details className='text-sm'>
          <summary className='rafii-focus text-muted-foreground min-h-11 cursor-pointer rounded-sm py-2'>{retired.length} retired</summary>
          <ul className='flex flex-col gap-1 pt-1'>
            {retired.map((item) => (
              <li key={item.id} className='text-muted-foreground px-1 py-1 text-sm'>
                {item.statement}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function OverlayRow({ item, isOwner }: { item: OverlayItem; isOwner: boolean }) {
  const setStatus = useOverlayStatus();
  const [editing, setEditing] = useState(false);
  const editRef = useRef<HTMLButtonElement>(null);
  const status = statusLabel(item.status);
  const evidence = item.evidenceIds?.length ?? 0;
  const counter = item.counterEvidenceIds?.length ?? 0;
  const off = item.status === 'disabled' || item.status === 'paused';
  const busy = setStatus.isPending;

  async function change(next: 'active' | 'disabled' | 'retired') {
    try {
      const result = await setStatus.mutateAsync({ id: item.id, status: next });
      if (!result.verified) return toast.warning('Rafii could not confirm that change. Refresh to see its state.');
      toast.success(next === 'active' ? 'Back in use for new drafts.' : next === 'disabled' ? 'Turned off. It stays listed and no longer shapes drafts.' : 'Retired.');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  if (editing) {
    return (
      <Band as='li'>
        <NoteForm kind={item.memoryType} note={item} onDone={() => { setEditing(false); requestAnimationFrame(() => editRef.current?.focus()); }} />
      </Band>
    );
  }

  return (
    <Band as='li' className='gap-2' data-overlay-id={item.id} data-origin={item.origin}>
      <div className='flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between'>
        <p className={cn('text-sm', off ? 'text-muted-foreground' : 'text-foreground')}>{item.statement}</p>
        <ToneChip tone={status.tone} icon={status.icon} className='self-start'>
          {status.label}
        </ToneChip>
      </div>
      <div className='flex flex-wrap items-center gap-2'>
        <OriginBadge origin={item.origin} />
        <ScopeChips scope={item.scope} />
      </div>
      <p className='text-muted-foreground text-xs leading-relaxed'>
        {item.origin === 'explicit' ? 'Always applies within its scope · no expiry' : `Confidence ${Math.round((item.confidence ?? 0) * 100)}%`}
        {item.origin === 'inferred' && ` · ${evidence} supporting example${evidence === 1 ? '' : 's'}`}
        {item.origin === 'inferred' && counter > 0 && ` · ${counter} against`}
        {item.lastSupportedAt && item.origin === 'inferred' ? ` · last supported ${formatDate(item.lastSupportedAt)}` : ''}
        {item.expiresAt && item.origin === 'inferred' ? ` · expires ${formatDate(item.expiresAt)}` : ''}
      </p>
      {isOwner && (
        <div className='flex flex-wrap gap-2 pt-1'>
          {item.kind === 'note' && (
            <Button ref={editRef} variant='glass' size='control' disabled={busy} onClick={() => setEditing(true)}>
              Edit
            </Button>
          )}
          <Button variant='glass' size='control' disabled={busy} onClick={() => void change(off ? 'active' : 'disabled')} aria-label={`${off ? 'Turn on' : 'Turn off'}: ${item.statement}`}>
            {off ? 'Turn on' : 'Turn off'}
          </Button>
          <Button variant='quiet' size='control' disabled={busy} onClick={() => void change('retired')} aria-label={`Retire: ${item.statement}`}>
            Retire
          </Button>
        </div>
      )}
    </Band>
  );
}

function NoteForm({ kind, note, onDone }: { kind: 'voice' | 'brand'; note?: OverlayItem; onDone: () => void }) {
  const save = useSaveNote();
  const id = useId();
  const [statement, setStatement] = useState(note?.statement ?? '');
  const [platform, setPlatform] = useState(note?.scope.platform ?? '');
  const [language, setLanguage] = useState(note?.scope.language ?? '');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => inputRef.current?.focus(), []); // the form opened in place of a button: put focus in it

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = statement.trim();
    if (!text) return;
    const scope: OverlayScope = {};
    if (platform) scope.platform = platform;
    if (language) scope.language = language;
    if (note?.scope.contentTypeId) scope.contentTypeId = note.scope.contentTypeId;
    if (note?.scope.audience) scope.audience = note.scope.audience;
    try {
      const result = await save.mutateAsync({ noteId: note?.id, values: { memoryType: kind, statement: text, scope } });
      if (!result.verified) return toast.warning('Rafii could not confirm the note was saved. Refresh to see it.');
      toast.success(note ? 'Note updated. It shapes new drafts, not ones already written.' : 'Note added. It shapes new drafts, not ones already written.');
      onDone();
    } catch (err) {
      toast.error(errorMessage(err, 'The note could not be saved.'));
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className='flex flex-col gap-3' aria-label={note ? `Edit ${kind} note` : `Add a ${kind} note`}>
      <label htmlFor={`${id}-statement`} className='text-foreground text-sm font-medium'>
        {note ? 'Edit note' : `New ${kind} note`}
      </label>
      <Textarea ref={inputRef} id={`${id}-statement`} value={statement} maxLength={240} rows={2} onChange={(e) => setStatement(e.target.value)} className={TEXTAREA_CLASS} placeholder={kind === 'voice' ? 'Short sentences; no exclamation marks.' : 'Say “members”, never “customers”.'} />
      <div className='grid gap-2 sm:grid-cols-2'>
        <SelectField label='Platform' value={platform} onChange={(e) => setPlatform(e.target.value)}>
          <option value=''>All platforms</option>
          {Array.from(new Set([...(platform ? [platform] : []), ...PLATFORMS])).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </SelectField>
        <SelectField label='Language' value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value=''>All languages</option>
          {Array.from(new Set([...(language ? [language] : []), ...LANGUAGES])).map((tag) => (
            <option key={tag} value={tag}>
              {languageLabel(tag) || tag}
            </option>
          ))}
        </SelectField>
      </div>
      <p className='text-muted-foreground text-xs'>{statement.length}/240 · Notes can’t change approval, publishing or safety rules.</p>
      <div className='flex flex-wrap gap-2'>
        <Button type='submit' variant='action' size='control' disabled={save.isPending || !statement.trim()}>
          {save.isPending ? 'Saving…' : note ? 'Save note' : 'Add note'}
        </Button>
        <Button type='button' variant='glass' size='control' onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function StrategySection({ hypotheses, isOwner, performanceNote, measured }: { hypotheses: StrategyHypothesis[]; isOwner: boolean; performanceNote?: string; measured: { posts: number; measured: number; unavailable: number } | null }) {
  const decide = useDecideHypothesis();

  async function onDecide(h: StrategyHypothesis, decision: 'experiment' | 'dismissed') {
    try {
      const result = await decide.mutateAsync({ id: h.id, decision });
      if (!result.verified) return toast.warning('Rafii could not confirm that decision. Refresh to see its state.');
      toast.success(decision === 'experiment' ? 'Running as an experiment: the next comparable posts alternate both ways. Nothing about your voice changes.' : 'Dismissed.');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <Panel
      title='Strategy'
      titleId='strategy-heading'
      description='What may work on a specific account, from comparable verified posts. These are hypotheses, not proof and not rules; they never change your voice on their own.'
    >
      {measured && (
        <p className='text-muted-foreground text-xs'>
          {measured.posts === 0
            ? 'No verified posts to compare yet.'
            : `${measured.measured} of ${measured.posts} verified posts have metrics${measured.unavailable ? `; ${measured.unavailable} unavailable (never counted as zero)` : ''}.`}
        </p>
      )}
      {hypotheses.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No patterns to test yet.' description='Rafii needs enough comparable, verified posts on one account before it suggests anything.' />
      ) : (
        <ul className='flex flex-col gap-2' aria-labelledby='strategy-heading'>
          {hypotheses.map((h) => {
            const [a, b] = samplesOf(h);
            const counter = h.counterEvidenceIds?.length;
            return (
              <Band as='li' key={h.id} className='gap-2' data-hypothesis-id={h.id}>
                <div className='flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between'>
                  <p className='text-foreground text-sm'>{hedged(h.statement)}</p>
                  <ToneChip tone='neutral' icon={h.status === 'experiment' ? 'hourglass' : 'trendingUp'} className='self-start'>
                    {h.status === 'experiment' ? 'Running as experiment' : h.status === 'supported' ? 'Supported so far' : 'Not proven'}
                  </ToneChip>
                </div>
                <div className='flex flex-wrap items-center gap-2'>
                  <OriginBadge origin='performance' />
                  <ScopeChips scope={{ platform: h.platform }} />
                </div>
                <p className='text-muted-foreground text-xs leading-relaxed'>
                  {humanize(h.confidence)} confidence · compared {a} and {b} posts
                  {typeof counter === 'number' ? ` · ${counter} post${counter === 1 ? '' : 's'} go${counter === 1 ? 'es' : ''} against it` : ''}
                  {h.expiresAt ? ` · re-checked by ${formatDate(h.expiresAt)}` : ''} · correlation, not cause
                </p>
                {h.why && <p className='text-muted-foreground text-xs leading-relaxed'>{h.why}</p>}
                {isOwner && (h.status === 'candidate' || h.status === 'experiment') && (
                  <div className='flex flex-wrap gap-2 pt-1'>
                    {h.status === 'candidate' && (
                      <Button variant='glass' size='control' disabled={decide.isPending} onClick={() => void onDecide(h, 'experiment')}>
                        Run as experiment
                      </Button>
                    )}
                    <Button variant='quiet' size='control' disabled={decide.isPending} onClick={() => void onDecide(h, 'dismissed')}>
                      Dismiss
                    </Button>
                  </div>
                )}
              </Band>
            );
          })}
        </ul>
      )}
      {performanceNote && <p className='text-muted-foreground text-xs'>{performanceNote}</p>}
    </Panel>
  );
}
