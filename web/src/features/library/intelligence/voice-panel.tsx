'use client';

import { useId, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { AssetRef, ContentSegment, VoiceSample } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import { METHOD_LABEL, voiceApproval, voiceCoverage, voicePassages, voiceRevocation, type VoiceDraft } from '@/lib/library/proactive';
import { locatorLabel } from '@/lib/library/wording';
import { relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function SampleRow({ sample, canRevoke, onRevoke }: { sample: VoiceSample; canRevoke: boolean; onRevoke: (sample: VoiceSample) => Promise<string | null> }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const live = sample.status === 'approved';
  return (
    <li className='rafii-quiet flex flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3 text-sm'>
      <span className='flex flex-wrap items-baseline justify-between gap-2'>
        <span className='font-medium'>{sample.locatorLabel || locatorLabel(sample.locator)}</span>
        <span className='text-muted-foreground text-xs'>{live ? 'In use' : sample.status === 'blocked' ? 'Paused' : 'Withdrawn'}</span>
      </span>
      {sample.text ? <blockquote className='border-foreground/20 line-clamp-4 border-l-2 pl-3'>{sample.text}</blockquote> : null}
      <span className='text-muted-foreground text-xs'>
        Persona {sample.personaId === 'default' ? 'workspace voice' : sample.personaId} · {sample.language}
        {sample.brand ? ` · ${sample.brand}` : ''} · {METHOD_LABEL[sample.attestation.method ?? ''] ?? 'Attested by the owner'}
        {sample.attestation.generatedTextApproved ? ' · AI-written text, approved separately' : ''}
        {sample.createdAt ? ` · approved ${relativeTime(sample.createdAt)}` : ''}
      </span>
      {sample.uses.length ? (
        <span className='text-muted-foreground text-xs'>Used for: {sample.uses.map((use) => (use.purpose === 'analysis' ? 'style analysis' : 'Rafii’s writer')).join(' and ')}</span>
      ) : null}
      {live && canRevoke ? (
        confirming ? (
          <span className='flex flex-wrap items-center gap-2'>
            <span className='text-xs'>Withdraw it? Future drafts stop using it; drafts already written keep their text.</span>
            <Button
              variant='destructive'
              size='control'
              className='h-11 rounded-[var(--rafii-radius-control)]'
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void onRevoke(sample).then((text) => {
                  setMessage(text);
                  setBusy(false);
                  setConfirming(false);
                });
              }}
            >
              Withdraw
            </Button>
            <Button variant='quiet' size='control' className='h-11' onClick={() => setConfirming(false)}>
              Keep
            </Button>
          </span>
        ) : (
          <Button variant='quiet' size='control' className='h-11 self-start' onClick={() => setConfirming(true)}>
            Withdraw this example…
          </Button>
        )
      ) : null}
      {message ? <p className='text-muted-foreground text-xs'>{message}</p> : null}
    </li>
  );
}

/**
 * "My voice" for one item (PRD R11): choose one passage — never the whole file — say you wrote or said it, name the
 * persona and language, and decide what it is for. AI-written text needs a second, separate approval. The list shows
 * provenance and counts only, never a grade.
 */
export function VoicePanel({ assetKey, segments, enabled }: { assetKey: string; segments: ContentSegment[]; enabled: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const id = useId();
  const voice = useQuery({ queryKey: ['library-asset-voice', workspaceId, assetKey], queryFn: () => api.libraryAssetVoice(workspaceId, assetKey), enabled: Boolean(workspaceId && assetKey && enabled), retry: false });
  const passages = voicePassages(segments);
  const [draft, setDraft] = useState<VoiceDraft>({
    passage: null,
    polarity: 'positive',
    personaId: 'default',
    language: '',
    attested: false,
    method: 'written_by_me',
    localAnalysis: true,
    writer: false,
    grantVoice: false,
    approveGeneratedText: false
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [needsGeneratedApproval, setNeedsGeneratedApproval] = useState(false);
  const keys = useRef<Record<string, string>>({});

  if (!enabled) return null;
  if (voice.isPending) return <p className='text-muted-foreground text-sm'>Loading voice examples…</p>;
  if (voice.isError || !voice.data) return <p className='text-muted-foreground text-sm'>Voice examples aren’t available here yet.</p>;
  const data = voice.data;
  const canApprove = data.admission.canApprove && data.admission.enabled;
  const reference = data.sourceRole.role === 'reference';
  const request = voiceApproval({ ...draft, grantVoice: !data.voicePermission.allowed }, passages.length);

  async function refresh() {
    await client.invalidateQueries({ queryKey: ['library-asset-voice', workspaceId, assetKey] });
    await client.invalidateQueries({ queryKey: ['library-card', workspaceId, assetKey] });
  }

  async function send(payload: Record<string, unknown>) {
    const digest = JSON.stringify(payload);
    keys.current[digest] ??= newIdempotencyKey('lib-voice', randomKey);
    const ref: AssetRef = data.assetRef;
    return api.libraryAction<VoiceSample>(workspaceId, {
      actionId: `voice-${Date.now()}`,
      uiInstanceId: 'library-voice',
      actionType: 'voice.approve_span',
      targetRefs: [ref],
      expectedRevision: data.voicePermission.grantRevision,
      idempotencyKey: keys.current[digest],
      payload
    });
  }

  async function approve(withGenerated: boolean) {
    const built = voiceApproval({ ...draft, grantVoice: !data.voicePermission.allowed, approveGeneratedText: withGenerated }, passages.length);
    if (!built.ok) {
      setMessage(built.reason);
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const result = await send(built.payload);
      if (result.status === 'requires_confirmation') {
        setNeedsGeneratedApproval(true);
        setMessage(result.warnings?.[0] || 'This passage was written by AI. Approve AI-written text separately.');
        return;
      }
      if (result.status !== 'applied') {
        setMessage(result.warnings?.[0] || (result.status === 'conflict' ? 'Permissions changed. Review them and try again.' : 'Not allowed.'));
        return;
      }
      setNeedsGeneratedApproval(false);
      setDraft((current) => ({ ...current, passage: null, attested: false, approveGeneratedText: false }));
      setMessage([draft.polarity === 'positive' ? 'Saved as a voice example.' : 'Saved as a “don’t write like this” example.', ...(result.warnings ?? [])].join(' '));
      await refresh();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : 'The example wasn’t saved.');
    } finally {
      setBusy(false);
    }
  }

  async function revoke(sample: VoiceSample): Promise<string | null> {
    const envelope = voiceRevocation(sample, `revoke-${Date.now()}`);
    const digest = `revoke:${sample.sampleId}:${sample.revision}`;
    keys.current[digest] ??= newIdempotencyKey('lib-voice-revoke', randomKey);
    try {
      const result = await api.libraryAction<{ residual?: string }>(workspaceId, { ...envelope, idempotencyKey: keys.current[digest] });
      if (result.status !== 'applied') return result.warnings?.[0] || 'It wasn’t withdrawn.';
      await refresh();
      return result.result?.residual || 'Withdrawn. Future drafts stop using it.';
    } catch (failure) {
      return failure instanceof Error ? failure.message : 'It wasn’t withdrawn.';
    }
  }

  const choose = (segment: ContentSegment) => setDraft((current) => ({ ...current, passage: segment, language: current.language || segment.language || '' }));
  return (
    <div className='flex flex-col gap-3'>
      <p className='text-sm'>{voiceCoverage(data.samples, data.negatives)}</p>
      <p className='text-muted-foreground text-xs'>{data.sourceRole.detail}</p>
      {[...data.samples, ...data.negatives].length ? (
        <ul className='flex flex-col gap-2' aria-label='Voice examples from this item'>
          {data.samples.map((sample) => (
            <SampleRow key={sample.sampleId} sample={sample} canRevoke={data.admission.canApprove} onRevoke={revoke} />
          ))}
          {data.negatives.map((sample) => (
            <SampleRow key={sample.sampleId} sample={sample} canRevoke={data.admission.canApprove} onRevoke={revoke} />
          ))}
        </ul>
      ) : null}

      {!data.admission.enabled ? (
        <p className='text-muted-foreground text-xs'>Learning your voice from Library items is turned off in this workspace.</p>
      ) : !data.admission.canApprove ? (
        <p className='text-muted-foreground text-xs'>Only the workspace owner can choose voice examples. You can see which passages are used.</p>
      ) : null}

      <fieldset disabled={!canApprove || reference || busy} className='flex flex-col gap-3 disabled:opacity-60'>
        <legend className='rafii-eyebrow mb-2'>Add an example</legend>
        {passages.length ? (
          <div role='radiogroup' aria-label='Passage' className='flex max-h-64 flex-col gap-1 overflow-y-auto overscroll-contain'>
            {passages.map((segment) => {
              const chosen = draft.passage?.id === segment.id;
              return (
                <label key={segment.id} className='rafii-quiet flex min-h-11 cursor-pointer items-start gap-2 rounded-[var(--rafii-radius-control)] p-2 text-sm'>
                  <input type='radio' name={`${id}-passage`} aria-label={`Passage at ${segment.locatorLabel || locatorLabel(segment.locator ?? null)}`} checked={chosen} onChange={() => choose(segment)} className='accent-foreground mt-1 size-4' />
                  <span className='flex min-w-0 flex-col'>
                    <span className='text-xs font-medium'>{segment.locatorLabel || locatorLabel(segment.locator ?? null)}</span>
                    <span className='line-clamp-2'>{segment.text}</span>
                  </span>
                </label>
              );
            })}
          </div>
        ) : (
          <p className='text-muted-foreground text-sm'>No passages with exact positions yet. Examples are chosen passage by passage, never the whole file.</p>
        )}
        <div role='radiogroup' aria-label='Kind of example' className='flex flex-wrap gap-3 text-sm'>
          <label className='flex min-h-11 items-center gap-2'>
            <input type='radio' name={`${id}-polarity`} aria-label='Teach my voice' checked={draft.polarity === 'positive'} onChange={() => setDraft({ ...draft, polarity: 'positive' })} className='accent-foreground size-4' />
            Teach my voice
          </label>
          <label className='flex min-h-11 items-center gap-2'>
            <input type='radio' name={`${id}-polarity`} aria-label='Don’t write like this' checked={draft.polarity === 'negative'} onChange={() => setDraft({ ...draft, polarity: 'negative' })} className='accent-foreground size-4' />
            Don’t write like this
          </label>
        </div>
        <div className='grid gap-2 sm:grid-cols-2'>
          <label htmlFor={`${id}-persona`} className='flex flex-col gap-1 text-xs'>
            Persona (“default” is your workspace voice)
            <Input id={`${id}-persona`} value={draft.personaId} maxLength={80} onChange={(event) => setDraft({ ...draft, personaId: event.target.value.trim() })} className='h-11 text-sm' />
          </label>
          <label htmlFor={`${id}-language`} className='flex flex-col gap-1 text-xs'>
            Language of the passage
            <Input id={`${id}-language`} value={draft.language} maxLength={12} placeholder='yue, zh-Hant, en' onChange={(event) => setDraft({ ...draft, language: event.target.value.trim() })} className='h-11 text-sm' />
          </label>
        </div>
        {draft.polarity === 'positive' ? (
          <div className='flex flex-col gap-1 text-sm'>
            <span className='text-xs'>Rafii may use this example for</span>
            <label className='flex min-h-11 items-center gap-2'>
              <input type='checkbox' aria-label='Style analysis on Rafii’s servers' checked={draft.localAnalysis} onChange={(event) => setDraft({ ...draft, localAnalysis: event.target.checked })} className='accent-foreground size-4' />
              Style analysis on Rafii’s servers
            </label>
            <label className='flex min-h-11 items-center gap-2'>
              <input type='checkbox' aria-label='Rafii’s AI writer (style only, never its facts)' checked={draft.writer} onChange={(event) => setDraft({ ...draft, writer: event.target.checked })} className='accent-foreground size-4' />
              Rafii’s AI writer (style only, never its facts)
            </label>
          </div>
        ) : null}
        <div className='flex flex-wrap items-start gap-3 text-sm'>
          <input
            id={`${id}-attest`}
            type='checkbox'
            aria-label='I wrote or said this myself'
            aria-describedby={`${id}-attest-help`}
            checked={draft.attested}
            onChange={(event) => setDraft({ ...draft, attested: event.target.checked })}
            className='accent-foreground mt-3 size-5 shrink-0'
          />
          <div className='flex flex-col gap-0.5'>
            <label htmlFor={`${id}-attest`} className='flex min-h-11 items-center font-medium'>
              I wrote or said this myself
            </label>
            <select
              aria-label='How you authored it'
              value={draft.method}
              onChange={(event) => setDraft({ ...draft, method: event.target.value as VoiceDraft['method'] })}
              className='rafii-field rafii-focus h-11 rounded-[var(--rafii-radius-control)] px-3 text-sm'
            >
              {data.admission.methods.map((method) => (
                <option key={method} value={method}>
                  {METHOD_LABEL[method]}
                </option>
              ))}
            </select>
            <p id={`${id}-attest-help`} className='text-muted-foreground text-xs'>
              Interviews, quotes and other people’s words should not teach your voice.
              {!data.voicePermission.allowed ? ' Saving also allows Rafii to learn your voice from this item.' : ''}
            </p>
          </div>
        </div>
        {needsGeneratedApproval ? (
          <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
            <p className='text-sm'>This passage was written by AI. It can teach your voice only if you approve AI-written text separately.</p>
            <Button variant='glass' size='control' className='self-start' disabled={busy} onClick={() => void approve(true)}>
              Approve AI-written text as my voice
            </Button>
          </div>
        ) : null}
        <Button variant='action' size='control' className='self-start' disabled={!request.ok || busy} onClick={() => void approve(false)}>
          {busy ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
          {draft.polarity === 'positive' ? 'Save as a voice example' : 'Save as “don’t write like this”'}
        </Button>
        {!request.ok && draft.passage ? <p className='text-muted-foreground text-xs'>{request.reason}</p> : null}
      </fieldset>
      {reference ? <p className='text-muted-foreground text-xs'>{data.sourceRole.detail}</p> : null}
      {message ? (
        <p role='status' className='text-sm'>
          {message}
        </p>
      ) : null}
      <p className='text-muted-foreground text-xs'>{data.explanation}</p>
    </div>
  );
}
