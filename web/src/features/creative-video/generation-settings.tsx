'use client';

import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { CreativeModel, CreativeSettings } from '@/lib/api/creative-video';
import { directionControls } from './intelligence';

function Choice<T extends string>({ id, label, value, options, onChange }: {
  id: string; label: string; value: T; options: readonly (readonly [T, string])[]; onChange: (value: T) => void;
}) {
  return <div className='grid min-w-0 content-start gap-1.5'>
    <Label htmlFor={id}>{label}</Label>
    <NativeSelect id={id} value={value} className='w-full [&_select]:min-h-11' onChange={e => {
      const choice = options.find(([key]) => key === e.target.value);
      if (choice) onChange(choice[0]);
    }}>
      {options.map(([key, name]) => <NativeSelectOption key={key} value={key}>{name}</NativeSelectOption>)}
    </NativeSelect>
  </div>;
}

export function GenerationSettings({ settings, onChange, limit, onLimit, models, hasReference, disabled }: {
  settings: CreativeSettings; onChange: (settings: CreativeSettings) => void; limit: string; onLimit: (value: string) => void;
  models: CreativeModel[]; hasReference: boolean; disabled: boolean;
}) {
  function change(patch: Partial<CreativeSettings>) { onChange({ ...settings, ...patch }); }
  const manualModel = settings.mode === 'manual' ? models.find(item => item.id === settings.model) : undefined;
  return <details className='rounded-xl border px-4'>
    <summary className='rafii-focus cursor-pointer rounded-sm py-3 text-sm font-medium'>Advanced settings</summary>
    <fieldset disabled={disabled} className='grid min-w-0 gap-4 pb-4'>
      <div className='grid min-w-0 gap-4 sm:grid-cols-2'>
        <Choice id='scene-routing' label='Model selection' value={settings.mode}
          options={[[ 'auto', 'Automatic' ], [ 'manual', 'Choose a model' ], [ 'budget', 'Fit a credit budget' ], [ 'hybrid', 'Match each scene' ]]}
          onChange={mode => { const { model: _previousModel, ...rest } = settings; onChange(mode === 'manual' ? { ...rest, mode, model: '' } : { ...rest, mode }); }} />
        <div className='grid min-w-0 content-start gap-1.5'>
          <Label htmlFor='generation-budget'>Maximum AI Credits</Label>
          <Input id='generation-budget' inputMode='decimal' type='text' maxLength={16} value={limit} placeholder={settings.mode === 'budget' ? 'Enter a limit' : 'Use this estimate'}
            onChange={e => onLimit(e.target.value)} />
        </div>
      </div>
      {settings.mode === 'manual' && <div className='grid min-w-0 gap-1.5'>
        <Label htmlFor='generation-model'>Model for this scene</Label>
        <NativeSelect id='generation-model' value={settings.model ?? ''} className='w-full [&_select]:min-h-11'
          onChange={e => change({ model: e.target.value })}>
          <NativeSelectOption value=''>Choose a model</NativeSelectOption>
          {models.map(item => <NativeSelectOption key={item.id} value={item.id} disabled={!item.available}>
            {item.label}{item.available ? '' : ' · unavailable'}
          </NativeSelectOption>)}
        </NativeSelect>
        {manualModel && <p className='text-xs text-muted-foreground'>{manualModel.aspectRatios.join(' / ')} · {manualModel.resolutions.join(' / ')}</p>}
      </div>}
      <div className='grid min-w-0 gap-4 sm:grid-cols-2'>
        <Choice id='scene-resolution' label='Native resolution' value={settings.resolution ?? 'auto'}
          options={[[ 'auto', 'Match intelligence level' ], [ '720p', '720p' ], [ '1080p', '1080p' ]]}
          onChange={resolution => change({ resolution: resolution === 'auto' ? undefined : resolution })} />
        <Choice id='scene-audio' label='Audio' value={settings.audio ?? 'auto'}
          options={[[ 'auto', 'Match the model' ], [ 'generated', 'Generated with the clip' ], [ 'silent', 'Silent clip' ]]} onChange={audio => change({ audio })} />
        <Choice id='scene-speed' label='Generation speed' value={settings.speed ?? 'standard'}
          options={[[ 'standard', 'Standard' ], [ 'fast', 'Favor fast routes' ]]} onChange={speed => change({ speed })} />
        <Choice id='scene-reliability' label='Output validation' value={settings.reliability ?? 'standard'}
          options={[[ 'standard', 'Standard checks' ], [ 'strict', 'Strict checks' ]]} onChange={reliability => change({ reliability })} />
      </div>
      <details className='border-t pt-2 text-sm'>
        <summary className='rafii-focus cursor-pointer rounded-sm py-2 font-medium'>Creative direction</summary>
        <p className='mb-3 text-xs text-muted-foreground'>These priorities guide the shot instructions. Confirm visual accuracy when reviewing the result.</p>
        <div className='grid min-w-0 gap-4 sm:grid-cols-2'>
          {directionControls.filter(([key]) => key !== 'referenceAdherence' || hasReference).map(([key, label]) =>
            <Choice key={key} id={`direction-${key}`} label={label} value={settings[key] ?? 'standard'}
              options={[[ 'low', 'Low' ], [ 'standard', 'Standard' ], [ 'high', 'High' ]]}
              onChange={value => change({ [key]: value })} />)}
        </div>
      </details>
    </fieldset>
  </details>;
}
