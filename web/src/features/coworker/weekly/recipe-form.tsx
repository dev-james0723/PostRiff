'use client';

import { useId, useMemo, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Band, FIELD_CLASS, Panel, SelectField, TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { useChannels, useModels } from '@/lib/api/hooks';
import { errorMessage } from '@/lib/coworker/api';
import { useRecipeStatus, useSaveRecipe } from '@/lib/coworker/hooks';
import type { Recipe, RecipeInput } from '@/lib/coworker/types';
import { languageLabel } from '@/lib/locales';
import { cn } from '@/lib/utils';
import { WEEKDAYS } from '../present';

/** The content the week can mix. Personal kinds ask you a short question before Rafii writes them. */
const MIX: { key: string; label: string; asks?: boolean }[] = [
  { key: 'tutorial_how_to', label: 'How-to' },
  { key: 'deep_point_of_view', label: 'Point of view' },
  { key: 'building_in_public', label: 'Building in public' },
  { key: 'behind_the_scenes', label: 'Behind the scenes', asks: true },
  { key: 'personal_reflection', label: 'Personal reflection', asks: true },
  { key: 'music_performance_teaching', label: 'Music, performance or teaching', asks: true }
];
const WEIGHTS = [
  { value: 0, label: 'None' },
  { value: 1, label: 'Some' },
  { value: 2, label: 'More' }
];
const LANGUAGES = ['en', 'en-GB', 'en-US', 'zh-Hant-HK', 'zh-Hant', 'zh-Hans', 'yue', 'ja', 'ko', 'fr', 'de', 'es'];

function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function zones(current: string): string[] {
  let list: string[] = [];
  try {
    list = Intl.supportedValuesOf('timeZone');
  } catch {
    list = [];
  }
  return Array.from(new Set([current, 'UTC', ...list]));
}

interface Destination {
  channelId: string;
  on: boolean;
  postsPerWeek: number;
  language: string;
}

function initial(recipe: Recipe | null, channelIds: string[]) {
  const destinations: Record<string, Destination> = {};
  for (const id of channelIds) destinations[id] = { channelId: id, on: false, postsPerWeek: 3, language: 'en' };
  for (const d of recipe?.destinations ?? []) destinations[d.channelId] = { channelId: d.channelId, on: true, postsPerWeek: d.postsPerWeek, language: d.language || 'en' };
  const mix: Record<string, number> = recipe ? { ...recipe.contentMix } : { tutorial_how_to: 1, deep_point_of_view: 1, building_in_public: 1 };
  return {
    name: recipe?.name ?? 'My week',
    goals: (recipe?.goals ?? []).join('\n'),
    destinations,
    mix,
    planningDay: recipe?.planningDay ?? 4,
    planningHour: recipe?.planningHour ?? 9,
    timeZone: recipe?.timeZone ?? browserZone(),
    voiceMode: recipe?.voiceMode ?? 'neutral',
    expectImages: recipe?.expectImages ?? false,
    budgetUsd: String(((recipe?.maxCostUsdMicroPerWeek ?? 2_000_000) / 1_000_000).toFixed(2)),
    model: recipe?.model ?? ''
  };
}

/**
 * The weekly recipe (owner only on the server): which accounts, how often, what for, when Rafii plans, and the
 * most it may spend on drafting per week. Saving a recipe drafts nothing; preparing a week does.
 */
export function RecipeForm({ recipe, isOwner, onSaved }: { recipe: Recipe | null; isOwner: boolean; onSaved?: (recipe: Recipe) => void }) {
  const channels = useChannels();
  const models = useModels();
  const save = useSaveRecipe();
  const status = useRecipeStatus();
  const list = useMemo(() => channels.data?.channels ?? [], [channels.data]);
  const [form, setForm] = useState(() => initial(recipe, list.map((c) => c.id)));
  const [error, setError] = useState<string | null>(null);
  const uid = useId();
  const writers = (models.data?.models ?? []).filter((m) => m.qualified);
  const zoneList = useMemo(() => zones(form.timeZone), [form.timeZone]);

  // Accounts that arrived after the form opened join it unchecked.
  const destinations = list.map((c) => form.destinations[c.id] ?? { channelId: c.id, on: false, postsPerWeek: 3, language: 'en' });
  const chosen = destinations.filter((d) => d.on && d.postsPerWeek > 0);
  const total = chosen.reduce((sum, d) => sum + d.postsPerWeek, 0);

  function setDestination(id: string, change: Partial<Destination>) {
    setForm((f) => ({ ...f, destinations: { ...f.destinations, [id]: { ...(f.destinations[id] ?? { channelId: id, on: false, postsPerWeek: 3, language: 'en' }), ...change } } }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const goals = form.goals.split('\n').map((g) => g.trim()).filter(Boolean).slice(0, 5);
    const budget = Number.parseFloat(form.budgetUsd);
    if (!goals.length) return setError('Give the week at least one goal.');
    if (!chosen.length) return setError('Choose at least one account and how often to post.');
    if (total > 28) return setError('A week plans at most 28 posts.');
    if (!Number.isFinite(budget) || budget < 0 || budget > 50) return setError('The weekly limit is between $0 and $50.');
    const values: RecipeInput = {
      name: form.name.trim() || 'My week',
      goals,
      destinations: chosen.map((d) => ({ channelId: d.channelId, postsPerWeek: d.postsPerWeek, language: d.language })),
      contentMix: Object.fromEntries(Object.entries(form.mix).filter(([, weight]) => weight > 0)),
      planningDay: form.planningDay,
      planningHour: form.planningHour,
      timeZone: form.timeZone,
      voiceMode: form.voiceMode,
      expectImages: form.expectImages,
      useResearch: recipe?.useResearch ?? false,
      maxCostUsdMicroPerWeek: Math.round(budget * 1_000_000),
      model: form.model || null
    };
    try {
      const result = await save.mutateAsync({ recipeId: recipe?.id, values });
      if (!result.verified || !result.recipe) {
        toast.warning('Rafii could not confirm the plan was saved. Refresh to see what is stored.');
        return;
      }
      toast.success(recipe ? 'Weekly plan updated. Nothing was drafted.' : 'Weekly plan saved. Prepare a week when you are ready; nothing is drafted yet.');
      onSaved?.(result.recipe);
    } catch (err) {
      setError(errorMessage(err, 'The plan could not be saved.'));
    }
  }

  async function setRecipeStatus(next: 'active' | 'paused') {
    if (!recipe) return;
    try {
      const result = await status.mutateAsync({ recipeId: recipe.id, status: next });
      if (!result.verified) toast.warning('Rafii could not confirm the change. Refresh to see the current state.');
      else toast.success(next === 'paused' ? 'Paused. Rafii will not plan new weeks until you resume.' : 'Resumed.');
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  if (!isOwner) {
    return (
      <Panel title='Weekly plan' titleId='recipe-heading' description='Only an owner can change the weekly plan, because it authorises paid drafting every week.'>
        {recipe ? <RecipeSummary recipe={recipe} /> : <StateMessage kind='permission' title='No weekly plan yet.' description='Ask an owner to set one up.' />}
      </Panel>
    );
  }

  if (!channels.isPending && list.length === 0) {
    return (
      <Panel title='Weekly plan' titleId='recipe-heading'>
        <StateMessage
          kind='empty'
          title='Connect an account first.'
          description='The weekly plan drafts for accounts you have connected.'
          action={
            <Link href='/app/channels' className={buttonVariants({ variant: 'action', size: 'control' })}>
              Open Channels
            </Link>
          }
        />
      </Panel>
    );
  }

  return (
    <Panel
      title={recipe ? 'Weekly plan' : 'Set up your week'}
      titleId='recipe-heading'
      description='What a normal week looks like. Rafii plans and drafts from this; you review every post, and nothing is scheduled until it is approved in Queue.'
      actions={
        recipe && (
          <Button variant='glass' size='control' disabled={status.isPending} onClick={() => void setRecipeStatus(recipe.status === 'paused' ? 'active' : 'paused')}>
            {recipe.status === 'paused' ? 'Resume weekly plan' : 'Pause weekly plan'}
          </Button>
        )
      }
    >
      <form onSubmit={(event) => void submit(event)} className='flex flex-col gap-5' aria-describedby={error ? 'recipe-error' : undefined} noValidate>
        <div className='flex flex-col gap-2 text-sm'>
          <label htmlFor={`${uid}-name`} className='text-foreground font-medium'>
            Name
          </label>
          <Input id={`${uid}-name`} value={form.name} maxLength={80} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} className={FIELD_CLASS} />
        </div>

        <div className='flex flex-col gap-2 text-sm'>
          <label htmlFor={`${uid}-goals`} className='text-foreground font-medium'>
            Goals
          </label>
          <span id={`${uid}-goals-hint`} className='text-muted-foreground text-xs'>
            One per line, up to five. Each post serves one goal.
          </span>
          <Textarea id={`${uid}-goals`} aria-describedby={`${uid}-goals-hint`} value={form.goals} rows={3} onChange={(e) => setForm((f) => ({ ...f, goals: e.target.value }))} placeholder={'Fill the autumn workshop\nShow how we make things by hand'} className={TEXTAREA_CLASS} />
        </div>

        <fieldset className='flex flex-col gap-2'>
          <legend className='text-foreground mb-2 text-sm font-medium'>Accounts and posts per week</legend>
          {channels.isPending && <StateMessage kind='loading' layout='inline' title='Loading accounts…' />}
          <ul className='flex flex-col gap-2'>
            {list.map((channel, index) => {
              const d = destinations[index];
              const label = `${channel.platform} · ${channel.account}`;
              return (
                <Band as='li' key={channel.id} className='gap-3 sm:flex-row sm:items-center sm:justify-between'>
                  <Label className='flex min-h-11 min-w-0 items-center gap-3 text-sm font-normal'>
                    <Checkbox checked={d.on} onCheckedChange={(checked) => setDestination(channel.id, { on: checked === true })} aria-label={`Include ${label}`} />
                    <span className='min-w-0'>
                      <span className='text-foreground block font-medium'>{channel.platform}</span>
                      <span className='text-muted-foreground block truncate text-xs'>{channel.account}</span>
                    </span>
                  </Label>
                  <div className={cn('grid grid-cols-2 gap-2 sm:w-80', !d.on && 'opacity-60')}>
                    <SelectField label={`Posts per week for ${label}`} hideLabel value={String(d.postsPerWeek)} disabled={!d.on} onChange={(e) => setDestination(channel.id, { postsPerWeek: Number(e.target.value) })}>
                      {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                        <option key={n} value={n}>
                          {n} a week
                        </option>
                      ))}
                    </SelectField>
                    <SelectField label={`Language for ${label}`} hideLabel value={d.language} disabled={!d.on} onChange={(e) => setDestination(channel.id, { language: e.target.value })}>
                      {Array.from(new Set([d.language, ...LANGUAGES])).map((tag) => (
                        <option key={tag} value={tag}>
                          {languageLabel(tag) || tag}
                        </option>
                      ))}
                    </SelectField>
                  </div>
                </Band>
              );
            })}
          </ul>
          <p className='text-muted-foreground text-xs' aria-live='polite'>
            {total} post{total === 1 ? '' : 's'} a week across {chosen.length} account{chosen.length === 1 ? '' : 's'}.
          </p>
        </fieldset>

        <fieldset className='flex flex-col gap-2'>
          <legend className='text-foreground mb-2 text-sm font-medium'>Content mix</legend>
          <div className='grid gap-2 sm:grid-cols-2'>
            {MIX.map((item) => (
              <SelectField
                key={item.key}
                label={
                  <>
                    {item.label}
                    {item.asks && <span className='text-muted-foreground font-normal'> · asks you first</span>}
                  </>
                }
                value={String(form.mix[item.key] ?? 0)}
                onChange={(e) => setForm((f) => ({ ...f, mix: { ...f.mix, [item.key]: Number(e.target.value) } }))}
              >
                {WEIGHTS.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </SelectField>
            ))}
          </div>
        </fieldset>

        <div className='grid gap-3 sm:grid-cols-3'>
          <SelectField label='Planning day' value={String(form.planningDay)} onChange={(e) => setForm((f) => ({ ...f, planningDay: Number(e.target.value) }))}>
            {WEEKDAYS.map((day, index) => (
              <option key={day} value={index}>
                {day}
              </option>
            ))}
          </SelectField>
          <SelectField label='Planning time' value={String(form.planningHour)} onChange={(e) => setForm((f) => ({ ...f, planningHour: Number(e.target.value) }))}>
            {Array.from({ length: 24 }, (_, hour) => (
              <option key={hour} value={hour}>
                {String(hour).padStart(2, '0')}:00
              </option>
            ))}
          </SelectField>
          <SelectField label='Time zone' value={form.timeZone} onChange={(e) => setForm((f) => ({ ...f, timeZone: e.target.value }))}>
            {zoneList.map((zone) => (
              <option key={zone} value={zone}>
                {zone.replace(/_/g, ' ')}
              </option>
            ))}
          </SelectField>
        </div>

        <div className='grid gap-3 sm:grid-cols-2'>
          <div className='flex flex-col gap-2 text-sm'>
            <label htmlFor={`${uid}-budget`} className='text-foreground font-medium'>
              Weekly drafting limit (USD)
            </label>
            <Input id={`${uid}-budget`} inputMode='decimal' value={form.budgetUsd} onChange={(e) => setForm((f) => ({ ...f, budgetUsd: e.target.value }))} className={FIELD_CLASS} aria-describedby='budget-hint' />
            <span id='budget-hint' className='text-muted-foreground text-xs'>
              Drafting stops at this amount; the rest of the week asks you instead. $0–$50.
            </span>
          </div>
          <SelectField label='Writing model' value={form.model} onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))}>
            <option value=''>Workspace default</option>
            {writers.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </SelectField>
        </div>

        <div className='flex flex-col gap-2'>
          <Label className='flex min-h-11 items-center justify-between gap-4 text-sm font-normal'>
            <span className='flex flex-col gap-0.5'>
              <span className='text-foreground font-medium'>Write in my voice</span>
              <span className='text-muted-foreground text-xs'>Uses your approved voice notes and samples. Off writes in a neutral voice.</span>
            </span>
            <Switch checked={form.voiceMode === 'personalized'} onCheckedChange={(on) => setForm((f) => ({ ...f, voiceMode: on ? 'personalized' : 'neutral' }))} aria-label='Write in my voice' />
          </Label>
          <Label className='flex min-h-11 items-center justify-between gap-4 text-sm font-normal'>
            <span className='flex flex-col gap-0.5'>
              <span className='text-foreground font-medium'>Plan images for visual platforms</span>
              <span className='text-muted-foreground text-xs'>Instagram, TikTok, Pinterest, YouTube and Xiaohongshu posts get a creative brief.</span>
            </span>
            <Switch checked={form.expectImages} onCheckedChange={(on) => setForm((f) => ({ ...f, expectImages: on }))} aria-label='Plan images for visual platforms' />
          </Label>
        </div>

        {error && (
          <p id='recipe-error' role='alert' className='text-foreground rafii-quiet rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
            {error}
          </p>
        )}
        <div className='flex flex-wrap gap-2'>
          <Button type='submit' variant='action' size='control' disabled={save.isPending}>
            {save.isPending ? 'Saving…' : recipe ? 'Save changes' : 'Save weekly plan'}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

export function RecipeSummary({ recipe }: { recipe: Recipe }) {
  const total = recipe.destinations.reduce((sum, d) => sum + d.postsPerWeek, 0);
  return (
    <dl className='grid gap-3 text-sm sm:grid-cols-2'>
      <div>
        <dt className='text-muted-foreground text-xs'>Goals</dt>
        <dd className='text-foreground'>{recipe.goals.join(' · ')}</dd>
      </div>
      <div>
        <dt className='text-muted-foreground text-xs'>Accounts</dt>
        <dd className='text-foreground'>
          {recipe.destinations.map((d) => `${d.platform ?? 'Account'} ${d.account ? `(${d.account})` : ''} ×${d.postsPerWeek}`).join(', ')} · {total} a week
        </dd>
      </div>
      <div>
        <dt className='text-muted-foreground text-xs'>Planning</dt>
        <dd className='text-foreground'>
          {WEEKDAYS[recipe.planningDay] ?? 'Friday'} {String(recipe.planningHour).padStart(2, '0')}:00 · {recipe.timeZone}
        </dd>
      </div>
      <div>
        <dt className='text-muted-foreground text-xs'>Weekly drafting limit</dt>
        <dd className='text-foreground'>${(recipe.maxCostUsdMicroPerWeek / 1_000_000).toFixed(2)}</dd>
      </div>
    </dl>
  );
}
