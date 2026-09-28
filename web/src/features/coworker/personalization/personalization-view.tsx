'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { useSnapshot } from '@/lib/api/hooks';
import { useTrendContext } from '@/features/trends/hooks';
import { performanceTrendLearningSchema, trendMetricChoiceInputSchema, type TrendLearning, type TrendLearningChoiceOption } from '@/lib/coworker/trend-types';
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
            {performanceOn && <TrendLearningSection performance={performance} />}
            {isOwner && (
              <Panel title='Reset' titleId='reset-heading' description='Start over without touching Rafii’s global writing rules, approvals or anything already scheduled.'>
                <div className='flex flex-wrap gap-2'>
                  <Button variant='glass' size='control' className='h-auto min-h-12 min-w-0 max-w-full whitespace-normal py-2' onClick={() => setResetScope('notes')}>
                    Reset my notes…
                  </Button>
                  <Button variant='glass' size='control' className='h-auto min-h-12 min-w-0 max-w-full whitespace-normal py-2' onClick={() => setResetScope('learned')}>
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
          <Button ref={addRef} variant='glass' size='control' className='h-auto min-h-12 min-w-0 max-w-full whitespace-normal py-2' onClick={() => setAdding(true)}>
            <Icons.add className='size-4' aria-hidden /><span className='min-w-0'>Add a {kind} note</span>
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

  async function onDecide(h: StrategyHypothesis, decision: 'experiment' | 'dismissed' | 'accepted') {
    try {
      const result = await decide.mutateAsync({ id: h.id, decision });
      if (!result.verified) return toast.warning('Rafii could not confirm that decision. Refresh to see its state.');
      toast.success(decision === 'accepted' ? 'Accepted for planning in this account and objective. Your voice is unchanged.' : decision === 'experiment' ? 'Running as an experiment: the next comparable posts alternate both ways. Nothing about your voice changes.' : 'Dismissed.');
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
                {isOwner && (h.status === 'candidate' || h.status === 'experiment' || h.planningAccepted) && (
                  <div className='flex flex-wrap gap-2 pt-1'>
                    {h.status === 'candidate' && (
                      <Button variant='glass' size='control' disabled={decide.isPending} onClick={() => void onDecide(h, 'experiment')}>
                        Run as experiment
                      </Button>
                    )}
                    {h.canAcceptPlanning && !h.planningAccepted && <Button variant='glass' size='control' disabled={decide.isPending} onClick={() => void onDecide(h, 'accepted')}>Use in planning</Button>}
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

const LEARNING_WINDOWS = { '1h': '1 hour', '24h': '24 hours', '7d': '7 days' };
const LEARNING_STATES = {
  unpublished: 'Not published',
  invalid_publication_chronology: 'Publication timing could not be verified',
  invalid_published_revision: 'Published version could not be verified',
  objective_unselected: 'No prior metric choice for this window',
  account_unavailable: 'Account unavailable',
  pending_horizon: 'Waiting for the measurement window',
  delayed: 'Waiting for platform metrics',
  unavailable: 'Metrics unavailable',
  ambiguous_native_publication: 'Publication link is ambiguous',
  measured: 'Measured outcomes'
};

function TrendLearningSection({ performance }: { performance: ReturnType<typeof usePerformance> }) {
  const context = useTrendContext();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const readable = !context.status.isError && context.flags.RAFII_TREND_INTELLIGENCE_ENABLED === true && context.flags.RAFII_TREND_TRUST_RECEIPTS_ENABLED === true;
  if (!readable) return null;
  const parsed = performanceTrendLearningSchema.safeParse(performance.data);
  const report = parsed.success ? parsed.data.trend_learning : undefined;
  return (
    <Panel title='Your trend ideas' titleId='trend-learning-heading' description='Recorded views, decisions and what happened after publication. These observations do not show what caused a result.'>
      {performance.isPending ? <StateMessage kind='loading' layout='inline' title='Loading trend activity…' />
        : performance.isError ? <QueryProblem error={performance.error} onRetry={() => void performance.refetch()} what='Trend activity' />
        : !report ? <StateMessage kind='unsupported' layout='inline' title='Trend activity is unavailable.' description='No verified report is available for this workspace. Missing results are not counted as zero.' />
        : <TrendLearningReport key={context.w} report={report} context={context} canEdit={canEdit} refresh={() => performance.refetch({ throwOnError: true })} />}
    </Panel>
  );
}

const optionKey = (o: TrendLearningChoiceOption) => JSON.stringify([o.selection_digest, o.channel_id, o.source_id]);

function TrendLearningReport({ report, context, canEdit, refresh }: {
  report: TrendLearning;
  context: ReturnType<typeof useTrendContext>;
  canEdit: boolean;
  refresh: () => Promise<unknown>;
}) {
  const [selection, setSelection] = useState('');
  const d = report.denominator;
  const option = report.choice_options.find((o) => optionKey(o) === selection);
  const counts = [['Recorded views', d.exposures], ['Accepted after a view', d.accepted], ['Dismissed after a view', d.dismissed]] as const;
  const outcomes = Object.entries(report.outcome_states);
  const notPublished = report.exposures.filter((e) => e.publication_coverage === 'not_published').length;
  const sourceUnavailable = report.exposures.filter((e) => e.publication_coverage === 'accepted_source_unavailable').length;
  const partial = report.coverage.exposure_page_truncated || report.coverage.decisions_truncated || report.coverage.job_history_truncated;
  return (
    <div className='flex min-w-0 flex-col gap-4' data-trend-learning>
      <dl className='grid grid-cols-1 gap-3 sm:grid-cols-3'>
        {counts.map(([label, value]) => <div key={label}><dt className='text-muted-foreground text-xs'>{label}</dt><dd className='text-foreground mt-1 text-xl tabular-nums'>{value.toLocaleString()}</dd></div>)}
      </dl>
      <p className='text-muted-foreground text-xs'>Views are client-reported displays, not unique people. This is a bounded report of currently permitted records, not a complete historical total.</p>
      {d.exposures === 0 && <StateMessage kind='empty' layout='inline' title='No recorded views in this report.' description='This does not mean the ideas received zero engagement.' />}
      <div>
        <h3 className='text-foreground text-sm font-medium'>Publication outcomes</h3>
        <p className='text-muted-foreground mt-1 text-xs'>Measurement window: {LEARNING_WINDOWS[report.window]} after publication. Updated {formatDate(Date.parse(report.as_of) / 1000)}.</p>
        {outcomes.length ? <dl className='mt-3 flex flex-col gap-2 text-sm'>{outcomes.map(([state, value]) => <div key={state} className='flex flex-wrap justify-between gap-x-4 gap-y-1'><dt>{LEARNING_STATES[state as keyof typeof LEARNING_STATES]}</dt><dd className='tabular-nums'>{value}</dd></div>)}</dl>
          : <p className='text-muted-foreground mt-2 text-sm'>No publication outcomes are available in this report.</p>}
        {notPublished > 0 && <p className='mt-2 text-sm'>{notPublished} accepted {notPublished === 1 ? 'idea has' : 'ideas have'} no linked publication yet.</p>}
        {sourceUnavailable > 0 && <p className='mt-2 text-sm'>{sourceUnavailable} accepted {sourceUnavailable === 1 ? 'source is' : 'sources are'} unavailable for checking publication.</p>}
        <p className='text-muted-foreground mt-2 text-xs'>Waiting, unavailable and unselected outcomes are not zero engagement.</p>
      </div>
      <details className='min-w-0 text-sm'>
        <summary className='rafii-focus cursor-pointer rounded-md py-2 font-medium'>Coverage and outcome details</summary>
        <div className='flex min-w-0 flex-col gap-3 pt-2'>
          <p>{d.unaccepted} views without an acceptance or dismissal · {d.unknown} views with an unresolved decision.</p>
          <p>Decisions without a linked view: {d.accepted_without_exposure} accepted · {d.dismissed_without_exposure} dismissed · {d.unknown_without_exposure} unresolved. These are outside the recorded-view counts.</p>
          <p>{partial ? 'Some records are outside this bounded report.' : 'No page truncation was reported.'} Historical coverage remains incomplete.</p>
          <dl className='text-muted-foreground grid grid-cols-1 gap-2 text-xs sm:grid-cols-2'>
            {Object.entries({ 'View page truncated': report.coverage.exposure_page_truncated, 'Decision history truncated': report.coverage.decisions_truncated, 'Publication history truncated': report.coverage.job_history_truncated }).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ? 'Yes' : 'No'}</dd></div>)}
            <div><dt>Views retained under independent analytics rights</dt><dd>{report.coverage.independent_analytics_views}</dd></div>
          </dl>
          {Object.entries(report.coverage.suppressed_in_page).map(([reason, value]) => <p key={reason} className='text-muted-foreground text-xs'>{humanize(reason)}: {value} excluded.</p>)}
          {report.exposures.filter((e) => e.outcomes.length).map((e) => <details key={e.exposure_id} className='min-w-0'>
            <summary className='rafii-focus cursor-pointer rounded-md py-2'>Accepted idea · {e.outcomes.length} publication {e.outcomes.length === 1 ? 'record' : 'records'}</summary>
            <p className='text-muted-foreground break-all text-xs'>View {e.exposure_id} · {e.eligible_candidate_count} eligible candidates on its returned page · {humanize(e.retention_basis)}. Source rights are not extended.</p>
            {e.outcomes.map((o, i) => <Band key={`${o.job_id}:${i}`} className='mt-2 min-w-0 gap-2'>
              <p className='text-sm'>{LEARNING_STATES[o.state]}{o.state === 'measured' ? `: ${o.value.toLocaleString()} ${o.unit}${o.metric ? ` · ${o.metric}` : ''}` : ' · No measured value'}</p>
              {o.reason && <p className='text-muted-foreground break-words text-xs'>{humanize(o.reason)} ({o.reason})</p>}
              <p className='text-muted-foreground break-all text-xs'>Publication record: {o.job_id} · Recommendation meaning: {humanize(o.treatment_state)}</p>
              {o.cohort && <p className='text-muted-foreground break-words text-xs'>{o.cohort.provider} · {o.cohort.account} · {humanize(o.cohort.objective)} · {LEARNING_WINDOWS[o.cohort.window]} · Definition {o.cohort.definition} · {o.cohort.language ?? 'Language unknown'} · {o.cohort.format ?? 'Format unknown'}</p>}
              {o.state === 'measured' && <p className='text-muted-foreground break-words text-xs'>Native counts: {Object.entries(o.native_values).map(([name, value]) => `${name}: ${value}`).join(' · ')}. Observed {formatDate(o.observed_at)}.</p>}
              {o.baseline && <p className='text-muted-foreground text-xs'>{o.baseline.count} earlier comparable publications. {o.baseline.median == null ? 'Comparison unavailable.' : `Descriptive median ${o.baseline.median}; median absolute deviation ${o.baseline.mad ?? 'unknown'}.`} {o.baseline.reason ? humanize(o.baseline.reason) : o.baseline.confounders?.map(humanize).join(' · ')}.</p>}
              {o.attribution && <p className='text-muted-foreground text-xs'>{humanize(o.attribution)}.</p>}
            </Band>)}
          </details>)}
          <ul className='text-muted-foreground list-disc space-y-1 pl-5 text-xs'>{report.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      </details>
      <div className='flex min-w-0 flex-col gap-3'>
        <h3 className='text-foreground text-sm font-medium'>Choose what to measure</h3>
        <p className='text-muted-foreground text-xs'>Choose a saved idea, account, objective and native metric. A saved choice applies only to future publications of that idea. It does not reclassify past results or change your strategy.</p>
        {!report.choice_options.length ? <p className='text-muted-foreground text-sm'>No current saved trend ideas are available for a metric choice.</p>
          : !canEdit ? <p className='text-muted-foreground text-sm'>An editor can save a metric choice. You can read the current choices below.</p>
          : !context.enabled ? <p className='text-muted-foreground text-sm'>Metric choices are not enabled for this workspace.</p>
          : <>
            <SelectField aria-label='Saved idea and account' label='Saved idea and account' value={selection} onChange={(e) => setSelection(e.target.value)}>
              <option value=''>Choose an idea and account…</option>
              {report.choice_options.map((o, i) => <option key={optionKey(o)} value={optionKey(o)}>{i + 1}. {o.source_label} · {o.channel_label} · {o.provider}</option>)}
            </SelectField>
            {option && <TrendMetricChoiceForm key={JSON.stringify({ ...option, saved_choice: null })} option={option} context={context} refresh={refresh} />}
          </>}
        {report.choice_options.some((o) => o.saved_choice) && <details className='min-w-0 text-sm'><summary className='rafii-focus cursor-pointer rounded-md py-2'>Saved metric choices</summary><ul className='mt-2 space-y-2'>{report.choice_options.filter((o) => o.saved_choice).map((o) => <li key={optionKey(o)} className='break-words'>{o.source_label} · {o.channel_label}: {o.saved_choice!.metric}{o.saved_choice!.denominator_metric ? ` / ${o.saved_choice!.denominator_metric}` : ''} · {humanize(o.saved_choice!.objective)} · {LEARNING_WINDOWS[o.saved_choice!.window]} · Definition {o.saved_choice!.definition_version}</li>)}</ul></details>}
      </div>
    </div>
  );
}

function TrendMetricChoiceForm({ option, context, refresh }: {
  option: TrendLearningChoiceOption;
  context: ReturnType<typeof useTrendContext>;
  refresh: () => Promise<unknown>;
}) {
  const snapshot = useSnapshot();
  const [metric, setMetric] = useState('');
  const [objective, setObjective] = useState('');
  const [window, setWindow] = useState('');
  const [denominator, setDenominator] = useState('');
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const [message, setMessage] = useState('');
  const [problem, setProblem] = useState('');
  const [saved, setSaved] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const input = trendMetricChoiceInputSchema.safeParse({
    selection_digest: option.selection_digest, channel_id: option.channel_id, provider: option.provider,
    definition_version: option.definition_version, metric, objective, window,
    ...(denominator ? { denominator_metric: denominator } : {})
  });
  const valid = input.success && option.metrics.includes(metric) && option.windows.some((v) => v === window) && option.objectives.some((v) => v === objective) && (!denominator || (option.metrics.includes(denominator) && denominator !== metric));
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!valid || !input.success || locked.current || saved || uncertain) return;
    locked.current = true;
    setBusy(true); setProblem(''); setMessage('');
    try {
      const response = await context.api.recordMetricChoice(context.w, input.data);
      if (response.execution_state !== 'stored_result' || Object.entries(input.data).some(([k, v]) => response.data[k as keyof typeof response.data] !== v) || response.data.denominator_metric !== input.data.denominator_metric) {
        throw new Error('The saved choice could not be confirmed. Refresh before trying again.');
      }
      setSaved(true);
      setMessage('Metric choice saved for future publications. Past results are unchanged.');
      toast.success('Metric choice saved for future publications.');
      try {
        await Promise.all([snapshot.refetch({ throwOnError: true }), refresh()]);
      } catch {
        setProblem('The choice was saved, but the refreshed report is unavailable. Refresh the page to check it before saving again.');
      }
    } catch (err) {
      setUncertain(true);
      setProblem(`${errorMessage(err)} Refresh the report to check its current state before trying again.`);
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <form onSubmit={(e) => void save(e)} className='flex min-w-0 flex-col gap-3' aria-label='Trend metric choice'>
      <fieldset disabled={busy || saved} className='grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2'>
        <SelectField aria-label='Objective' label='Objective' value={objective} onChange={(e) => setObjective(e.target.value)} required><option value=''>Choose an objective…</option>{option.objectives.map((o) => <option key={o} value={o}>{humanize(o)}</option>)}</SelectField>
        <SelectField aria-label='Native metric' label='Native metric' value={metric} onChange={(e) => { setMetric(e.target.value); setDenominator(''); }} required><option value=''>Choose a metric…</option>{option.metrics.map((m) => <option key={m} value={m}>{m}</option>)}</SelectField>
        <SelectField aria-label='Measurement window' label='Measurement window' value={window} onChange={(e) => setWindow(e.target.value)} required><option value=''>Choose a window…</option>{option.windows.map((w) => <option key={w} value={w}>{LEARNING_WINDOWS[w]} after publication</option>)}</SelectField>
        <SelectField aria-label='Divide by another metric (optional)' label='Divide by another metric (optional)' value={denominator} onChange={(e) => setDenominator(e.target.value)}><option value=''>No division — native count</option>{option.metrics.filter((m) => m !== metric).map((m) => <option key={m} value={m}>{m}</option>)}</SelectField>
      </fieldset>
      <p className='text-muted-foreground break-words text-xs'>Account: {option.channel_label} · {option.provider} · Metric definition {option.definition_version}. {denominator ? 'A missing or zero divisor leaves the outcome unavailable.' : 'Native counts retain the platform’s metric definition.'}</p>
      <div><Button type='submit' variant='glass' size='control' className='h-auto min-h-12 min-w-0 max-w-full whitespace-normal py-2' disabled={!valid || busy || saved || uncertain}>{busy ? 'Saving…' : 'Save metric choice'}</Button></div>
      <div><Button type='button' variant='quiet' size='control' className='h-auto min-h-12 min-w-0 max-w-full whitespace-normal py-2' disabled={busy} onClick={async () => { try { await refresh(); setUncertain(false); setProblem(''); } catch (err) { setProblem(errorMessage(err, 'The report could not be refreshed.')); } }}>Refresh report</Button></div>
      {message && <p role='status' className='text-sm'>{message}</p>}
      {problem && <p role='alert' className='text-sm'>{problem}</p>}
    </form>
  );
}
