'use client';
/**
 * Native confirmation and receipt for generated actions (D-A12, D-A29; spec §2.2, §6.3). Rendered by
 * RafiiGenerativeMessage OUTSIDE the generated subtree, inside the bridges provider.
 *
 *   confirming  a modal sheet with the server's own copy (title, change summary, target, time zone, cost) and
 *               Confirm / Cancel. Nothing executes until the person confirms.
 *   executing   the sheet shows that it is working (Cancel is not offered once the server may be applying it).
 *   done        an inline receipt below the view, worded from the server's outcome: "prepared" is never shown as
 *               applied, and "applied" reads as done only when the server verified it.
 *   error       the bridge's sanitized message with Try again (same key and activation) and Close.
 *
 * The sheet element carries `data-rafii-genui-confirmation` so the site-agent panel's Escape handler leaves it alone
 * (Escape closes this sheet, not the whole panel). After it closes, focus returns to the control that opened it.
 */
import { type JSX, type RefObject, useEffect, useRef } from 'react';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import type { UiActionResultV1 } from '@/lib/agent-runtime/ui-contracts';
import { useRafiiActionBridge, useRafiiActionState } from '../bridges/context';
import { type GenUiLocale, type GenUiMessageKey, useGenUiLocale } from './locale';

export const CONFIRMATION_ATTRIBUTE = 'data-rafii-genui-confirmation';

/** The person-facing outcome of a server result (never upgraded: prepared ≠ applied, applied needs `verified`). */
export function outcomeKey(result: Pick<UiActionResultV1, 'outcome' | 'verified'>): GenUiMessageKey {
  switch (result.outcome) {
    case 'prepared':
      return 'outcomePrepared';
    case 'applied':
      return result.verified ? 'outcomeApplied' : 'outcomeAppliedUnverified';
    case 'pending':
      return 'outcomePending';
    case 'conflict':
      return 'outcomeConflict';
    case 'rejected':
      return 'outcomeRejected';
    default:
      return 'outcomeFailed';
  }
}

function Receipt(props: { l: GenUiLocale; text: string; tone: 'ok' | 'info' | 'error'; onClose(): void; onRetry?: () => void }): JSX.Element {
  return (
    <div
      role={props.tone === 'error' ? 'alert' : 'status'}
      data-genui-action-receipt={props.tone}
      className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--rafii-radius-card,0.875rem)] border border-border bg-muted/40 px-3 py-2 text-sm"
    >
      <span>{props.text}</span>
      <span className="flex gap-2">
        {props.onRetry ? (
          <Button type="button" size="sm" variant="outline" onClick={props.onRetry}>
            {props.l.t('tryAgain')}
          </Button>
        ) : null}
        <Button type="button" size="sm" variant="quiet" onClick={props.onClose}>
          {props.l.t('close')}
        </Button>
      </span>
    </div>
  );
}

export function ActionConfirmation(props: { frame: RefObject<HTMLElement | null> }): JSX.Element | null {
  const bridge = useRafiiActionBridge();
  const state = useRafiiActionState();
  const l = useGenUiLocale();
  const lastControl = useRef<string | null>(null);
  if (state.request?.controlId) lastControl.current = state.request.controlId;

  const returnFocus = () => {
    const id = lastControl.current;
    const frame = props.frame.current;
    if (!id || !frame) return;
    const control = Array.from(frame.querySelectorAll<HTMLElement>('[data-genui-control]')).find((el) => el.dataset.genuiControl === id);
    control?.focus();
  };
  const phase = state.phase;
  const previous = useRef(phase);
  useEffect(() => {
    if ((previous.current === 'confirming' || previous.current === 'executing') && (phase === 'idle' || phase === 'done' || phase === 'error')) {
      returnFocus();
    }
    previous.current = phase;
  });

  if (!bridge) return null;
  const activation = state.activation;
  const binding = state.request ? bridge.binding(state.request.actionId) : undefined;
  const open = phase === 'confirming' || (phase === 'executing' && !!activation?.confirmation.required);
  const confirmation = activation?.confirmation;

  return (
    <>
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          if (!next && phase === 'confirming') bridge.cancel();
        }}
      >
        <AlertDialogContent data-rafii-genui-confirmation="" className="max-w-sm">
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmation?.title || binding?.label || l.t('confirm')}</AlertDialogTitle>
            {confirmation?.summary?.length ? (
              <AlertDialogDescription render={<div />}>
                <ul className="grid list-disc gap-1 pl-4 text-left">
                  {confirmation.summary.map((line, index) => (
                    <li key={index} dir="auto">
                      {line}
                    </li>
                  ))}
                </ul>
              </AlertDialogDescription>
            ) : binding?.summary ? (
              <AlertDialogDescription dir="auto">{binding.summary}</AlertDialogDescription>
            ) : null}
          </AlertDialogHeader>
          {confirmation?.target || confirmation?.timeZone || confirmation?.cost ? (
            <div className="grid gap-1 text-xs text-muted-foreground">
              {confirmation.target ? <p dir="auto">{confirmation.target}</p> : null}
              {confirmation.timeZone ? <p>{l.t('timeZoneNote', { zone: confirmation.timeZone })}</p> : null}
              {confirmation.cost ? <p>{l.t('costNote', { cost: confirmation.cost })}</p> : null}
            </div>
          ) : null}
          <AlertDialogFooter>
            {phase === 'confirming' ? <AlertDialogCancel>{l.t('cancel')}</AlertDialogCancel> : null}
            <Button
              type="button"
              disabled={phase !== 'confirming'}
              aria-busy={phase === 'executing' || undefined}
              onClick={() => {
                void bridge.confirm();
              }}
            >
              {phase === 'executing' ? l.t('working') : binding?.label || l.t('confirm')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {phase === 'done' && state.result ? (
        <Receipt
          l={l}
          text={l.t(outcomeKey(state.result))}
          tone={state.result.outcome === 'applied' && state.result.verified ? 'ok' : state.result.outcome === 'prepared' || state.result.outcome === 'pending' ? 'info' : 'error'}
          onClose={() => bridge.cancel()}
        />
      ) : null}
      {phase === 'error' ? (
        <Receipt
          l={l}
          text={state.error || l.t('outcomeFailed')}
          tone="error"
          onClose={() => bridge.cancel()}
          onRetry={state.activation ? () => void bridge.confirm() : undefined}
        />
      ) : null}
    </>
  );
}
