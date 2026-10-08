'use client';
/**
 * Shared pieces of the journey components (lane E): the data-state frame every bound component renders through, the
 * source line (as-of, coverage, warnings), status pills, the selection toggle and the guarded action button.
 *
 * Facts on screen come from the bound query result only. Generated text never reaches these pieces except through the
 * separate `Commentary` component, which is labelled as Rafii's note.
 */
import type { ReactNode } from 'react';
import { StateMessage } from '@/components/rafii/state-message';
import { LoadingRows } from '../primitives/shared';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { JsonValue, UiQueryResultV1 } from '@/lib/agent-runtime/ui-contracts';
import { formatAsOf, formatCount } from '../../journeys/format';
import { useBindingStatus, useJourneyAction, useJourneyEnvironment, useStreaming } from '../../journeys/runtime';
import { readQuery, type BindingName, type ViewData } from '../../journeys/views';

export type Tone = 'neutral' | 'good' | 'waiting' | 'attention' | 'muted';

const TONE: Record<Tone, string> = {
  neutral: 'border-border text-foreground',
  good: 'border-emerald-500/30 text-emerald-700 dark:text-emerald-300',
  waiting: 'border-amber-500/30 text-amber-700 dark:text-amber-300',
  attention: 'border-destructive/40 text-destructive',
  muted: 'border-border text-muted-foreground',
};

export function Pill({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cn('inline-flex h-5 shrink-0 items-center rounded-full border px-2 text-xs font-medium whitespace-nowrap', TONE[tone])}>{children}</span>;
}

/** Printed in place of a value the records don't have. Never a zero. */
export function Missing({ word }: { word?: 'unknown' | 'unavailable' | 'notMeasured' | 'none' | 'noDate' }) {
  const { copy } = useJourneyEnvironment();
  return <span className='text-muted-foreground italic'>{copy.common[word ?? 'unknown']}</span>;
}

/** A count that may be unknown. */
export function CountValue({ value }: { value: number | null | undefined }) {
  const { locale } = useJourneyEnvironment();
  const text = formatCount(value, locale);
  return text === null ? <Missing /> : <span className='tabular-nums'>{text}</span>;
}

export function JourneySection({ title, label, children, className }: { title?: string | null; label: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title || label} className={cn('flex min-w-0 flex-col gap-3', className)}>
      {title ? <h3 className='text-foreground text-sm font-semibold text-balance'>{title}</h3> : null}
      {children}
    </section>
  );
}

/** As-of time, coverage and warnings of one query result: where the facts above came from. */
export function SourceLine({ result }: { result: UiQueryResultV1 }) {
  const { copy, locale, timeZone } = useJourneyEnvironment();
  const asOf = formatAsOf(result.asOf, timeZone, locale);
  const known = result.coverage.known;
  const total = result.coverage.total;
  const showCoverage = known !== null && total !== null && known !== total;
  return (
    <div className='text-muted-foreground flex flex-col gap-1 text-xs'>
      <p>
        {asOf ? (
          <>
            {copy.common.asOf} {asOf}
          </>
        ) : null}
        {showCoverage ? <span>{asOf ? ' · ' : ''}{copy.common.shownOf(known, total)}</span> : null}
      </p>
      {result.coverage.note ? <p>{result.coverage.note}</p> : null}
      {result.warnings.length > 0 ? (
        <ul className='flex flex-col gap-0.5'>
          {result.warnings.slice(0, 5).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

interface QueryFrameProps<B extends BindingName> {
  value: unknown;
  binding: B;
  /** Label for the region and its loading announcement. */
  label: string;
  title?: string | null;
  /** Rendered for available / partial / stale data. */
  children: (data: ViewData<B>, result: UiQueryResultV1) => ReactNode;
  /** Optional custom empty state (still labelled empty, never as success). */
  empty?: (result: UiQueryResultV1) => ReactNode;
  className?: string;
}

/**
 * Every bound journey component renders through this frame: loading, empty, denied, unavailable and unreadable data
 * each get their own native state; partial and stale data are labelled above the content; the source line follows.
 */
export function QueryFrame<B extends BindingName>({ value, binding, label, title, children, empty, className }: QueryFrameProps<B>) {
  const { copy } = useJourneyEnvironment();
  const status = useBindingStatus(binding);
  const read = readQuery(value, binding);
  let body: ReactNode;
  if (read.kind === 'loading') {
    // Loading rows are announced once by the message-level status (lane C), not by every component.
    if (status === 'denied') body = <StateMessage kind='permission' title={copy.states.denied} description={copy.states.deniedHint} layout='inline' />;
    else if (status === 'unavailable') body = <StateMessage kind='unsupported' title={copy.states.unavailable} layout='inline' />;
    else body = <LoadingRows label={copy.states.loading} />;
  } else if (read.kind === 'invalid') {
    body = <StateMessage kind='error' title={copy.states.invalid} description={copy.states.invalidHint} layout='inline' />;
  } else if (read.kind === 'denied') {
    body = <StateMessage kind='permission' title={copy.states.denied} description={read.result.warnings[0] ?? copy.states.deniedHint} layout='inline' />;
  } else if (read.kind === 'unavailable') {
    body = <StateMessage kind='unsupported' title={copy.states.unavailable} description={read.result.coverage.note ?? read.result.warnings[0]} layout='inline' />;
  } else if (read.kind === 'empty') {
    body = (
      <>
        {empty ? empty(read.result) : <StateMessage kind='empty' title={copy.states.empty} description={read.result.coverage.note ?? undefined} layout='inline' />}
        <SourceLine result={read.result} />
      </>
    );
  } else {
    body = (
      <>
        {read.state === 'partial' ? <StateMessage kind='partial' title={copy.states.partial} layout='inline' /> : null}
        {read.state === 'stale' ? <StateMessage kind='stale' title={copy.states.stale} layout='inline' /> : null}
        {children(read.data, read.result)}
        <SourceLine result={read.result} />
      </>
    );
  }
  return (
    <JourneySection title={title} label={label} className={className}>
      {body}
    </JourneySection>
  );
}

/** Pick / unpick one record. Selection only changes this view and the follow-up context; it never approves anything. */
export function SelectToggle({ selected, label, onToggle, disabled }: { selected: boolean; label: string; onToggle: () => void; disabled?: boolean }) {
  return (
    <Button
      type='button'
      variant={selected ? 'default' : 'outline'}
      size='icon-xs'
      aria-pressed={selected}
      aria-label={label}
      disabled={disabled}
      onClick={() => onToggle()}
      className='shrink-0'
    >
      {selected ? '✓' : ''}
    </Button>
  );
}

/** Ordered selection helper: toggling appends at the end (selection order is what "the second one" means later). */
export function toggleInOrder(current: readonly string[], value: string, max: number): string[] {
  if (current.includes(value)) return current.filter((v) => v !== value);
  if (current.length >= max) return [...current];
  return [...current, value];
}

/**
 * The one way a journey component starts a write: the server manifest's label, disabled until the view is accepted, a
 * trusted click asks the action bridge, and the native confirmation (outside this view) decides. The outcome shown
 * here is only the bridge's verified/prepared state; it never claims more than the server reported.
 */
export function GuardedAction({
  actionId,
  controlId,
  inputs,
  ready,
  notReadyHint,
  label,
  quiet,
}: {
  actionId: string | undefined;
  controlId: string | undefined;
  inputs: Record<string, JsonValue> | null;
  /** The component's own inputs are complete and valid. */
  ready: boolean;
  notReadyHint?: string;
  /** Rafii's own native copy for this button (e.g. "Remember" / "Dismiss" for one decide action); never model text. */
  label?: string;
  /** Compact row control: no summary line. */
  quiet?: boolean;
}) {
  const { copy } = useJourneyEnvironment();
  const streaming = useStreaming();
  const action = useJourneyAction(actionId, controlId);
  if (!actionId || !action.binding) {
    return <p className='text-muted-foreground text-xs'>{copy.common.actionUnavailable}</p>;
  }
  const phase = action.state?.phase ?? 'idle';
  const busy = phase === 'activating' || phase === 'executing';
  const result = phase === 'done' ? action.state?.result ?? null : null;
  const disabled = !action.enabled || !ready || busy || inputs === null;
  return (
    <div className='flex flex-col gap-1.5'>
      <div className='flex flex-wrap items-center gap-2'>
        <Button
          type='button'
          variant='action'
          size='sm'
          disabled={disabled}
          aria-busy={busy || undefined}
          onClick={(event) => {
            if (inputs) action.request(inputs, event);
          }}
        >
          {busy ? copy.common.working : label ?? action.binding.label}
        </Button>
        {result ? <ActionOutcomeLine outcome={result.outcome} verified={result.verified} /> : null}
      </div>
      {phase === 'confirming' ? <p className='text-muted-foreground text-xs'>{copy.common.confirmInSheet}</p> : null}
      {phase === 'error' && action.state?.error ? (
        <p role='alert' className='text-destructive text-xs'>
          {action.state.error}
        </p>
      ) : null}
      {streaming && !quiet ? <p className='text-muted-foreground text-xs'>{copy.common.waitForView}</p> : null}
      {!ready && notReadyHint ? <p className='text-muted-foreground text-xs'>{notReadyHint}</p> : null}
      {action.binding.summary && !quiet ? <p className='text-muted-foreground text-xs'>{action.binding.summary}</p> : null}
    </div>
  );
}

/** Prepared is never applied; applied is "done" only when the server verified it by re-reading. */
export function ActionOutcomeLine({ outcome, verified }: { outcome: string; verified: boolean }) {
  const { copy } = useJourneyEnvironment();
  if (outcome === 'prepared') {
    return (
      <span role='status' className='text-xs'>
        <Pill tone='waiting'>{copy.common.prepared}</Pill> <span className='text-muted-foreground'>{copy.common.preparedHint}</span>
      </span>
    );
  }
  if (outcome === 'applied') {
    return (
      <span role='status'>
        <Pill tone={verified ? 'good' : 'waiting'}>{verified ? copy.common.applied : copy.common.notVerified}</Pill>
      </span>
    );
  }
  return null;
}

export function CountLabel({ value, word }: { value: number | null | undefined; word: (n: number) => string }) {
  if (typeof value !== 'number') return <Missing />;
  return <>{word(value)}</>;
}
