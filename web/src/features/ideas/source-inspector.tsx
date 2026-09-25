'use client';

import { useEffect, useMemo, useState, type HTMLAttributes, type ReactNode } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import { Checkbox } from '@/components/motion/checkbox';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { Switch } from '@/components/motion/switch';
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAct, useModels, useSnapshot } from '@/lib/api/hooks';
import type { SourcePolicy } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatBytes, formatDate, formatDateTime } from '@/lib/time';
import { retractionImpact, retractionLines } from '@/lib/sources';
import { cn } from '@/lib/utils';
import { InfoTip } from '@/components/rafii';
import { STATUS } from '@/lib/status-labels';
import { useDraftHandoff } from './use-draft';
import { factsDigest, isWeb, kindIcon, kindLabel, LINK_PATTERN, plural, POLICIES, toEpoch, useActError, variantsUsing, type IdeaSource, type UseState } from './use-sources';

const FACT_KINDS = new Set(['text', 'document', 'sample']);

/* Rafii materials on the existing motion controls (DNA §10): one inverted commitment, quiet glass for the rest. */
const ACTION = 'rafii-action h-12 rounded-[var(--rafii-radius-control)] px-5 text-sm hover:bg-transparent hover:brightness-[1.06]';
const GLASS = 'rafii-glass hover:rafii-glass-selected text-foreground hover:text-foreground h-11 rounded-[var(--rafii-radius-control)] px-4 text-sm hover:bg-transparent';
const FIELD = 'rafii-field rounded-[var(--rafii-radius-control)] border-0 bg-(--rafii-surface-field) dark:bg-(--rafii-surface-field) h-12 w-full px-4 text-base data-[size=default]:h-12 md:text-sm';
// Sized like the Queue's hold-to-cancel: a quiet fill at rest, a destructive tint for the fill and its liquid edge.
const HOLD_CLASS = 'rafii-quiet h-11 w-full min-w-0 bg-transparent px-4 text-foreground [--hold-radius:var(--rafii-radius-control)]';
const HOLD_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const HOLD_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
/** A state that needs attention keeps its tint but loses the chip outline; a settled state is monochrome. */
const ATTENTION_BADGE = 'h-auto border-transparent bg-transparent px-0';
const SETTLED_BADGE = 'h-auto border-transparent bg-transparent px-0 text-foreground dark:text-foreground';
const TEXT_LINK = 'rafii-focus text-foreground decoration-muted-foreground/60 hover:decoration-foreground inline-flex w-fit max-w-full items-center gap-1 rounded-md underline underline-offset-4';

/** A StatefulButton success that settles back to idle. */
function useFlashState() {
  const [state, setState] = useState<ButtonState>('idle');
  useEffect(() => {
    if (state !== 'success') return;
    const timer = setTimeout(() => setState('idle'), 1600);
    return () => clearTimeout(timer);
  }, [state]);
  return [state, setState] as const;
}

function Section({ title, children, className, ...rest }: { title: string; children: ReactNode; className?: string } & HTMLAttributes<HTMLElement>) {
  return (
    <section className={cn('flex flex-col gap-2.5', className)} {...rest}>
      <h3 className='rafii-eyebrow'>{title}</h3>
      {children}
    </section>
  );
}

/** A plain reminder line: information, not an alarm (DNA §22.1). */
function Notes({ items, className }: { items: string[]; className?: string }) {
  return (
    <ul className={cn('text-muted-foreground flex flex-col gap-1 text-xs leading-relaxed', className)}>
      {items.map((item) => (
        <li key={item} className='flex gap-1.5'>
          <Icons.info className='mt-px size-3.5 shrink-0' aria-hidden />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

interface SourceInspectorProps {
  source: IdeaSource;
  useApproved: UseState;
}

/** One source's decisions and provenance: facts, how it may be used, public use, drafts, withdrawal. */
export function SourceInspector({ source, useApproved }: SourceInspectorProps) {
  const snapshot = useSnapshot();
  const state = snapshot.data?.state;
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const blocked = variantsUsing(state, source.id).filter((v) => v.blockedByRetraction).length;

  return (
    <div className='flex flex-col gap-6'>
      <Header source={source} />
      {source.active ? (
        <>
          <Provenance source={source} />
          <ActiveBody key={source.id} source={source} useApproved={useApproved} canEdit={canEdit} />
        </>
      ) : (
        <Section title='Withdrawn'>
          <p className='text-sm leading-relaxed'>Withdrawn {formatDateTime(toEpoch(source.withdrawnAt))}. Its text and facts were removed.</p>
          {blocked > 0 && <p className='text-muted-foreground text-sm leading-relaxed'>{plural(blocked, 'draft')} blocked until drafted again.</p>}
          <UsedIn source={source} />
        </Section>
      )}
    </div>
  );
}

function Header({ source }: { source: IdeaSource }) {
  const added = toEpoch(source.createdAt);
  const Mark = Icons[kindIcon(source)];
  return (
    <div className='flex flex-col gap-1.5 pr-8'>
      <div className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
        <span className='inline-flex items-center gap-1.5'>
          <Mark aria-hidden className='size-3.5' />
          {kindLabel(source)}
        </span>
        {added !== null && <span>Added {formatDate(added)}</span>}
      </div>
      <p className='text-foreground text-base leading-snug font-medium break-words'>{source.title || kindLabel(source)}</p>
    </div>
  );
}

function Provenance({ source }: { source: IdeaSource }) {
  const origin = source.origin;
  const unknowns = source.unknowns ?? [];
  const bytes = useMemo(() => new TextEncoder().encode(source.text ?? '').length, [source.text]);

  return (
    <Section title={source.kind === 'idea' ? 'The idea' : 'Where it came from'}>
      {isWeb(source) && origin ? (
        <div className='flex flex-col gap-1 text-sm'>
          {origin.url && LINK_PATTERN.test(origin.url) ? (
            <a href={origin.url} target='_blank' rel='noreferrer' className={TEXT_LINK}>
              <span className='truncate'>{origin.host || origin.url}</span>
              <Icons.externalLink className='size-3.5 shrink-0' />
            </a>
          ) : null}
          {origin.query && <span className='text-muted-foreground'>Found by web research for “{origin.query}”</span>}
          {(origin.fetchedAt || origin.published) && (
            <span className='text-muted-foreground text-xs'>
              {origin.fetchedAt ? `Read ${formatDateTime(toEpoch(origin.fetchedAt))}` : ''}
              {origin.fetchedAt && origin.published ? ' · ' : ''}
              {origin.published ? `published ${formatDate(toEpoch(origin.published))}` : ''}
            </span>
          )}
        </div>
      ) : source.kind === 'link' && LINK_PATTERN.test(source.text) ? (
        <div className='flex flex-col gap-1 text-sm'>
          <a href={source.text} target='_blank' rel='noreferrer' className={TEXT_LINK}>
            <span className='truncate'>{source.text}</span>
            <Icons.externalLink className='size-3.5 shrink-0' />
          </a>
        </div>
      ) : source.kind === 'document' ? (
        <p className='text-sm'>
          File <span className='font-medium'>{source.title}</span> <span className='text-muted-foreground'>· {formatBytes(bytes)} of text</span>
        </p>
      ) : source.kind === 'idea' ? (
        <blockquote className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3.5 py-3 text-sm leading-relaxed whitespace-pre-wrap'>{source.text}</blockquote>
      ) : source.kind === 'sample' ? (
        <p className='text-muted-foreground text-sm'>A fictional sample source.</p>
      ) : (
        <p className='text-sm'>
          Pasted text <span className='text-muted-foreground'>· {formatBytes(bytes)}</span>
        </p>
      )}
      {unknowns.length > 0 && <Notes items={unknowns} />}
    </Section>
  );
}

function ActiveBody({ source, useApproved, canEdit }: { source: IdeaSource; useApproved: UseState; canEdit: boolean }) {
  const snapshot = useSnapshot();
  const state = snapshot.data?.state;
  const models = useModels();
  const draft = useDraftHandoff();
  const onError = useActError();
  const factsAct = useAct();
  const policyAct = useAct();
  const approveAct = useAct();
  const retractAct = useAct();
  const [factsState, setFactsState] = useFlashState();
  const [confirmUse, setConfirmUse] = useState(false);
  const [holdEpoch, setHoldEpoch] = useState(0);

  const saved = source.facts.filter((f) => f.approved).map((f) => f.id);
  const savedKey = saved.join(',');
  // Local ticks follow the server whenever the saved approval changes (another tab, or a save here).
  const [base, setBase] = useState(savedKey);
  const [picked, setPicked] = useState<Set<string>>(() => new Set(saved));
  if (base !== savedKey) {
    setBase(savedKey);
    setPicked(new Set(saved));
  }
  const dirty = picked.size !== saved.length || saved.some((id) => !picked.has(id));

  const policy = source.sourcePolicy ?? null;
  const cloud = (source.egressConsent ?? []).includes('cloud');
  const qualified = (models.data?.models ?? []).filter((m) => m.qualified);
  const cloudAvailable = qualified.some((m) => m.costClass === 'paid');
  const hasFacts = FACT_KINDS.has(source.kind);
  const approvedFacts = source.facts.filter((f) => f.approved);
  const paragraphs = (source.text ?? '').split(/\n+/).filter((line) => line.trim()).length;
  const drafts = variantsUsing(state, source.id);
  const impact = state ? retractionImpact(state, source.id) : null;
  const retractionCopy = impact ? retractionLines(impact).join(" ") : "Retraction impact is unavailable.";
  const hashing = typeof crypto !== 'undefined' && Boolean(crypto.subtle);
  const revision = () => snapshot.data?.revision ?? 0;

  function saveFacts() {
    setFactsState('loading');
    factsAct.mutate(
      { revision: revision(), action: 'approve_source', payload: { sourceId: source.id, factIds: source.facts.filter((f) => picked.has(f.id)).map((f) => f.id) } },
      {
        onSuccess: () => setFactsState('success'),
        onError: (err) => {
          setFactsState('idle');
          onError(err, 'Couldn’t save the approved facts');
        }
      }
    );
  }

  function updatePolicy(next: SourcePolicy, nextCloud: boolean) {
    policyAct.mutate(
      { revision: revision(), action: 'source_policy', payload: { sourceId: source.id, policy: next, egressConsent: nextCloud ? ['local', 'cloud'] : ['local'], confirmed: true } },
      {
        // The switch and the select show the saved choice, so success needs no toast.
        onError: (err) => onError(err, 'Couldn’t save how this source may be used')
      }
    );
  }

  async function approveUse() {
    const digest = await factsDigest(source.facts);
    if (!digest) {
      toast.error('This browser can’t approve public use.');
      return;
    }
    approveAct.mutate(
      { revision: revision(), action: 'source_use_approve', payload: { sourceId: source.id, factsDigest: digest, confirmed: true } },
      {
        // The Public use badge turns to Approved, so success needs no toast.
        onSuccess: () => setConfirmUse(false),
        onError: (err) => {
          setConfirmUse(false);
          onError(err, 'Couldn’t approve public use');
        }
      }
    );
  }

  function retract() {
    retractAct.mutate(
      { revision: revision(), action: 'retract_source', payload: { sourceId: source.id } },
      {
        onSuccess: () => toast.success('Source withdrawn', { description: retractionCopy }),
        onError: (err) => {
          // Reset the hold so a failed withdrawal can be tried again.
          setHoldEpoch((n) => n + 1);
          onError(err, 'Couldn’t withdraw this source');
        }
      }
    );
  }

  // Only what the controls above do not already say (the chosen use is on its select).
  const reminders: string[] = [];
  if (!policy) reminders.push('Drafts leave it out until you choose how it may be used.');
  if (hasFacts && approvedFacts.length === 0 && policy !== 'prohibited') reminders.push('No approved facts, so drafts can’t use its wording.');
  if (policy === 'rewrite_approval' && approvedFacts.length > 0 && useApproved === false) reminders.push('Drafts from it can’t be scheduled until public use is approved.');

  return (
    <>
      {hasFacts && (
        <Section title='Facts' data-tour='ideas-facts'>
          {source.facts.length === 0 ? (
            <p className='text-muted-foreground text-sm leading-relaxed'>No facts found in this text.</p>
          ) : (
            <>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <p className='text-sm tabular-nums'>
                  {picked.size}/{source.facts.length} selected{dirty ? ' · not saved' : ''}
                </p>
                {canEdit && (
                  <div className='-mr-2 flex gap-1'>
                    <Button size='lg' variant='quiet' onClick={() => setPicked(new Set(source.facts.map((f) => f.id)))} disabled={factsAct.isPending}>
                      Select all
                    </Button>
                    <Button size='lg' variant='quiet' onClick={() => setPicked(new Set())} disabled={factsAct.isPending}>
                      None
                    </Button>
                  </div>
                )}
              </div>
              {/* Inclusion in analysis is its own checkbox per fact (DNA §10.6); public quoting is a separate decision below. */}
              <ul className='flex flex-col gap-2'>
                {source.facts.map((fact) => (
                  <li key={fact.id} className='flex min-h-11 items-start gap-3 py-1'>
                    <Checkbox
                      checked={picked.has(fact.id)}
                      disabled={!canEdit || factsAct.isPending}
                      aria-label={`Approve: ${fact.text.slice(0, 80)}`}
                      onCheckedChange={(checked) =>
                        setPicked((current) => {
                          const next = new Set(current);
                          if (checked) next.add(fact.id);
                          else next.delete(fact.id);
                          return next;
                        })
                      }
                      className='mt-0.5 shrink-0'
                    />
                    <span className='flex min-w-0 flex-col gap-0.5 text-sm leading-relaxed'>
                      <span className='break-words'>{fact.text}</span>
                      {fact.locator && <span className='text-muted-foreground text-xs'>{fact.locator}</span>}
                    </span>
                  </li>
                ))}
              </ul>
              {paragraphs > source.facts.length && (
                <p className='text-muted-foreground text-xs'>Only the first {source.facts.length} of {paragraphs} paragraphs became facts.</p>
              )}
              {canEdit && (
                <StatefulButton
                  variant='ghost'
                  className={cn(GLASS, 'w-fit')}
                  state={factsState}
                  loadingText='Saving…'
                  successText='Saved'
                  disabled={!dirty && factsState === 'idle'}
                  onClick={saveFacts}
                >
                  {dirty ? `Save ${plural(picked.size, 'approved fact')}` : `${plural(saved.length, 'fact')} approved`}
                </StatefulButton>
              )}
            </>
          )}
        </Section>
      )}
      {!hasFacts && (
        <p className='text-muted-foreground text-sm leading-relaxed'>
          {source.kind === 'idea' ? 'No facts to approve; drafts use the idea as the brief.' : 'No facts until the page is read; drafts use the link as the brief.'}
        </p>
      )}

      <Section title='How it may be used' data-tour='ideas-policy'>
        <Select value={policy ?? ''} onValueChange={(value) => updatePolicy(value as SourcePolicy, cloud)}>
          <SelectTrigger className={cn(FIELD, 'justify-between')} aria-label='How this source may be used' disabled={!canEdit || policyAct.isPending}>
            <SelectValue>{POLICIES.find((p) => p.id === policy)?.label ?? 'Choose how it may be used'}</SelectValue>
          </SelectTrigger>
          <SelectContent className='rafii-elevated rounded-[var(--rafii-radius-card)] ring-0'>
            {POLICIES.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                <span className='flex flex-col'>
                  <span>{p.label}</span>
                  <span className='text-muted-foreground text-xs'>{p.note}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {policy ? (
          <p className='text-muted-foreground text-xs leading-relaxed'>{POLICIES.find((p) => p.id === policy)?.note}</p>
        ) : (
          <AnimatedBadge size='sm' status='warning' className={cn(ATTENTION_BADGE, 'w-fit')} contentKey='policy-needed'>
            Policy needed
          </AnimatedBadge>
        )}
        <div className='flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1'>
          <Switch
            checked={cloud}
            disabled={!canEdit || policyAct.isPending || !policy || policy === 'prohibited'}
            onCheckedChange={(checked) => policy && updatePolicy(policy, checked)}
            ariaLabel='Allow the cloud model to read this source'
            label='Allow the cloud model'
          />
          {models.isSuccess && !cloudAvailable && <span className='text-muted-foreground text-xs'>· not available yet</span>}
          {/* Privacy detail one tap away; the line below keeps the essential fact visible. */}
          <InfoTip
            label='What the cloud switch covers'
            description={`${cloud ? 'Cloud models may read its approved facts.' : 'Cloud models don’t read its approved facts.'} Other writing routes, like an agent on your own machine, can.${
              !hasFacts ? ` Drafting from this ${source.kind === 'idea' ? 'idea' : 'link'} sends it to the model you pick, whatever this switch says.` : ''
            }`}
            className='-my-2'
          />
        </div>
        <p className='text-muted-foreground text-xs leading-relaxed'>{cloud ? 'Cloud models may read its approved facts.' : 'Cloud models don’t read its approved facts.'}</p>
      </Section>

      {policy === 'rewrite_approval' && (
        // Permission to quote publicly is explicit and separate from inclusion (DNA §21.10); it is never pre-enabled.
        <Section title='Public use'>
          {!hashing ? (
            <p className='text-muted-foreground text-sm'>Public-use status is unavailable in this browser.</p>
          ) : useApproved === true ? (
            <AnimatedBadge size='sm' status='success' className={cn(SETTLED_BADGE, 'w-fit')} contentKey='use-approved' title='Approved for the current facts'>
              {STATUS.approved}
            </AnimatedBadge>
          ) : useApproved === false ? (
            <AnimatedBadge size='sm' status='warning' pulse={drafts.length > 0} className={cn(ATTENTION_BADGE, 'w-fit')} contentKey='use-needed' title='Needed before a draft from it can be scheduled'>
              {STATUS.needsReview}
            </AnimatedBadge>
          ) : null}
          {useApproved === false && (source.useApprovals ?? []).length > 0 && <p className='text-muted-foreground text-xs leading-relaxed'>Facts changed since the last approval.</p>}
          {canEdit && useApproved === false && (
            <>
              <Button variant='glass' size='control' className='w-fit' disabled={approvedFacts.length === 0 || approveAct.isPending} onClick={() => setConfirmUse(true)}>
                {`Approve public use of ${plural(approvedFacts.length, 'fact')}`}
              </Button>
              {approvedFacts.length === 0 && <p className='text-muted-foreground text-xs'>Approve at least one fact first.</p>}
              {dirty && approvedFacts.length > 0 && <p className='text-muted-foreground text-xs'>Covers saved facts only.</p>}
            </>
          )}
          <AlertDialog open={confirmUse} onOpenChange={(open) => !approveAct.isPending && setConfirmUse(open)}>
            <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-dialog)] p-5 ring-0 data-[size=default]:sm:max-w-lg md:p-6'>
              <AlertDialogHeader>
                <AlertDialogTitle>Approve public use of these facts?</AlertDialogTitle>
                <AlertDialogDescription>
                  Drafts may publish rewritten versions of these {plural(approvedFacts.length, 'fact')} from “{source.title}”. Changing the facts needs a new approval.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <ol className='rafii-quiet flex max-h-64 list-decimal flex-col gap-1.5 overflow-y-auto rounded-[var(--rafii-radius-control)] py-2.5 pr-3 pl-8 text-sm leading-relaxed'>
                {approvedFacts.map((fact) => (
                  <li key={fact.id} className='break-words'>
                    {fact.text}
                  </li>
                ))}
              </ol>
              <AlertDialogFooter>
                <AlertDialogCancel variant='glass' size='control' disabled={approveAct.isPending}>Cancel</AlertDialogCancel>
                <AlertDialogAction variant='action' size='control' disabled={approveAct.isPending} onClick={() => void approveUse()}>
                  {approveAct.isPending ? 'Approving…' : 'Approve public use'}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </Section>
      )}

      <Section title='Drafts that use it'>
        <UsedIn source={source} />
      </Section>

      {canEdit && (
        <>
          <div className='flex flex-col gap-2'>
            {/* The one dominant commitment on this surface (DNA §9.2). */}
            <StatefulButton data-tour='ideas-draft' className={cn(ACTION, 'w-full')} state={draft.busy ? 'loading' : 'idle'} loadingText='Starting…' disabled={retractAct.isPending} onClick={() => void draft.fromSource(source)}>
              Draft from this source
            </StatefulButton>
            <p className='text-muted-foreground hidden text-xs leading-relaxed sm:block'>
              {draft.modelLabel} · {draft.destinationLabel}
            </p>
            {reminders.length > 0 && <Notes items={reminders} />}
          </div>
          <div className='flex flex-col gap-1.5'>
            <HoldActionButton
              key={holdEpoch}
              type='horizontal'
              holdDuration={900}
              holdingLabel='Keep holding…'
              completeLabel='Withdrawing…'
              disabled={!impact || retractAct.isPending || draft.busy}
              onHoldComplete={retract}
              aria-label={`Hold to withdraw ${source.title}`}
              title='Press and hold (or hold Space) to withdraw this source.'
              className={HOLD_CLASS}
              fillClassName={HOLD_FILL}
              waveClassName={HOLD_WAVE}
              labelClassName='text-sm'
            >
              Hold to withdraw
            </HoldActionButton>
            <p className='text-muted-foreground text-xs leading-relaxed'>
              Removes its text and facts. {retractionCopy}
            </p>
          </div>
        </>
      )}
    </>
  );
}

function UsedIn({ source }: { source: IdeaSource }) {
  const snapshot = useSnapshot();
  const drafts = variantsUsing(snapshot.data?.state, source.id);
  if (drafts.length === 0) return <p className='text-muted-foreground text-sm'>Not used yet</p>;
  return (
    <ul className='flex flex-col gap-1.5'>
      {drafts.map((variant) => (
        <li key={variant.id} className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm'>
          <span className='font-medium'>{variant.platform}</span>
          <span className='text-muted-foreground'>· {variant.language}</span>
          {variant.blockedByRetraction ? (
            <span className='text-destructive inline-flex items-center gap-1 text-xs font-medium'>
              <Icons.warning aria-hidden className='size-3.5' />
              Blocked
            </span>
          ) : variant.needsReview ? (
            <span className='text-muted-foreground inline-flex items-center gap-1 text-xs'>
              <Icons.eye aria-hidden className='size-3.5' />
              {STATUS.needsReview}
            </span>
          ) : null}
        </li>
      ))}
      <li>
        <Link href='/app/queue?view=drafts' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-9 items-center gap-1 rounded-md text-xs'>
          Open drafts <Icons.chevronRight className='size-3' />
        </Link>
      </li>
    </ul>
  );
}
