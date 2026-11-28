'use client';

import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { CreativePlan, CreativeScene, CreativeSettings, IntelligenceLevel } from '@/lib/api/creative-video';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { formatCredits, parseCreditLimit, videoLevels } from './intelligence';

export function ProjectPlan({ id, revision, scenes, localOnly, overrides, disabled, onScene }: {
  id: string; revision: number; scenes: CreativeScene[]; localOnly: boolean; overrides: Record<string, CreativeSettings>;
  disabled: boolean; onScene: (id: string) => void;
}) {
  const { workspaceId, api } = useWorkspaceApi();
  const [open, setOpen] = useState(false);
  const [level, setLevel] = useState<IntelligenceLevel>(localOnly ? 'draft' : 'balanced');
  const [mode, setMode] = useState<'hybrid' | 'auto' | 'budget'>('hybrid');
  const [limit, setLimit] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [read, setRead] = useState<{ key: string; plan?: CreativePlan; error?: string } | null>(null);
  const cap = parseCreditLimit(limit);
  const issue = limit.trim() && cap == null ? 'Use up to three decimal places.' :
    !localOnly && mode === 'budget' && cap == null ? 'Enter a maximum for all unproduced scenes.' : '';
  const body = useMemo(() => {
    const settings: CreativeSettings = localOnly ? { mode: 'manual', model: 'storyboard-v1', level: 'draft' } : { level, mode };
    if (cap != null) settings.maxMilliCredits = cap;
    return { revision, settings, ...(!localOnly && mode === 'hybrid' && Object.keys(overrides).length ? { sceneSettings: overrides } : {}) };
  }, [localOnly, level, mode, cap, revision, overrides]);
  const key = JSON.stringify([body, refresh, scenes.map(s => [s.clipId, s.generation?.state])]);
  useEffect(() => {
    if (!open || disabled || issue) return;
    let active = true;
    const timer = setTimeout(() => {
      api.creativeVideoPlan(workspaceId, id, body).then(plan => { if (active) setRead({ key, plan }); }, error => {
        if (active) setRead({ key, error: error instanceof Error ? error.message : 'The project estimate could not be loaded.' });
      });
    }, 220);
    return () => { active = false; clearTimeout(timer); };
  }, [api, workspaceId, id, body, key, open, disabled, issue]);
  const current = read?.key === key ? read : null;
  return <details className='border-t pt-3 text-sm' onToggle={e => setOpen(e.currentTarget.open)}>
    <summary className='rafii-focus cursor-pointer rounded-sm py-1 font-medium'>Project credit estimate</summary>
    {open && <div className='mt-3 grid min-w-0 gap-3'>
      <p className='text-xs text-muted-foreground'>Estimate additional production for this timeline. Each take is authorized separately.</p>
      {!localOnly && <fieldset disabled={disabled} className='grid gap-3'>
        <div className='grid gap-1.5'>
          <Label htmlFor='plan-level'>Starting intelligence level</Label>
          <NativeSelect id='plan-level' value={level} className='w-full [&_select]:min-h-11' onChange={e => setLevel(e.target.value as IntelligenceLevel)}>
            {videoLevels.map(item => <NativeSelectOption key={item.id} value={item.id}>{item.label}</NativeSelectOption>)}
          </NativeSelect>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='plan-mode'>Planning strategy</Label>
          <NativeSelect id='plan-mode' value={mode} className='w-full [&_select]:min-h-11' onChange={e => setMode(e.target.value as typeof mode)}>
            <NativeSelectOption value='hybrid'>Use each scene’s settings</NativeSelectOption>
            <NativeSelectOption value='auto'>Automatic across all scenes</NativeSelectOption>
            <NativeSelectOption value='budget'>Fit a project budget</NativeSelectOption>
          </NativeSelect>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='plan-budget'>Budget for this estimate (AI Credits)</Label>
          <Input id='plan-budget' inputMode='decimal' maxLength={16} value={limit} placeholder='Optional limit' onChange={e => setLimit(e.target.value)} />
        </div>
      </fieldset>}
      {localOnly && <p>Free storyboard plan</p>}
      <div aria-live='polite' className='grid gap-2'>
        {disabled ? <p>Save current edits to update this plan.</p> : issue ? <p>{issue}</p> : !current ? <p>Estimating missing scenes…</p> :
          current.error ? <p>{current.error}</p> : current.plan && <>
            <p className='font-medium'>{current.plan.totalMilliCredits == null ? 'Total unavailable' : `${formatCredits(current.plan.totalMilliCredits)} estimated AI Credits`}</p>
            {current.plan.unpricedScenes > 0 && <p>{current.plan.unpricedScenes} {current.plan.unpricedScenes === 1 ? 'scene needs' : 'scenes need'} a supported route.</p>}
            <ul className='grid gap-1'>{current.plan.scenes.map(row => <li key={row.sceneId}>
              <Button variant='quiet' className='h-auto min-h-11 w-full justify-start whitespace-normal px-2 py-1.5 text-left'
                onClick={() => onScene(row.sceneId)}>
                <span className='grid gap-0.5'>
                  <span>{scenes.find(s => s.sceneId === row.sceneId)?.purpose ?? row.sceneId}</span>
                  <span className='text-xs font-normal text-muted-foreground'>{row.label}
                    {row.estimatedMilliCredits != null ? ` · ${formatCredits(row.estimatedMilliCredits)} credits` : ''}{row.reason ? ` · ${row.reason}` : ''}
                  </span>
                </span>
              </Button>
            </li>)}</ul>
          </>}
      </div>
      {current?.error && <Button variant='quiet' size='sm' onClick={() => setRefresh(v => v + 1)}>Refresh project estimate</Button>}
    </div>}
  </details>;
}
