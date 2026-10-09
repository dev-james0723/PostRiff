'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import Image from 'next/image';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { PanelButton as Button } from '../ui/controls';
import { ApiError } from '@/lib/api/client';
import type { AnswerResult, LibraryScope, SourceRef, ViewerResult } from '@/lib/api/library-intelligence-types';
import {
  ANSWER_GRANT,
  SUMMARY_GRANT,
  abstentionLines,
  answerModeLabel,
  answerPermission,
  answerRequest,
  citationKey,
  sourceRefOnly,
  supportLabel,
  viewerOpenPlan,
  type CitedRef
} from '@/lib/library/answers';
import { parseLibraryProps, type SourceCitationProps } from '@/lib/library/openui-schemas';
import type { ScopeDescription } from '@/lib/library/wording';
import { useNowPlaying } from '@/lib/media/now-playing';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useAssetImage } from '../asset-card';
import { SourceCitation, SourceScope } from './openui/components';

type ViewerInfo = Omit<ViewerResult, 'target'> & { targetKind: ViewerResult['target']['kind'] };

/** Identity fields only, typed for the client (the viewer refuses anything else). */
function toSourceRef(ref: CitedRef): SourceRef {
  return sourceRefOnly(ref) as unknown as SourceRef;
}

/** A legacy photo opens through the app's own authenticated media read, never a link in the address bar. */
function CitedPicture({ assetId, title }: { assetId: string; title: string }) {
  const image = useAssetImage(assetId);
  return image.data ? (
    <Image src={image.data} alt={title} width={640} height={640} unoptimized className='rafii-quiet max-h-[50vh] w-full rounded-[var(--rafii-radius-card)] object-contain' />
  ) : (
    <p className='text-muted-foreground text-sm'>{image.isError ? 'Preview unavailable.' : 'Loading preview…'}</p>
  );
}

/**
 * Ask Library (PRD R08): a question over an explicit scope, answered only from verified passages. Quotations are said to
 * be quotations, disagreement is shown, an abstention says what was searched, and every citation opens its own version
 * at its locator through a fresh viewer link.
 */
export function AskLibraryPanel({
  scope,
  scopeDescription,
  canEdit,
  isOwner,
  enabled,
  summariesAvailable,
  onAnnounce
}: {
  scope: LibraryScope;
  scopeDescription: ScopeDescription;
  canEdit: boolean;
  isOwner: boolean;
  /** The Library intelligence service answers in this build. */
  enabled: boolean;
  /** The AI provider is configured (null when the server didn't say). */
  summariesAvailable: boolean | null;
  onAnnounce: (message: string) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const id = useId();
  const grants = useQuery({ queryKey: ['library-grants', workspaceId], queryFn: () => api.libraryGrants(workspaceId), enabled: Boolean(workspaceId && enabled), retry: false });
  const permission = answerPermission(grants.data?.grants ?? [], scope);
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [granting, setGranting] = useState<'answers' | 'summaries' | null>(null);
  const [viewer, setViewer] = useState<{ ref: CitedRef; info: ViewerInfo } | null>(null);
  const [opening, setOpening] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const cited = useMemo(() => {
    const map = new Map<string, CitedRef>();
    for (const claim of result?.claims ?? []) for (const ref of claim.sourceRefs) map.set(citationKey(ref.assetRef, ref.locator ?? null), ref as CitedRef);
    return map;
  }, [result]);

  if (!enabled) return <StateMessage kind='unsupported' title='Ask Library isn’t available here yet' description='Search and browsing work as usual.' />;

  async function grant(kind: 'answers' | 'summaries') {
    setGranting(kind);
    try {
      await api.libraryGrant(workspaceId, kind === 'answers' ? { ...ANSWER_GRANT } : { ...SUMMARY_GRANT });
      await client.invalidateQueries({ queryKey: ['library-grants', workspaceId] });
      onAnnounce(kind === 'answers' ? 'Answers are allowed for this workspace.' : 'AI summaries are allowed for this workspace.');
    } catch (failure) {
      toast.error(failure instanceof Error ? failure.message : 'Couldn’t change this permission');
    } finally {
      setGranting(null);
    }
  }

  async function ask() {
    if (!question.trim()) return;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setAsking(true);
    setError(null);
    try {
      const answer = await api.libraryAnswer(workspaceId, answerRequest(question, scope), abort.signal);
      if (abort.signal.aborted) return;
      setResult(answer);
      onAnnounce(answer.abstained ? 'No answer: the selected material doesn’t support one.' : `Answer ready with ${answer.claims.length} ${answer.claims.length === 1 ? 'statement' : 'statements'}.`);
    } catch (failure) {
      if (abort.signal.aborted) return;
      setError(failure instanceof ApiError && failure.status === 503 ? 'Answers aren’t available in this version yet.' : failure instanceof Error ? failure.message : 'The answer didn’t finish.');
    } finally {
      if (!abort.signal.aborted) setAsking(false);
    }
  }

  /** Fetches a fresh viewer target each time; only what the dialog shows is kept, never the link. */
  async function openCitation(ref: CitedRef) {
    try {
      const data = await api.libraryViewer(workspaceId, toSourceRef(ref));
      const { target, ...info } = data;
      setViewer({ ref, info: { ...info, targetKind: target.kind } });
    } catch (failure) {
      toast.error(failure instanceof ApiError && failure.status === 409 ? failure.message : 'This source couldn’t be opened.');
    }
  }

  /** From a press only: a new link from the server, used at once and dropped. */
  async function openOriginal(ref: CitedRef) {
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    setOpening(true);
    try {
      const plan = viewerOpenPlan(await api.libraryViewer(workspaceId, toSourceRef(ref)));
      if (plan.href && tab) tab.location.href = plan.href;
      else {
        tab?.close();
        if (!plan.proxy) toast.error('Allow a new tab to open the original.');
      }
    } catch {
      tab?.close();
      toast.error('This source couldn’t be opened.');
    } finally {
      setOpening(false);
    }
  }

  async function playCitation(ref: CitedRef, title: string) {
    setOpening(true);
    try {
      const data = await api.libraryViewer(workspaceId, toSourceRef(ref));
      const plan = viewerOpenPlan(data);
      if (plan.playFrom === null || !plan.href) throw new Error('Playback unavailable');
      useNowPlaying.getState().open({ kind: data.kind === 'video' ? 'video' : 'audio', workspaceId, assetId: data.assetRef.assetId, title, url: plan.href, startAt: plan.playFrom });
    } catch {
      toast.error('This recording couldn’t be played.');
    } finally {
      setOpening(false);
    }
  }

  const onAction = (actionId: string, inputs: Record<string, unknown>) => {
    if (actionId !== 'library.open') return;
    const assetRef = inputs.assetRef as CitedRef['assetRef'] | undefined;
    if (!assetRef) return;
    const ref = cited.get(citationKey(assetRef, inputs.locator ?? null));
    if (ref) void openCitation(ref);
  };

  const info = viewer?.info;
  const plan = info ? viewerOpenPlan({ ...info, target: { kind: info.targetKind } }) : null;
  const title = info?.displayTitle || viewer?.ref.displayTitle || 'Source';
  return (
    <section aria-label='Ask Library' className='flex min-w-0 flex-col gap-4'>
      <SourceScope kind={scopeDescription.kind} selectedCount={scopeDescription.selectedCount ?? 0} collectionName={scopeDescription.collectionName ?? undefined} />
      {grants.isPending ? (
        <p className='text-muted-foreground text-sm'>Checking what Rafii may use to answer…</p>
      ) : !permission.answers ? (
        <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4'>
          <p className='text-sm font-medium'>Answer questions from your Library</p>
          <p className='text-muted-foreground text-sm'>
            Rafii reads passages from the items in the scope you choose and quotes them, each with a link to where it came from. This runs on Rafii’s own servers; nothing is sent to an outside AI.
          </p>
          {canEdit ? (
            <Button variant='action' size='control' className='self-start' disabled={granting !== null} onClick={() => void grant('answers')}>
              Allow answers
            </Button>
          ) : (
            <p className='text-muted-foreground text-xs'>Ask an editor of this workspace to allow answers.</p>
          )}
        </div>
      ) : !permission.summaries ? (
        <div className='flex flex-col gap-2'>
          <p className='text-muted-foreground text-xs'>Answers quote the passages they come from. AI summaries are off.</p>
          {isOwner && summariesAvailable !== false ? (
            <details className='rafii-quiet rounded-[var(--rafii-radius-card)] px-3'>
              <summary className='rafii-focus flex min-h-11 cursor-pointer items-center text-sm'>Allow AI summaries…</summary>
              <div className='flex flex-col gap-2 pb-3'>
                <p className='text-muted-foreground text-sm'>
                  The matching passages (never whole files) are sent to the AI provider to write a short summary. Only statements Rafii can match to exact quotations from those passages are shown. This applies to everyone in this workspace and can be withdrawn.
                </p>
                <Button variant='glass' size='control' className='self-start' disabled={granting !== null} onClick={() => void grant('summaries')}>
                  Allow AI summaries
                </Button>
              </div>
            </details>
          ) : !isOwner ? (
            <p className='text-muted-foreground text-xs'>Only the workspace owner can allow AI summaries.</p>
          ) : null}
        </div>
      ) : null}

      <form
        className='flex flex-col gap-2'
        onSubmit={(event) => {
          event.preventDefault();
          void ask();
        }}
      >
        <label htmlFor={`${id}-question`} className='flex flex-col gap-1.5 text-sm font-medium'>
          Question
          <textarea
            id={`${id}-question`}
            aria-label='Question'
            value={question}
            maxLength={1000}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder='When is the spring recital, and which pieces are on the programme?'
            className='rafii-field rafii-focus min-h-24 w-full rounded-[var(--rafii-radius-control)] p-3 text-base font-normal md:text-sm'
          />
        </label>
        <Button type='submit' variant='action' size='control' className='self-start' disabled={asking || !question.trim() || !permission.answers}>
          {asking ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
          Ask
        </Button>
      </form>

      {error ? <StateMessage kind='error' layout='inline' title='No answer' description={error} /> : null}
      {result ? (
        <section aria-label='Answer' aria-busy={asking || undefined} className='flex flex-col gap-3'>
          <p className='rafii-eyebrow'>{answerModeLabel(result.mode)}</p>
          {result.abstained ? (
            <div role='status' className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-card)] p-4 text-sm'>
              {abstentionLines(result).map((line, index) => (
                <p key={line} className={index === 0 ? 'font-medium' : 'text-muted-foreground'}>
                  {line}
                </p>
              ))}
            </div>
          ) : (
            <ol className='flex flex-col gap-3'>
              {result.claims.map((claim, index) => (
                <li key={`${index}-${claim.text.slice(0, 24)}`} className='flex flex-col gap-2'>
                  <p className='text-muted-foreground flex items-center gap-1.5 text-xs font-medium'>
                    {claim.kind === 'conflict' || claim.support === 'conflicting' ? <Icons.warning className='size-3.5' aria-hidden /> : <Icons.page className='size-3.5' aria-hidden />}
                    {supportLabel(claim)}
                  </p>
                  {claim.kind === 'quotation' ? <blockquote className='border-foreground/20 border-l-2 pl-3 text-sm'>“{claim.text}”</blockquote> : <p className='text-sm'>{claim.text}</p>}
                  <div className='grid gap-2 sm:grid-cols-2'>
                    {claim.sourceRefs.map((ref, position) => {
                      const props: SourceCitationProps | null = (() => {
                        const parsed = parseLibraryProps('SourceCitation', {
                          sourceRef: sourceRefOnly(ref as CitedRef),
                          title: ref.displayTitle || 'Source',
                          support: claim.support,
                          ...(ref.excerpt ? { quote: ref.excerpt } : {}),
                          ...(ref.locatorLabel ? { locatorLabel: ref.locatorLabel } : {})
                        });
                        return parsed && parsed.ok ? (parsed.props as SourceCitationProps) : null;
                      })();
                      return props ? (
                        <SourceCitation key={`${ref.segmentId ?? ref.assetRef.versionId}-${position}`} {...props} onAction={onAction} />
                      ) : (
                        <div key={`${ref.assetRef.versionId}-${position}`} className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-card)] p-3 text-sm'>
                          <span className='font-medium'>{ref.displayTitle || 'Source'}</span>
                          <Button variant='quiet' size='lg' className='h-11 self-start' onClick={() => void openCitation(ref as CitedRef)}>
                            Open source
                          </Button>
                        </div>
                      );
                    })}
                  </div>
                </li>
              ))}
            </ol>
          )}
          {result.attributionOnly !== false && !result.abstained ? <p className='text-muted-foreground text-xs'>These report what the cited sources say; they are not approved facts.</p> : null}
          {result.droppedClaims ? (
            <p className='text-muted-foreground text-xs'>
              {result.droppedClaims} {result.droppedClaims === 1 ? 'statement' : 'statements'} from the AI couldn’t be matched to the sources and {result.droppedClaims === 1 ? 'was' : 'were'} left out.
            </p>
          ) : null}
          {result.warnings.map((warning) => (
            <p key={warning} className='text-muted-foreground text-xs'>
              {warning}
            </p>
          ))}
        </section>
      ) : null}

      <RafiiDialog open={viewer !== null} onOpenChange={(open) => !open && setViewer(null)}>
        <RafiiDialogContent size='md'>
          {viewer && info && plan ? (
            <>
              <RafiiDialogHeader title={title} intro={info.locatorLabel ? `Cited at ${info.locatorLabel}` : 'Cited source'} />
              <RafiiDialogBody className='flex flex-col gap-3'>
                {plan.versionNote ? <StateMessage kind='stale' layout='inline' title='A newer version exists' description={plan.versionNote} /> : null}
                {info.passage ? (
                  <blockquote className='rafii-quiet rounded-[var(--rafii-radius-card)] p-3 text-sm whitespace-pre-wrap'>
                    {info.passage.text}
                    {info.passage.superseded ? <span className='text-muted-foreground mt-2 block text-xs'>This passage has since been corrected in the item.</span> : null}
                  </blockquote>
                ) : null}
                {info.targetKind === 'proxy' ? <CitedPicture assetId={info.assetRef.versionId || info.assetRef.assetId} title={title} /> : null}
              </RafiiDialogBody>
              <RafiiDialogFooter className='flex-row flex-wrap justify-end'>
                {info.targetKind === 'signedUrl' && (info.kind === 'audio' || info.kind === 'video') ? (
                  <Button variant='glass' size='control' disabled={opening} onClick={() => void playCitation(viewer.ref, title)}>
                    <Icons.play aria-hidden />
                    {plan.playFrom !== null || info.locator?.kind === 'time' ? `Play from ${info.locatorLabel?.split('–')[0] ?? 'the start'}` : 'Play'}
                  </Button>
                ) : null}
                {info.targetKind === 'signedUrl' ? (
                  <Button variant='action' size='control' disabled={opening} onClick={() => void openOriginal(viewer.ref)}>
                    {info.locatorLabel ? `Open original at ${info.locatorLabel}` : 'Open original'}
                  </Button>
                ) : null}
              </RafiiDialogFooter>
            </>
          ) : null}
        </RafiiDialogContent>
      </RafiiDialog>
    </section>
  );
}
