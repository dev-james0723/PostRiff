'use client';

/**
 * How Rafii talks (Contract 1): three starting points and, under "More options", each setting on its own: tone,
 * detail, speaking pace, voice, language and suggestions. It applies to written answers and to voice. Every choice
 * saves at once through `useAgentStyle`; the control shows the result, and only a failure shows a toast.
 *
 * `firstRun` is the picker before the first voice call: choosing a starting point saves it (with `chosen`), closes the
 * sheet and calls `onChosen`. A failed save never holds that up; the toast says the choice wasn't kept.
 */
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SegmentedControl } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import {
  DETAIL_LABELS,
  DETAILS,
  INITIATIVE,
  INITIATIVE_LABELS,
  LANGUAGE_LABELS,
  LANGUAGES,
  PACE_LABELS,
  PACES,
  PRESETS,
  presetOf,
  TONE_LABELS,
  TONES,
  VOICE_LABELS,
  VOICES,
  type AgentStyle,
  type AgentStylePatch,
  type Language,
  type PresetId
} from '@/lib/agent-runtime/style';
import { useAgentStyle } from '@/lib/agent-runtime/use-agent-style';
import { useMeasuredDisclosure } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

const PRESET_IDS = Object.keys(PRESETS) as PresetId[];
/** So screen readers read the Chinese names in the right language. */
const LANGUAGE_TAGS: Partial<Record<Language, string>> = { yue: 'zh-HK', cmn: 'zh-CN' };

/** One line for a settings row: the starting point (or the tone and detail of a custom mix), the voice and the language. */
export function styleSummary(style: AgentStyle): string {
  const preset = presetOf(style);
  const manner = preset ? PRESETS[preset].label : `${TONE_LABELS[style.tone]} tone, ${DETAIL_LABELS[style.detail].toLowerCase()} answers`;
  return [manner, `${VOICE_LABELS[style.voice]} voice`, LANGUAGE_LABELS[style.language]].join(' · ');
}

export function StyleSheet({ open, onOpenChange, onChosen, firstRun = false }: { open: boolean; onOpenChange: (open: boolean) => void; onChosen?: () => void; firstRun?: boolean }) {
  return (
    <RafiiDialog open={open} onOpenChange={(next) => onOpenChange(next)}>
      {/* The marker lets the Rafii panel leave Escape to this sheet when it opens above the panel. */}
      <RafiiDialogContent size='sm' data-rafii-style-sheet=''>
        <StyleStage firstRun={firstRun} onClose={() => onOpenChange(false)} onChosen={onChosen} />
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

/** The sheet's contents; they mount with each opening, so every opening starts from the saved style. */
function StyleStage({ firstRun, onClose, onChosen }: { firstRun: boolean; onClose: () => void; onChosen?: () => void }) {
  const { style, save } = useAgentStyle();
  const current = presetOf(style);
  const [more, setMore] = useState(() => !firstRun && current === null);
  const [choosing, setChoosing] = useState<PresetId | 'done' | null>(null);
  const finishing = useRef(false);
  const moreId = useId();
  const moreRef = useMeasuredDisclosure<HTMLDivElement>(more);

  function change(patch: AgentStylePatch) {
    // A failure has already rolled back and shown a toast.
    save({ ...patch, chosen: true }).catch(() => undefined);
  }

  async function finish(patch: AgentStylePatch | null, marker: PresetId | 'done') {
    if (finishing.current) return;
    finishing.current = true;
    setChoosing(marker);
    if (patch) await save({ ...patch, chosen: true }).catch(() => undefined);
    onClose();
    onChosen?.();
  }

  function pick(id: PresetId) {
    if (firstRun) void finish({ preset: id }, id);
    else change({ preset: id });
  }

  function done() {
    if (firstRun) void finish(style.chosen ? null : {}, 'done');
    else onClose();
  }

  return (
    <>
      <RafiiDialogHeader
        eyebrow={firstRun ? undefined : 'Rafii’s style'}
        title={firstRun ? 'How should Rafii talk to you?' : 'How Rafii talks to you'}
        intro={firstRun ? 'Pick a starting point. You can change it any time.' : 'For written answers and voice. Changes save as you make them.'}
        closeLabel='Close style settings'
      />
      <RafiiDialogBody className='flex flex-col gap-3 pt-1'>
        <PresetCards firstRun={firstRun} current={firstRun ? null : current} busy={choosing} onPick={pick} />
        {!firstRun && current === null && <p className='text-muted-foreground px-1 text-xs leading-relaxed'>Custom: your own mix of the settings under More options.</p>}
        <div className='flex flex-col'>
          <button
            type='button'
            aria-expanded={more}
            aria-controls={moreId}
            onClick={() => setMore((open) => !open)}
            className='rafii-focus text-foreground flex min-h-11 w-fit items-center gap-1.5 rounded-[var(--rafii-radius-control)] px-1 text-sm font-medium'
          >
            More options
            <Icons.chevronDown aria-hidden className={cn('size-4 transition-transform duration-200', more && 'rotate-180')} />
          </button>
          <div ref={moreRef} id={moreId}>
            <FineTune style={style} onChange={change} />
          </div>
        </div>
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <Button variant='action' size='control' className='w-full' onClick={done} aria-busy={choosing === 'done' || undefined}>
          Done
        </Button>
      </RafiiDialogFooter>
    </>
  );
}

/** Arrow keys on a radio (the radio pattern): they move to the next option in its group and choose it. */
function radioKeys<V extends string>(event: KeyboardEvent<HTMLButtonElement>, values: readonly V[], onPick: (value: V) => void) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
  const index = Math.max(0, values.indexOf(event.currentTarget.dataset.value as V));
  const last = values.length - 1;
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? last : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? (index + 1) % values.length : (index - 1 + values.length) % values.length;
  event.preventDefault();
  event.currentTarget.parentElement?.querySelector<HTMLElement>(`[data-value="${CSS.escape(values[next])}"]`)?.focus();
  onPick(values[next]);
}

/**
 * The three starting points. In settings they are radios marking the one in use (none for a custom mix); before a first
 * call they are plain buttons, since choosing one also starts the call.
 */
function PresetCards({ firstRun, current, busy, onPick }: { firstRun: boolean; current: PresetId | null; busy: PresetId | 'done' | null; onPick: (id: PresetId) => void }) {
  const tabStop = current ?? PRESET_IDS[0];
  return (
    <div role={firstRun ? 'group' : 'radiogroup'} aria-label='Starting points' className='flex flex-col gap-2'>
      {PRESET_IDS.map((id) => {
        const selected = !firstRun && id === current;
        const waiting = busy === id;
        return (
          <button
            key={id}
            type='button'
            data-value={id}
            role={firstRun ? undefined : 'radio'}
            aria-checked={firstRun ? undefined : selected}
            tabIndex={firstRun || id === tabStop ? 0 : -1}
            aria-disabled={busy !== null || undefined}
            aria-busy={waiting || undefined}
            onClick={() => busy === null && !selected && onPick(id)}
            onKeyDown={firstRun ? undefined : (event) => radioKeys(event, PRESET_IDS, (next) => next !== current && onPick(next))}
            className={cn(
              'rafii-focus flex min-h-16 w-full items-start gap-3 rounded-[var(--rafii-radius-card)] px-4 py-3.5 text-left transition-colors',
              selected || waiting ? 'rafii-glass-selected' : 'rafii-glass hover:rafii-glass-selected',
              busy !== null && !waiting && 'opacity-60'
            )}
          >
            {!firstRun && (
              <span aria-hidden className={cn('mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full', selected ? 'bg-foreground text-background' : 'rafii-quiet')}>
                {selected && <Icons.check className='size-3' />}
              </span>
            )}
            <span className='flex min-w-0 flex-1 flex-col gap-1'>
              <span className='text-foreground text-sm font-medium'>{PRESETS[id].label}</span>
              <span className='text-muted-foreground text-xs leading-relaxed'>{PRESETS[id].description}</span>
            </span>
            {firstRun && (waiting ? <Icons.spinner aria-hidden className='text-muted-foreground mt-0.5 size-4 shrink-0 animate-spin' /> : <Icons.arrowRight aria-hidden className='text-muted-foreground mt-0.5 size-4 shrink-0' />)}
          </button>
        );
      })}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className='flex min-w-0 flex-col gap-2'>
      <div className='flex items-baseline justify-between gap-3 px-1'>
        <span className='text-foreground text-sm font-medium'>{label}</span>
        {hint && <span className='text-muted-foreground text-xs'>{hint}</span>}
      </div>
      {children}
    </div>
  );
}

/**
 * A segmented control whose options wrap onto rows, for settings with longer or more labels than one row of a phone
 * holds. Same look as `SegmentedControl` (a quiet track, the chosen option under a lens) and the same radio keys.
 */
function ChoiceGrid<V extends string>({ label, options, value, onChange, className }: { label: string; options: { value: V; label: string; lang?: string }[]; value: V; onChange: (value: V) => void; className?: string }) {
  const values = options.map((option) => option.value);
  return (
    <div role='radiogroup' aria-label={label} className={cn('rafii-quiet grid gap-1 rounded-[var(--rafii-radius-segment)] p-1', className)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type='button'
            role='radio'
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            data-value={option.value}
            lang={option.lang}
            onClick={() => !active && onChange(option.value)}
            onKeyDown={(event) => radioKeys(event, values, (next) => next !== value && onChange(next))}
            className={cn(
              'rafii-focus min-h-11 min-w-0 rounded-[calc(var(--rafii-radius-segment)-4px)] px-3 py-2 text-sm leading-tight font-medium text-balance transition-colors duration-200',
              active ? 'rafii-lens text-foreground' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function FineTune({ style, onChange }: { style: AgentStyle; onChange: (patch: AgentStylePatch) => void }) {
  return (
    <div className='flex flex-col gap-5 pt-2 pb-1'>
      <Field label='Tone'>
        <ChoiceGrid label='Tone' value={style.tone} onChange={(tone) => onChange({ tone })} className='grid-cols-2 sm:grid-cols-4' options={TONES.map((value) => ({ value, label: TONE_LABELS[value] }))} />
      </Field>
      <Field label='Detail'>
        <SegmentedControl label='Detail' value={style.detail} onChange={(detail) => onChange({ detail })} options={DETAILS.map((value) => ({ value, label: DETAIL_LABELS[value] }))} />
      </Field>
      <Field label='Speaking pace' hint='When you talk to Rafii'>
        <SegmentedControl label='Speaking pace' value={style.pace} onChange={(pace) => onChange({ pace })} options={PACES.map((value) => ({ value, label: PACE_LABELS[value] }))} />
      </Field>
      <Field label='Voice' hint='When you talk to Rafii'>
        <ChoiceGrid label='Voice' value={style.voice} onChange={(voice) => onChange({ voice })} className='grid-cols-3' options={VOICES.map((value) => ({ value, label: VOICE_LABELS[value] }))} />
      </Field>
      <Field label='Language'>
        <ChoiceGrid label='Language' value={style.language} onChange={(language) => onChange({ language })} className='grid-cols-2 sm:grid-cols-4' options={LANGUAGES.map((value) => ({ value, label: LANGUAGE_LABELS[value], lang: LANGUAGE_TAGS[value] }))} />
      </Field>
      <Field label='Suggestions'>
        <ChoiceGrid label='Suggestions' value={style.initiative} onChange={(initiative) => onChange({ initiative })} className='grid-cols-2' options={INITIATIVE.map((value) => ({ value, label: INITIATIVE_LABELS[value] }))} />
      </Field>
    </div>
  );
}

/**
 * A compact pill with the starting point in use ("Custom" for a mix) that opens the sheet. It keeps its own open state,
 * or follows `open`/`onOpenChange` when the owner also opens the sheet from elsewhere (the panel's `/style`).
 */
export function StyleButton({ className, open, onOpenChange }: { className?: string; open?: boolean; onOpenChange?: (open: boolean) => void }) {
  const { style, loading } = useAgentStyle();
  const [ownOpen, setOwnOpen] = useState(false);
  const shown = open ?? ownOpen;
  const setShown = onOpenChange ?? setOwnOpen;
  const preset = presetOf(style);
  const label = loading ? 'Style' : preset ? PRESETS[preset].label : 'Custom';
  return (
    <>
      <button
        type='button'
        aria-haspopup='dialog'
        aria-expanded={shown}
        title='Change how Rafii talks'
        onClick={() => setShown(true)}
        className={cn(
          'rafii-glass rafii-focus hover:rafii-glass-selected text-foreground inline-flex h-8 max-w-full min-w-0 items-center gap-1.5 rounded-full px-3 text-xs font-medium pointer-coarse:h-11 pointer-coarse:px-4',
          className
        )}
      >
        <Icons.adjustments aria-hidden className='size-3.5 shrink-0' />
        <span className='sr-only'>Rafii’s style: </span>
        <span className='truncate'>{label}</span>
      </button>
      <StyleSheet open={shown} onOpenChange={setShown} />
    </>
  );
}
