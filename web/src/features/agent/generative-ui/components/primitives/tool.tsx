'use client';
/**
 * Interactive-tool primitives (J10): NumberField, Slider, Toggle and Readout.
 *
 * Purely local. They read and write this view's `$variables` (OpenUI store) and nothing else: no Query, no network, no
 * model call and no business write. A Readout's `value` is an openui-lang expression over those `$variables`; OpenUI's
 * Renderer re-evaluates every prop expression whenever the store changes (`evaluateElementProps` keyed on the store
 * snapshot), so moving a Slider updates each Readout that uses its `$variable` immediately.
 *
 * Numbers are stored as numbers (never strings: `+` would concatenate text), and only while the typed text is a valid
 * number inside min..max; partial input stays local, like DateRange. A value that cannot be computed (NaN, Infinity, null,
 * an object) shows "—" with an accessible "can't be calculated" label, never "NaN".
 */
import { type JSX, useId, useState } from 'react';
import { z } from 'zod';
import { cn } from '@/lib/utils';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { type GenUiLocale, useGenUiLocale } from '../../core/locale';
import { useStateField } from '../../core/openui';
import { plainText, safeProps } from '../../core/props';
import { Unrenderable } from './shared';

const fieldClass =
  'w-full min-w-0 rounded-[var(--rafii-radius-control,0.75rem)] border border-input bg-background px-3 py-2 text-sm tabular-nums outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive disabled:opacity-60 [.rafii-chat_&]:bg-white/5';

const finite = z.number().refine((n) => Number.isFinite(n));
const labelSchema = z.union([z.string(), z.number()]);
const UNIT_MAX = 16;
const MAX_FRACTION_DIGITS = 2;

/** A finite number, or null. Numeric strings from persisted state are accepted; anything else is null. */
export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string' && value.trim() !== '' && /^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/** Why a number is not accepted (localized), or null when it is within min..max. */
export function numberProblem(value: number | null, min: number | undefined, max: number | undefined, l: GenUiLocale): string | null {
  if (value === null) return l.t('enterNumber');
  if (min !== undefined && max !== undefined && (value < min || value > max)) return l.t('numberBetween', { min: l.formatNumber(min), max: l.formatNumber(max) });
  if (min !== undefined && value < min) return l.t('numberAtLeast', { min: l.formatNumber(min) });
  if (max !== undefined && value > max) return l.t('numberAtMost', { max: l.formatNumber(max) });
  return null;
}

function unitText(unit: unknown): string {
  return typeof unit === 'string' ? plainText(unit.trim(), UNIT_MAX) : '';
}

export type ReadoutFormat = 'number' | 'currency' | 'percent';

/**
 * The text a Readout shows for a computed value, or null when it cannot be computed (shown as "—"). Pure; tests call it.
 * number: up to two decimals plus unit; currency: Intl currency for a valid ISO 4217 code, otherwise two decimals plus
 * unit; percent: a ratio (0.15 → 15%). Text values are shown as written (bounded); booleans as Yes/No.
 */
export function readoutText(
  value: unknown,
  options: { format?: ReadoutFormat; unit?: string; currency?: string },
  l: GenUiLocale,
): string | null {
  const unit = unitText(options.unit);
  const withUnit = (text: string) => (unit ? `${text} ${unit}` : text);
  if (typeof value === 'boolean') return l.t(value ? 'yes' : 'no');
  if (typeof value === 'string') {
    const text = plainText(value.trim(), 200);
    return text ? withUnit(text) : null;
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const format = options.format ?? 'number';
  if (format === 'percent') return l.formatNumber(value, { style: 'percent', maximumFractionDigits: 1 });
  if (format === 'currency') {
    const code = typeof options.currency === 'string' ? options.currency.trim().toUpperCase() : '';
    if (/^[A-Z]{3}$/.test(code)) {
      try {
        // Validate the code first: a malformed code makes Intl throw, which formatNumber would hide with a plain format.
        if (new Intl.NumberFormat('en', { style: 'currency', currency: code }).resolvedOptions().currency) {
          return l.formatNumber(value, { style: 'currency', currency: code });
        }
      } catch {
        // fall through to a plain two-decimal amount
      }
    }
    return withUnit(l.formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  }
  return withUnit(l.formatNumber(value, { maximumFractionDigits: MAX_FRACTION_DIGITS }));
}

/* ------------------------------------------------------------------------------------------------ NumberField */

const numberFieldProps = z.object({
  name: z.string().min(1).max(64),
  label: labelSchema,
  value: z.unknown().optional(),
  min: finite.optional(),
  max: finite.optional(),
  step: finite.optional(),
  unit: z.string().optional(),
});
export const NumberField: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(numberFieldProps, props);
  const l = useGenUiLocale();
  const id = useId();
  const name = p.ok ? p.value.name : `number_${statementId ?? 'x'}`;
  const field = useStateField<number | null>(name, p.ok ? (p.value.value as number | undefined) : undefined);
  // Text the person is typing that is not (yet) a valid number in range; the bound $variable keeps its last valid value.
  const [draft, setDraft] = useState<string | null>(null);
  if (!p.ok || (p.value.min !== undefined && p.value.max !== undefined && p.value.min > p.value.max)) return <Unrenderable component="NumberField" />;
  const { min, max, step } = p.value;
  const stored = toFiniteNumber(field.value);
  const shown = draft ?? (stored === null ? '' : String(stored));
  const problem = draft !== null ? numberProblem(toFiniteNumber(draft), min, max, l) : null;
  const unit = unitText(p.value.unit);
  return (
    <div data-genui="NumberField" data-statement-id={statementId} className="grid min-w-0 gap-1">
      <label htmlFor={id} dir="auto" className="text-xs font-medium text-muted-foreground">
        {plainText(p.value.label, 120)}
      </label>
      <div className="flex min-w-0 items-center gap-2">
        <input
          id={id}
          name={name}
          type="number"
          inputMode="decimal"
          aria-label={plainText(p.value.label, 120) || undefined}
          value={shown}
          min={min}
          max={max}
          step={step ?? 'any'}
          aria-invalid={problem ? true : undefined}
          aria-describedby={[problem ? `${id}-error` : null, unit ? `${id}-unit` : null].filter(Boolean).join(' ') || undefined}
          onChange={(event) => {
            const text = event.target.value;
            const next = toFiniteNumber(text);
            if (next !== null && !numberProblem(next, min, max, l)) {
              field.setValue(next);
              setDraft(null);
            } else {
              setDraft(text);
            }
          }}
          onBlur={() => {
            // An empty field keeps the last valid number visible again instead of a silent zero.
            if (draft !== null && draft.trim() === '') setDraft(null);
          }}
          className={fieldClass}
        />
        {unit ? (
          <span id={`${id}-unit`} dir="auto" className="shrink-0 text-xs text-muted-foreground">
            {unit}
          </span>
        ) : null}
      </div>
      {problem ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {problem}
        </p>
      ) : null}
    </div>
  );
};

/* ------------------------------------------------------------------------------------------------ Slider */

const sliderProps = z.object({
  name: z.string().min(1).max(64),
  label: labelSchema,
  min: finite,
  max: finite,
  value: z.unknown().optional(),
  step: finite.optional(),
  unit: z.string().optional(),
});
export const Slider: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(sliderProps, props);
  const l = useGenUiLocale();
  const id = useId();
  const name = p.ok ? p.value.name : `slider_${statementId ?? 'x'}`;
  const field = useStateField<number | null>(name, p.ok ? (p.value.value as number | undefined) : undefined);
  if (!p.ok || !(p.value.max > p.value.min) || (p.value.step !== undefined && !(p.value.step > 0))) return <Unrenderable component="Slider" />;
  const { min, max } = p.value;
  const step = p.value.step ?? 1;
  const stored = toFiniteNumber(field.value);
  const current = Math.min(max, Math.max(min, stored ?? min));
  const unit = unitText(p.value.unit);
  const display = `${l.formatNumber(current, { maximumFractionDigits: MAX_FRACTION_DIGITS })}${unit ? ` ${unit}` : ''}`;
  return (
    <div data-genui="Slider" data-statement-id={statementId} className="grid min-w-0 gap-1">
      <div className="flex min-w-0 items-baseline justify-between gap-2">
        <label htmlFor={id} dir="auto" className="min-w-0 truncate text-xs font-medium text-muted-foreground">
          {plainText(p.value.label, 120)}
        </label>
        <output htmlFor={id} className="shrink-0 text-sm font-medium tabular-nums text-foreground">
          {display}
        </output>
      </div>
      <input
        id={id}
        name={name}
        type="range"
        aria-label={plainText(p.value.label, 120) || undefined}
        min={min}
        max={max}
        step={step}
        value={current}
        aria-valuetext={display}
        onChange={(event) => {
          const next = toFiniteNumber(event.target.value);
          if (next !== null) field.setValue(Math.min(max, Math.max(min, next)));
        }}
        className="h-6 w-full min-w-0 cursor-pointer accent-primary focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      />
      <div aria-hidden="true" className="flex justify-between text-[11px] text-muted-foreground tabular-nums">
        <span>{l.formatNumber(min, { maximumFractionDigits: MAX_FRACTION_DIGITS })}</span>
        <span>{l.formatNumber(max, { maximumFractionDigits: MAX_FRACTION_DIGITS })}</span>
      </div>
    </div>
  );
};

/* ------------------------------------------------------------------------------------------------ Toggle */

const toggleProps = z.object({ name: z.string().min(1).max(64), label: labelSchema, value: z.unknown().optional() });
export const Toggle: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(toggleProps, props);
  const id = useId();
  const name = p.ok ? p.value.name : `toggle_${statementId ?? 'x'}`;
  const field = useStateField<boolean | null>(name, p.ok ? (p.value.value as boolean | undefined) : undefined);
  if (!p.ok) return <Unrenderable component="Toggle" />;
  const on = field.value === true;
  return (
    <div data-genui="Toggle" data-statement-id={statementId} className="flex min-w-0 items-center justify-between gap-3">
      <span id={`${id}-label`} dir="auto" className="min-w-0 text-sm text-foreground">
        {plainText(p.value.label, 120)}
      </span>
      <button
        type="button"
        role="switch"
        name={name}
        aria-checked={on}
        aria-label={plainText(p.value.label, 120) || undefined}
        onClick={() => field.setValue(!on)}
        className={cn(
          'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-transparent transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50',
          on ? 'bg-primary' : 'bg-input',
        )}
      >
        <span
          aria-hidden="true"
          className={cn('inline-block size-5 rounded-full bg-background shadow-sm transition-transform', on ? 'translate-x-5' : 'translate-x-0.5')}
        />
      </button>
    </div>
  );
};

/* ------------------------------------------------------------------------------------------------ Readout */

const readoutProps = z.object({
  label: labelSchema,
  value: z.unknown().optional(),
  format: z.enum(['number', 'currency', 'percent']).optional(),
  unit: z.string().optional(),
  currency: z.string().optional(),
});
export const Readout: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(readoutProps, props);
  const l = useGenUiLocale();
  if (!p.ok) return <Unrenderable component="Readout" />;
  const text = readoutText(p.value.value, { format: p.value.format, unit: p.value.unit, currency: p.value.currency }, l);
  return <ReadoutView label={plainText(p.value.label, 120)} text={text} statementId={statementId} unavailable={l.t('notComputable')} />;
};

/** The Readout surface (exported for tests): a polite live region, so assistive tech hears the new result as inputs move. */
export function ReadoutView(props: { label: string; text: string | null; statementId?: string; unavailable: string }): JSX.Element {
  return (
    <div
      data-genui="Readout"
      data-statement-id={props.statementId}
      className="grid min-w-0 gap-0.5 rounded-[var(--rafii-radius-card,0.875rem)] border border-border bg-card px-3 py-2.5"
    >
      <p dir="auto" className="text-xs text-muted-foreground">
        {props.label}
      </p>
      <output aria-live="polite" aria-atomic="true" className="block min-w-0 text-xl font-semibold break-words tabular-nums text-foreground">
        {props.text === null ? (
          <>
            <span aria-hidden="true">—</span>
            <span className="sr-only">{props.unavailable}</span>
          </>
        ) : (
          props.text
        )}
      </output>
    </div>
  );
}
