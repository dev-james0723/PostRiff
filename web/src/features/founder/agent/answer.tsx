'use client';

/**
 * One Founder Rafii answer. The typed blocks render through the site agent's `RichText` (plain text with bold and
 * lists, never HTML), links are followed only inside `/founder/…`, and the founder section (PRD §6.4) is shown as
 * Facts (with receipt chips), Hypotheses, Recommendations and Unknowns. Nothing is invented: a chip appears only for
 * a receipt the server returned, "checked" rows only for tool activity it reported.
 */
import Link from 'next/link';
import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { FounderAnswerReveal, FounderApprovalCard, FounderToolChips } from '@/features/founder/motion/founder-motion';
import { RichText } from '@/features/site-agent/answer';
import { ReceiptChips } from '@/features/founder/shared/receipt-chip';
import { founderSafeHref } from '@/features/founder/shared/safe-href';
import { useEvidence } from '@/features/founder/shared/evidence-state';
import type { FounderAgentSection, FounderAgentTurnResponse, FounderLink } from '@/lib/founder/types';
import type { SiteAgentBlock } from '@/lib/site-agent/types';
import { cn } from '@/lib/utils';

export interface FounderAnswerActions {
  onAsk?: (text: string) => void;
  onNavigate?: () => void;
  latest?: boolean;
}

function FounderLinkRow({ link, onNavigate }: { link: FounderLink; onNavigate?: () => void }) {
  const { open } = useEvidence();
  const label = link.label ?? `${link.type.replaceAll('_', ' ')} ${link.id.slice(0, 8)}`;
  if (link.type === 'receipt') {
    return (
      <button type='button' onClick={() => open(link.id)} className='rafii-quiet hover:rafii-glass rafii-focus flex min-h-10 w-full items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-left text-sm'>
        <span className='min-w-0 truncate'>{label}</span>
        <Icons.page className='size-4 shrink-0' aria-hidden />
      </button>
    );
  }
  const href = founderSafeHref(link.href);
  if (!href) return <span className='text-muted-foreground px-3 text-sm'>{label}</span>;
  return (
    <Link href={href} onClick={onNavigate} className='rafii-quiet hover:rafii-glass rafii-focus flex min-h-10 items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
      <span className='min-w-0 truncate'>{label}</span>
      <Icons.arrowRight className='size-4 shrink-0' aria-hidden />
    </Link>
  );
}

function Section({ title, items, tone = 'default' }: { title: string; items: string[]; tone?: 'default' | 'muted' }) {
  if (!items.length) return null;
  return (
    <section className='flex flex-col gap-1' aria-label={title}>
      <h4 className='rafii-eyebrow'>{title}</h4>
      <ul className={cn('flex list-disc flex-col gap-1 pl-5 text-sm leading-relaxed', tone === 'muted' && 'text-muted-foreground')}>
        {items.map((item, index) => (
          <li key={index} className='break-words'>
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FounderSectionView({ founder, onNavigate }: { founder: FounderAgentSection; onNavigate?: () => void }) {
  return (
    <div className='flex flex-col gap-3' data-founder-answer>
      <Section title='Facts' items={founder.facts ?? []} />
      <ReceiptChips receiptIds={founder.receiptIds} />
      <Section title='Hypotheses' items={founder.hypotheses ?? []} tone='muted' />
      <Section title='Recommendations' items={founder.recommendations ?? []} />
      <Section title='Unknowns' items={founder.unknowns ?? []} tone='muted' />
      {founder.links?.length > 0 && (
        <nav aria-label='Related records' className='flex flex-col gap-1'>
          {founder.links.map((link) => (
            <FounderLinkRow key={`${link.type}-${link.id}`} link={link} onNavigate={onNavigate} />
          ))}
        </nav>
      )}
    </div>
  );
}

function Block({ block, actions }: { block: SiteAgentBlock; actions: FounderAnswerActions }) {
  switch (block.type) {
    case 'text':
      return <RichText text={block.text} />;
    case 'warning':
      return (
        <p role='note' className='rafii-quiet text-muted-foreground flex items-start gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-xs leading-relaxed'>
          <Icons.info className='mt-0.5 size-3.5 shrink-0' aria-hidden />
          <span>{block.message}</span>
        </p>
      );
    case 'error':
      return (
        <p role='alert' className='text-destructive flex items-start gap-2 text-sm'>
          <Icons.warning className='mt-0.5 size-4 shrink-0' aria-hidden />
          <span>{block.message}</span>
        </p>
      );
    case 'navigation_card': {
      const href = founderSafeHref(block.href);
      return href ? (
        <Link href={href} onClick={actions.onNavigate} className='rafii-glass hover:rafii-glass-selected rafii-focus flex min-h-11 items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm font-medium'>
          <span className='min-w-0 truncate'>{block.label}</span>
          <Icons.arrowRight className='size-4 shrink-0' aria-hidden />
        </Link>
      ) : (
        <span className='text-sm'>{block.label}</span>
      );
    }
    case 'question_form':
      return (
        <FounderApprovalCard title='Review Rafii suggestion' description='Choose only if you want this answer to continue; nothing is approved automatically.'>
          <RichText text={block.prompt} />
          {block.options.length > 0 && (
            <div className='flex flex-wrap gap-2' role='group' aria-label='Choose an answer'>
              {block.options.map((option) => (
                <Button key={option} type='button' variant='glass' size='sm' className='min-h-9' disabled={!actions.latest || !actions.onAsk} onClick={() => actions.onAsk?.(option)}>
                  {option}
                </Button>
              ))}
            </div>
          )}
        </FounderApprovalCard>
      );
    case 'result_list':
      return (
        <section aria-label={block.title} className='flex flex-col gap-1.5'>
          <span className='rafii-eyebrow'>{block.title}</span>
          {block.items.length === 0 ? (
            <p className='text-muted-foreground text-sm'>{block.empty ?? 'Nothing here.'}</p>
          ) : (
            <ul className='flex flex-col gap-1'>
              {block.items.map((item, index) => {
                const href = founderSafeHref(item.href);
                const inner = (
                  <>
                    <span className='min-w-0 text-sm font-medium break-words'>{item.title}</span>
                    {item.excerpt && <span className='text-muted-foreground line-clamp-2 text-xs break-words'>{item.excerpt}</span>}
                    {item.meta && <span className='text-muted-foreground text-[11px] break-words'>{item.meta}</span>}
                  </>
                );
                return (
                  <li key={`${item.kind}-${index}`}>
                    {href ? (
                      <Link href={href} onClick={actions.onNavigate} className='rafii-quiet hover:rafii-glass rafii-focus flex min-h-11 flex-col justify-center rounded-[var(--rafii-radius-control)] px-3 py-2'>
                        {inner}
                      </Link>
                    ) : (
                      <div className='rafii-quiet flex min-h-11 flex-col justify-center rounded-[var(--rafii-radius-control)] px-3 py-2'>{inner}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      );
    default:
      return null;
  }
}

/** Tool activity rows the server reported, folded away; nothing is listed that did not run. */
function Checked({ response }: { response: FounderAgentTurnResponse }) {
  return <FounderToolChips response={response} />;
}

export function FounderAnswer({ response, actions }: { response: FounderAgentTurnResponse; actions: FounderAnswerActions }) {
  const blocks = response.result?.blocks ?? [];
  const answerText = response.result?.answerText ?? '';
  const warnings = response.result?.warnings ?? [];
  const errors = response.result?.errors ?? [];
  const empty = blocks.length === 0 && !answerText && !response.founder && errors.length === 0;
  const body: ReactNode = empty ? <p className='text-muted-foreground text-sm'>Rafii returned no answer for this turn (status: {response.status}).</p> : null;
  return (
    <FounderAnswerReveal>
    <div className='flex min-w-0 flex-col gap-3'>
      {body}
      {blocks.length > 0 ? blocks.map((block, index) => <Block key={`${block.type}-${index}`} block={block} actions={actions} />) : answerText ? <RichText text={answerText} /> : null}
      {response.founder && <FounderSectionView founder={response.founder} onNavigate={actions.onNavigate} />}
      {warnings.map((warning) => (
        <p key={warning.code} role='note' className='text-muted-foreground flex items-start gap-2 text-xs'>
          <Icons.info className='mt-0.5 size-3.5 shrink-0' aria-hidden />
          <span>{warning.message}</span>
        </p>
      ))}
      {errors.map((error) => (
        <p key={error.code} role='alert' className='text-destructive flex items-start gap-2 text-sm'>
          <Icons.warning className='mt-0.5 size-4 shrink-0' aria-hidden />
          <span>{error.message}</span>
        </p>
      ))}
      <Checked response={response} />
    </div>
    </FounderAnswerReveal>
  );
}