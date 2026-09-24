'use client';
import { ModelPicker } from '@/features/agent/model-picker';
import { useModelChoice } from '@/features/agent/use-model';
import type { ModelCatalog } from '@/lib/api/types';
const catalog = {
  models: [
    {
      id: 'deterministic-preview',
      label: 'Deterministic preview',
      qualified: true,
      route: 'fixture',
      costClass: 'none',
      detail: 'Local preview; no model call.'
    },
    ...['default', 'fable', 'opus', 'sonnet', 'haiku'].map((alias) => ({
      id: `claude-code:${alias}`,
      label: `Claude Code · ${alias}`,
      qualified: true,
      route: 'claude-code',
      costClass: 'subscription',
      detail: 'Uses your Claude Code subscription.',
      reasoning: [
        { id: 'low', available: true, detail: 'Low' },
        { id: 'high', available: true, detail: 'High' }
      ]
    })),
    {
      id: 'codex:default',
      label: 'Codex CLI · default',
      qualified: true,
      route: 'codex',
      costClass: 'subscription',
      detail: 'Uses your Codex subscription.'
    },
    {
      id: 'gemini:test',
      label: 'Gemini CLI · test',
      qualified: false,
      route: 'gemini-cli',
      detail: 'Test fixture: not connected.'
    }
  ]
} as ModelCatalog;
export default function Check() {
  const choice = useModelChoice(catalog);
  return (
    <main className='bg-background text-foreground min-h-screen p-6'>
      <h1 className='mb-8'>Model selector · synthetic catalog</h1>
      <ModelPicker
        options={choice.options}
        model={choice.model}
        onChoose={choice.choose}
        reasoning={choice.reasoning}
        reasoningOptions={choice.reasoningOptions}
        onReasoning={choice.chooseReasoning}
      />
      <output aria-label='Selected model'>{choice.model}</output>
      <output aria-label='Selected effort'>{choice.reasoning}</output>
    </main>
  );
}
