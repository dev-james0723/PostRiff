'use client';

import Link from 'next/link';
import { useEffect, useId, useState } from 'react';
import { AssetPicker } from '@/components/application/asset-picker';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { createSubmissionGate } from '@/features/agent/submission-gate';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { ApiError } from '@/lib/api/client';
import type { CreativeProject, CreativeScene } from '@/lib/api/creative-video';
import { useSnapshot } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { isPostableImage } from '@/lib/media/asset-kinds';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { campaignPhotoBrief, photoTurnRequest, type PhotoFormat } from './campaign-photo-brief';

type Props = { project: CreativeProject; scene: CreativeScene; disabled: boolean };

export function CampaignPhoto(props: Props) {
  const { user } = useAuth();
  const { workspaceId } = useWorkspaceApi();
  if (!user?.id || !workspaceId) return null;
  return <PhotoOptions key={[user.id, workspaceId, props.project.id, props.project.revision, props.scene.sceneId].join('/')}
    {...props} owner={user.id} />;
}

function PhotoOptions(props: Props & { owner: string }) {
  const [format, setFormat] = useState<PhotoFormat | null>(null);
  return <section aria-label='Campaign photo' className='grid gap-3 border-t pt-4'>
    <h3 className='text-sm font-medium'>Campaign photo</h3>
    {format
      ? <PhotoReview {...props} format={format} close={() => setFormat(null)} />
      : <div className='flex flex-wrap gap-2'>
        <Button type='button' variant='glass' size='sm' disabled={props.disabled} onClick={() => setFormat('thumbnail')}>Prepare thumbnail</Button>
        <Button type='button' variant='quiet' size='sm' disabled={props.disabled} onClick={() => setFormat('product')}>Prepare product photo</Button>
      </div>}
  </section>;
}

function PhotoReview({ project, scene, disabled, owner, format, close }: Props & { owner: string; format: PhotoFormat; close: () => void }) {
  const agent = useAgent();
  const snapshot = useSnapshot();
  const inputId = useId();
  const [brief, setBrief] = useState(() => campaignPhotoBrief(format, project, scene));
  const [photo, setPhoto] = useState('');
  const [rights, setRights] = useState(false);
  const [gate] = useState(createSubmissionGate);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [uncertain, setUncertain] = useState(false);
  const [conversation, setConversation] = useState('');
  useEffect(() => { gate.activate(); return () => gate.dispose(); }, [gate]);
  const assets = snapshot.data?.state.phase2?.assets ?? [];
  const selected = !photo || (rights && assets.some(asset => asset.id === photo && isPostableImage(asset)));
  const available = Boolean(agent.status?.canUseModel && agent.status?.manager.available && agent.status?.imageAvailable);
  const locked = disabled || busy || uncertain || Boolean(conversation);
  async function send() {
    if (locked || !available || !selected || !brief.trim() || !gate.enter()) return;
    setBusy(true);
    setError('');
    try {
      const scope = [owner, agent.workspaceId, project.id, String(project.revision), scene.sceneId, format];
      const request = await photoTurnRequest(scope, brief, photo);
      if (!gate.alive()) return;
      const result = await agent.api.turn(agent.workspaceId, request);
      if (gate.alive()) setConversation(result.conversationId);
    } catch (reason) {
      if (!gate.alive()) return;
      if (reason instanceof ApiError && reason.status >= 400 && reason.status < 500) {
        setError(reason.message);
      } else {
        setUncertain(true);
        setError('The outcome is unknown. Check your recent Rafii conversations for this image request.');
      }
    } finally {
      gate.leave();
      if (gate.alive()) setBusy(false);
    }
  }
  return <div className='grid gap-3'>
    <div className='grid gap-2'>
      <Label htmlFor={inputId}>{format === 'thumbnail' ? 'Thumbnail brief' : 'Product photo brief'}</Label>
      <Textarea id={inputId} value={brief} maxLength={1000} disabled={locked} rows={5} onChange={event => setBrief(event.target.value)} />
    </div>
    <div className='grid gap-2'>
      <Label htmlFor={inputId + '-reference'}>Reference photo (optional)</Label>
      <AssetPicker id={inputId + '-reference'} assets={assets} value={photo} disabled={locked}
        onValueChange={id => { setPhoto(id); setRights(false); }} noneLabel='Choose a Library photo' />
      {photo && <Label className='flex items-start gap-2'>
        <Checkbox checked={rights} disabled={locked} onCheckedChange={v => setRights(v === true)} />
        I can use this photo as a reference with the image provider.
      </Label>}
    </div>
    <p className='text-muted-foreground text-xs'>Sending this brief starts a new Rafii conversation. Image Studio uses one media credit per image.</p>
    {!available && <p role='status' className='text-sm'>{agent.statusError || agent.status
      ? 'Image generation is unavailable in this workspace.' : 'Checking image generation…'}</p>}
    {error && <p role='alert' className='text-sm text-destructive'>{error}</p>}
    {conversation
      ? <Link className='w-fit text-sm underline underline-offset-4' href={`/app/agent/${encodeURIComponent(conversation)}`}>Open image request</Link>
      : <div className='flex flex-wrap gap-2'>
        <Button type='button' size='sm' disabled={locked || !available || !selected || !brief.trim()} onClick={() => void send()}>
          {busy ? 'Sending image request…' : 'Send to Image Studio'}
        </Button>
        <Button type='button' variant='quiet' size='sm' disabled={busy} onClick={close}>Close</Button>
      </div>}
  </div>;
}
