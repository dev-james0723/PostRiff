'use client';

import { useId, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Checkbox } from '@/components/motion/checkbox';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { StatusChip } from '@/features/queue/status-chip';
import { panelStore } from '@/features/site-agent/store';
import { useSnapshot } from '@/lib/api/hooks';
import { errorMessage } from '@/lib/growth-v2/request';
import { useDraftCheck, useSeries, useSeriesChange, type SeriesChange } from '@/lib/growth-v2/series-hooks';
import type { SeriesClaim, SeriesEpisode, SeriesView } from '@/lib/growth-v2/series-types';
import { addDays, coverageLine, episodeBrief, fill, nextActionText, percent, stateTone, type SeriesCopy } from './series-copy';
import { useSeriesCopy } from './use-series-copy';

type Apply = (change: SeriesChange) => void;
const HEADING = 'text-sm font-medium';

function WarningList({ copy, warnings }: { copy: SeriesCopy; warnings: { code: string; similarity: number; index?: number }[] }) {
  return (
    <ul className='flex flex-col gap-1 text-xs'>
      {warnings.map((warning, i) => (
        <li key={i} className='flex items-center gap-1.5'>
          <Icons.warning className='size-3.5 shrink-0' aria-hidden />
          {fill(copy.warning[warning.code as keyof SeriesCopy['warning']] ?? warning.code, { pct: percent(warning.similarity), n: warning.index ?? '' })}
        </li>
      ))}
    </ul>
  );
}

/** Choose an existing draft, see what the duplicate check says, acknowledge any near-duplicate, then add it. */
function DraftPicker({ copy, series, episode, apply, busy, onDone }: { copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; apply: Apply; busy: boolean; onDone: () => void }) {
  const id = useId();
  const snapshot = useSnapshot();
  const linked = useMemo(() => new Set(series.episodes.flatMap((e) => e.drafts.map((d) => d.variantId))), [series]);
  const drafts = (snapshot.data?.state.variants ?? []).filter((variant) => !variant.rejected && !linked.has(variant.id) && variant.text.trim());
  const [variantId, setVariantId] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const check = useDraftCheck(series.id, episode.id, variantId);
  const warnings = check.data?.warnings ?? [];
  if (!drafts.length) return <p className='text-muted-foreground text-sm'>{copy.noDrafts}</p>;
  return (
    <div className='flex flex-col gap-2'>
      <label htmlFor={`${id}-draft`} className='text-sm font-medium'>{copy.chooseDraft}</label>
      <NativeSelect id={`${id}-draft`} value={variantId ?? ''} onChange={(event) => { setVariantId(event.target.value || null); setAcknowledged(false); }} className='w-full'>
        <NativeSelectOption value=''>—</NativeSelectOption>
        {drafts.slice(0, 50).map((draft) => (
          <NativeSelectOption key={draft.id} value={draft.id}>{`${draft.platform} · ${draft.language} · ${draft.text.slice(0, 60)}`}</NativeSelectOption>
        ))}
      </NativeSelect>
      {check.isError && <p role='alert' className='text-destructive text-sm'>{errorMessage(check.error)}</p>}
      {check.data?.refusal && (
        <p role='alert' className='text-destructive text-sm'>{copy.refused}: {check.data.refusal.message}</p>
      )}
      {warnings.length > 0 && (
        <div className='flex flex-col gap-2'>
          <WarningList copy={copy} warnings={warnings} />
          <Checkbox checked={acknowledged} onCheckedChange={(value) => setAcknowledged(Boolean(value))} label={copy.acknowledge} className='min-h-11 gap-2.5 [&>span]:text-sm' />
        </div>
      )}
      <div className='flex gap-2'>
        <Button
          variant='glass'
          size='lg'
          className='min-h-11'
          disabled={busy || !variantId || !check.data || Boolean(check.data.refusal) || (warnings.length > 0 && !acknowledged)}
          onClick={() => {
            if (!variantId) return;
            apply({ kind: 'link', id: series.id, revision: series.revision, episodeId: episode.id, variantId, acknowledgedWarnings: warnings.map((w) => w.id) });
            onDone();
          }}
        >
          {copy.link}
        </Button>
        <Button variant='quiet' size='lg' className='min-h-11' onClick={onDone}>{copy.cancel}</Button>
      </div>
    </div>
  );
}

/** Reference one Library image for the episode (images only; the image itself stays in Library). */
function ImagePicker({ copy, series, episode, apply, busy, onDone }: { copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; apply: Apply; busy: boolean; onDone: () => void }) {
  const id = useId();
  const snapshot = useSnapshot();
  const images = (snapshot.data?.state.phase2?.assets ?? []).filter((asset) => !asset.deleted && !asset.mime?.startsWith('video/') && !episode.assetIds.includes(asset.id));
  const [assetId, setAssetId] = useState('');
  if (!images.length) return <p className='text-muted-foreground text-sm'>{copy.noImages}</p>;
  return (
    <div className='flex flex-wrap items-end gap-2'>
      <label htmlFor={`${id}-image`} className='flex flex-col gap-1 text-sm font-medium'>
        {copy.chooseImage}
        <NativeSelect id={`${id}-image`} value={assetId} onChange={(event) => setAssetId(event.target.value)}>
          <NativeSelectOption value=''>—</NativeSelectOption>
          {images.slice(0, 50).map((asset) => (
            <NativeSelectOption key={asset.id} value={asset.id}>{`${asset.width ?? '?'}×${asset.height ?? '?'} · ${asset.hash.slice(0, 8)}`}</NativeSelectOption>
          ))}
        </NativeSelect>
      </label>
      <Button variant='glass' size='lg' className='min-h-11' disabled={busy || !assetId}
              onClick={() => { apply({ kind: 'linkAsset', id: series.id, revision: series.revision, episodeId: episode.id, assetId }); onDone(); }}>
        {copy.link}
      </Button>
      <Button variant='quiet' size='lg' className='min-h-11' onClick={onDone}>{copy.cancel}</Button>
    </div>
  );
}

function EpisodeCard({ copy, series, episode, canEdit, apply, busy }: { copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; canEdit: boolean; apply: Apply; busy: boolean }) {
  const [picking, setPicking] = useState(false);
  const [pickingImage, setPickingImage] = useState(false);
  const titleId = useId();
  const decide = (decision: 'accept' | 'reject' | 'do_not_repeat', level: 'angle' | 'role' = 'angle') =>
    apply({ kind: 'decide', id: series.id, revision: series.revision, episodeId: episode.id, decision, level });
  const open = episode.workflowState !== 'skipped';
  const producing = episode.workflowState === 'approved' || episode.workflowState === 'drafting' || episode.workflowState === 'drafted';
  return (
    <Surface as='article' material='glass' radius='card' padding='md' aria-labelledby={titleId} className='flex flex-col gap-2'>
      <div className='flex flex-wrap items-center gap-2'>
        <h4 id={titleId} className='min-w-0 flex-1 text-sm font-medium'>{episode.index}. {copy.role[episode.role]}</h4>
        <StatusChip tone={stateTone(episode.state, episode.factState)}>{copy.state[episode.state]}</StatusChip>
        {episode.factState === 'needs_fact_review' && open && <StatusChip tone='warning'>{copy.factNeeds}</StatusChip>}
        {episode.angleDecision === 'accepted' && <StatusChip tone='neutral'>{copy.angleAccepted}</StatusChip>}
      </div>
      <dl className='grid gap-x-3 gap-y-1 text-sm sm:grid-cols-[6rem_minmax(0,1fr)]'>
        <dt className='text-muted-foreground'>{copy.question}</dt>
        <dd>{episode.question}</dd>
        <dt className='text-muted-foreground'>{copy.angle}</dt>
        <dd>{episode.angle.text}</dd>
      </dl>
      {episode.factReasons.length > 0 && open && (
        <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
          {episode.factReasons.map((reason) => <li key={reason}>· {copy.reason[reason]}</li>)}
        </ul>
      )}
      {episode.drafts.length > 0 && (
        <ul className='flex flex-col gap-1.5'>
          {episode.drafts.map((draft) => (
            <li key={draft.variantId} className='rafii-quiet flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
              <span className='min-w-0 flex-1'>
                <span className='font-medium'>{[draft.platform, draft.language].filter(Boolean).join(' · ')}</span>
                {draft.excerpt && <span className='text-muted-foreground block truncate text-xs'>{draft.excerpt}</span>}
                {draft.factGate && <span className='block text-xs'>{copy.gateNote}</span>}
                {draft.warnings.length > 0 && <WarningList copy={copy} warnings={draft.warnings} />}
              </span>
              {draft.published && <StatusChip tone='success'>{copy.published}</StatusChip>}
              {canEdit && !draft.published && (
                <Button variant='quiet' size='lg' className='min-h-11' disabled={busy}
                        onClick={() => apply({ kind: 'unlink', id: series.id, revision: series.revision, episodeId: episode.id, variantId: draft.variantId })}>
                  {copy.unlink}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {episode.assets.length > 0 && (
        <div className='flex flex-wrap items-center gap-2 text-xs'>
          <span className='text-muted-foreground'>{fill(copy.images, { n: episode.assets.length })}</span>
          {episode.assets.some((asset) => !asset.available) && <span role='status'>{copy.imageGone}</span>}
          {canEdit && episode.assets.map((asset) => (
            <Button key={asset.assetId} variant='quiet' size='lg' className='min-h-11' disabled={busy}
                    aria-label={`${copy.unlink} ${asset.assetId.slice(0, 8)}`}
                    onClick={() => apply({ kind: 'unlinkAsset', id: series.id, revision: series.revision, episodeId: episode.id, assetId: asset.assetId })}>
              {copy.unlink} · {asset.assetId.slice(0, 8)}
            </Button>
          ))}
        </div>
      )}
      {canEdit && episode.candidateDrafts.length > 0 && (
        <ul className='flex flex-col gap-1.5' aria-label={copy.candidate}>
          {episode.candidateDrafts.map((draft) => (
            <li key={draft.variantId} className='flex flex-wrap items-center gap-2 text-sm'>
              <span className='text-muted-foreground min-w-0 flex-1 truncate text-xs'>{copy.candidate}: {draft.excerpt}</span>
              <Button variant='glass' size='lg' className='min-h-11' disabled={busy}
                      onClick={() => apply({ kind: 'link', id: series.id, revision: series.revision, episodeId: episode.id, variantId: draft.variantId, acknowledgedWarnings: [] })}>
                {copy.link}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {canEdit && open && (
        <div className='flex flex-wrap gap-2'>
          {episode.canApprove && (
            <Button variant='action' size='lg' className='min-h-11' disabled={busy} onClick={() => apply({ kind: 'approve', id: series.id, revision: series.revision, episodeId: episode.id })}>
              {copy.approveNext}
            </Button>
          )}
          {producing && !picking && (
            <Button variant='glass' size='lg' className='min-h-11' onClick={() => setPicking(true)}>{copy.addDraft}</Button>
          )}
          {producing && !pickingImage && (
            <Button variant='quiet' size='lg' className='min-h-11' onClick={() => setPickingImage(true)}>{copy.addImage}</Button>
          )}
          {producing && episode.factState === 'ok' && (
            <Button variant='glass' size='lg' className='min-h-11' onClick={() => panelStore.ask(episodeBrief(copy, series, episode))}>
              <Icons.sparkles aria-hidden />
              {copy.draftWithRafii}
            </Button>
          )}
          <Button variant='quiet' size='lg' className='min-h-11'
                  onClick={() => void navigator.clipboard?.writeText(episodeBrief(copy, series, episode)).then(() => toast.success(copy.copied), () => undefined)}>
            <Icons.copy aria-hidden />
            {copy.copyBrief}
          </Button>
          {episode.angleDecision !== 'accepted' && <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('accept')}>{copy.accept}</Button>}
          {!episode.drafts.length && <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('reject')}>{copy.reject}</Button>}
          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('do_not_repeat')}>{copy.doNotRepeat}</Button>
          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('do_not_repeat', 'role')}>{copy.doNotRepeatRole}</Button>
        </div>
      )}
      {producing && <p className='text-muted-foreground text-xs'>{copy.draftNote}</p>}
      {picking && <DraftPicker copy={copy} series={series} episode={episode} apply={apply} busy={busy} onDone={() => setPicking(false)} />}
      {pickingImage && <ImagePicker copy={copy} series={series} episode={episode} apply={apply} busy={busy} onDone={() => setPickingImage(false)} />}
    </Surface>
  );
}

function ClaimRow({ copy, series, claim, canEdit, apply, busy }: { copy: SeriesCopy; series: SeriesView; claim: SeriesClaim; canEdit: boolean; apply: Apply; busy: boolean }) {
  const id = useId();
  const [mode, setMode] = useState<'idle' | 'review' | 'correct'>('idle');
  const [reviewBy, setReviewBy] = useState(() => addDays(new Date(), 180));
  const [text, setText] = useState(claim.text);
  const flagged = claim.freshness.state !== 'ok' && claim.freshness.state !== 'removed';
  return (
    <li className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-sm'>
      <div className='flex flex-wrap items-start gap-2'>
        <span className={claim.status === 'removed' ? 'text-muted-foreground min-w-0 flex-1 line-through' : 'min-w-0 flex-1'}>{claim.text}</span>
        {flagged && <StatusChip tone='warning'>{claim.freshness.reason ? copy.reason[claim.freshness.reason] : copy.factNeeds}</StatusChip>}
      </div>
      <span className='text-muted-foreground text-xs'>
        {copy.reviewBy}: {claim.reviewBy}{claim.support.title ? ` · ${claim.support.title}` : ''}
      </span>
      {canEdit && flagged && mode === 'idle' && (
        <div className='flex flex-wrap gap-2'>
          {claim.support.available && <Button variant='glass' size='lg' className='min-h-11' onClick={() => setMode('review')}>{copy.stillTrue}</Button>}
          <Button variant='glass' size='lg' className='min-h-11' onClick={() => setMode('correct')}>{copy.correct}</Button>
          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => apply({ kind: 'claim', id: series.id, revision: series.revision, claimId: claim.id, action: { action: 'remove' } })}>
            {copy.removeFact}
          </Button>
        </div>
      )}
      {mode !== 'idle' && (
        <form
          className='flex flex-col gap-2'
          onSubmit={(event) => {
            event.preventDefault();
            apply({ kind: 'claim', id: series.id, revision: series.revision, claimId: claim.id,
                    action: mode === 'review' ? { action: 'reviewed', reviewBy } : { action: 'update', text: text.trim(), reviewBy } });
            setMode('idle');
          }}
        >
          {mode === 'correct' && (
            <label htmlFor={`${id}-text`} className='flex flex-col gap-1 font-medium'>
              {copy.correctedText}
              <Textarea id={`${id}-text`} required maxLength={280} rows={2} value={text} onChange={(event) => setText(event.target.value)} className='rafii-field text-base md:text-sm' />
            </label>
          )}
          <label htmlFor={`${id}-date`} className='flex flex-col gap-1 font-medium'>
            {copy.reviewBy}
            <Input id={`${id}-date`} type='date' required value={reviewBy} min={addDays(new Date(), 1)} max={addDays(new Date(), series.limits.reviewMaxDays)}
                   onChange={(event) => setReviewBy(event.target.value)} className='rafii-field h-11 w-fit rounded-[var(--rafii-radius-control)] px-3' />
          </label>
          <div className='flex gap-2'>
            <Button type='submit' variant='glass' size='lg' className='min-h-11' disabled={busy || (mode === 'correct' && !text.trim())}>{copy.save}</Button>
            <Button type='button' variant='quiet' size='lg' className='min-h-11' onClick={() => setMode('idle')}>{copy.cancel}</Button>
          </div>
        </form>
      )}
    </li>
  );
}

/** One series: the next action, which audience questions are covered, each episode with its facts, drafts and angle
 *  decisions, and the plan/status controls. Every change waits for the server's re-read before it shows. */
export function SeriesDetailDialog({ seriesId, onClose }: { seriesId: string | null; onClose: () => void }) {
  const copy = useSeriesCopy();
  const query = useSeries(seriesId);
  const change = useSeriesChange();
  const [count, setCount] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const series = query.data?.series;
  const canEdit = Boolean(query.data?.canEdit);
  const busy = change.isPending;
  const apply: Apply = (next) => {
    setError(null);
    change.mutate(next, {
      onSuccess: (data) => (data.verified ? toast.success(copy.saved) : toast(copy.unverified)),
      onError: (failure) => setError(errorMessage(failure, copy.changeFailed))
    });
  };
  const live = series?.episodes.filter((episode) => episode.workflowState !== 'skipped') ?? [];
  const setAside = series?.episodes.filter((episode) => episode.workflowState === 'skipped') ?? [];
  return (
    <RafiiDialog open={Boolean(seriesId)} onOpenChange={(open) => !open && onClose()}>
      <RafiiDialogContent size='lg'>
        <RafiiDialogHeader title={series?.title ?? copy.sectionTitle} intro={series?.audienceQuestion} closeLabel={copy.cancel} eyebrow={series ? copy.status[series.status] : undefined} />
        <RafiiDialogBody className='flex flex-col gap-5'>
          {query.isError && <StateMessage kind='error' layout='inline' title={copy.loadError} description={errorMessage(query.error)} />}
          {query.isPending && <p role='status' className='text-muted-foreground text-sm'>…</p>}
          {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
          {series && (
            <>
              <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-1' role='status'>
                <span className='text-sm font-medium'>{nextActionText(copy, series)}</span>
                <span className='text-muted-foreground text-xs'>
                  {series.origin.available
                    ? series.origin.kind === 'post'
                      ? fill(copy.fromPost, { platform: series.origin.platform ?? '', date: series.origin.publishedAt ?? '' })
                      : fill(copy.fromSource, { title: series.origin.title ?? '' })
                    : copy.originGone}
                  {series.followers.length > 0 ? ` · ${fill(copy.followers, { n: series.followers.length })}` : ''}
                </span>
              </Surface>
              <section aria-labelledby='series-coverage' className='flex flex-col gap-2'>
                <h3 id='series-coverage' className={HEADING}>{copy.coverageHeading} · {coverageLine(copy, series.coverage.coveredCount, series.coverage.total)}</h3>
                <ul className='flex flex-col gap-1 text-sm'>
                  {series.coverage.questions.map((item) => (
                    <li key={item.episodeId} className='flex items-start gap-2'>
                      {item.covered ? <Icons.circleCheck className='mt-0.5 size-4 shrink-0' aria-hidden /> : <Icons.circleDashed className='text-muted-foreground mt-0.5 size-4 shrink-0' aria-hidden />}
                      <span>{item.index}. {item.question} <span className='text-muted-foreground'>({copy.state[item.state]})</span></span>
                    </li>
                  ))}
                </ul>
              </section>
              <section aria-labelledby='series-episodes' className='flex flex-col gap-3'>
                <h3 id='series-episodes' className={HEADING}>{copy.episodesHeading}</h3>
                {live.map((episode) => <EpisodeCard key={episode.id} copy={copy} series={series} episode={episode} canEdit={canEdit} apply={apply} busy={busy} />)}
                {setAside.length > 0 && (
                  <p className='text-muted-foreground text-xs'>{copy.state.skipped}: {setAside.map((episode) => `${episode.index}. ${copy.role[episode.role]}`).join(', ')}</p>
                )}
              </section>
              <section aria-labelledby='series-facts' className='flex flex-col gap-2'>
                <h3 id='series-facts' className={HEADING}>{copy.factsHeading}</h3>
                <ul className='flex flex-col gap-1.5'>
                  {series.claims.map((claim) => <ClaimRow key={claim.id} copy={copy} series={series} claim={claim} canEdit={canEdit} apply={apply} busy={busy} />)}
                </ul>
              </section>
              {series.decisions.length > 0 && (
                <section aria-labelledby='series-decisions' className='flex flex-col gap-2'>
                  <h3 id='series-decisions' className={HEADING}>{copy.decisionsHeading}</h3>
                  <ul className='flex flex-col gap-1.5'>
                    {series.decisions.map((decision) => (
                      <li key={decision.id} className='rafii-quiet flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
                        <span className='min-w-0 flex-1'>
                          <span className='font-medium'>{copy.decision[decision.decision]}</span> · {copy.role[decision.role]}
                          {decision.angleText ? ` · ${decision.angleText}` : ''}
                          <span className='text-muted-foreground block text-xs'>
                            {decision.status !== 'active' ? copy.revoked : decision.storage === 'overlay' ? copy.storageMemory
                              : decision.reason === 'owner_required' ? copy.reasonOwner : decision.reason === 'overlays_disabled' ? copy.reasonOverlaysOff : copy.storageSeries}
                          </span>
                        </span>
                        {decision.canRevoke && (
                          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => apply({ kind: 'revoke', id: series.id, revision: series.revision, decisionId: decision.id })}>
                            {copy.revoke}
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </RafiiDialogBody>
        {series && canEdit && (
          <RafiiDialogFooter className='flex-row flex-wrap items-center justify-end'>
            {(series.status === 'active' || series.status === 'paused') && (
              <span className='flex items-center gap-2'>
                <NativeSelect value={count} onChange={(event) => setCount(Number(event.target.value))} aria-label={copy.planMore}>
                  {[1, 2, 3, 4, 5, 6].map((value) => <NativeSelectOption key={value} value={value}>{value}</NativeSelectOption>)}
                </NativeSelect>
                <Button variant='glass' size='control' disabled={busy} onClick={() => apply({ kind: 'plan', id: series.id, revision: series.revision, count })}>{copy.planMore}</Button>
              </span>
            )}
            {series.status === 'active' && <Button variant='quiet' size='control' disabled={busy} onClick={() => apply({ kind: 'status', id: series.id, revision: series.revision, status: 'paused' })}>{copy.pause}</Button>}
            {series.status !== 'active' && <Button variant='quiet' size='control' disabled={busy} onClick={() => apply({ kind: 'status', id: series.id, revision: series.revision, status: 'active' })}>{copy.resume}</Button>}
            {series.status !== 'completed' && series.status !== 'archived' && (
              <Button variant='quiet' size='control' disabled={busy} onClick={() => apply({ kind: 'status', id: series.id, revision: series.revision, status: 'completed' })}>{copy.complete}</Button>
            )}
            {series.status !== 'archived' && <Button variant='quiet' size='control' disabled={busy} onClick={() => apply({ kind: 'status', id: series.id, revision: series.revision, status: 'archived' })}>{copy.archive}</Button>}
          </RafiiDialogFooter>
        )}
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
