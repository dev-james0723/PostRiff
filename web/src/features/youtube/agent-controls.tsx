'use client';

import { useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { isPostableVideo } from '@/lib/media/asset-kinds';
import type { YouTubeAgentDraft, YouTubeAgentPolicy } from '@/lib/youtube/types';
import type { OAuthStart } from '@/lib/api/types';

const control = 'border-input bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm';

export function YouTubeAgentControls({ channel, canPublic }: { channel: string; canPublic: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { role: 'owner' });
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const snapshot = useSnapshot();
  const client = useQueryClient();
  const prefix = useId();
  const query = useQuery({
    queryKey: ['youtube-agent', workspaceId, channel],
    queryFn: () => api.youtubeAgent(workspaceId, channel),
    enabled: Boolean(channel), retry: false, staleTime: 30_000
  });
  const assets = snapshot.data?.state.phase2?.assets.filter((a) => isPostableVideo(a, 'YouTube')) ?? [];
  const [asset, setAsset] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [goal, setGoal] = useState('');
  const [localTime, setLocalTime] = useState('');
  const [timeZone, setTimeZone] = useState('UTC');
  const [fold, setFold] = useState('');
  const [privacy, setPrivacy] = useState('private');
  const [mode, setMode] = useState('video');
  const [workflow, setWorkflow] = useState('upload_now');
  const [uploadTime, setUploadTime] = useState('');
  const [uploadFold, setUploadFold] = useState('');
  const [rights, setRights] = useState(false);
  const [kids, setKids] = useState('');
  const [synthetic, setSynthetic] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [maxDaily, setMaxDaily] = useState('1');
  const [endsAt, setEndsAt] = useState('');
  const [policyReview, setPolicyReview] = useState<YouTubeAgentPolicy>();
  const [confirmedPolicy, setConfirmedPolicy] = useState(false);
  const [agenticConsent, setAgenticConsent] = useState(false);
  const [agenticAuthorization, setAgenticAuthorization] = useState<OAuthStart>();
  const [confirmedDraft, setConfirmedDraft] = useState<string>();
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function run(work: () => Promise<unknown>, message: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      await work();
      await Promise.all([
        client.invalidateQueries({ queryKey: ['snapshot', workspaceId] }),
        client.invalidateQueries({ queryKey: ['youtube-agent', workspaceId, channel] })
      ]);
      setNotice(message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The publishing-agent action failed.');
    } finally { setBusy(false); }
  }
  const revision = async () => (await api.snapshot(workspaceId)).revision;
  async function prepare() {
    if (!rights || !kids || !synthetic) throw new Error('Confirm video rights, audience and realistic synthetic media declarations.');
    const publishOptions = {
      title, description, privacyStatus: privacy, mode,
      madeForKids: kids === 'yes', containsSyntheticMedia: synthetic === 'yes'
    };
    await api.youtubeAgentPrepare(workspaceId, channel, {
      revision: await revision(), assetId: asset, publishOptions, goal,
      localTime, timeZone, fold: fold === '' ? null : Number(fold), rightsConfirmed: rights,
      uploadWorkflow: workflow, uploadLocalTime: uploadTime,
      uploadFold: uploadFold === '' ? null : Number(uploadFold)
    });
  }
  async function approve(draft: YouTubeAgentDraft) {
    await api.youtubeAgentApprove(workspaceId, channel, draft.id, {
      revision: await revision(), digest: draft.digest, confirmed: true
    });
    setConfirmedDraft(undefined);
  }
  async function previewPolicy() {
    const expiry = Date.parse(endsAt);
    if (!Number.isFinite(expiry)) throw new Error('Choose an authority expiry with an explicit UTC offset, for example 2026-10-20T18:00:00Z.');
    const result = await api.youtubeAgentPolicyPreview(workspaceId, channel, {
      revision: await revision(), draftIds: selected, maxDaily: Number(maxDaily), timeZone, endsAt: expiry / 1000
    });
    setPolicyReview(result.result); setConfirmedPolicy(false);
  }
  async function policyAction(policy: YouTubeAgentPolicy, action: 'activate' | 'pause' | 'revoke') {
    await api.youtubeAgentPolicyAction(workspaceId, channel, policy.id, action, {
      revision: await revision(), ...(action === 'activate' ? {
        digest: policy.digest, confirmed: true, confirmationChannelId: policy.channelId
      } : {})
    });
    setPolicyReview(undefined); setConfirmedPolicy(false);
  }
  const input = (name: string, value: string, change: (value: string) => void, type = 'text') => (
    <div className='grid min-w-0 grid-cols-1 gap-1.5'>
      <Label htmlFor={`${prefix}-${name}`}>{name}</Label>
      <Input id={`${prefix}-${name}`} aria-label={name} type={type} value={value} onChange={(event) => change(event.target.value)} />
    </div>
  );
  const selection = (name: string, value: string, change: (value: string) => void, options: [string, string][]) => (
    <div className='grid min-w-0 grid-cols-1 gap-1.5'>
      <Label htmlFor={`${prefix}-${name}`}>{name}</Label>
      <select className={control} id={`${prefix}-${name}`} aria-label={name} value={value} onChange={(event) => change(event.target.value)}>
        {options.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
    </div>
  );
  return (
    <section className='grid min-w-0 grid-cols-1 gap-4 rounded-lg border p-4 [overflow-wrap:anywhere]' aria-label='YouTube publishing agent'>
      <h2 className='font-medium'>Library publishing plans</h2>
      <p className='text-muted-foreground text-sm'>Prepare a video plan, then approve its exact channel, metadata and time. Draft suggestions use Library filenames and your inputs; no AI model has inspected the video.</p>
      {query.isError && <p role='alert' className='text-destructive text-sm'>{query.error.message}</p>}
      <div className='grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2'>
        {selection('Library video', asset, (value) => {
          setAsset(value); setRights(false);
          const video = assets.find((item) => item.id === value);
          setTitle((video?.displayTitle || video?.originalFilename || '').replace(/\.[a-z0-9]+$/i, '').replace(/[_-]+/g, ' ').slice(0, 100));
        }, [['', 'Choose an inspected video'], ...assets.map((video): [string, string] => [video.id, video.displayTitle || video.originalFilename || video.id])])}
        {selection('Format', mode, setMode, [['video', 'Standard video'], ['short', 'Short (official format eligibility)']])}
        {input('Proposed title', title, setTitle)}
        {input('Channel goal (planning context)', goal, setGoal)}
        <div className='grid min-w-0 grid-cols-1 gap-1.5 sm:col-span-2'>
          <Label htmlFor={`${prefix}-description`}>Proposed description</Label>
          <textarea id={`${prefix}-description`} aria-label='Proposed description' className={control} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
        </div>
        {selection('Intended visibility', privacy, setPrivacy, [['private', 'Private (stays private)'], ...(canPublic ? [['public', 'Public at planned time'] as [string, string]] : [])])}
        {input('Planned publication time', localTime, setLocalTime, 'datetime-local')}
        {input('IANA time zone', timeZone, setTimeZone)}
        {selection('Repeated clock time', fold, setFold, [['', 'Ask if the time occurs twice'], ['0', 'First occurrence'], ['1', 'Second occurrence']])}
        {selection('Upload workflow', workflow, setWorkflow, [['upload_now', 'Upload privately now, then schedule'], ['upload_later', 'Queue the upload itself for later']])}
        {workflow === 'upload_later' && <>
          {input('Begin upload at least ten minutes earlier', uploadTime, setUploadTime, 'datetime-local')}
          {selection('Upload repeated clock time', uploadFold, setUploadFold, [['', 'Ask if the time occurs twice'], ['0', 'First occurrence'], ['1', 'Second occurrence']])}
        </>}
        {selection('Made for kids', kids, setKids, [['', 'Choose explicitly'], ['no', 'No'], ['yes', 'Yes']])}
        {selection('Realistic altered or synthetic media', synthetic, setSynthetic, [['', 'Choose explicitly'], ['no', 'No'], ['yes', 'Yes']])}
      </div>
      <label htmlFor={`${prefix}-rights`} className='flex items-start gap-2 text-sm'>
        <input id={`${prefix}-rights`} aria-label='Confirm rights to this exact Library video and metadata' type='checkbox' checked={rights} onChange={(event) => setRights(event.target.checked)} />
        I have the rights to upload this exact Library video and its metadata.
      </label>
      <Button className='w-fit' disabled={busy || !canEdit || !asset || !title || !localTime || !rights || !kids || !synthetic}
        onClick={() => run(prepare, 'Plan prepared. Review it below before approving publication.')}>Prepare reviewable plan</Button>
      <div className='grid min-w-0 grid-cols-1 gap-3' aria-label='Publishing calendar'>
        {query.data?.drafts.map((draft) => <article key={draft.id} className='grid min-w-0 grid-cols-1 gap-2 rounded-md border p-3 text-sm'>
          <div className='flex items-start gap-2'>
            {owner && draft.status === 'proposed' && <input id={`${prefix}-include-${draft.id}`} type='checkbox' aria-label={`Include ${draft.publishOptions.title} in autopilot policy`}
              checked={selected.includes(draft.id)} onChange={(event) => setSelected((ids) => event.target.checked ? [...ids, draft.id] : ids.filter((id) => id !== draft.id))} />}
            <div className='min-w-0'><p className='font-medium'>{draft.publishOptions.title}</p>
              <p className='text-muted-foreground'>{draft.timing.local.replace('T', ' ')} · {draft.timing.timeZone} · {draft.publishOptions.privacyStatus} · {draft.privacyErased ? 'Data removed' : draft.status}</p></div>
          </div>
          <p className='whitespace-pre-wrap'>{draft.publishOptions.description || '(Empty description)'}</p>
          <p>{draft.channelId && `Channel: ${draft.channelId} · `}Library video: {draft.assetId}</p>
          {draft.privacyErased ? <p>Data removed. This plan cannot run again. Prepare and approve a new plan. A schedule already accepted by YouTube is not canceled.</p> : <p>{draft.uploadWorkflow === 'upload_now' ? 'Upload privately after approval.' : `Upload begins ${new Date(draft.uploadAt * 1000).toISOString()}.`} {draft.publishOptions.privacyStatus === 'private' ? 'There is no automatic public transition.' : 'YouTube applies the native future publication schedule.'}</p>}
          {draft.status === 'proposed' && <>
            <label htmlFor={`${prefix}-approve-${draft.id}`} className='flex items-start gap-2'><input id={`${prefix}-approve-${draft.id}`} aria-label={`Approve the exact video, metadata, channel, time and visibility for ${draft.publishOptions.title}`} type='checkbox' checked={confirmedDraft === draft.id} onChange={(event) => setConfirmedDraft(event.target.checked ? draft.id : undefined)} />I approve this exact video, metadata, channel, time and visibility.</label>
            <Button className='w-fit' disabled={busy || !canApprove || confirmedDraft !== draft.id} onClick={() => run(() => approve(draft), 'Approved and queued. Publication is complete only when the provider receipt verifies it.')}>Approve and queue this plan</Button>
          </>}
          {draft.jobId && <p>Queue receipt: {draft.jobId} · {draft.approvalMode}</p>}
        </article>)}
      </div>
      {owner && <div className='grid min-w-0 grid-cols-1 gap-3 border-t pt-4'>
        <h3 className='font-medium'>Bounded authorized autopilot</h3>
        <p className='text-muted-foreground text-sm'>Standing authority covers only the selected exact plans and Library videos on this channel. Changes require fresh owner approval. Authority expires within 30 days.</p>
        {!query.data?.autopilotGate.canActivate && <p className='text-sm'>{query.data?.autopilotGate.reason || 'Checking Google approval and agentic OAuth availability.'}</p>}
        {!query.data?.autopilotGate.canActivate && <div className='grid min-w-0 grid-cols-1 gap-3 rounded-md border p-3 text-sm'>
          <label htmlFor={`${prefix}-agentic-consent`} className='flex items-start gap-2'><input id={`${prefix}-agentic-consent`} aria-label='Request separate Google authorization for owner-authorized Rafii publishing plans' type='checkbox' checked={agenticConsent} onChange={(event) => { setAgenticConsent(event.target.checked); setAgenticAuthorization(undefined); }} />I want a separate Google authorization for Rafii to execute owner-authorized publishing plans. Connecting does not activate autopilot or grant permission to delete content.</label>
          <Button variant='outline' className='w-fit' disabled={busy || !agenticConsent} onClick={() => run(async () => {
            setAgenticAuthorization(await api.oauthStart(workspaceId, 'youtube', 'autopilot', { authorizationLane: 'agentic', agenticConsent: true }));
          }, 'Review the Google permissions below, then authorize your own channel.')}>Prepare separate agentic Google consent</Button>
          {agenticAuthorization && <>
            <p>{agenticAuthorization.permissionExplanation}</p>
            <p>Scopes: {agenticAuthorization.scopes.join(', ')}</p>
            {agenticAuthorization.authorizeUrl && <a className='w-fit underline' href={agenticAuthorization.authorizeUrl} aria-label='Continue to Google to select and authorize your channel'>Continue to Google to select and authorize your channel</a>}
          </>}
        </div>}
        <div className='grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2'>
          {input('Maximum publications per day (1–20)', maxDaily, setMaxDaily, 'number')}
          {input('Authority expires (ISO date with UTC offset)', endsAt, setEndsAt)}
        </div>
        <Button variant='outline' className='w-fit' disabled={busy || !selected.length || !endsAt} onClick={() => run(previewPolicy, 'Policy prepared. Review its exact scope before activation.')}>Review standing authority for {selected.length} plans</Button>
        {policyReview && <div className='grid min-w-0 grid-cols-1 gap-3 rounded-md border p-3 text-sm'>
          <p>Channel {policyReview.channelId} · {policyReview.drafts.length} exact plans · {policyReview.assetIds.length} Library videos · maximum {policyReview.maxDaily}/day in {policyReview.timeZone} · expires {new Date(policyReview.endsAt * 1000).toISOString()}</p>
          <label htmlFor={`${prefix}-policy-consent`} className='flex items-start gap-2'><input id={`${prefix}-policy-consent`} aria-label='Authorize only the reviewed exact publishing plans within their limits until expiry or revocation' type='checkbox' checked={confirmedPolicy} onChange={(event) => setConfirmedPolicy(event.target.checked)} />I authorize Rafii to execute only these exact plans within these limits until expiry or revocation.</label>
          <Button className='w-fit' disabled={busy || !confirmedPolicy || !query.data?.autopilotGate.canActivate} onClick={() => run(() => policyAction(policyReview, 'activate'), 'Bounded authority activated. The worker still verifies credentials, quotas and each publishing receipt.')}>Enable bounded autopilot</Button>
        </div>}
        {query.data?.policies.filter((policy) => policy.status !== 'prepared').map((policy) => <div key={policy.id} className='grid min-w-0 grid-cols-1 gap-2 rounded-md border p-3 text-sm'>
          <p>{policy.status} · {policy.drafts.length} plans · {policy.maxDaily}/day · expires {new Date(policy.endsAt * 1000).toISOString()}</p>
          {policy.privacyErased && <p>Channel data was removed and this authority cannot restart. Prepare a new policy after reviewing new plans.</p>}
          {policy.intervention && <p role='alert'>{policy.intervention.message}</p>}
          {policy.status === 'paused' && <p>Restarting this policy permits new plan dispatch only. Held jobs require separate review and do not resume automatically. Creator recovery is available only for recoverable journaled uploads.</p>}
          <div className='flex flex-wrap gap-2'>
            {policy.status === 'active' && <Button variant='outline' disabled={busy} onClick={() => run(() => policyAction(policy, 'pause'), 'Autopilot paused. Already accepted native YouTube schedules need separate cancellation.')}>Pause new execution</Button>}
            {policy.status === 'paused' && <Button variant='outline' disabled={busy || !query.data?.autopilotGate.canActivate} onClick={() => { setPolicyReview(policy); setConfirmedPolicy(false); }}>Review policy restart</Button>}
            {policy.status !== 'revoked' && <Button variant='outline' disabled={busy} onClick={() => run(() => policyAction(policy, 'revoke'), 'Standing authority revoked. Already accepted native YouTube schedules need separate cancellation.')}>Revoke authority</Button>}
          </div>
        </div>)}
        <p className='text-muted-foreground text-sm'>{query.data?.pauseNotice}</p>
      </div>}
      {notice && <p role='status' className='text-sm'>{notice}</p>}
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
    </section>
  );
}
