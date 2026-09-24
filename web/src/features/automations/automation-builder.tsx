'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { LanguagePicker } from '@/components/application/language-picker/language-picker';
import { Checkbox } from '@/components/motion/checkbox';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SegmentedControl, SemanticIllustration, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { DRAFT_PLATFORMS } from '@/features/agent/composer';
import { contentChoice, type LibraryValue } from '@/features/agent/content-choice';
import { ContentLibraryDialog } from '@/features/agent/content-library-dialog';
import { pocketSources } from '@/features/agent/home/context-pocket';
import { settingsOf } from '@/features/agent/use-channel-languages';
import { useModelChoice } from '@/features/agent/use-model';
import { ChannelBloomDialog, toFolderAccounts } from '@/features/channels/channel-bloom';
import { ApiError } from '@/lib/api/client';
import { useModels, useSnapshot } from '@/lib/api/hooks';
import type { RaffiCampaign, RecurringDestination, Snapshot } from '@/lib/api/types';
import { selectionLabel, type FolderContext } from '@/lib/channels/folders';
import { languageLabel, locales } from '@/lib/locales';
import { useTimeZone } from '@/lib/preferences';
import { cn } from '@/lib/utils';
import type { Automation } from './use-automations';
import { WEEKDAYS, WEEKDAY_SHORT, missingFacts, nextRuns, parseTime, runLabel, scheduleSummary, usd, validTimeZone, weekdaysOf, weeklyCeilingMicro, type Weekday } from './schedule';

/** 48px fields with 16px text on phones (no iOS zoom), quiet field material (DNA §10, §12). */
const FIELD = 'rafii-field h-12 rounded-[var(--rafii-radius-control)] px-3.5 text-base md:h-11 md:text-sm';
const LABEL = 'text-foreground text-sm font-medium';
const HINT = 'text-muted-foreground text-xs leading-relaxed';
const CREATOR_PACK = { packId: 'pack.creator', version: '1.0.0' };
const DEFAULT_LIBRARY: LibraryValue = { editorialId: 'status_update', nativeId: 'text' };
const MAX_DESTINATIONS = 10;

type Step = 'what' | 'when' | 'where' | 'review';
type Reasoning = 'quick' | 'standard' | 'deep';
const STEPS: { value: Step; label: string }[] = [
  { value: 'what', label: '1 · What' },
  { value: 'when', label: '2 · When' },
  { value: 'where', label: '3 · Where' },
  { value: 'review', label: '4 · Review' }
];

/** The content an automation writes as: a workspace content type (with its Library pairing when known) or general writing. */
export interface ContentState {
  contentTypeId: string;
  formatId: string | null;
  label: string;
  library: LibraryValue | null;
  needsCreatorPack: boolean;
}

/** One destination row: an account (or a platform without one) and the languages drafted for it. */
export interface TargetState {
  key: string;
  platform: string;
  channelId?: string;
  languages: string[];
}

export interface BuilderInitial {
  taskId?: string;
  campaignId?: string;
  wasActive: boolean;
  name: string;
  goal: string;
  audience: string;
  facts: Record<string, string>;
  weekdays: Weekday[];
  localTime: string;
  timeZone: string;
  targets: TargetState[];
  folderContext: FolderContext | null;
  destinationLabel: string | null;
  content: ContentState | null;
  route: string | null;
  reasoning: Reasoning;
  maxCostUsd: string;
  sourceIds: string[];
}

const REASONING: Reasoning[] = ['quick', 'standard', 'deep'];
const REASONING_LABEL: Record<Reasoning, string> = { quick: 'Quick', standard: 'Standard', deep: 'Deep' };

function groupTargets(destinations: RecurringDestination[]): TargetState[] {
  const out: TargetState[] = [];
  for (const d of destinations) {
    const key = d.channelId ?? d.platform;
    const found = out.find((t) => t.key === key);
    if (found) {
      if (!found.languages.includes(d.language)) found.languages.push(d.language);
    } else out.push({ key, platform: d.platform, channelId: d.channelId, languages: [d.language] });
  }
  return out;
}

export function blankInitial(timeZone: string): BuilderInitial {
  return { wasActive: false, name: '', goal: '', audience: '', facts: {}, weekdays: ['Monday'], localTime: '09:00', timeZone, targets: [], folderContext: null, destinationLabel: null, content: null, route: null, reasoning: 'quick', maxCostUsd: '0', sourceIds: [] };
}

/** Start a new automation from an existing campaign brief (an older campaign or a suggestion). */
export function initialFromBrief(campaign: RaffiCampaign, timeZone: string): BuilderInitial {
  return { ...blankInitial(timeZone), campaignId: campaign.id, name: campaign.goal.slice(0, 80), goal: campaign.goal, audience: campaign.audience, facts: campaign.facts ?? {} };
}

export function initialFromAutomation(automation: Automation, timeZone: string): BuilderInitial {
  const { task, campaign } = automation;
  const content = task.contentType
    ? { contentTypeId: task.contentType.contentTypeId, formatId: task.contentType.formatId, label: task.contentLabel || task.contentType.contentTypeId, library: task.contentLibrary ?? null, needsCreatorPack: task.contentType.contentTypeId.startsWith(`${CREATOR_PACK.packId}:`) }
    : null;
  return {
    taskId: task.id,
    wasActive: task.status === 'active',
    name: automation.name,
    goal: campaign?.goal ?? '',
    audience: campaign?.audience ?? '',
    facts: campaign?.facts ?? {},
    weekdays: weekdaysOf(task.schedule),
    localTime: task.schedule.localTime,
    timeZone: validTimeZone(task.schedule.timeZone) ? task.schedule.timeZone : timeZone,
    targets: groupTargets(automation.destinations),
    folderContext: null,
    destinationLabel: task.destinationLabel ?? null,
    content,
    route: task.route && task.route !== 'local-cli' ? task.route : null,
    reasoning: (REASONING as string[]).includes(task.reasoning ?? '') ? (task.reasoning as Reasoning) : 'quick',
    maxCostUsd: String((task.maxCostUsdMicro ?? 0) / 1_000_000),
    sourceIds: task.contextSourceIds ?? []
  };
}

function timeZones(current: string[]): string[] {
  let all: string[] = [];
  try {
    all = Intl.supportedValuesOf('timeZone');
  } catch {
    all = [];
  }
  return Array.from(new Set([...current.filter(Boolean), ...all]));
}

export interface AutomationBuilderProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial: BuilderInitial;
  isOwner: boolean;
  /** The serialized action channel from `useAutomations`. */
  act: (action: string, payload: Record<string, unknown>) => Promise<Snapshot>;
  onSaved?: (taskId: string) => void;
}

/**
 * The Automation builder: What (brief, content type, sources) → When (weekdays, time, zone) → Where
 * (accounts or folders, languages) → Review (writer, reasoning, cost limit). Saving creates or edits
 * a draft with one `raffi_recurrence_save`; only an owner activates it. Nothing here publishes.
 */
export function AutomationBuilder({ open, onOpenChange, initial, isOwner, act, onSaved }: AutomationBuilderProps) {
  const snapshot = useSnapshot();
  const models = useModels();
  const modelChoice = useModelChoice(models.data);
  const viewerZone = useTimeZone();
  const state = snapshot.data?.state;

  const [step, setStep] = useState<Step>('what');
  const [savedTaskId, setSavedTaskId] = useState<string | undefined>(initial.taskId);
  const [name, setName] = useState(initial.name);
  const [goal, setGoal] = useState(initial.goal);
  const [audience, setAudience] = useState(initial.audience);
  const [date, setDate] = useState(initial.facts.date ?? '');
  const [venue, setVenue] = useState(initial.facts.venue ?? '');
  const [weekdays, setWeekdays] = useState<Weekday[]>(initial.weekdays);
  const [localTime, setLocalTime] = useState(initial.localTime);
  const [timeZone, setTimeZone] = useState(initial.timeZone);
  const [targets, setTargets] = useState<TargetState[]>(initial.targets);
  const [folderContext, setFolderContext] = useState<FolderContext | null>(initial.folderContext);
  const [destinationLabel, setDestinationLabel] = useState<string | null>(initial.destinationLabel);
  const [content, setContent] = useState<ContentState | null>(initial.content);
  const [route, setRoute] = useState<string | null>(initial.route);
  const [reasoning, setReasoning] = useState<Reasoning>(initial.reasoning);
  const [maxCost, setMaxCost] = useState(initial.maxCostUsd);
  const [sourceIds, setSourceIds] = useState<string[]>(initial.sourceIds);
  const [inner, setInner] = useState<null | 'library' | 'channels'>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now] = useState(() => Date.now());

  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const accounts = useMemo(() => toFolderAccounts(channels), [channels]);
  const draftable = useMemo(() => accounts.filter((a) => a.connected && (DRAFT_PLATFORMS as readonly string[]).includes(a.platform)), [accounts]);
  const folders = useMemo(() => state?.phase2?.channelFolders ?? [], [state?.phase2?.channelFolders]);
  const sources = useMemo(() => pocketSources(state?.sources), [state?.sources]);
  const settings = useMemo(() => settingsOf(snapshot.data), [snapshot.data]);
  const writers = useMemo(() => models.data?.models.filter((m) => m.qualified) ?? [], [models.data]);
  const zones = useMemo(() => timeZones([initial.timeZone, viewerZone]), [initial.timeZone, viewerZone]);

  // A new automation starts with the writer chosen on Home when it can run unattended.
  useEffect(() => {
    if (route || !writers.length) return;
    setRoute(writers.find((m) => m.id === modelChoice.model)?.id ?? writers[0].id);
  }, [route, writers, modelChoice.model]);

  const writer = writers.find((m) => m.id === route);
  const reasoningOptions = REASONING.map((id) => {
    const listed = writer?.reasoning?.find((r) => r.id === id);
    return { value: id, label: REASONING_LABEL[id], disabled: listed ? !listed.available : false, title: listed?.detail };
  });
  const reasoningDisabled = Boolean(reasoningOptions.find((o) => o.value === reasoning)?.disabled);
  useEffect(() => {
    if (reasoningDisabled) setReasoning('quick');
  }, [reasoningDisabled]);

  const startingLanguages = (platform: string): string[] => {
    const remembered = settings.channels[platform];
    if (remembered?.length) return remembered;
    const usual = locales.usualFor(platform);
    return [usual ?? settings.default ?? 'en'];
  };
  const accountName = (target: TargetState) => (target.channelId ? (accounts.find((a) => a.id === target.channelId)?.account ?? 'Disconnected account') : `${target.platform} (no account)`);
  const accountConnected = (target: TargetState) => !target.channelId || Boolean(accounts.find((a) => a.id === target.channelId)?.connected);

  const schedule = { weekdays, localTime, timeZone };
  const runs = useMemo(() => nextRuns(schedule, now, 3), [weekdays, localTime, timeZone, now]); // eslint-disable-line react-hooks/exhaustive-deps
  const destinations: RecurringDestination[] = targets.flatMap((t) => t.languages.map((language) => ({ platform: t.platform, language, ...(t.channelId ? { channelId: t.channelId } : {}) })));
  const costMicro = Math.round(Number(maxCost || '0') * 1_000_000);
  const costValid = Number.isFinite(costMicro) && costMicro >= 0 && costMicro <= 10_000_000;
  const facts = { ...initial.facts, date: date.trim(), venue: venue.trim() };
  const cleanFacts = Object.fromEntries(Object.entries(facts).filter(([, value]) => typeof value === 'string' && value.trim()));
  const missing = missingFacts(goal, cleanFacts);

  const blockers: { step: Step; text: string }[] = [
    ...(!name.trim() ? [{ step: 'what' as Step, text: 'Name the automation.' }] : []),
    ...(!goal.trim() ? [{ step: 'what' as Step, text: 'Describe what the drafts should be about.' }] : []),
    ...(!audience.trim() ? [{ step: 'what' as Step, text: 'Describe who the drafts are for.' }] : []),
    ...(!weekdays.length ? [{ step: 'when' as Step, text: 'Choose at least one day.' }] : []),
    ...(!parseTime(localTime) ? [{ step: 'when' as Step, text: 'Choose a time.' }] : []),
    ...(!validTimeZone(timeZone) ? [{ step: 'when' as Step, text: 'Choose a time zone.' }] : []),
    ...(!destinations.length ? [{ step: 'where' as Step, text: 'Choose at least one account or channel.' }] : []),
    ...(destinations.length > MAX_DESTINATIONS ? [{ step: 'where' as Step, text: `Keep it to ${MAX_DESTINATIONS} drafts a run or fewer.` }] : []),
    ...(targets.some((t) => !accountConnected(t)) ? [{ step: 'where' as Step, text: 'Remove the accounts that are no longer connected.' }] : []),
    ...(!route ? [{ step: 'review' as Step, text: 'Choose a writer.' }] : []),
    ...(!costValid ? [{ step: 'review' as Step, text: 'Set a cost limit between $0 and $10 a run.' }] : [])
  ];
  const reminders = [
    ...(missing.length ? [`Add the event ${missing.join(' and ')} before it can be activated. You can still save it as a draft.`] : []),
    ...(writer?.costClass === 'paid' && costMicro === 0 ? ['This writer charges per run. With a $0 limit every run is held, so set a limit above $0.'] : [])
  ];
  const stepIndex = STEPS.findIndex((s) => s.value === step);
  const draftsPerRun = destinations.length;

  function commitAccounts(accountIds: string[], context: FolderContext) {
    setTargets((current) => {
      const kept = accountIds.map((id) => {
        const existing = current.find((t) => t.channelId === id);
        if (existing) return existing;
        const account = accounts.find((a) => a.id === id)!;
        return { key: id, platform: account.platform, channelId: id, languages: startingLanguages(account.platform) };
      });
      // Platform rows (no account) stay; accounts come from the dialog.
      return [...kept, ...current.filter((t) => !t.channelId)];
    });
    setFolderContext(context);
    setDestinationLabel(context.sources.length ? selectionLabel(accountIds, context) : null);
    setInner(null);
  }

  function togglePlatform(platform: string) {
    setTargets((current) => (current.some((t) => !t.channelId && t.platform === platform) ? current.filter((t) => t.channelId || t.platform !== platform) : [...current, { key: platform, platform, languages: startingLanguages(platform) }]));
  }

  function setLanguage(key: string, index: number, tag: string) {
    setTargets((current) => current.map((t) => (t.key !== key ? t : { ...t, languages: Array.from(new Set(t.languages.map((l, i) => (i === index ? tag : l)))) })));
  }
  function addLanguage(key: string, tag: string) {
    setTargets((current) => current.map((t) => (t.key !== key || t.languages.includes(tag) ? t : { ...t, languages: [...t.languages, tag] })));
  }
  function removeLanguage(key: string, index: number) {
    setTargets((current) => current.map((t) => (t.key !== key || t.languages.length < 2 ? t : { ...t, languages: t.languages.filter((_, i) => i !== index) })));
  }
  function removeTarget(key: string) {
    setTargets((current) => current.filter((t) => t.key !== key));
    setDestinationLabel(null);
  }

  function applyLibrary(value: LibraryValue) {
    const choice = contentChoice(value);
    if (!choice) return;
    setContent({ contentTypeId: choice.contentTypeId, formatId: choice.formatId, label: choice.summary, library: choice.value, needsCreatorPack: choice.needsCreatorPack });
    setInner(null);
  }

  async function save(activate: boolean) {
    if (blockers.length || saving) return;
    setSaving(true);
    setError(null);
    let taskId = savedTaskId;
    try {
      if (content?.needsCreatorPack && !state?.contentTypes?.installedPacks?.some((pack) => pack.id === CREATOR_PACK.packId)) {
        await act('p2_content_install_pack', CREATOR_PACK);
      }
      const after = await act('raffi_recurrence_save', {
        ...(taskId ? { taskId } : initial.campaignId ? { campaignId: initial.campaignId } : {}),
        name: name.trim(),
        goal: goal.trim(),
        audience: audience.trim(),
        facts: cleanFacts,
        schedule: { weekdays, localTime, timeZone },
        destinations,
        destinationLabel,
        contentType: content ? { contentTypeId: content.contentTypeId, formatId: content.formatId, label: content.label, ...(content.library ? { library: content.library } : {}) } : null,
        route,
        reasoning,
        maxCostUsdMicro: costMicro,
        sourceIds
      });
      // The server appends a new automation last; an edit keeps its id.
      taskId = taskId ?? after.state.raffi?.campaignPlanning?.recurringTasks.at(-1)?.id;
      setSavedTaskId(taskId);
      if (activate && taskId) {
        try {
          await act('raffi_recurrence_activate', { taskId, confirmed: true });
        } catch (err) {
          setError(`Saved as a draft, but it could not be activated: ${err instanceof ApiError ? err.message : 'try again.'}`);
          return;
        }
      }
      toast.success(activate ? 'Automation saved and active. Drafts will wait for your review.' : 'Automation saved as a draft.');
      if (taskId) onSaved?.(taskId);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Rafii could not save this automation.');
    } finally {
      setSaving(false);
    }
  }

  const title = savedTaskId ? 'Edit' : 'New';
  return (
      <RafiiDialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
        <RafiiDialogContent size='lg' className='md:h-[min(52rem,92dvh)]'>
          <RafiiDialogHeader eyebrow='Automations' title={title} accent='automation' intro='Rafii prepares drafts on your schedule. Nothing publishes: every draft waits for your review.' />
          <div className='px-5 pb-1 md:px-7'>
            <SegmentedControl options={STEPS.map((s) => ({ value: s.value, label: s.label }))} value={step} onChange={setStep} pattern='tabs' label='Automation steps' size='sm' panelIds={STEPS.map((s) => `automation-step-${s.value}`)} />
          </div>
          <RafiiDialogBody className='flex flex-col gap-5'>
            {step === 'what' && (
              <section id='automation-step-what' role='tabpanel' aria-label='What' className='flex flex-col gap-4'>
                <Field label='Name' htmlFor='automation-name' hint='Shown on the Automations page and as the title of each run’s conversation.'>
                  <Input id='automation-name' value={name} onChange={(e) => setName(e.target.value)} placeholder='Weekly practice tip' maxLength={120} className={FIELD} />
                </Field>
                <Field label='What should each draft be about?' htmlFor='automation-goal' hint='This brief is sent to the writer each run. Names of apps, times or instructions inside it are treated as text, never as settings.'>
                  <Textarea id='automation-goal' value={goal} onChange={(e) => setGoal(e.target.value)} placeholder='One practical practice tip for adult piano students, drawn from this week’s lessons.' maxLength={1200} className='rafii-field min-h-24 rounded-[var(--rafii-radius-control)] px-3.5 py-3 text-base md:text-sm' />
                </Field>
                <Field label='Who is it for?' htmlFor='automation-audience'>
                  <Input id='automation-audience' value={audience} onChange={(e) => setAudience(e.target.value)} placeholder='Adult beginners and parents of young students' maxLength={800} className={FIELD} />
                </Field>
                <div className='grid gap-3 sm:grid-cols-2'>
                  <Field label='Event date' htmlFor='automation-date' hint={missing.includes('date') ? 'Needed before an event automation can be activated.' : 'Only for event briefs.'}>
                    <Input id='automation-date' value={date} onChange={(e) => setDate(e.target.value)} placeholder='18 April 2026, 7:30 pm' maxLength={400} className={FIELD} />
                  </Field>
                  <Field label='Venue' htmlFor='automation-venue' hint={missing.includes('venue') ? 'Needed before an event automation can be activated.' : 'Only for event briefs.'}>
                    <Input id='automation-venue' value={venue} onChange={(e) => setVenue(e.target.value)} placeholder='City Hall Recital Hall' maxLength={400} className={FIELD} />
                  </Field>
                </div>
                <div className='flex flex-col gap-2'>
                  <span className={LABEL}>Content type</span>
                  <Surface material='quiet' radius='control' padding='sm' className='flex flex-wrap items-center gap-3'>
                    {content?.library ? (
                      <span aria-hidden className='relative block h-8 w-9 shrink-0'>
                        <span className='absolute top-0.5 left-0 h-5 w-[30px] -rotate-[9deg] overflow-hidden rounded-[3px] shadow-sm'>
                          <SemanticIllustration id={content.library.editorialId} size='compact' decorative className='h-full w-full' />
                        </span>
                        <span className='absolute top-2.5 left-1.5 h-5 w-[30px] rotate-[8deg] overflow-hidden rounded-[3px] shadow-sm'>
                          <SemanticIllustration id={content.library.nativeId} size='compact' decorative className='h-full w-full' />
                        </span>
                      </span>
                    ) : (
                      <span className='rafii-glass flex size-9 shrink-0 items-center justify-center rounded-lg'>
                        <Icons.page className='size-4' />
                      </span>
                    )}
                    <span className='flex min-w-0 flex-[1_1_10rem] flex-col'>
                      <span className='text-sm font-medium'>{content ? content.label : 'General writing'}</span>
                      <span className={HINT}>{content ? 'The automation always writes as this type, whatever Home has selected.' : 'No specific content type or checks.'}</span>
                    </span>
                    <span className='flex gap-1'>
                      <Button variant='glass' size='sm' className='min-h-11' onClick={() => setInner('library')}>
                        {content ? 'Change' : 'Choose'}
                      </Button>
                      {content && (
                        <Button variant='quiet' size='sm' className='min-h-11' onClick={() => setContent(null)}>
                          Use general
                        </Button>
                      )}
                    </span>
                  </Surface>
                </div>
                {sources.length > 0 && (
                  <fieldset className='flex flex-col gap-2'>
                    <legend className={cn(LABEL, 'mb-1')}>Sources to draw from (optional)</legend>
                    <p className={HINT}>Only the sources you tick are read on each run. Leave all unticked to write from the brief alone.</p>
                    <div className='flex flex-col gap-1.5'>
                      {sources.map((source) => (
                        <Checkbox key={source.id} checked={sourceIds.includes(source.id)} onCheckedChange={(checked) => setSourceIds((ids) => (checked ? [...ids, source.id] : ids.filter((id) => id !== source.id)))} label={source.title || 'Untitled source'} className='min-h-11 gap-2.5 [&>span]:text-sm' />
                      ))}
                    </div>
                  </fieldset>
                )}
              </section>
            )}

            {step === 'when' && (
              <section id='automation-step-when' role='tabpanel' aria-label='When' className='flex flex-col gap-5'>
                <fieldset className='flex flex-col gap-2'>
                  <legend className={cn(LABEL, 'mb-1')}>On these days</legend>
                  <div className='grid grid-cols-7 gap-1.5'>
                    {WEEKDAYS.map((day) => {
                      const on = weekdays.includes(day);
                      return (
                        <button
                          key={day}
                          type='button'
                          aria-pressed={on}
                          aria-label={day}
                          onClick={() => setWeekdays((current) => (on ? current.filter((d) => d !== day) : WEEKDAYS.filter((d) => d === day || current.includes(d))))}
                          className={cn('rafii-focus min-h-11 rounded-[var(--rafii-radius-control)] text-sm font-medium transition-colors', on ? 'rafii-glass-selected text-foreground' : 'rafii-quiet text-muted-foreground hover:text-foreground')}
                        >
                          {WEEKDAY_SHORT[day]}
                        </button>
                      );
                    })}
                  </div>
                  <div className='flex flex-wrap gap-1'>
                    <Button variant='quiet' size='sm' className='min-h-11' onClick={() => setWeekdays(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])}>
                      Weekdays
                    </Button>
                    <Button variant='quiet' size='sm' className='min-h-11' onClick={() => setWeekdays([...WEEKDAYS])}>
                      Every day
                    </Button>
                    <Button variant='quiet' size='sm' className='min-h-11' onClick={() => setWeekdays(['Monday'])}>
                      Once a week
                    </Button>
                  </div>
                </fieldset>
                <div className='grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)]'>
                  <Field label='At' htmlFor='automation-time'>
                    <Input id='automation-time' type='time' value={localTime} onChange={(e) => setLocalTime(e.target.value)} className={FIELD} />
                  </Field>
                  <Field label='Time zone' htmlFor='automation-zone'>
                    <select id='automation-zone' value={timeZone} onChange={(e) => setTimeZone(e.target.value)} className={cn(FIELD, 'rafii-focus w-full min-w-0')}>
                      {zones.map((zone) => (
                        <option key={zone} value={zone}>
                          {zone.replaceAll('_', ' ')}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <Surface material='quiet' radius='control' padding='sm' aria-live='polite'>
                  <p className='text-sm font-medium'>{weekdays.length && parseTime(localTime) ? scheduleSummary(schedule) : 'Choose days and a time'}</p>
                  {runs.length > 0 && (
                    <ul className='mt-2 flex flex-col gap-1'>
                      {runs.map((run, index) => (
                        <li key={run} className='text-muted-foreground flex flex-wrap items-baseline gap-x-2 text-xs'>
                          <span className='text-foreground'>{index === 0 ? 'First run' : 'Then'} · {runLabel(run, timeZone)}</span>
                          {timeZone !== viewerZone && validTimeZone(viewerZone) && <span>({runLabel(run, viewerZone)} your time)</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className={cn(HINT, 'mt-2')}>A run that is more than a day late, for example after a pause, is skipped rather than caught up.</p>
                </Surface>
              </section>
            )}

            {step === 'where' && (
              <section id='automation-step-where' role='tabpanel' aria-label='Where' className='flex flex-col gap-4'>
                {draftable.length > 0 ? (
                  <div className='flex flex-wrap items-center justify-between gap-2'>
                    <p className={HINT}>Each account gets its own draft in each of its languages. Two accounts on one app get two drafts.</p>
                    <Button variant='glass' size='control' onClick={() => setInner('channels')}>
                      <Icons.broadcast />
                      Choose accounts or folders
                    </Button>
                  </div>
                ) : (
                  <div className='flex flex-col gap-2'>
                    <p className={HINT}>No account is connected yet, so drafts are written per app. Connect an account on the Channels page to draft for it.</p>
                    <div className='flex flex-wrap gap-1.5'>
                      {DRAFT_PLATFORMS.map((platform) => {
                        const on = targets.some((t) => !t.channelId && t.platform === platform);
                        return (
                          <button key={platform} type='button' aria-pressed={on} onClick={() => togglePlatform(platform)} className={cn('rafii-focus inline-flex min-h-11 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 text-sm', on ? 'rafii-glass-selected text-foreground' : 'rafii-quiet text-muted-foreground hover:text-foreground')}>
                            <ChannelIcon platform={platform} size='sm' />
                            {platform}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
                {destinationLabel && <p className='text-sm'>From <span className='font-medium'>{destinationLabel}</span></p>}
                {targets.length === 0 ? (
                  <Surface material='quiet' radius='control' padding='sm'>
                    <p className='text-muted-foreground text-sm'>No destinations yet.</p>
                  </Surface>
                ) : (
                  <ul className='flex flex-col gap-2'>
                    {targets.map((target) => (
                      <li key={target.key}>
                        <Surface material='quiet' radius='control' padding='sm' className='flex flex-wrap items-center gap-x-3 gap-y-2'>
                          <ChannelIcon platform={target.platform} size='sm' />
                          <span className='flex min-w-0 flex-[1_1_9rem] flex-col'>
                            <span className='truncate text-sm font-medium'>{accountName(target)}</span>
                            <span className={HINT}>{accountConnected(target) ? target.platform : 'No longer connected: remove it or reconnect it on Channels.'}</span>
                          </span>
                          <span className='flex flex-wrap items-center gap-1'>
                            {target.languages.map((tag, index) => (
                              <span key={tag} className='rafii-glass inline-flex items-center rounded-full'>
                                <LanguagePicker
                                  title={`Language for ${accountName(target)}`}
                                  selected={[tag]}
                                  onPick={(next) => setLanguage(target.key, index, next)}
                                  suggestions={startingLanguages(target.platform).map((t) => ({ tag: t, reason: `Used for ${target.platform}` }))}
                                  trigger={
                                    <button type='button' className='rafii-focus inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 text-xs font-medium' aria-label={`Language ${languageLabel(tag)} for ${accountName(target)}, change`}>
                                      {languageLabel(tag)}
                                    </button>
                                  }
                                />
                                {target.languages.length > 1 && (
                                  <button type='button' onClick={() => removeLanguage(target.key, index)} aria-label={`Remove ${languageLabel(tag)} for ${accountName(target)}`} className='rafii-focus text-muted-foreground hover:text-foreground inline-flex size-9 items-center justify-center rounded-full'>
                                    <Icons.close className='size-3.5' />
                                  </button>
                                )}
                              </span>
                            ))}
                            <LanguagePicker
                              title={`Add a language for ${accountName(target)}`}
                              selected={target.languages}
                              onPick={(next) => addLanguage(target.key, next)}
                              trigger={
                                <button type='button' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-9 items-center gap-1 rounded-full px-2.5 text-xs' aria-label={`Add a language for ${accountName(target)}`}>
                                  <Icons.add className='size-3.5' />
                                  Language
                                </button>
                              }
                            />
                          </span>
                          <Button variant='quiet' size='icon-control' aria-label={`Remove ${accountName(target)}`} onClick={() => removeTarget(target.key)}>
                            <Icons.trash />
                          </Button>
                        </Surface>
                      </li>
                    ))}
                  </ul>
                )}
                <p className={cn('text-sm', draftsPerRun > MAX_DESTINATIONS && 'text-destructive')}>
                  {draftsPerRun} draft{draftsPerRun === 1 ? '' : 's'} each run{draftsPerRun > MAX_DESTINATIONS ? ` · keep it to ${MAX_DESTINATIONS} or fewer` : ''}
                </p>
              </section>
            )}

            {step === 'review' && (
              <section id='automation-step-review' role='tabpanel' aria-label='Review' className='flex flex-col gap-5'>
                <div className='grid gap-3 sm:grid-cols-2'>
                  <Field label='Writer' htmlFor='automation-writer' hint={writer?.egress === 'cloud' ? 'The brief and the ticked sources are sent to this writer’s provider on every run.' : writer ? 'Runs without sending the brief to a cloud provider.' : undefined}>
                    <select id='automation-writer' value={route ?? ''} onChange={(e) => setRoute(e.target.value || null)} className={cn(FIELD, 'rafii-focus w-full min-w-0')}>
                      {!route && <option value=''>Choose a writer</option>}
                      {writers.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label='Cost limit per run (USD)' htmlFor='automation-cost' hint={writer?.costClass === 'paid' ? 'A run whose quote is above this limit is held, never charged.' : 'This writer has no per-run charge.'}>
                    <Input id='automation-cost' type='number' inputMode='decimal' min='0' max='10' step='0.01' value={maxCost} onChange={(e) => setMaxCost(e.target.value)} className={FIELD} />
                  </Field>
                </div>
                <div className='flex flex-col gap-2'>
                  <span className={LABEL}>Reasoning</span>
                  <SegmentedControl options={reasoningOptions} value={reasoning} onChange={setReasoning} label='Reasoning' size='sm' widths='content' className='self-start' />
                </div>
                <Surface material='quiet' radius='control' padding='sm' className='flex flex-col gap-1'>
                  <span className='rafii-eyebrow'>Budget</span>
                  <p className='text-sm'>
                    Up to <span className='font-medium'>{usd(costValid ? costMicro : 0)}</span> a run · {weekdays.length} run{weekdays.length === 1 ? '' : 's'} a week · at most <span className='font-medium'>{usd(weeklyCeilingMicro(costValid ? costMicro : 0, schedule))}</span> a week.
                  </p>
                  <p className={HINT}>Charges come from your workspace credits, the same as drafting on Home.</p>
                </Surface>
                <dl className='grid gap-x-4 gap-y-3 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]'>
                  <Summary term='What' onEdit={() => setStep('what')}>
                    <span className='font-medium'>{name || 'Unnamed'}</span>
                    <span className='text-muted-foreground line-clamp-2'>{goal || 'No brief yet'}</span>
                    <span className='text-muted-foreground'>{content ? content.label : 'General writing'} · {sourceIds.length ? `${sourceIds.length} source${sourceIds.length === 1 ? '' : 's'}` : 'brief only'}</span>
                  </Summary>
                  <Summary term='When' onEdit={() => setStep('when')}>
                    <span>{weekdays.length ? scheduleSummary(schedule) : 'No days chosen'}</span>
                    {runs[0] && <span className='text-muted-foreground'>First run after activation: {runLabel(runs[0], timeZone)}</span>}
                  </Summary>
                  <Summary term='Where' onEdit={() => setStep('where')}>
                    {targets.length ? (
                      targets.map((t) => (
                        <span key={t.key} className='inline-flex items-center gap-1.5'>
                          <ChannelIcon platform={t.platform} size='sm' />
                          {accountName(t)} · {t.languages.map((l) => languageLabel(l)).join(', ')}
                        </span>
                      ))
                    ) : (
                      <span className='text-muted-foreground'>No destinations</span>
                    )}
                  </Summary>
                </dl>
                {(blockers.length > 0 || reminders.length > 0) && (
                  <ul className='flex flex-col gap-1.5' aria-label='Before saving'>
                    {blockers.map((b) => (
                      <li key={b.text} className='flex items-start gap-2 text-sm'>
                        <Icons.alertCircle className='text-muted-foreground mt-0.5 size-4 shrink-0' />
                        <button type='button' className='rafii-focus text-left underline-offset-2 hover:underline' onClick={() => setStep(b.step)}>
                          {b.text}
                        </button>
                      </li>
                    ))}
                    {reminders.map((text) => (
                      <li key={text} className='text-muted-foreground flex items-start gap-2 text-sm'>
                        <Icons.info className='mt-0.5 size-4 shrink-0' />
                        {text}
                      </li>
                    ))}
                  </ul>
                )}
                <p className={HINT}>
                  {isOwner ? 'Activating lets Rafii prepare drafts on this schedule. Every draft still needs your review and approval before anything is published.' : 'Saving creates a draft. The workspace owner activates it before any run.'}
                  {initial.wasActive ? ' Changing anything except the name returns it to draft until the owner activates it again.' : ''}
                </p>
              </section>
            )}
            {error && (
              <p role='alert' className='text-destructive text-sm'>
                {error}
              </p>
            )}
          </RafiiDialogBody>
          <RafiiDialogFooter className='flex flex-wrap items-center justify-between gap-2'>
            <Button variant='quiet' size='control' disabled={saving} onClick={() => (stepIndex === 0 ? onOpenChange(false) : setStep(STEPS[stepIndex - 1].value))}>
              {stepIndex === 0 ? 'Cancel' : 'Back'}
            </Button>
            {step !== 'review' ? (
              <Button variant='action' size='control' onClick={() => setStep(STEPS[stepIndex + 1].value)}>
                Next
                <Icons.arrowRight />
              </Button>
            ) : (
              <span className='flex flex-wrap gap-2'>
                <Button variant={isOwner ? 'glass' : 'action'} size='control' disabled={saving || blockers.length > 0} onClick={() => void save(false)}>
                  {saving ? 'Saving…' : 'Save as draft'}
                </Button>
                {isOwner && (
                  <Button variant='action' size='control' disabled={saving || blockers.length > 0 || missing.length > 0} onClick={() => void save(true)}>
                    <Icons.bolt />
                    Save and activate
                  </Button>
                )}
              </span>
            )}
          </RafiiDialogFooter>
          {/* Nested inside the builder's popup so they stack as child dialogs (outside presses and Escape stay local). */}
          <ContentLibraryDialog open={inner === 'library'} onOpenChange={(next) => setInner(next ? 'library' : null)} value={content?.library ?? DEFAULT_LIBRARY} onApply={applyLibrary} platformsForFit={Array.from(new Set(targets.map((t) => t.platform)))} />
          <ChannelBloomDialog open={inner === 'channels'} onOpenChange={(next) => setInner(next ? 'channels' : null)} accounts={accounts} folders={folders} selected={targets.flatMap((t) => (t.channelId ? [t.channelId] : []))} context={folderContext} onCommit={(result) => commitAccounts(result.accountIds, result.context)} />
        </RafiiDialogContent>
      </RafiiDialog>
  );
}

function Field({ label, htmlFor, hint, children }: { label: string; htmlFor: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className='flex min-w-0 flex-col gap-1.5'>
      <label htmlFor={htmlFor} className={LABEL}>
        {label}
      </label>
      {children}
      {hint && <p className={HINT}>{hint}</p>}
    </div>
  );
}

function Summary({ term, onEdit, children }: { term: string; onEdit: () => void; children: React.ReactNode }) {
  return (
    <>
      <dt className='text-muted-foreground flex items-start justify-between gap-2 sm:block'>
        {term}
        <button type='button' onClick={onEdit} className='rafii-focus text-foreground text-xs underline-offset-2 hover:underline sm:hidden'>
          Edit
        </button>
      </dt>
      <dd className='flex min-w-0 flex-col gap-1'>
        {children}
        <button type='button' onClick={onEdit} className='rafii-focus text-muted-foreground hover:text-foreground hidden self-start text-xs underline-offset-2 hover:underline sm:inline'>
          Edit {term.toLowerCase()}
        </button>
      </dd>
    </>
  );
}
