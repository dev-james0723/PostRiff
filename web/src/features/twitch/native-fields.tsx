'use client';

import { useId } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { TwitchField } from './types';

export const TWITCH_SELECT_CLASS = 'rafii-focus border-input bg-background h-10 w-full rounded-md border px-3 text-sm disabled:opacity-50';

function fieldLabel(name: string, field: TwitchField): string {
  return field.label || name.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());
}

/** A genuine form for the server's strict native schema, including polls and nested reward settings. */
export function NativeFields({
  fields,
  values,
  onChange,
  disabled = false,
  requiredProperties = []
}: {
  fields: Record<string, TwitchField>;
  values: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
  requiredProperties?: string[];
}) {
  return (
    <div className='grid gap-4'>
      {Object.entries(fields).map(([name, field]) => (
        <NativeField
          key={name}
          name={name}
          field={field}
          required={requiredProperties.includes(name)}
          value={values[name]}
          disabled={disabled}
          onChange={(value) => {
            const next = { ...values };
            if (value === undefined) delete next[name];
            else next[name] = value;
            onChange(next);
          }}
        />
      ))}
    </div>
  );
}

function NativeField({ name, field, value, onChange, disabled, required: parentRequired = false }: {
  name: string;
  field: TwitchField;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
  required?: boolean;
}) {
  const id = useId();
  const label = fieldLabel(name, field);
  const required = parentRequired || field.required === true;
  const helpId = `${id}-help`;
  const help = [field.description, field.format === 'date-time' ? 'Use a date and time with its UTC offset, for example 2026-10-20T19:00:00-04:00.' : undefined].filter(Boolean).join(' ');

  if (field.type === 'object') {
    if (!field.properties) return <p role='alert'>The fields for {label} are unavailable. Refresh before continuing.</p>;
    const requiredProperties = Array.isArray(field.required) ? field.required : [];
    const included = required || value !== undefined;
    return (
      <fieldset disabled={disabled} className='grid gap-3 rounded-lg border p-4'>
        <legend className='px-1 text-sm font-medium'>{label}{required ? ' *' : ' (optional)'}</legend>
        {help && <p className='text-muted-foreground text-xs'>{help}</p>}
        {included ? <NativeFields fields={field.properties} requiredProperties={requiredProperties} values={value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}} onChange={onChange} disabled={disabled} /> : <Button type='button' size='sm' variant='outline' className='justify-self-start' onClick={() => onChange({})}>Specify {label.toLowerCase()}</Button>}
        {!required && value !== undefined && <Button type='button' size='sm' variant='ghost' className='justify-self-start' onClick={() => onChange(undefined)}>Leave {label.toLowerCase()} unchanged</Button>}
      </fieldset>
    );
  }

  if (field.type === 'array') {
    if (!field.items) return <p role='alert'>The items for {label} are unavailable. Refresh before continuing.</p>;
    const items = Array.isArray(value) ? value : [];
    const maximum = Math.min(field.maxItems ?? 100, 100);
    return (
      <fieldset disabled={disabled} className='grid gap-3 rounded-lg border p-4'>
        <legend className='px-1 text-sm font-medium'>{label}{required ? ' *' : ' (optional)'}</legend>
        {(help || field.minItems || field.maxItems) && <p className='text-muted-foreground text-xs'>{help} {field.minItems ? `At least ${field.minItems} items. ` : ''}{field.maxItems ? `Up to ${field.maxItems} items.` : ''}</p>}
        {items.map((item, index) => (
          <div key={index} className='grid gap-2 rounded-md border border-dashed p-3'>
            <NativeField name={`${name}_${index + 1}`} field={{ ...field.items!, label: `${label} ${index + 1}` }} required value={item} disabled={disabled} onChange={(next) => onChange(items.map((existing, i) => i === index ? next : existing))} />
            <Button type='button' size='sm' variant='ghost' className='justify-self-end' aria-label={`Remove ${label} ${index + 1}`} onClick={() => onChange(items.filter((_, i) => i !== index))}>Remove</Button>
          </div>
        ))}
        <div className='flex flex-wrap gap-2'>
          <Button type='button' size='sm' variant='outline' disabled={disabled || items.length >= maximum} onClick={() => onChange([...items, field.items?.type === 'object' ? {} : ''])}>Add {label.toLowerCase()} item</Button>
          {!required && value !== undefined && <Button type='button' size='sm' variant='ghost' onClick={() => onChange(undefined)}>Leave unchanged</Button>}
        </div>
      </fieldset>
    );
  }

  const scalar = typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : '';
  const choices = field.enum ?? (field.type === 'boolean' ? [true, false] : undefined);
  const multiline = field.type === 'string' && !choices && /(?:message|description|reason|prompt|text|announcement)/i.test(name);
  const numeric = field.type === 'integer' || field.type === 'number';
  const sourceAudience = name === 'for_source_only';

  return (
    <div className='grid gap-1.5'>
      <Label htmlFor={id}>{label}{required ? ' *' : <span className='text-muted-foreground font-normal'> (optional)</span>}</Label>
      {choices ? (
        <select id={id} aria-describedby={help || sourceAudience ? helpId : undefined} className={TWITCH_SELECT_CLASS} value={scalar} disabled={disabled} required={required} onChange={(event) => onChange(event.target.value)}>
          <option value=''>{required ? 'Choose…' : 'Leave unchanged / not specified'}</option>
          {choices.map((choice) => <option key={String(choice)} value={String(choice)}>{typeof choice === 'boolean' ? choice ? sourceAudience ? 'Only this source channel' : 'Yes' : sourceAudience ? 'All channels in the Shared Chat session' : 'No' : String(choice)}</option>)}
        </select>
      ) : multiline ? (
        <Textarea id={id} aria-describedby={help ? helpId : undefined} rows={3} required={required} disabled={disabled} value={scalar} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <Input id={id} aria-describedby={help ? helpId : undefined} type={numeric ? 'number' : 'text'} inputMode={numeric ? 'numeric' : undefined} step={field.type === 'integer' ? 1 : numeric ? 'any' : undefined} min={field.minimum ?? field.min} max={field.maximum ?? field.max} required={required} disabled={disabled} value={scalar} autoComplete='off' onChange={(event) => onChange(event.target.value)} />
      )}
      {(help || sourceAudience) && <p id={helpId} className='text-muted-foreground text-xs leading-relaxed'>{help}{sourceAudience ? ' “All channels” can send beyond the channel selected in Rafii. The server verifies whether this audience is supported by the current authorization.' : ''}</p>}
      {field.type === 'string' && !choices && field.maxLength !== undefined && <p className='text-muted-foreground text-xs'>{Array.from(scalar).length} / {field.maxLength} characters</p>}
    </div>
  );
}
