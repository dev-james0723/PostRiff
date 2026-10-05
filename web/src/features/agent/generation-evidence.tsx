'use client';

import type { GenerationProvenance } from '@/lib/api/types';
import { memoryFileLabel } from '@/features/memory/memory-files';

/** Frozen application input for this run; never reconstructed from today's workspace badges. */
export function GenerationEvidence({ evidence }: { evidence?: GenerationProvenance | null }) {
  if (!evidence) return <p className='text-muted-foreground text-xs'>This older draft has no detailed generation record.</p>;
  const files = evidence.memory.files.filter((file) => file.used);
  const facts = evidence.sources.flatMap((source) => source.facts);
  return (
    <details className='rafii-quiet mt-3 rounded-lg p-3 text-xs'>
      <summary className='rafii-focus cursor-pointer font-medium'>Why this draft</summary>
      <div className='text-muted-foreground mt-3 space-y-2 leading-relaxed'>
        <p>{evidence.execution === 'fixture' ? 'Local fixture: these inputs were prepared; no model was called.' : `Inputs sent to ${evidence.model}.`}</p>
        <p>Voice: {evidence.profile.used ? `${evidence.profile.kind === 'sample_derived' ? 'sample-derived voice' : 'approved owner direction'}, revision ${evidence.voiceRevision}` : evidence.voiceMode === 'neutral' ? 'neutral for this draft' : 'no eligible active voice'}.</p>
        <p>{evidence.voiceBindings.length} eligible writing sample{evidence.voiceBindings.length === 1 ? '' : 's'} included. {facts.length} source statement{facts.length === 1 ? '' : 's'} approved for use and included.</p>
        <p>Memory included: {files.length ? files.map((file) => `${memoryFileLabel(file.name)}${file.truncated ? ' (partly included)' : ''}`).join(', ') : 'none'}.</p>
        {evidence.execution === 'cloud_model' && !evidence.memory.shared && <p>Cloud memory sharing was off for this draft.</p>}
        {evidence.preferences.length > 0 && (
          <ul className='list-disc space-y-1 pl-4'>
            {evidence.preferences.map((preference) => (
              <li key={preference.id}>
                {preference.statement} — {['deterministic', 'model'].includes(preference.source ?? '') ? 'inferred from saved edits and approved' : preference.source === 'chat' ? 'explicit instruction, approved' : 'reviewed saved preference'}
                {' · '}{Object.values(preference.scope).filter(Boolean).join(' / ') || 'all matching drafts'}
              </li>
            ))}
          </ul>
        )}
        <p>Scope: {evidence.destinations.map((d) => `${d.platform}/${d.language}`).join(', ')}{evidence.campaignId ? ' · campaign scoped' : ''}{evidence.contentTypeId ? ` · ${evidence.contentTypeId}` : ''}.</p>
        {evidence.excludedSources.length > 0 && <p>Sources left out: {evidence.excludedSources.map((source) => source.reason.replaceAll('_', ' ')).join(', ')}.</p>}
        {evidence.memory.omittedPreferenceIds.length > 0 && <p>{evidence.memory.omittedPreferenceIds.length} saved preference{evidence.memory.omittedPreferenceIds.length === 1 ? '' : 's'} did not enter this draft.</p>}
        {facts.length > 0 && <p>Source locations: {facts.map((fact) => fact.locator || 'location unavailable').join(', ')}.</p>}
        <p>This records application inputs. It does not attest to a provider’s hidden upstream request or prove that the model followed every input.</p>
      </div>
    </details>
  );
}
