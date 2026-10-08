'use client';
/**
 * Inputs and local controls: Form, TextField, Select, DateRange, Button.
 *
 * Inputs only change the view (OpenUI store: `$variables`, or fields under the Form name). They stay usable while a view
 * streams or updates, keep their value and focus across stream chunks and patches (stable keys, controlled values from
 * the store), and validate locally for the person's benefit only; the server re-validates every action input.
 * `Button` runs a sanitized local plan (@Set/@Reset/@Run(query)/@ToAssistant/@OpenUrl) and never changes saved data.
 */
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import { z } from 'zod';
import { Button as UiButton } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { sanitizePlan } from '../../core/actions';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { type GenUiLocale, useGenUiLocale } from '../../core/locale';
import { FormNameContext, useFormName, useGetFieldValue, useIsStreaming, useStateField, useTriggerAction } from '../../core/openui';
import { plainText, safeProps } from '../../core/props';
import { Children, Unrenderable } from './shared';

/* ------------------------------------------------------------------------------------------------ Form context */

type Validator = () => boolean;

export interface RafiiFormContextValue {
  name: string;
  register(field: string, validate: Validator): () => void;
  /** Validate every registered field; true when all pass. */
  validateAll(): boolean;
  /** Names of registered fields (the values come from OpenUI's store under the Form name). */
  fields(): string[];
}

const RafiiFormContext = createContext<RafiiFormContextValue | null>(null);

export function useRafiiForm(): RafiiFormContextValue | null {
  return useContext(RafiiFormContext);
}

const FORM_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const formProps = z.object({ name: z.string().regex(FORM_NAME), children: z.array(z.unknown()) });
export const Form: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(formProps, props);
  const validators = useRef(new Map<string, Validator>());
  const name = p.ok ? p.value.name : '';
  const value = useMemo<RafiiFormContextValue>(
    () => ({
      name,
      register(field, validate) {
        validators.current.set(field, validate);
        return () => {
          if (validators.current.get(field) === validate) validators.current.delete(field);
        };
      },
      validateAll() {
        let ok = true;
        for (const validate of validators.current.values()) if (!validate()) ok = false;
        return ok;
      },
      fields: () => [...validators.current.keys()],
    }),
    [name],
  );
  if (!p.ok) return <Unrenderable component="Form" />;
  return (
    <FormNameContext.Provider value={name}>
      <RafiiFormContext.Provider value={value}>
        <form
          data-genui="Form"
          data-statement-id={statementId}
          noValidate
          onSubmit={(event) => event.preventDefault()}
          className="grid min-w-0 gap-3"
        >
          <Children value={p.value.children} renderNode={renderNode} />
        </form>
      </RafiiFormContext.Provider>
    </FormNameContext.Provider>
  );
};

/* ------------------------------------------------------------------------------------------------ fields */

interface Rules {
  required?: boolean;
  minLength?: number;
  maxLength?: number;
}

function ruleError(value: unknown, rules: Rules | undefined, l: GenUiLocale): string | null {
  if (!rules) return null;
  const text = typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value);
  if (rules.required && !text.trim()) return l.t('required');
  if (typeof rules.minLength === 'number' && text && text.length < rules.minLength) return l.t('tooShort');
  if (typeof rules.maxLength === 'number' && text.length > rules.maxLength) return l.t('tooLong');
  return null;
}

/** Register a field's validator with the enclosing Form (no-op outside a Form). */
function useFieldValidation(name: string, check: () => string | null): [string | null, () => boolean] {
  const form = useRafiiForm();
  const [error, setError] = useState<string | null>(null);
  const checkRef = useRef(check);
  checkRef.current = check;
  const validate = useCallback(() => {
    const message = checkRef.current();
    setError(message);
    return message === null;
  }, []);
  useEffect(() => (form ? form.register(name, validate) : undefined), [form, name, validate]);
  return [error, validate];
}

const fieldClass =
  'w-full min-w-0 rounded-[var(--rafii-radius-control,0.75rem)] border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive disabled:opacity-60 [.rafii-chat_&]:bg-white/5';

const textFieldProps = z.object({
  name: z.string().min(1).max(64),
  label: z.union([z.string(), z.number()]),
  value: z.unknown().optional(),
  placeholder: z.union([z.string(), z.number()]).optional(),
  multiline: z.boolean().optional(),
  rules: z.object({ required: z.boolean().optional(), minLength: z.number().optional(), maxLength: z.number().optional() }).optional(),
});
export const TextField: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(textFieldProps, props);
  const l = useGenUiLocale();
  const id = useId();
  const name = p.ok ? p.value.name : `field_${statementId ?? 'x'}`;
  const field = useStateField<string>(name, p.ok ? (p.value.value as string | undefined) : undefined);
  const rules = p.ok ? p.value.rules : undefined;
  const [error, validate] = useFieldValidation(name, () => ruleError(field.value, rules, l));
  if (!p.ok) return <Unrenderable component="TextField" />;
  const value = typeof field.value === 'string' ? field.value : field.value === null || field.value === undefined ? '' : String(field.value);
  const common = {
    id,
    name,
    value,
    placeholder: p.value.placeholder !== undefined ? plainText(p.value.placeholder, 200) : undefined,
    maxLength: rules?.maxLength,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': error ? `${id}-error` : undefined,
    'aria-required': rules?.required ? true : undefined,
    dir: 'auto' as const,
    onChange: (event: { target: { value: string } }) => field.setValue(event.target.value),
    onBlur: () => {
      if (error || value) validate();
    },
    className: fieldClass,
  };
  return (
    <div data-genui="TextField" data-statement-id={statementId} className="grid min-w-0 gap-1">
      <label htmlFor={id} dir="auto" className="text-xs font-medium text-muted-foreground">
        {plainText(p.value.label, 120)}
        {rules?.required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {p.value.multiline ? <textarea {...common} rows={4} className={cn(fieldClass, 'resize-y')} /> : <input type="text" {...common} />}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
};

const optionSchema = z.object({ value: z.union([z.string(), z.number()]), label: z.union([z.string(), z.number()]) });
const selectProps = z.object({
  name: z.string().min(1).max(64),
  label: z.union([z.string(), z.number()]),
  options: z.array(optionSchema).max(200),
  value: z.unknown().optional(),
  placeholder: z.union([z.string(), z.number()]).optional(),
});
export const Select: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(selectProps, props);
  const id = useId();
  const name = p.ok ? p.value.name : `select_${statementId ?? 'x'}`;
  const field = useStateField<string>(name, p.ok ? (p.value.value as string | undefined) : undefined);
  if (!p.ok) return <Unrenderable component="Select" />;
  const options = p.value.options.map((o) => ({ value: String(o.value), label: plainText(o.label, 120) }));
  const current = typeof field.value === 'string' ? field.value : field.value === null || field.value === undefined ? '' : String(field.value);
  return (
    <div data-genui="Select" data-statement-id={statementId} className="grid min-w-0 gap-1">
      <label htmlFor={id} dir="auto" className="text-xs font-medium text-muted-foreground">
        {plainText(p.value.label, 120)}
      </label>
      <select id={id} name={name} value={current} onChange={(event) => field.setValue(event.target.value)} className={cn(fieldClass, 'pr-8')}>
        {!options.some((o) => o.value === current) ? <option value={current}>{p.value.placeholder !== undefined ? plainText(p.value.placeholder, 120) : '—'}</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_RANGE_DAYS = 366;
const dateRangeProps = z.object({ name: z.string().min(1).max(64), label: z.union([z.string(), z.number()]), value: z.unknown().optional() });

function rangeError(start: string, end: string, l: GenUiLocale): string | null {
  if (!DATE.test(start) || !DATE.test(end)) return null;
  const a = Date.parse(`${start}T00:00:00Z`);
  const b = Date.parse(`${end}T00:00:00Z`);
  if (b < a) return l.t('rangeOrder');
  if ((b - a) / 86_400_000 > MAX_RANGE_DAYS) return l.t('rangeTooLong');
  return null;
}

export const DateRange: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(dateRangeProps, props);
  const l = useGenUiLocale();
  const id = useId();
  const name = p.ok ? p.value.name : `range_${statementId ?? 'x'}`;
  const field = useStateField<{ start: string; end: string } | null>(name, p.ok ? (p.value.value as { start: string; end: string } | undefined) : undefined);
  const stored = field.value && typeof field.value === 'object' ? (field.value as { start?: unknown; end?: unknown }) : null;
  const [draft, setDraft] = useState<{ start: string; end: string } | null>(null);
  const start = draft?.start ?? (typeof stored?.start === 'string' ? stored.start : '');
  const end = draft?.end ?? (typeof stored?.end === 'string' ? stored.end : '');
  const error = rangeError(start, end, l);
  if (!p.ok) return <Unrenderable component="DateRange" />;
  const change = (next: { start: string; end: string }) => {
    setDraft(next);
    // Only a complete, valid range reaches the bound $variable (and so the Query); partial input stays local.
    if (DATE.test(next.start) && DATE.test(next.end) && !rangeError(next.start, next.end, l)) {
      field.setValue({ start: next.start, end: next.end });
      setDraft(null);
    }
  };
  return (
    <fieldset data-genui="DateRange" data-statement-id={statementId} className="grid min-w-0 gap-1 border-0 p-0" aria-describedby={error ? `${id}-error` : `${id}-zone`}>
      <legend dir="auto" className="mb-1 text-xs font-medium text-muted-foreground">
        {plainText(p.value.label, 120)}
      </legend>
      <div className="flex flex-wrap gap-2">
        <label className="grid min-w-[9rem] flex-1 gap-0.5 text-xs text-muted-foreground">
          {l.t('start')}
          <input type="date" value={start} onChange={(event) => change({ start: event.target.value, end })} aria-invalid={error ? true : undefined} className={fieldClass} />
        </label>
        <label className="grid min-w-[9rem] flex-1 gap-0.5 text-xs text-muted-foreground">
          {l.t('end')}
          <input type="date" value={end} onChange={(event) => change({ start, end: event.target.value })} aria-invalid={error ? true : undefined} className={fieldClass} />
        </label>
      </div>
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        <p id={`${id}-zone`} className="text-xs text-muted-foreground">
          {l.t('timeZoneNote', { zone: l.timeZone })}
        </p>
      )}
    </fieldset>
  );
};

/* ------------------------------------------------------------------------------------------------ Button */

const VARIANT = { primary: 'default', secondary: 'outline', quiet: 'quiet' } as const;
const buttonProps = z.object({
  label: z.union([z.string(), z.number()]),
  action: z.unknown().optional(),
  variant: z.enum(['primary', 'secondary', 'quiet']).optional(),
});
export const Button: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(buttonProps, props);
  const trigger = useTriggerAction();
  const streaming = useIsStreaming();
  const formName = useFormName();
  if (!p.ok) return <Unrenderable component="Button" />;
  const label = plainText(p.value.label, 80);
  const plan = p.value.action === undefined ? null : sanitizePlan(p.value.action);
  return (
    <UiButton
      data-genui="Button"
      data-statement-id={statementId}
      type="button"
      size="sm"
      variant={VARIANT[p.value.variant ?? 'secondary']}
      disabled={streaming || (p.value.action !== undefined && (!plan || plan.steps.length === 0))}
      onClick={(event: { isTrusted?: boolean; nativeEvent?: { isTrusted?: boolean } }) => {
        // Generated code cannot click on the person's behalf: only a trusted (browser-originated) event runs the plan.
        if (event.nativeEvent?.isTrusted === false) return;
        void trigger(label, formName, plan ?? undefined);
      }}
      className="w-fit"
    >
      <span dir="auto">{label}</span>
    </UiButton>
  );
};

/** Values of a Form's registered fields, read from OpenUI's store (for ActionButton). */
export function useFormValues(): (formName: string | undefined, fields: string[]) => Record<string, unknown> {
  const get = useGetFieldValue();
  return useCallback(
    (formName, fields) => {
      const out: Record<string, unknown> = {};
      for (const field of fields) out[field] = get(formName, field);
      return out;
    },
    [get],
  );
}

