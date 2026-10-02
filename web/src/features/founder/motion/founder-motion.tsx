'use client';

import Link from 'next/link';
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, isValidElement, type ReactElement, type ReactNode } from 'react';
import { useIsFetching, useIsMutating } from '@tanstack/react-query';
import { AnimatePresence, LayoutGroup, motion } from 'motion/react';
import { Icons } from '@/components/icons';
import { useFounderPendingActions, useVisibleFounderMotion } from './founder-motion-root';
export { FounderBentoFocus } from './founder-bento-focus';
import { TooltipSurface } from '@/components/motion/tooltip-surface';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { FOUNDER_SECTIONS, FOUNDER_NAV_GROUPS, founderHref, sectionForPathname } from '@/config/founder-nav';
import { formatMetricValue, formatTick } from '@/features/founder/shared/format';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import type { FounderAgentTurnResponse, OverviewTrend } from '@/lib/founder/types';
import { conversationKey, useFounderPanel, type FounderThreadItem } from '../agent/store';
import { useFounderSession } from '../shell/founder-session';
import {
  applyDraftSuggestion,
  buildDiffRows,
  createAgentRevisionPrompt,
  createDraftRevision,
  createSingleDispatchGuard,
  deriveFounderDynamicStatus,
  founderTrendRows,
  makeLocalDraftSuggestion,
  normalizeDonutItems,
  reconcileTrendIndex,
  undoDraftSuggestion,
  type AppliedDraftSuggestion,
  type DraftSuggestion
} from './founder-motion-behavior';

const TRANSITION = { type: 'spring', stiffness: 440, damping: 38, mass: 0.8 } as const;
const LINE_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)'];

export function FounderDynamicStatus({ className }: { className?: string }) {
  const { mode, environment, sessionStatus } = useFounderSession();
  const key = conversationKey(mode, environment);
  const busy = useFounderPanel((state) => Boolean(state.busy[key]));
  const fetching = useIsFetching({ queryKey: ['founder'] });
  // The enclosing QueryClient belongs only to Founder. Existing mutations have no mutationKey.
  const mutating = useIsMutating() + useFounderPendingActions();
  const status = deriveFounderDynamicStatus({ founderFetching: fetching, founderMutating: mutating, agentBusy: busy, sessionStatus });
  return (
    <motion.div layout transition={TRANSITION} className={cn('rafii-glass hidden min-h-9 items-center gap-2 rounded-full px-3 text-xs md:inline-flex', className)} data-founder-motion='07'>
      <span aria-hidden className={cn('relative flex size-2.5 rounded-full bg-current', status.tone)}>
        {status.busy && <span className='absolute inset-0 rounded-full bg-current opacity-30' />}
      </span>
      <AnimatePresence mode='wait' initial={false}>
        <motion.span key={`${status.state}-${status.label}`} initial={{ y: 8, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -8, opacity: 0 }} transition={{ duration: 0.18 }}>
          {status.label}
        </motion.span>
      </AnimatePresence>
    </motion.div>
  );
}

export function FounderNavIsland({ pathname }: { pathname: string }) {
  const { mode, environment } = useFounderSession();
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const current = FOUNDER_SECTIONS[sectionForPathname(pathname) ?? 'overview'];
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    function onPointer(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node | null)) setOpen(false);
    }
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);
  return (
    <div ref={root} className='relative hidden lg:block' data-founder-motion='03'>
      <Button type='button' variant='ghost' size='control' aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)} className='relative isolate h-9 gap-2 rounded-full px-3 text-xs'>
        {!open && <motion.span layoutId={`founder-island-${id}`} aria-hidden className='rafii-glass pointer-events-none absolute inset-0 -z-1 rounded-full' transition={TRANSITION} />}
        <Icons.shieldCheck className='size-3.5' />
        <span>{environment ?? 'checking'}</span>
        <span className='text-muted-foreground'>/ {current.shortTitle}</span>
        <Icons.chevronDown className='size-3.5' />
      </Button>
      <AnimatePresence>
        {open && (
          <motion.div id={id} layoutId={`founder-island-${id}`} initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6, scale: 0.98 }} transition={{ duration: 0.18 }} className='rafii-elevated absolute right-0 mt-2 grid w-72 grid-cols-2 gap-1 rounded-[var(--rafii-radius-dialog)] p-2 text-sm shadow-lg'>
            {FOUNDER_NAV_GROUPS.flatMap((group) => group.items).map((id) => {
              const section = FOUNDER_SECTIONS[id];
              const Icon = Icons[section.icon];
              return (
                <Link key={id} href={founderHref(id, mode)} onClick={() => setOpen(false)} aria-current={section.id === current.id ? 'page' : undefined} className='rafii-focus hover:rafii-glass flex min-h-10 items-center gap-2 rounded-[var(--rafii-radius-control)] px-2'>
                  <Icon className='size-4 shrink-0' />
                  <span className='truncate'>{section.shortTitle}</span>
                </Link>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function FounderMobileAccountSheet() {
  const { mode, environment, sessionStatus, signOut } = useFounderSession();
  const [open, setOpen] = useState(false);
  return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger render={<Button type='button' variant='ghost' size='icon' aria-label='Founder account menu' aria-expanded={open} className='md:hidden' data-founder-motion='05' />}>
          <Icons.shieldCheck className='size-[1.2rem]' />
        </SheetTrigger>
        <SheetContent side='bottom' className='rafii-elevated max-h-[82dvh] gap-3 overflow-y-auto rounded-t-[var(--rafii-radius-mobile-dialog)] border-0 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]'>
          <SheetHeader className='p-0'>
            <SheetTitle>Founder session</SheetTitle>
            <SheetDescription>{sessionStatus === 'ready' ? `Verified in ${environment ?? 'this environment'} · ${mode === 'demo' ? 'Demo data' : 'Live data'}` : sessionStatus === 'loading' ? 'Verifying session' : 'Session verification failed'}</SheetDescription>
          </SheetHeader>
          <nav aria-label='Quick navigation' className='grid grid-cols-2 gap-2'>
            {FOUNDER_NAV_GROUPS.flatMap((group) => group.items).map((id) => {
              const section = FOUNDER_SECTIONS[id];
              const Icon = Icons[section.icon];
              return (
                <Link key={id} href={founderHref(id, mode)} onClick={() => setOpen(false)} className='rafii-quiet rafii-focus flex min-h-12 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 text-sm'>
                  <Icon className='size-4' />
                  {section.shortTitle}
                </Link>
              );
            })}
          </nav>
          <Button type='button' variant='glass' size='control' onClick={() => void signOut()}>
            <Icons.logout /> Sign out
          </Button>
        </SheetContent>
      </Sheet>
  );
}

export function FounderMorphSelect<T extends string>({ label, value, options, onChange, className }: { label: string; value: T; options: readonly { value: T; label: ReactNode }[]; onChange: (value: T) => void; className?: string }) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger aria-label={label} size='sm' className={cn('rafii-glass h-9 rounded-full border-transparent px-3 text-xs shadow-none', className)} data-founder-motion='04'>
        <span className='text-muted-foreground'>{label}</span>
        <motion.span layout='position' transition={TRANSITION} className='font-medium'>
          <SelectValue>{options.find((option) => option.value === value)?.label ?? value}</SelectValue>
        </motion.span>
      </SelectTrigger>
      <SelectContent align='end' className='rounded-2xl'>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function FounderExpandableActionBar({ actions, className, 'aria-describedby': ariaDescribedBy }: { actions: { id: string; label: string; icon: ReactNode; disabled?: boolean; reason?: string | null; onClick: () => void }[]; className?: string; 'aria-describedby'?: string }) {
  const base = useId();
  return (
    <div className={cn('flex flex-wrap gap-2', className)} aria-describedby={ariaDescribedBy} data-founder-motion='06'>
      {actions.map((action, index) => {
        const reasonId = action.reason ? `${base}-${index}-reason` : undefined;
        return (
        <Tooltip key={action.id}>
          <TooltipTrigger render={<Button variant='glass' size='sm' disabled={action.disabled} aria-label={action.label} aria-describedby={reasonId ?? ariaDescribedBy} onClick={action.onClick} className='group/action max-w-full overflow-hidden transition-[max-width,padding] duration-300 [@media(hover:hover)]:max-w-10 [@media(hover:hover)]:focus-within:max-w-56 [@media(hover:hover)]:hover:max-w-56' />}>
            <span className='shrink-0'>{action.icon}</span>
            <span className='truncate [@media(hover:hover)]:max-w-0 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:transition-[max-width,opacity] [@media(hover:hover)]:duration-300 [@media(hover:hover)]:group-focus-within/action:max-w-44 [@media(hover:hover)]:group-focus-within/action:opacity-100 [@media(hover:hover)]:group-hover/action:max-w-44 [@media(hover:hover)]:group-hover/action:opacity-100'>{action.label}</span>
          </TooltipTrigger>
          <TooltipContent>{action.reason ?? action.label}</TooltipContent>
          {action.reason && <span id={reasonId} className='sr-only'>{action.reason}</span>}
        </Tooltip>
        );
      })}
    </div>
  );
}

export function FounderInlineConfirm({ label, confirmLabel = 'Confirm', disabled, onConfirm, children }: { label: ReactNode; confirmLabel?: string; disabled?: boolean; onConfirm: () => void; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <motion.div layout className='inline-flex flex-wrap items-center gap-2' data-founder-motion='10'>
      {!open ? (
        <Button type='button' variant='glass' size='sm' disabled={disabled} onClick={() => setOpen(true)}>
          {label}
        </Button>
      ) : (
        <motion.div layout initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} className='rafii-glass flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] p-1'>
          {children}
          <Button type='button' variant='quiet' size='sm' onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type='button' variant='action' size='sm' disabled={disabled} onClick={() => { setOpen(false); onConfirm(); }}>
            {confirmLabel}
          </Button>
        </motion.div>
      )}
    </motion.div>
  );
}

export function FounderSlideConfirm({ disabled, onConfirm, label = 'Slide to confirm' }: { disabled?: boolean; onConfirm: () => void; label?: string }) {
  const [value, setValue] = useState(0);
  const id = useId();
  const guard = useRef(createSingleDispatchGuard());
  useEffect(() => {
    setValue(0);
    guard.current = createSingleDispatchGuard();
  }, [disabled]);
  function commit(complete: boolean) {
    guard.current(!disabled && complete, () => {
      setValue(0);
      onConfirm();
    });
  }
  return (
    <div className='rafii-quiet flex min-w-0 flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3' data-founder-motion='11' onPointerCancel={() => setValue(0)} onBlur={(event) => !event.currentTarget.contains(event.relatedTarget as Node | null) && setValue(0)}>
      <label className='text-muted-foreground text-xs' htmlFor={id}>{label}</label>
      <input id={id} type='range' min={0} max={100} value={value} disabled={disabled} aria-label={label} aria-describedby={`${id}-alternative`} onChange={(event) => setValue(Number(event.target.value))} onPointerUp={(event) => commit(Number(event.currentTarget.value) >= 96)} onKeyUp={(event) => (event.key === 'Enter' || event.key === ' ') && commit(Number(event.currentTarget.value) >= 96)} className='w-full accent-foreground' />
      <span id={`${id}-alternative`} className='text-muted-foreground text-xs'>Drag to the end, or use the confirmation button. The same permission and preview checks apply.</span>
      <Button type='button' variant='destructive' size='sm' disabled={disabled} onClick={() => commit(true)}>Confirm action</Button>
    </div>
  );
}

export function FounderDetailDialog({ children, className, sourceId }: { children: ReactNode; className?: string; sourceId?: string | null }) {
  return (
    <motion.div layout layoutId={sourceId ? `founder-customer-${sourceId}` : undefined} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 12 }} transition={TRANSITION} className={className} data-founder-motion='12'>
      {children}
    </motion.div>
  );
}

export function FounderStepPanel({ step, children }: { step: string; children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  const { reduced } = useMotionPreference();
  useLayoutEffect(() => {
    const element = inner.current;
    if (!element) return;
    const measure = () => setHeight(element.getBoundingClientRect().height);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <motion.div initial={false} animate={{ height: height ?? 'auto' }} transition={{ duration: reduced ? 0 : 0.22 }} className='overflow-hidden' data-founder-motion='13' data-step={step}>
      <div ref={inner}>{children}</div>
    </motion.div>
  );
}

export function FounderAnimatedRows({ children, className, label }: { children: ReactNode; className?: string; label?: string }) {
  return (
    <LayoutGroup>
      <motion.div layout className={className} aria-label={label} data-founder-motion='14'>
        {children}
      </motion.div>
    </LayoutGroup>
  );
}

export function FounderSelectedRow({ selected, children, className }: { selected?: boolean; children: ReactNode; className?: string }) {
  return (
    <motion.div layout transition={TRANSITION} data-selected={selected ? 'true' : 'false'} className={className} data-founder-motion='15'>
      {selected && <motion.span layoutId='founder-row-highlight' aria-hidden className='pointer-events-none absolute inset-0 rounded-[var(--rafii-radius-control)] bg-foreground/[0.045]' />}
      {children}
    </motion.div>
  );
}

export function FounderScrubbableTrend({ trend, selectedIndex, onSelectedIndexChange }: { trend: OverviewTrend | null; selectedIndex?: number; onSelectedIndexChange?: (index: number) => void }) {
  const rows = useMemo(() => founderTrendRows(trend), [trend]);
  const [localIndex, setLocalIndex] = useState(0);
  const rawIndex = selectedIndex ?? localIndex;
  const index = reconcileTrendIndex(rows.length, rawIndex);
  const row = rows[index] ?? null;
  useEffect(() => {
    if (rawIndex !== index) {
      if (selectedIndex !== undefined) onSelectedIndexChange?.(index);
      else setLocalIndex(index);
    }
  }, [index, onSelectedIndexChange, rawIndex, selectedIndex]);
  if (!trend || rows.length === 0) return null;
  const series = trend.series ?? [];
  const setIndex = (next: number) => {
    const clamped = reconcileTrendIndex(rows.length, next);
    if (selectedIndex !== undefined) onSelectedIndexChange?.(clamped);
    else setLocalIndex(clamped);
  };
  return (
    <div className='rafii-quiet mt-3 flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3' data-founder-motion='17'>
      <input aria-label={`Scrub ${trend.title}`} type='range' min={0} max={Math.max(0, rows.length - 1)} value={index} onChange={(event) => setIndex(Number(event.target.value))} className='w-full accent-foreground' />
      <div className='flex flex-wrap items-center gap-x-4 gap-y-1 text-xs' aria-live='polite'>
        <span className='text-muted-foreground'>{formatTick(String(row?.t ?? ''))}</span>
        {series.map((item, itemIndex) => {
          const value = row?.[item.id];
          return (
            <span key={item.id} className='inline-flex items-center gap-1.5'>
              <span aria-hidden className='size-2 rounded-full' style={{ background: LINE_COLORS[itemIndex % LINE_COLORS.length] }} />
              {item.label}: <span className='font-mono'>{typeof value === 'number' ? formatMetricValue(value, item.unit ?? trend.unit ?? 'count', item.currency ?? trend.currency) : 'Unknown'}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function FounderDonutBreakdown({ items, label }: { items: { id: string; label: string; value: number | null | undefined }[]; label: string }) {
  const { reduced } = useMotionPreference();
  const { valid, rejected, total } = normalizeDonutItems(items);
  const shown = valid.toSorted((a, b) => a.id.localeCompare(b.id));
  const color = (id: string) => LINE_COLORS[Array.from(id).reduce((n, c) => n + c.charCodeAt(0), 0) % LINE_COLORS.length];
  let offset = 0;
  return (
    <div className='rafii-quiet flex flex-wrap items-center gap-3 rounded-[var(--rafii-radius-control)] p-3' data-founder-motion='18'>
      {total > 0 ? <svg viewBox='0 0 44 44' className='size-16 shrink-0 -rotate-90' role='img' aria-label={`${label}; ${rejected.length ? 'measured subtotal' : 'total'} ${total}`}>
        <circle cx='22' cy='22' r='16' fill='none' stroke='var(--muted)' strokeWidth='8' />
        {shown.map(item => {
          const length = item.value / total * 100;
          const position = -offset;
          offset += length;
          return <motion.circle key={item.id} cx='22' cy='22' r='16' fill='none' stroke={color(item.id)} strokeWidth='8' pathLength={100} initial={false} animate={{ strokeDasharray: `${length} ${100 - length}`, strokeDashoffset: position }} transition={{ duration: reduced ? 0 : 0.28 }} />;
        })}
      </svg> : <span className='text-muted-foreground text-xs'>{rejected.length ? 'No valid categorical total available.' : 'Measured total: 0'}</span>}
      <ul className='flex min-w-0 flex-1 flex-col gap-1 text-xs'>
        {shown.map(item => <li key={item.id} className='flex items-center gap-2'><span aria-hidden className='size-2 rounded-full' style={{ background: color(item.id) }} /><span className='truncate'>{item.label}</span><span className='ml-auto font-mono tabular-nums'>{item.value}</span></li>)}
        {rejected.length > 0 && <li className='text-muted-foreground'>Unsupported values, not drawn: {rejected.map(item => item.label).join(', ')}. The chart shows only measured categories.</li>}
      </ul>
    </div>
  );
}

export function FounderThinkingOrb({ text = 'Rafii is checking the records' }: { text?: string }) {
  const { ref, enabled } = useVisibleFounderMotion<HTMLSpanElement>();
  return (
    <span ref={ref} className='inline-flex items-center gap-2 text-xs text-muted-foreground' role='status' data-founder-motion='23'>
      <motion.span aria-hidden className='size-3 rounded-full bg-foreground' animate={enabled ? { scale: [1, 1.45, 1], opacity: [0.35, 0.8, 0.35] } : { scale: 1, opacity: 0.6 }} transition={enabled ? { duration: 1.1, repeat: Infinity } : { duration: 0 }} />
      {text}
    </span>
  );
}

export function FounderToolChips({ response }: { response: FounderAgentTurnResponse }) {
  const activity = response.result?.toolActivity ?? [];
  if (activity.length === 0) return null;
  return (
    <details className='text-muted-foreground text-xs' data-founder-motion='24'>
      <summary className='rafii-focus cursor-pointer rounded'>Tool receipts ({activity.length})</summary>
      <div className='mt-2 flex flex-wrap gap-1.5'>
        {activity.map((row, index) => (
          <span key={`${row.tool}-${index}`} className='rafii-quiet inline-flex min-h-7 items-center gap-1 rounded-full px-2' title={`${row.tool}: ${row.effect || row.status}`}>
            {row.status === 'ok' || row.status === 'verified' || row.status === 'done' ? <Icons.check className='size-3' /> : <Icons.warning className='size-3' />}
            <span>{row.label || row.tool}</span>
            <span className='text-muted-foreground'>· {row.status}</span>
            {row.code && <span className='text-muted-foreground'>({row.code})</span>}
          </span>
        ))}
      </div>
    </details>
  );
}

export function FounderLiveTaskRows({ item }: { item: FounderThreadItem }) {
  const label = item.error ? 'Request failed' : item.response ? `Observed server status: ${item.response.status}` : item.runId ? 'Server run accepted; waiting for an update' : 'Preparing request';
  return <motion.ol layout className='flex flex-col gap-1.5 text-xs' data-founder-motion='25'><li className='flex items-center gap-2'><span aria-hidden className={cn('size-2 rounded-full', item.error ? 'bg-destructive' : item.pending ? 'bg-foreground' : 'bg-foreground/50')} /><span>{label}</span></li></motion.ol>;
}

export function FounderApprovalCard({ title = 'Approval required', description, children }: { title?: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className='rafii-glass flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-3' aria-label={title} data-founder-motion='26'>
      <div>
        <h4 className='text-sm font-medium'>{title}</h4>
        {description && <p className='text-muted-foreground mt-1 text-xs'>{description}</p>}
      </div>
      {children}
    </section>
  );
}

export function FounderDiffTable({ before, after, comparison = 'snapshot' }: { before?: Record<string, unknown> | null; after?: Record<string, unknown> | null; comparison?: 'snapshot' | 'reported-fields' }) {
  const rows = buildDiffRows(before, after);
  if (rows.length === 0) return null;
  return (
    <div className='overflow-hidden rounded-[var(--rafii-radius-control)] border border-border/40' data-founder-motion='28'>
      <table className='w-full text-left text-xs'>
        <caption className='sr-only'>{comparison === 'snapshot' ? 'Before and after proposal' : 'Reported current and effect fields. An absent field is not a deletion.'}</caption>
        <thead className='bg-foreground/[0.04]'>
          <tr><th className='px-3 py-2'>Field</th><th className='px-3 py-2'>{comparison === 'snapshot' ? 'Before' : 'Current reported'}</th><th className='px-3 py-2'>{comparison === 'snapshot' ? 'After' : 'Proposed effect'}</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className='border-t border-border/40'>
              <td className='px-3 py-2 font-medium'>{row.key}<span className='sr-only'> {comparison === 'snapshot' || ['changed', 'unchanged'].includes(row.status) ? row.status : 'reported in one section'}</span></td>
              <td className='px-3 py-2 text-muted-foreground break-all'>{comparison === 'reported-fields' && row.before === 'Absent' ? 'Not supplied in this section' : row.before}</td>
              <td className='px-3 py-2 break-all'>{comparison === 'reported-fields' && row.after === 'Absent' ? 'Not supplied in this section' : row.after}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FounderAiEditor({ value, onChange, onRequestRevision, busy }: { value: string; onChange: (value: string) => void; onRequestRevision?: (prompt: string) => Promise<FounderAgentTurnResponse | null>; busy?: boolean }) {
  const [suggestion, setSuggestion] = useState<DraftSuggestion | null>(null);
  const [applied, setApplied] = useState<AppliedDraftSuggestion | null>(null);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState('');
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  async function requestRevision() {
    if (!onRequestRevision || pending || busy) return;
    const revision = createDraftRevision(value);
    const prompt = createAgentRevisionPrompt(value);
    if (prompt.length > 4000) { setFailure('This draft is too long for one revision request. Your text has not been changed.'); return; }
    const request = ++generation.current;
    setPending(true);
    setFailure('');
    setSuggestion(null);
    try {
      const response = await onRequestRevision(prompt);
      if (request !== generation.current) return;
      const answer = response?.result?.answerText;
      if (!response || !['completed', 'done'].includes(response.status) || typeof answer !== 'string' || !answer.trim()) {
        setFailure('Rafii did not return a completed revision. Your draft is unchanged; the conversation contains the request status.');
        return;
      }
      setSuggestion({ revision, text: answer, source: 'agent' });
    } catch {
      if (request === generation.current) setFailure('The revision request failed. Your original draft is unchanged.');
    } finally {
      if (request === generation.current) setPending(false);
    }
  }
  function apply() {
    if (!suggestion) return;
    const next = applyDraftSuggestion(value, suggestion);
    if (!next) return;
    setApplied(next);
    onChange(next.text);
    setSuggestion(null);
  }
  function undo() {
    const previous = undoDraftSuggestion(value, applied);
    if (previous === null) return;
    onChange(previous);
    setApplied(null);
  }
  if (!value.trim() && !suggestion && !pending && !applied) return null;
  const stale = suggestion !== null && applyDraftSuggestion(value, suggestion) === null;
  return (
    <div className='rafii-quiet mb-2 flex max-h-[45dvh] min-h-0 flex-col gap-2 overflow-y-auto rounded-[var(--rafii-radius-control)] p-2 text-xs' data-founder-motion='29'>
      <div className='flex flex-wrap items-center gap-2'>
        <Button type='button' variant='quiet' size='xs' disabled={pending || !value.trim()} onClick={() => { setFailure(''); setSuggestion(makeLocalDraftSuggestion(value)); }}>
          <Icons.edit className='size-3' /> Local tighten
        </Button>
        {onRequestRevision && <Button type='button' variant='quiet' size='xs' disabled={busy || pending || !value.trim()} onClick={() => void requestRevision()}><Icons.sparkles className='size-3' /> Ask Rafii to revise</Button>}
        {applied !== null && <Button type='button' variant='quiet' size='xs' disabled={undoDraftSuggestion(value, applied) === null} onClick={undo}>Undo</Button>}
      </div>
      {pending && <FounderThinkingOrb text='Waiting for the requested draft revision' />}
      {failure && <p role='alert' className='text-destructive'>{failure}</p>}
      {suggestion !== null && (
        <FounderApprovalCard title={suggestion.source === 'agent' ? 'Review Rafii revision' : 'Review local cleanup'} description={suggestion.source === 'agent' ? 'This is the actual returned answer. Review its wording and caveats before applying. Sources and run details remain in the conversation.' : 'Deterministic whitespace cleanup, not AI inference.'}>
          <FounderDiffTable before={{ draft: suggestion.revision.text }} after={{ draft: suggestion.text }} />
          <p className='max-h-44 overflow-y-auto text-sm whitespace-pre-wrap break-words'>{suggestion.text}</p>
          {stale && <p role='status'>Your draft changed after this suggestion was requested. Request a new revision rather than overwriting those edits.</p>}
          <div className='flex gap-2'>
            <Button type='button' variant='quiet' size='sm' onClick={() => setSuggestion(null)}>Cancel</Button>
            <Button type='button' variant='action' size='sm' disabled={stale} onClick={apply}>Apply</Button>
          </div>
        </FounderApprovalCard>
      )}
    </div>
  );
}

export function FounderProcessRail({ steps, className }: { steps: { id: string; label: string; state: 'current' | 'complete' | 'blocked' | 'error' | 'pending' }[]; className?: string }) {
  const id = useId();
  const { reduced } = useMotionPreference();
  return <LayoutGroup id={`process-${id}`}><ol className={cn('relative grid gap-2 text-xs', className)} style={{ gridTemplateColumns: `repeat(${Math.max(1, steps.length)}, minmax(0, 1fr))` }} data-founder-motion='30'>
    {steps.map((step, index) => <li key={step.id} className='relative flex min-w-0 flex-col items-center gap-2 text-center' aria-current={step.state === 'current' ? 'step' : undefined}>
      {index < steps.length - 1 && <span aria-hidden className='absolute top-1.5 left-1/2 h-px w-[calc(100%+0.5rem)] bg-border' />}
      <span className='relative z-1 flex size-3 rounded-full bg-background'>
        <span aria-hidden className={cn('absolute inset-0 rounded-full border-2', step.state === 'complete' ? 'border-foreground bg-foreground' : step.state === 'blocked' || step.state === 'error' ? 'border-destructive' : 'border-foreground/30')} />
        {step.state === 'current' && <motion.span layoutId='active-bead' aria-hidden className='absolute -inset-0.5 rounded-full border-2 border-foreground bg-background' transition={reduced ? { duration: 0 } : TRANSITION} />}
      </span>
      <span className='break-words'>{step.label}</span><span className='sr-only'>{step.state}</span>
    </li>)}
  </ol></LayoutGroup>;
}

export function FounderSaveButton({ state, disabled, title, children }: { state: 'idle' | 'saving' | 'saved' | 'error'; disabled?: boolean; title?: string; children?: ReactNode }) {
  const label = state === 'saving' ? 'Saving' : state === 'saved' ? 'Saved' : state === 'error' ? 'Retry save' : children ?? 'Save';
  return (
    <Button type='submit' variant='action' size='control' disabled={disabled || state === 'saving'} title={title} aria-live='polite' data-founder-motion='09'>
      {state === 'saving' ? <Icons.spinner className='animate-spin motion-reduce:animate-none' /> : state === 'saved' ? <Icons.check /> : <Icons.check />}
      <AnimatePresence mode='wait' initial={false}>
        <motion.span key={String(label)} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.16 }}>
          {label}
        </motion.span>
      </AnimatePresence>
    </Button>
  );
}

export function FounderAnswerReveal({ children }: { children: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22 }} data-founder-motion='27'>
      {children}
    </motion.div>
  );
}

export function FounderInsightMotion({ children }: { children: ReactNode }) {
  return (
    <motion.div layout initial={{ opacity: 0.86 }} animate={{ opacity: 1 }} transition={TRANSITION} data-founder-motion='19'>
      {children}
    </motion.div>
  );
}

export function FounderFilterChips({ children, chips }: { children?: ReactNode; chips?: { id: string; label: string; onRemove: () => void }[] }) {
  return (
    <motion.div layout className='flex min-w-0 flex-wrap items-center gap-1.5' aria-live='polite' data-founder-motion='20'>
      {chips ? <AnimatePresence initial={false} mode='popLayout'>
        {chips.map(chip => <motion.button key={chip.id} type='button' layout initial={{ opacity: 0, scale: 0.92, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.92, y: -4 }} transition={{ duration: 0.16 }} onClick={chip.onRemove} aria-label={`Clear ${chip.label} filter`} className='rafii-glass rafii-focus inline-flex min-h-8 items-center gap-1 rounded-full px-2.5 text-xs'><span>{chip.label}</span><Icons.close aria-hidden className='size-3' /></motion.button>)}
      </AnimatePresence> : children}
    </motion.div>
  );
}

export function FounderTooltipMotion({ children, label, side = 'top' }: { children: ReactNode; label?: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  const { reduced } = useMotionPreference();
  if (!label) return <span data-founder-motion='21'>{children}</span>;
  const trigger = isValidElement(children) ? children as ReactElement<Record<string, unknown>> : <button type='button' className='rafii-focus'>{children}</button>;
  return (
    <Tooltip>
      <TooltipTrigger render={trigger} data-founder-motion='21' />
      <TooltipContent side={side} sideOffset={8} className='max-w-[min(18rem,calc(100vw-1rem))] whitespace-normal rounded-xl bg-popover text-popover-foreground text-center' render={<TooltipSurface layoutId='founder-tooltip-surface' side={side} initial={false} transition={reduced ? { duration: 0 } : TRANSITION} />}>
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

export function FounderMotionUnavailable({ title, description }: { title: string; description: string }) {
  return <StateMessage kind='unsupported' layout='inline' title={title} description={description} />;
}