'use client';
/**
 * J05 — Campaign planning (lane E): campaign briefs, one campaign's plan with derived gaps and progress (each with the
 * rule that produced it), its complete membership, a zone-explicit timeline, and the guarded campaign commands: create a
 * brief, edit it at the version the person saw, and add picked drafts to it.
 *
 * Truth rules: a campaign has no completion state of its own, so progress is labelled as derived; dependencies between
 * items are not recorded, so none are drawn; linking is organisation only (nothing is drafted, scheduled or published).
 */
import { z } from 'zod';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { formatCalendarDate, formatInstant } from '../../journeys/format';
import { useBound, useJourneyEnvironment, useSelectionRecorder } from '../../journeys/runtime';
import { GuardedAction, Missing, Pill, QueryFrame, SelectToggle } from './shared';
import type { JourneyRendererProps } from './types';

const ID = /^[A-Za-z0-9_.:-]{1,120}$/;
const titleProps = z.object({ title: z.string().max(120).optional() });

function idList(value: unknown, max: number): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string' && ID.test(v)).slice(0, max) : [];
}

export function CampaignList({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = titleProps.safeParse(props);
  const selection = useBound<string>(`${statementId ?? 'campaigns'}Selected`, props.selected);
  const selected = typeof selection.value === 'string' && selection.value ? selection.value : null;
  const record = useSelectionRecorder(statementId ?? 'campaigns');
  return (
    <QueryFrame value={props.data} binding='campaigns_list' label={copy.campaigns.listTitle} title={(literal.success ? literal.data.title : null) ?? copy.campaigns.listTitle}>
      {(data) => (
        <ul className='flex flex-col divide-y divide-border rounded-[var(--rafii-radius-card)] border'>
          {data.campaigns.map((c) => {
            const isSelected = selected === c.campaignId;
            return (
              <li key={c.ref} className={cn('flex items-start gap-3 p-2.5', isSelected && 'bg-muted/40')}>
                <SelectToggle
                  selected={isSelected}
                  label={c.goal ?? c.campaignId}
                  onToggle={() => {
                    selection.set(isSelected ? '' : c.campaignId);
                    record(isSelected ? [] : [{ type: 'campaign', id: c.campaignId, title: (c.goal ?? '').slice(0, 80) }], data.campaigns.map((x) => ({ type: 'campaign', id: x.campaignId })));
                  }}
                />
                <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
                  <span className='text-sm font-medium break-words' dir='auto'>
                    {c.goal ?? <Missing />}
                  </span>
                  <span className='flex flex-wrap items-center gap-2 text-xs'>
                    {c.status ? <Pill tone={c.status === 'active' ? 'good' : c.status === 'needs_input' ? 'waiting' : 'muted'}>{copy.campaigns.status[c.status] ?? c.status}</Pill> : null}
                    {c.platforms && c.platforms.length ? <span className='text-muted-foreground'>{c.platforms.join(', ')}</span> : null}
                    {c.missingFacts && c.missingFacts.length ? (
                      <span className='text-muted-foreground'>
                        {copy.campaigns.missingFacts}: {c.missingFacts.join(', ')}
                      </span>
                    ) : null}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </QueryFrame>
  );
}

export function CampaignPlan({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='campaign_detail' label={copy.campaigns.listTitle}>
      {(c) => (
        <article className='flex flex-col gap-3 rounded-[var(--rafii-radius-card)] border p-3'>
          <header className='flex flex-col gap-1'>
            <span className='flex flex-wrap items-center gap-2'>
              {c.status ? <Pill tone={c.status === 'active' ? 'good' : 'muted'}>{copy.campaigns.status[c.status] ?? c.status}</Pill> : null}
              {c.platforms && c.platforms.length ? <span className='text-muted-foreground text-xs'>{c.platforms.join(', ')}</span> : null}
            </span>
            <dl className='grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm'>
              <dt className='text-muted-foreground'>{copy.campaigns.goal}</dt>
              <dd dir='auto'>{c.goal ?? <Missing />}</dd>
              <dt className='text-muted-foreground'>{copy.campaigns.audience}</dt>
              <dd dir='auto'>{c.audience ?? <Missing />}</dd>
              {c.facts && Object.keys(c.facts).length ? (
                <>
                  <dt className='text-muted-foreground'>{copy.campaigns.facts}</dt>
                  <dd>
                    {Object.entries(c.facts)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(' · ')}
                  </dd>
                </>
              ) : null}
              {c.missingFacts && c.missingFacts.length ? (
                <>
                  <dt className='text-muted-foreground'>{copy.campaigns.missingFacts}</dt>
                  <dd>{c.missingFacts.join(', ')}</dd>
                </>
              ) : null}
            </dl>
          </header>
          <div className='flex flex-col gap-1'>
            <h4 className='text-xs font-semibold'>{copy.campaigns.automations}</h4>
            {c.automations && c.automations.length ? (
              <ul className='flex flex-col gap-1 text-sm'>
                {c.automations.map((a) => (
                  <li key={a.automationId} className='flex flex-wrap items-center gap-2'>
                    <span>{a.name ?? a.automationId}</span>
                    {a.status ? <Pill tone={a.status === 'active' ? 'good' : 'muted'}>{copy.automations.status[a.status] ?? a.status}</Pill> : null}
                    <span className='text-muted-foreground text-xs'>{a.schedule ?? ''}</span>
                    <span className='text-muted-foreground text-xs'>
                      {copy.campaigns.nextRun}: {a.nextRun ?? copy.campaigns.noNextRun}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className='text-muted-foreground text-xs'>{copy.common.none}</p>
            )}
          </div>
          {c.progress ? (
            <div className='flex flex-col gap-0.5 text-sm'>
              <h4 className='text-xs font-semibold'>{copy.campaigns.progressTitle}</h4>
              <p>
                {copy.campaigns.progress({
                  drafts: c.progress.items.drafts,
                  review: c.progress.items.draftsNeedingReview,
                  posts: c.progress.items.posts,
                  verified: c.progress.items.postsVerified,
                  waiting: c.progress.items.postsWaiting,
                })}
              </p>
              {c.progress.items.missing ? <p className='text-muted-foreground text-xs'>{copy.campaigns.missingItems(c.progress.items.missing)}</p> : null}
              <p className='text-muted-foreground text-xs'>
                {copy.common.rule}: {c.progress.rule}
              </p>
            </div>
          ) : null}
          {c.derived ? (
            <div className='flex flex-col gap-0.5 text-xs'>
              <h4 className='font-semibold'>{copy.campaigns.gaps}</h4>
              {c.derived.platformsNotCovered && c.derived.platformsNotCovered.items.length ? (
                <p>
                  {c.derived.platformsNotCovered.items.join(', ')} <span className='text-muted-foreground'>({c.derived.platformsNotCovered.rule})</span>
                </p>
              ) : null}
              {c.derived.noUpcomingRun && c.derived.noUpcomingRun.value ? (
                <p>
                  {copy.campaigns.noNextRun} <span className='text-muted-foreground'>({c.derived.noUpcomingRun.rule})</span>
                </p>
              ) : null}
              {c.derived.failedOrSkippedLastWeek && c.derived.failedOrSkippedLastWeek.items.length ? (
                <p>
                  {c.derived.failedOrSkippedLastWeek.items.map((r) => [r.status, r.when].filter(Boolean).join(' ')).join('; ')}{' '}
                  <span className='text-muted-foreground'>({c.derived.failedOrSkippedLastWeek.rule})</span>
                </p>
              ) : null}
            </div>
          ) : null}
          <p className='text-muted-foreground text-xs'>{copy.campaigns.noDependencies}</p>
        </article>
      )}
    </QueryFrame>
  );
}

export function CampaignItems({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='campaign_items' label={copy.campaigns.itemsTitle} title={copy.campaigns.itemsTitle}>
      {(data) => (
        <ul className='flex flex-col gap-1 text-sm'>
          {data.items.map((item, i) => (
            <li key={item.itemId ?? item.ref ?? i} className='flex flex-col gap-0.5 rounded-md border p-2'>
              <span className='flex flex-wrap items-center gap-2'>
                <Pill tone='neutral'>{copy.campaigns.itemKind[item.kind] ?? item.kind}</Pill>
                {item.platform ? <span className='text-muted-foreground text-xs'>{item.platform}</span> : null}
                {item.needsReview ? <Pill tone='waiting'>{copy.drafts.needsReview}</Pill> : null}
                {item.exists === false ? <Pill tone='attention'>{copy.campaigns.itemGone}</Pill> : null}
                {item.state ? <span className='text-muted-foreground text-xs'>{item.state.replaceAll('_', ' ')}</span> : null}
              </span>
              {item.excerpt ? (
                <span className='break-words' dir='auto'>
                  {item.excerpt}
                </span>
              ) : null}
              {item.kind === 'post' && (item.atUtc || item.local) ? (
                <span className='text-muted-foreground text-xs'>{formatInstant(item.atUtc, item.timeZone, locale, item.local)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </QueryFrame>
  );
}

export function CampaignTimeline({ props }: JourneyRendererProps) {
  const { copy, locale } = useJourneyEnvironment();
  const literal = titleProps.safeParse(props);
  return (
    <QueryFrame value={props.data} binding='campaign_timeline' label={copy.campaigns.timelineTitle} title={(literal.success ? literal.data.title : null) ?? copy.campaigns.timelineTitle}>
      {(data) => {
        const days = new Map<string, typeof data.events>();
        for (const e of data.events) {
          const day = e.local && /^\d{4}-\d{2}-\d{2}/.test(e.local) ? e.local.slice(0, 10) : '';
          days.set(day, [...(days.get(day) ?? []), e]);
        }
        return (
          <div className='flex flex-col gap-2'>
            <p className='text-muted-foreground text-xs'>
              {copy.common.timeZone}: {data.timeZone}
            </p>
            <ol className='flex flex-col gap-2'>
              {[...days.entries()].map(([day, events]) => (
                <li key={day || 'undated'} className='flex flex-col gap-1'>
                  <h4 className='text-xs font-semibold'>{formatCalendarDate(day, locale) ?? copy.common.noDate}</h4>
                  <ul className='flex flex-col gap-1 border-l pl-3 text-sm'>
                    {events.map((e, i) => (
                      <li key={`${e.ref ?? e.kind}:${i}`} className='flex flex-wrap items-center gap-2'>
                        <span className='tabular-nums'>{formatInstant(e.atUtc, data.timeZone, locale, e.local, { withZone: false })}</span>
                        <Pill tone={e.kind === 'planned_run' ? 'muted' : 'neutral'}>{copy.campaigns.eventKind[e.kind] ?? e.kind}</Pill>
                        {e.name || e.platform ? <span>{e.name ?? e.platform}</span> : null}
                        {e.status ? <span className='text-muted-foreground text-xs'>{(copy.automations.runStatus[e.status] ?? e.status).replaceAll('_', ' ')}</span> : null}
                        {e.scheduleZone && e.scheduleZone !== data.timeZone ? <span className='text-muted-foreground text-xs'>({e.scheduleZone})</span> : null}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
            {data.truncated ? <p className='text-muted-foreground text-xs'>{copy.common.more}</p> : null}
          </div>
        );
      }}
    </QueryFrame>
  );
}

const briefProps = z.object({ actionId: z.literal('campaign_create'), name: z.string().regex(/^[A-Za-z][A-Za-z0-9_]{0,39}$/) });

export function CampaignBriefForm({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = briefProps.safeParse(props);
  const name = literal.success ? literal.data.name : 'brief';
  const goal = useBound<string>(`${name}Goal`, undefined);
  const audience = useBound<string>(`${name}Audience`, undefined);
  const date = useBound<string>(`${name}Date`, undefined);
  const venue = useBound<string>(`${name}Venue`, undefined);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  const v = (f: { value: string | undefined }) => (typeof f.value === 'string' ? f.value : '');
  const ready = v(goal).trim().length > 0 && v(audience).trim().length > 0;
  const base = statementId ?? name;
  return (
    <section aria-label={copy.campaigns.briefTitle} className='flex flex-col gap-2'>
      <h3 className='text-sm font-semibold'>{copy.campaigns.briefTitle}</h3>
      <label className='flex flex-col gap-1 text-xs' htmlFor={`${base}-goal`}>
        {copy.campaigns.goal}
        <Textarea id={`${base}-goal`} rows={2} maxLength={1200} value={v(goal)} dir='auto' onChange={(e) => goal.set(e.target.value)} />
      </label>
      <label className='flex flex-col gap-1 text-xs' htmlFor={`${base}-audience`}>
        {copy.campaigns.audience}
        <Textarea id={`${base}-audience`} rows={2} maxLength={800} value={v(audience)} dir='auto' onChange={(e) => audience.set(e.target.value)} />
      </label>
      <div className='grid gap-2 @[24rem]:grid-cols-2'>
        <label className='flex flex-col gap-1 text-xs' htmlFor={`${base}-date`}>
          {copy.campaigns.date}
          <Input id={`${base}-date`} maxLength={80} value={v(date)} onChange={(e) => date.set(e.target.value)} />
        </label>
        <label className='flex flex-col gap-1 text-xs' htmlFor={`${base}-venue`}>
          {copy.campaigns.venue}
          <Input id={`${base}-venue`} maxLength={160} value={v(venue)} onChange={(e) => venue.set(e.target.value)} />
        </label>
      </div>
      <p className='text-muted-foreground text-xs'>{copy.campaigns.briefHint}</p>
      <GuardedAction
        actionId={literal.data.actionId}
        controlId={statementId}
        ready={ready}
        inputs={
          ready
            ? {
                goal: v(goal).trim(),
                audience: v(audience).trim(),
                ...(v(date).trim() ? { date: v(date).trim() } : {}),
                ...(v(venue).trim() ? { venue: v(venue).trim() } : {}),
              }
            : null
        }
      />
    </section>
  );
}

const editProps = z.object({ actionId: z.literal('campaign_update'), name: z.string().regex(/^[A-Za-z][A-Za-z0-9_]{0,39}$/) });

export function CampaignBriefEditor({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = editProps.safeParse(props);
  const name = literal.success ? literal.data.name : 'briefEdit';
  const goal = useBound<string>(`${name}Goal`, undefined);
  const audience = useBound<string>(`${name}Audience`, undefined);
  const base = useBound<number>(`${name}Version`, undefined);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  return (
    <QueryFrame value={props.data} binding='campaign_detail' label={copy.campaigns.editTitle} title={copy.campaigns.editTitle}>
      {(c) => {
        const goalValue = typeof goal.value === 'string' ? goal.value : c.goal ?? '';
        const audienceValue = typeof audience.value === 'string' ? audience.value : c.audience ?? '';
        const version = typeof base.value === 'number' ? base.value : c.version;
        const changed = goalValue.trim() !== (c.goal ?? '').trim() || audienceValue.trim() !== (c.audience ?? '').trim();
        const stale = typeof base.value === 'number' && base.value !== c.version;
        const remember = () => {
          if (typeof base.value !== 'number') base.set(c.version);
        };
        const id = statementId ?? name;
        return (
          <div className='flex flex-col gap-2'>
            <label className='flex flex-col gap-1 text-xs' htmlFor={`${id}-goal`}>
              {copy.campaigns.goal}
              <Textarea id={`${id}-goal`} rows={2} maxLength={1200} value={goalValue} dir='auto' onChange={(e) => {
                remember();
                goal.set(e.target.value);
              }} />
            </label>
            <label className='flex flex-col gap-1 text-xs' htmlFor={`${id}-audience`}>
              {copy.campaigns.audience}
              <Textarea id={`${id}-audience`} rows={2} maxLength={800} value={audienceValue} dir='auto' onChange={(e) => {
                remember();
                audience.set(e.target.value);
              }} />
            </label>
            {stale ? <p className='text-destructive text-xs'>{copy.states.stale}</p> : null}
            <p className='text-muted-foreground text-xs'>{copy.campaigns.editHint}</p>
            <GuardedAction
              actionId={literal.data.actionId}
              controlId={statementId}
              ready={changed && goalValue.trim().length > 0 && audienceValue.trim().length > 0}
              inputs={{ campaignId: c.campaignId, expectedVersion: version, goal: goalValue.trim(), audience: audienceValue.trim() }}
            />
          </div>
        );
      }}
    </QueryFrame>
  );
}

const linkProps = z.object({ actionId: z.literal('campaign_link') });

/** Add the picked drafts to a campaign (organisation only). `data` is the campaign_detail Query of the target campaign. */
export function CampaignLinkDrafts({ props, statementId }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const literal = linkProps.safeParse(props);
  const drafts = useBound<string[]>(`${statementId ?? 'link'}Drafts`, props.drafts);
  const picked = idList(drafts.value, 20);
  if (!literal.success) return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  return (
    <QueryFrame value={props.data} binding='campaign_detail' label={copy.campaigns.linkTitle} title={copy.campaigns.linkTitle}>
      {(c) => (
        <div className='flex flex-col gap-1.5'>
          <p className='text-sm' dir='auto'>
            {c.goal ?? <Missing />}
          </p>
          <p className='text-muted-foreground text-xs'>
            {picked.length ? copy.common.selected(picked.length) : copy.campaigns.pickDrafts} · {copy.campaigns.linkHint}
          </p>
          <GuardedAction
            actionId={literal.data.actionId}
            controlId={statementId}
            ready={picked.length > 0}
            notReadyHint={copy.campaigns.pickDrafts}
            inputs={picked.length ? { campaignId: c.campaignId, draftIds: picked } : null}
          />
        </div>
      )}
    </QueryFrame>
  );
}
