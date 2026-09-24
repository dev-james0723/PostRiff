'use client';

import { useState } from 'react';
import { ModelDialog } from '@/features/agent/model-dialog';
import { ModelPicker } from '@/features/agent/model-picker';
import { SettingButtons } from '@/features/agent/setting-buttons';
import { useModelChoice } from '@/features/agent/use-model';
import { useModels } from '@/lib/api/hooks';
import { AuthProvider } from '@/lib/auth/session';
import { WorkspaceProvider } from '@/lib/workspace/provider';

/** The real catalog (`useModels`) needs the session and workspace providers the app shell mounts. */
export function ModelDialogPlayground() {
  return (
    <AuthProvider>
      <WorkspaceProvider>
        <Inner />
      </WorkspaceProvider>
    </AuthProvider>
  );
}

function Inner() {
  const models = useModels();
  const choice = useModelChoice(models.data);
  const [open, setOpen] = useState(false);
  return (
    <main className='bg-background text-foreground mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-6 px-4 py-8'>
      <header>
        <p className='rafii-eyebrow'>Dev · Rafii v9 stream C</p>
        <h1 className='mt-1 text-2xl font-medium tracking-tight'>Model and reasoning dialog</h1>
        <p className='text-muted-foreground mt-1 text-sm'>Real catalog from the API host. Browsing never changes the committed model; “Use this model” does.</p>
      </header>
      <SettingButtons
        language={{ value: 'English (US)', onClick: () => {}, disabled: true }}
        model={{ value: models.isLoading ? 'Loading…' : models.isError ? 'Model list unavailable' : choice.label, onClick: () => setOpen(true), expanded: open, controls: 'dev-model-dialog' }}
        voice={{ value: 'Neutral', onClick: () => {}, popup: 'none', pressed: false, disabled: true }}
      />
      <ModelDialog
        id='dev-model-dialog'
        open={open}
        onOpenChange={setOpen}
        catalog={models.data}
        value={{ model: choice.model, reasoning: choice.reasoningFor(choice.model) ?? choice.reasoning }}
        reasoningFor={choice.reasoningFor}
        onApply={({ model, reasoning }) => {
          choice.choose(model);
          choice.setReasoningFor(model, reasoning);
        }}
      />
      <section className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-card)] p-4 text-sm'>
        <h2 className='mb-1 font-medium'>Committed choice</h2>
        <p>
          Model: <output aria-label='Selected model' className='font-mono text-xs'>{choice.model}</output>
        </p>
        <p>
          Sent as reasoning: <output aria-label='Selected effort' className='font-mono text-xs'>{choice.reasoning}</output>
        </p>
        <p>
          Preference: <output aria-label='Reasoning preference' className='font-mono text-xs'>{choice.reasoningFor(choice.model) ?? '(provider default)'}</output>
        </p>
        <p className='text-muted-foreground text-xs'>{choice.reasoningMapping.summary}</p>
      </section>
      <section className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4 text-sm'>
        <h2 className='font-medium'>Restyled compact selector (existing composer control)</h2>
        <div>
          <ModelPicker options={choice.options} model={choice.model} onChoose={choice.choose} reasoning={choice.reasoning} reasoningOptions={choice.reasoningOptions} onReasoning={choice.chooseReasoning} />
        </div>
      </section>
    </main>
  );
}
