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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { useAct, useModels, useSnapshot } from '@/lib/api/hooks';
import type { SourcePolicy } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatBytes, formatDate, formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useDraftHandoff } from './use-draft';
import { factsDigest, isWeb, kindLabel, LINK_PATTERN, plural, POLICIES, toEpoch, useActError, variantsUsing, wouldBlock, type IdeaSource, type UseState } from './use-sources';

const FACT_KINDS = new Set(['text', 'document', 'sample']);

// Sized like the Queue's hold-to-cancel: a destructive tint for the fill and its liquid edge.
const HOLD_CLASS = 'h-9 w-full min-w-0 bg-secondary px-4 text-secondary-foreground [--hold-radius:min(var(--radius-md),12px)]';
const HOLD_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const HOLD_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';

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
      <h3 className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>{title}</h3>
      {children}
    </section>
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
    <div className='flex flex-col gap-5'>
      <Header source={source} />
      {source.active ? (
        <>
          <Provenance source={source} />
          <Separator />
          <ActiveBody key={source.id} source={source} useApproved={useApproved} canEdit={canEdit} />
        </>
      ) : (
        <Section title='Withdrawn'>
          <p className='text-sm'>Withdrawn {formatDateTime(toEpoch(source.withdrawnAt))}. Its text and facts were removed from this workspace.</p>
          <p className='text-muted-foreground text-sm'>
            {blocked > 0 ? `${plural(blocked, 'draft')} that used it ${blocked === 1 ? 'is' : 'are'} blocked until regenerated.` : 'No draft is blocked by it.'}
          </p>
          <UsedIn source={source} />
        </Section>
      )}
    </div>
  );
}

function Header({ source }: { source: IdeaSource }) {
  const added = toEpoch(source.createdAt);
  return (
    <div className='flex flex-col gap-1.5 pr-8'>
      <div className='flex flex-wrap items-center gap-2'>
        <Badge variant='secondary' className='font-normal'>
          {kindLabel(source)}
        </Badge>
        {added !== null && <span className='text-muted-foreground text-xs'>Added {formatDate(added)}</span>}
      </div>
      <p className='text-base leading-snug font-semibold break-words'>{source.title || kindLabel(source)}</p>
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
            <a href={origin.url} target='_blank' rel='noreferrer' className='text-primary inline-flex w-fit max-w-full items-center gap-1 underline-offset-2 hover:underline'>
              <span className='truncate'>{origin.host || origin.url}</span>
              <Icons.externalLink className='size-3.5 shrink-0' />
            </a>
          ) : null}
          {origin.query && <span className='text-muted-foreground'>Found by web research for “{origin.query}”</span>}
          <span className='text-muted-foreground text-xs'>
            {origin.fetchedAt ? `Read ${formatDateTime(toEpoch(origin.fetchedAt))}` : 'Read time not recorded'}
            {origin.published ? ` · published ${formatDate(toEpoch(origin.published))}` : ''}
          </span>
        </div>
      ) : source.kind === 'link' && LINK_PATTERN.test(source.text) ? (
        <div className='flex flex-col gap-1 text-sm'>
          <a href={source.text} target='_blank' rel='noreferrer' className='text-primary inline-flex w-fit max-w-full items-center gap-1 underline-offset-2 hover:underline'>
            <span className='truncate'>{source.text}</span>
            <Icons.externalLink className='size-3.5 shrink-0' />
          </a>
        </div>
      ) : source.kind === 'document' ? (
        <p className='text-sm'>
          File <span className='font-medium'>{source.title}</span> <span className='text-muted-foreground'>· {formatBytes(bytes)} of text</span>
        </p>
      ) : source.kind === 'idea' ? (
        <blockquote className='border-l-2 pl-3 text-sm whitespace-pre-wrap'>{source.text}</blockquote>
      ) : source.kind === 'sample' ? (
        <p className='text-muted-foreground text-sm'>A fictional sample source.</p>
      ) : (
        <p className='text-sm'>
          Pasted text <span className='text-muted-foreground'>· {formatBytes(bytes)}</span>
        </p>
      )}
      {unknowns.length > 0 && (
        <ul className='text-muted-foreground flex flex-col gap-1 text-xs'>
          {unknowns.map((item) => (
            <li key={item} className='flex gap-1.5'>
              <Icons.info className='mt-px size-3.5 shrink-0' />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
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
  const blocks = wouldBlock(state, source.id);
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
          onError(err, 'The approved facts could not be saved.');
        }
      }
    );
  }

  function updatePolicy(next: SourcePolicy, nextCloud: boolean) {
    policyAct.mutate(
      { revision: revision(), action: 'source_policy', payload: { sourceId: source.id, policy: next, egressConsent: nextCloud ? ['local', 'cloud'] : ['local'], confirmed: true } },
      {
        onSuccess: () => toast.success(nextCloud !== cloud ? (nextCloud ? 'The cloud model may now read this source.' : 'The cloud model can no longer read this source.') : 'How this source may be used is saved.'),
        onError: (err) => onError(err, 'How this source may be used could not be saved.')
      }
    );
  }

  async function approveUse() {
    const digest = await factsDigest(source.facts);
    if (!digest) {
      toast.error('This browser cannot compute the facts fingerprint the approval needs.');
      return;
    }
    approveAct.mutate(
      { revision: revision(), action: 'source_use_approve', payload: { sourceId: source.id, factsDigest: digest, confirmed: true } },
      {
        onSuccess: () => {
          setConfirmUse(false);
          toast.success(`Public use approved for ${plural(approvedFacts.length, 'fact')}.`);
        },
        onError: (err) => {
          setConfirmUse(false);
          onError(err, 'Public use could not be approved.');
        }
      }
    );
  }

  function retract() {
    retractAct.mutate(
      { revision: revision(), action: 'retract_source', payload: { sourceId: source.id } },
      {
        onSuccess: () => toast.success(blocks > 0 ? `Source withdrawn. ${plural(blocks, 'draft')} that used it ${blocks === 1 ? 'is' : 'are'} blocked until regenerated.` : 'Source withdrawn.'),
        onError: (err) => {
          // Reset the hold so a failed withdrawal can be tried again.
          setHoldEpoch((n) => n + 1);
          onError(err, 'The source could not be withdrawn.');
        }
      }
    );
  }

  const reminders: string[] = [];
  if (!policy) reminders.push('No use is chosen yet, so drafts leave this source out until you choose one.');
  else if (policy === 'prohibited') reminders.push('Set to Do not use, so drafts leave it out.');
  else if (policy === 'internal_reference') reminders.push('Internal only, so public drafts leave it out.');
  if (hasFacts && approvedFacts.length === 0 && policy !== 'prohibited') reminders.push('No facts are approved, so a draft cannot use its wording.');
  if (policy === 'rewrite_approval' && approvedFacts.length > 0 && useApproved === false) reminders.push('Drafts from it stay candidates until public use is approved.');

  return (
    <>
      {hasFacts && (
        <Section title='Facts' data-tour='ideas-facts'>
          {source.facts.length === 0 ? (
            <p className='text-muted-foreground text-sm'>No paragraphs were split into facts from this text, so drafts cannot use its wording.</p>
          ) : (
            <>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <p className='text-sm tabular-nums'>
                  {picked.size}/{source.facts.length} selected{dirty ? ' · not saved' : ''}
                </p>
                {canEdit && (
                  <div className='flex gap-1'>
                    <Button size='xs' variant='ghost' onClick={() => setPicked(new Set(source.facts.map((f) => f.id)))} disabled={factsAct.isPending}>
                      Select all
                    </Button>
                    <Button size='xs' variant='ghost' onClick={() => setPicked(new Set())} disabled={factsAct.isPending}>
                      None
                    </Button>
                  </div>
                )}
              </div>
              <ul className='flex flex-col gap-2.5'>
                {source.facts.map((fact) => (
                  <li key={fact.id} className='flex items-start gap-2.5'>
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
                    <span className='flex min-w-0 flex-col gap-0.5 text-sm'>
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
                  size='sm'
                  variant='secondary'
                  state={factsState}
                  loadingText='Saving…'
                  successText='Saved'
                  disabled={!dirty && factsState === 'idle'}
                  onClick={saveFacts}
                  className='w-fit'
                >
                  {dirty ? `Save ${plural(picked.size, 'approved fact')}` : `${plural(saved.length, 'fact')} approved`}
                </StatefulButton>
              )}
            </>
          )}
        </Section>
      )}
      {!hasFacts && (
        <p className='text-muted-foreground text-sm'>
          {source.kind === 'idea' ? 'An idea carries no facts to approve; a draft from it uses the idea itself as the brief.' : 'A link carries no facts to approve until its page is read; a draft from it names the link as the brief.'}
        </p>
      )}

      <Section title='How it may be used' data-tour='ideas-policy'>
        <Select value={policy ?? ''} onValueChange={(value) => updatePolicy(value as SourcePolicy, cloud)}>
          <SelectTrigger className='h-9 w-full' aria-label='How this source may be used' disabled={!canEdit || policyAct.isPending}>
            <SelectValue>{POLICIES.find((p) => p.id === policy)?.label ?? 'Choose how it may be used'}</SelectValue>
          </SelectTrigger>
          <SelectContent>
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
          <p className='text-muted-foreground text-xs'>{POLICIES.find((p) => p.id === policy)?.note}</p>
        ) : (
          <AnimatedBadge size='sm' status='warning' className='w-fit' contentKey='policy-needed'>
            Policy needed
          </AnimatedBadge>
        )}
        <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
          <Switch
            checked={cloud}
            disabled={!canEdit || policyAct.isPending || !policy || policy === 'prohibited'}
            onCheckedChange={(checked) => policy && updatePolicy(policy, checked)}
            ariaLabel='Allow the cloud model to read this source'
            label='Allow the cloud model'
          />
          {models.isSuccess && !cloudAvailable && <span className='text-muted-foreground text-xs'>· no cloud model on this deployment</span>}
        </div>
        <p className='text-muted-foreground text-xs'>
          {cloud ? 'A paid cloud model may read its approved facts.' : 'A paid cloud model does not read its approved facts; other writing routes can.'}
          {!hasFacts && ` Drafting from this ${source.kind === 'idea' ? 'idea' : 'link'} sends the ${source.kind === 'idea' ? 'idea' : 'link'} itself to the model you pick, whatever this switch says.`}
        </p>
      </Section>

      {policy === 'rewrite_approval' && (
        <Section title='Public use'>
          {!hashing ? (
            <p className='text-muted-foreground text-sm'>Public-use status is unavailable in this browser.</p>
          ) : useApproved === true ? (
            <AnimatedBadge size='sm' status='success' className='w-fit' contentKey='use-approved'>
              Approved for the current facts
            </AnimatedBadge>
          ) : useApproved === false ? (
            <AnimatedBadge size='sm' status='warning' pulse={drafts.length > 0} className='w-fit' contentKey='use-needed'>
              Needed before a draft from it can be scheduled
            </AnimatedBadge>
          ) : null}
          {useApproved === false && (source.useApprovals ?? []).length > 0 && (
            <p className='text-muted-foreground text-xs'>The approved facts changed since public use was last approved, so it needs approving again.</p>
          )}
          {canEdit && useApproved === false && (
            <>
              <Button size='sm' variant='outline' className='w-fit' disabled={approvedFacts.length === 0 || approveAct.isPending} onClick={() => setConfirmUse(true)}>
                {`Approve public use of ${plural(approvedFacts.length, 'fact')}`}
              </Button>
              {approvedFacts.length === 0 && <p className='text-muted-foreground text-xs'>Approve at least one fact first.</p>}
              {dirty && approvedFacts.length > 0 && <p className='text-muted-foreground text-xs'>Approval covers the saved facts, not the unsaved ticks above.</p>}
            </>
          )}
          <AlertDialog open={confirmUse} onOpenChange={(open) => !approveAct.isPending && setConfirmUse(open)}>
            <AlertDialogContent className='data-[size=default]:sm:max-w-lg'>
              <AlertDialogHeader>
                <AlertDialogTitle>Approve public use of these facts?</AlertDialogTitle>
                <AlertDialogDescription>
                  Drafts may publish rewritten versions of exactly these {plural(approvedFacts.length, 'fact')} from “{source.title}”. Changing the facts later needs a new approval.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <ol className='bg-muted/40 flex max-h-64 list-decimal flex-col gap-1.5 overflow-y-auto rounded-lg py-2 pr-3 pl-7 text-sm'>
                {approvedFacts.map((fact) => (
                  <li key={fact.id} className='break-words'>
                    {fact.text}
                  </li>
                ))}
              </ol>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={approveAct.isPending}>Cancel</AlertDialogCancel>
                <AlertDialogAction disabled={approveAct.isPending} onClick={() => void approveUse()}>
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
          <Separator />
          <div className='flex flex-col gap-2'>
            <StatefulButton data-tour='ideas-draft' state={draft.busy ? 'loading' : 'idle'} loadingText='Starting…' disabled={retractAct.isPending} onClick={() => void draft.fromSource(source)} className='w-full'>
              Draft from this source
            </StatefulButton>
            <p className='text-muted-foreground text-xs'>
              Opens a conversation · {draft.modelLabel} · for {draft.destinationLabel}
            </p>
            {reminders.length > 0 && (
              <ul className='flex flex-col gap-1 text-xs text-amber-700 dark:text-amber-400'>
                {reminders.map((item) => (
                  <li key={item} className='flex gap-1.5'>
                    <Icons.info className='mt-px size-3.5 shrink-0' />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className='flex flex-col gap-1.5'>
            <HoldActionButton
              key={holdEpoch}
              type='horizontal'
              holdDuration={900}
              holdingLabel='Keep holding…'
              completeLabel='Withdrawing…'
              disabled={retractAct.isPending || draft.busy}
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
            <p className='text-muted-foreground text-xs'>
              Removes its text and facts. {blocks > 0 ? `Blocks ${plural(blocks, 'draft')} that used it until regenerated.` : 'No draft uses it, so nothing is blocked.'}
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
  if (drafts.length === 0) return <p className='text-muted-foreground text-sm'>Not used in any draft yet.</p>;
  return (
    <ul className='flex flex-col gap-1.5'>
      {drafts.map((variant) => (
        <li key={variant.id} className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm'>
          <span className='font-medium'>{variant.platform}</span>
          <span className='text-muted-foreground'>· {variant.language}</span>
          {variant.blockedByRetraction ? (
            <Badge variant='destructive' className='font-normal'>
              Blocked
            </Badge>
          ) : variant.needsReview ? (
            <Badge variant='outline' className='font-normal'>
              Needs review
            </Badge>
          ) : null}
        </li>
      ))}
      <li>
        <Link href='/app/pipeline' className='text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs'>
          Open the pipeline <Icons.chevronRight className='size-3' />
        </Link>
      </li>
    </ul>
  );
}
