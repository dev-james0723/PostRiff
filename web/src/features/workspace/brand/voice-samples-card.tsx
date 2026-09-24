'use client';

import { useId, useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Band, FIELD_CLASS, Panel, SelectField, StatusChip, TEXTAREA_CLASS } from '@/features/workspace/rafii-parts';
import { ApiError } from '@/lib/api/client';
import { useAct, useModels } from '@/lib/api/hooks';
import type { SnapshotSource, SnapshotState } from '@/lib/api/types';
import { OwnedPostsPicker } from './owned-posts-picker';

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : 'The writing sample could not be updated.';
}

function VoiceSampleRow({ source, revision, isOwner, analysisRoute }: { source: SnapshotSource; revision: number; isOwner: boolean; analysisRoute?: string }) {
  const act = useAct();
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const models = useModels();
  const [writerRoute, setWriterRoute] = useState('');
  const writers = models.data?.models.filter((model) => model.qualified && model.voiceRoute) ?? [];

  async function update(action: string, payload: Record<string, unknown>) {
    try {
      await act.mutateAsync({ revision, action, payload: { sourceId: source.id, ...payload } });
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  const allowed = source.purposeGrants?.length || source.routeGrants?.length;
  const aiAllowed = source.useGrants?.some((grant) => grant.purpose === 'analysis' && grant.route === analysisRoute);
  return (
    <Band as='li' className='gap-3'>
      <div className='flex min-w-0 items-start justify-between gap-3'>
        <div className='min-w-0'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='text-foreground font-medium'>{source.title || 'Writing sample'}</span>
            <StatusChip icon={source.selected ? 'check' : 'circle'}>{source.selected ? 'Selected' : 'Not selected'}</StatusChip>
            {source.label && <StatusChip icon={null}>{source.label.replace('_', ' ')}</StatusChip>}
            <StatusChip icon={source.voiceOrigin === 'official_api' ? 'badgeCheck' : 'edit'}>{source.voiceOrigin === 'official_api' ? 'Official account import' : 'User-provided text'}</StatusChip>
          </div>
          <p className='text-muted-foreground mt-1 text-xs'>
            {[source.platform, source.account, source.language, source.publishedAt].filter(Boolean).join(' · ') || 'Manual sample'} · revision {source.revision ?? 1}
          </p>
        </div>
        <Checkbox aria-label={`Select ${source.title || 'writing sample'}`} checked={source.selected === true} disabled={act.isPending || !source.active} onCheckedChange={(checked) => void update('voice_sample_select', { selected: checked === true })} />
      </div>
      <p className='text-foreground text-sm whitespace-pre-wrap'>{source.text}</p>
      <p className='text-muted-foreground text-xs'>{allowed ? `Allowed for ${(source.purposeGrants ?? []).join(' and ')} via ${(source.routeGrants ?? []).join(', ')}.` : 'Retained only. It is not allowed for analysis or drafting yet.'}</p>
      <div className='flex flex-wrap gap-2'>
        {isOwner && source.active && (
          <Button
            size='default'
            variant='glass'
            disabled={act.isPending}
            onClick={() => void update('voice_sample_grant', { grants: [...(source.useGrants ?? []).filter((grant) => !(grant.purpose === 'analysis' && grant.route === 'local-rules')), { purpose: 'analysis', route: 'local-rules' }], confirmed: true })}
          >
            Allow local analysis
          </Button>
        )}
        {isOwner && source.active && analysisRoute && (
          <Button
            size='default'
            variant='glass'
            disabled={act.isPending || aiAllowed}
            onClick={() => void update('voice_sample_grant', { grants: [...(source.useGrants ?? []).filter((grant) => !(grant.purpose === 'analysis' && grant.route === analysisRoute)), { purpose: 'analysis', route: analysisRoute }], confirmed: true })}
          >
            {aiAllowed ? 'Selected AI model allowed' : 'Allow selected AI model to analyse this text'}
          </Button>
        )}
        <Button size='default' variant='quiet' disabled={act.isPending || !source.active} onClick={() => void update('voice_sample_exclude', {})}>
          Exclude
        </Button>
        <Button
          size='default'
          variant={confirmRevoke ? 'destructive' : 'quiet'}
          disabled={act.isPending || !source.active}
          onClick={() => {
            if (!confirmRevoke) return setConfirmRevoke(true);
            setConfirmRevoke(false);
            void update('voice_sample_revoke', { confirmed: true });
          }}
        >
          {confirmRevoke ? 'Confirm revoke' : 'Revoke & remove text'}
        </Button>
      </div>
      {isOwner && source.active && (
        <div className='flex flex-col gap-2'>
          <SelectField label='Writer for this sample' aria-label={`Writer for ${source.title || 'writing sample'}`} value={writerRoute} onChange={(event) => setWriterRoute(event.target.value)}>
            <option value=''>Choose a writer</option>
            {writers.map((model) => (
              <option key={model.id} value={model.voiceRoute}>
                {model.label} · {model.egress === 'cloud' ? 'cloud processing' : 'local preview'}
              </option>
            ))}
          </SelectField>
          <p className='text-muted-foreground text-xs'>Cloud processing includes Claude Code and Codex CLI. Only bounded style signals from this sample are sent for writing; sample facts are excluded. Permission applies only to the selected route.</p>
          <Button
            size='default'
            variant='glass'
            className='w-fit'
            disabled={!writerRoute || act.isPending}
            onClick={() => void update('voice_sample_grant', { grants: [...(source.useGrants ?? []).filter((grant) => !(grant.purpose === 'generation' && grant.route === writerRoute)), { purpose: 'generation', route: writerRoute }], confirmed: true })}
          >
            Allow this writer to use style
          </Button>
        </div>
      )}
    </Band>
  );
}

export function VoiceSamplesCard({ state, revision, isOwner, preferredPlatform, analysisRequest, autoPropose = false }: { state: SnapshotState | undefined; revision: number; isOwner: boolean; preferredPlatform?: string; analysisRequest?: string; autoPropose?: boolean }) {
  const act = useAct();
  const [text, setText] = useState('');
  const [platform, setPlatform] = useState(preferredPlatform ?? '');
  const [format, setFormat] = useState<'pasted' | 'csv' | 'json'>('pasted');
  const [manualConsent, setManualConsent] = useState(false);
  const manualConsentId = useId();
  const models = useModels();
  const [analysisModel, setAnalysisModel] = useState('');
  const [instructions, setInstructions] = useState(analysisRequest ?? 'Analyse my tone, rhythm and openings. Describe platform differences only when the samples support them.');
  const [confirmedAI, setConfirmedAI] = useState('');
  const analysisModels = models.data?.models.filter((model) => model.qualified && model.voiceAnalysisAvailable && model.voiceRoute) ?? [];
  const selectedModel = analysisModels.find((model) => model.id === analysisModel);
  const samples = (state?.sources ?? []).filter((source) => source.kind === 'voice_sample');
  const selected = samples.filter((source) => source.active && source.selected);
  const confirmationKey = JSON.stringify([analysisModel, instructions, selected.map((source) => [source.id, source.revision, source.useGrants])]);
  const aiAllowed = selected.filter((source) => source.useGrants?.some((grant) => grant.purpose === 'analysis' && grant.route === selectedModel?.voiceRoute));
  const analyzable = samples.filter((source) => source.active && source.selected && source.useGrants?.some((grant) => grant.purpose === 'analysis' && grant.route === 'local-rules'));

  async function importSample() {
    if (!manualConsent || !text.trim()) return;
    try {
      await act.mutateAsync({ revision, action: 'voice_samples_import', payload: format === 'pasted' ? { format, text, platform } : { format, data: text } });
      setText('');
      setManualConsent(false);
      toast.success('Writing sample retained. Choose it and approve how Rafii may use it.');
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function analyzeWithAI() {
    if (!isOwner || confirmedAI !== confirmationKey || !selectedModel || !selected.length || aiAllowed.length !== selected.length) return;
    try {
      await act.mutateAsync({ revision, action: 'voice_profile_analyze', payload: { sourceIds: selected.map((source) => source.id), route: selectedModel.voiceRoute, model: selectedModel.id, instructions, confirmed: true, requestId: crypto.randomUUID() } });
      setConfirmedAI('');
      toast.success('AI writing-DNA proposal ready. Review the evidence and approve it before use.');
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function analyzeSelected() {
    try {
      await act.mutateAsync({ revision, action: 'voice_profile_analyze', payload: { sourceIds: analyzable.map((source) => source.id), route: 'local-rules' } });
      toast.success('A provisional voice profile is ready for review. It is not active yet.');
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <Panel
      data-tour='voice-samples'
      title='Learn my voice'
      titleId='voice-samples-heading'
      description='Retain writing you choose, then separately select it and approve its use. Sample facts never become current brand facts. Analysis consent does not grant future generation consent.'
    >
      <OwnedPostsPicker revision={revision} isOwner={isOwner} preferredPlatform={preferredPlatform} autoPropose={autoPropose} />

      <Band aria-labelledby='manual-writing-samples'>
        <h3 id='manual-writing-samples' className='text-foreground text-sm font-medium'>
          Import writing samples manually
        </h3>
        <SelectField
          label='Import format'
          aria-label='Writing sample import format'
          className='sm:max-w-xs'
          value={format}
          onChange={(event) => {
            setFormat(event.target.value as typeof format);
            setManualConsent(false);
          }}
        >
          <option value='pasted'>Pasted text</option>
          <option value='csv'>CSV</option>
          <option value='json'>JSON array</option>
        </SelectField>
        <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_14rem]'>
          <Textarea
            aria-label='Writing sample'
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setManualConsent(false);
            }}
            maxLength={format === 'pasted' ? 8000 : 524288}
            rows={4}
            className={TEXTAREA_CLASS}
            placeholder={
              format === 'pasted' ? 'Paste one caption or post…' : format === 'csv' ? 'text,platform,language,label\n"Your writing",LinkedIn,English,representative' : '[{"text":"Your writing","platform":"LinkedIn","language":"English","label":"representative"}]'
            }
          />
          <div className='flex flex-col gap-3'>
            {format === 'pasted' && (
              <Input
                aria-label='Sample platform'
                value={platform}
                onChange={(event) => {
                  setPlatform(event.target.value);
                  setManualConsent(false);
                }}
                maxLength={80}
                placeholder='Platform (optional)'
                className={FIELD_CLASS}
              />
            )}
            <label htmlFor={manualConsentId} className='text-foreground flex items-start gap-2 text-xs leading-relaxed'>
              <Checkbox id={manualConsentId} className='mt-0.5' aria-label='Confirm manual writing sample authorship and retention' checked={manualConsent} onCheckedChange={(checked) => setManualConsent(checked === true)} disabled={act.isPending} />
              I wrote or have permission to use this text and consent to private retention, not AI analysis or generation.
            </label>
            <Button variant='action' size='control' disabled={act.isPending || !text.trim() || !manualConsent} onClick={() => void importSample()}>
              {act.isPending ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> Saving…
                </>
              ) : (
                'Retain samples'
              )}
            </Button>
            {format !== 'pasted' && <p className='text-muted-foreground text-xs'>Up to 50 records, 8,000 characters per text, 512 KiB total. Each record needs text; platform, language and label are optional. Validation is atomic.</p>}
            <p className='text-muted-foreground text-xs'>This is labelled user-provided text, not a verified platform import. It also works when LinkedIn history permission is unavailable.</p>
          </div>
        </div>
      </Band>

      {isOwner && (
        <Band aria-label='AI voice analysis'>
          <h3 className='text-foreground text-sm font-medium'>Ask Rafii to analyse my writing DNA</h3>
          <SelectField
            label='Analysis model'
            aria-label='Voice analysis model'
            value={analysisModel}
            disabled={act.isPending}
            onChange={(event) => {
              setAnalysisModel(event.target.value);
              setConfirmedAI('');
            }}
          >
            <option value=''>Choose a configured analysis model</option>
            {analysisModels.map((model) => (
              <option key={model.id} value={model.id}>
                {model.label} · {model.provider}
              </option>
            ))}
          </SelectField>
          {!analysisModels.length && <StateMessage kind='unsupported' layout='inline' title='No managed AI analysis model is configured and qualified.' description='Local writing statistics remain available; they are not AI tone analysis.' />}
          <Textarea aria-label='What should Rafii analyse about my writing?' value={instructions} onChange={(event) => setInstructions(event.target.value)} maxLength={1500} rows={3} className={TEXTAREA_CLASS} />
          <p className='text-muted-foreground text-xs break-all'>
            Choose samples below and grant analysis to this exact route: {selectedModel?.voiceRoute ?? 'no model selected'}. Raw sample text is sent to this processing route for analysis. Rafii does not fine-tune a model. Interpretation remains provisional.
          </p>
          <label htmlFor='voice-ai-processing-consent' className='text-foreground flex items-start gap-2 text-xs leading-relaxed'>
            <Checkbox id='voice-ai-processing-consent' className='mt-0.5' aria-label='Confirm AI sample processing and writing allowance use' checked={confirmedAI === confirmationKey} onCheckedChange={(checked) => setConfirmedAI(checked === true ? confirmationKey : '')} disabled={!selectedModel || act.isPending} />I agree to send the selected, permitted text to this model route for one analysis. It uses writing allowance and metered model usage within approved budgets. It does not publish or activate a voice.
          </label>
          <div className='flex flex-wrap items-center gap-3'>
            <Button variant='action' size='control' disabled={act.isPending || confirmedAI !== confirmationKey || !selectedModel || !selected.length || aiAllowed.length !== selected.length} onClick={() => void analyzeWithAI()}>
              {act.isPending ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> Analysing…
                </>
              ) : (
                'Analyse with AI'
              )}
            </Button>
            <p className='text-muted-foreground text-xs'>
              {aiAllowed.length} of {selected.length} selected samples allowed for this model. All selected samples need permission before analysis starts.
            </p>
          </div>
        </Band>
      )}

      {samples.length ? (
        <>
          <ul className='flex flex-col gap-3'>
            {samples.map((source) => (
              <VoiceSampleRow key={source.id} source={source} revision={revision} isOwner={isOwner} analysisRoute={selectedModel?.voiceRoute} />
            ))}
          </ul>
          <div className='flex flex-wrap items-center gap-3'>
            <Button variant='action' size='control' disabled={act.isPending || analyzable.length === 0 || analyzable.length !== selected.length} onClick={() => void analyzeSelected()}>
              {act.isPending ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> Analysing…
                </>
              ) : (
                'Describe local writing statistics'
              )}
            </Button>
            <p className='text-muted-foreground text-xs'>
              {analyzable.length} selected sample{analyzable.length === 1 ? '' : 's'} allowed for local analysis.
            </p>
          </div>
        </>
      ) : (
        <StateMessage kind='empty' layout='inline' title='No retained writing samples.' description='A few samples can produce a provisional profile later; there is no minimum guarantee.' />
      )}
    </Panel>
  );
}
