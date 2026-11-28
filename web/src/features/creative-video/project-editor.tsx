'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Icons } from '@/components/icons';
import PageContainer from '@/components/layout/page-container';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { CreativeSettings, CreativeVideoReply } from '@/lib/api/creative-video';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { departureHref } from '@/features/workspace/brand/brain-navigation';
import { BlueprintDetails } from './blueprint-details';
import { CutTimeline } from './cut-timeline';
import { PrivateVideo, useVideoLibrary, VideoSelect } from './media';
import { changedScenes, draftScene, editIssue, unresolved, type SceneDraft } from './scene-edit';
import { SceneGeneration } from './scene-generation';
import { ProjectPlan } from './project-plan';
import { ProjectVariants } from './project-variants';
import { CampaignPhoto } from './campaign-photo';

const sourceLabels = {
  'user-provided': 'Uploaded footage',
  generated: 'AI-generated footage',
  composed: 'Composed footage',
  unknown: 'Library footage'
};

export function ProjectEditor({ initial, pinnedRevision, selectedSceneId, onUpdate }: { initial: CreativeVideoReply; pinnedRevision?: number; selectedSceneId?: string; onUpdate: (result: CreativeVideoReply) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const router = useRouter();
  const library = useVideoLibrary();
  const canApprove = !library.sample && checkAccess(access, { permission: 'approve' });
  const canEdit = !library.sample && checkAccess(access, { permission: 'edit' });
  const [current, setCurrent] = useState(initial);
  const [conflict, setConflict] = useState<CreativeVideoReply | null>(null);
  const [openingSceneId] = useState(() => initial.project.scenes.find(unresolved)?.sceneId ?? initial.project.scenes[0]?.sceneId);
  const [drafts, setDrafts] = useState<Record<string, SceneDraft>>({});
  const [sceneOrder, setSceneOrder] = useState<string[] | null>(null);
  const [sceneSettings, setSceneSettings] = useState<Record<string, CreativeSettings>>({});
  const [playback, setPlayback] = useState({ key: '', elapsedMs: 0 });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const locked = useRef(false);
  const active = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const { project, provider } = current;
  const timeline = sceneOrder ? sceneOrder.map(id => project.scenes.find(s => s.sceneId === id)!) : project.scenes;
  const timelineClips = timeline.map(item => {
    const seconds = drafts[item.sceneId]?.seconds ?? '';
    const durationMs = Math.round(Number(seconds) * 1000);
    const validDuration = /^\d+(\.\d{1,3})?$/.test(seconds) && durationMs >= 42 && durationMs <= 8000;
    return { id: item.sceneId, label: item.purpose, durationMs: validDuration ? durationMs : item.durationMs };
  });
  const scene = project.scenes.find(s => s.sceneId === (selectedSceneId ?? openingSceneId));
  const draft = scene ? (drafts[scene.sceneId] ?? draftScene(scene)) : null;
  const changes = changedScenes(project.scenes, drafts);
  const issue = editIssue(timeline, drafts, project.referenceAssetId);
  const dirty = sceneOrder !== null || changes.length > 0 || (Object.keys(drafts).length > 0 && issue !== null);
  const historical = pinnedRevision !== undefined || project.revision !== project.headRevision;
  const pending = scene ? unresolved(scene) : false;
  const readOnly = Boolean(busy || pending || conflict || historical || !canEdit);
  const readyCount = project.scenes.filter(s => s.clipId).length;
  const exported = project.export?.revision === project.revision ? project.export.assetId : null;
  const revision = project.revision;
  const durationMs = project.scenes.reduce((sum, s) => sum + s.durationMs, 0);
  const previewKey = scene && draft?.clipId && !issue
    ? JSON.stringify([project.id, revision, scene.sceneId, draft.clipId, draft.startSeconds, draft.seconds])
    : '';
  if (playback.key !== previewKey) setPlayback({ key: previewKey, elapsedMs: 0 });
  const selectedIndex = timelineClips.findIndex(clip => clip.id === scene?.sceneId);
  const startMs = timelineClips.slice(0, selectedIndex).reduce((sum, clip) => sum + clip.durationMs, 0);
  const playheadMs = selectedIndex < 0 ? undefined : startMs + (playback.key === previewKey ? playback.elapsedMs : 0);
  function sceneHref(id?: string, savedRevision?: number) {
    const params = new URLSearchParams({ project: project.id });
    if (id) params.set('scene', id);
    if (savedRevision !== undefined) params.set('revision', String(savedRevision));
    return `/app/creative?${params}`;
  }

  function selectScene(id: string) {
    router.replace(sceneHref(id, pinnedRevision), { scroll: false });
  }

  const latestHref = sceneHref(selectedSceneId ?? scene?.sceneId);
  const sceneId = scene?.sceneId;
  const quote = useCallback((settings: CreativeSettings) => api.creativeVideoQuote(workspaceId, project.id, {
    revision, sceneId: sceneId ?? '', settings
  }), [api, workspaceId, project.id, revision, sceneId]);

  useEffect(() => {
    if (!dirty) return;
    function warn(event: BeforeUnloadEvent) { event.preventDefault(); event.returnValue = ''; }
    function beforeLink(event: MouseEvent) {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target instanceof Element ? event.target.closest('a') : null;
      if (!link || !departureHref(link.href, window.location.href, link.target, link.hasAttribute('download'))) return;
      if (!window.confirm('Leave the project and discard your unsaved scene edits?')) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    window.addEventListener('beforeunload', warn);
    document.addEventListener('click', beforeLink, true);
    return () => { window.removeEventListener('beforeunload', warn); document.removeEventListener('click', beforeLink, true); };
  }, [dirty]);

  function acceptSaved(result: CreativeVideoReply) {
    setCurrent(result);
    setConflict(null);
    setDrafts({});
    setSceneOrder(null);
    onUpdate(result);
  }

  function reconcile(result: CreativeVideoReply) {
    if (dirty && result.project.revision !== revision) {
      setConflict(result);
    } else {
      setCurrent(result);
      onUpdate(result);
    }
  }

  async function perform(label: string, operation: () => Promise<CreativeVideoReply>, reload = false) {
    if (locked.current) return;
    locked.current = true;
    setBusy(label);
    setError('');
    try {
      const result = await operation();
      if (!active.current) return;
      if (reload) reconcile(result);
      else acceptSaved(result);
    } catch (reason) {
      if (!active.current) return;
      setError(reason instanceof Error ? reason.message : 'The workspace could not confirm this action.');
      if (!reload) {
        try {
          const latest = await api.creativeVideoProject(workspaceId, project.id);
          if (active.current) reconcile(latest);
        } catch { if (active.current) setError(message => `${message} Reload the project to check its saved state.`); }
      }
    } finally {
      locked.current = false;
      if (active.current) setBusy('');
    }
  }

  function modify(change: Partial<SceneDraft>) {
    if (!scene || readOnly) return;
    setDrafts(previous => ({
      ...previous,
      [scene.sceneId]: { ...(previous[scene.sceneId] ?? draftScene(scene)), ...change }
    }));
  }

  function moveScene(id: string, step: number) {
    const index = timeline.findIndex(item => item.sceneId === id);
    const nextIndex = index + step;
    if (readOnly || index < 0 || nextIndex < 0 || nextIndex >= timeline.length) return;
    const next = timeline.map(item => item.sceneId);
    next.splice(nextIndex, 0, ...next.splice(index, 1));
    setSceneOrder(next.every((key, i) => key === project.scenes[i].sceneId) ? null : next);
  }

  useEffect(() => {
    if (!sceneId || scene?.generation?.state !== 'pending' || historical || !(canApprove || canEdit && scene.generation.mediaKind === 'composed') || busy || dirty || error || conflict) return;
    const poll = setInterval(() => {
      if (document.visibilityState === 'visible' && !locked.current) {
        void perform('Checking the saved request…', () => api.creativeVideoPoll(workspaceId, project.id, { revision, sceneId }));
      }
    }, 15_000);
    return () => clearInterval(poll);
  });

  return <PageContainer pageTitle={project.title} pageEyebrow='Video Studio'
    pageDescription={`${project.platform} · ${project.aspectRatio} · Revision ${revision}`}
    pageHeaderAction={<>
      <Button variant='quiet' size='lg' disabled={Boolean(busy)} onClick={() => {
        if (!dirty || window.confirm('Leave the project and discard your unsaved scene edits?')) router.push('/app/creative');
      }}>All projects</Button>
      <Button variant='glass' size='lg' disabled={Boolean(busy)} onClick={() => void perform('Checking the saved project…', () => api.creativeVideoProject(workspaceId, project.id, pinnedRevision), true)}>
        <Icons.refresh aria-hidden />Reload project
      </Button>
    </>}>
    {busy && <StateMessage kind='loading' layout='inline' title={busy} />}
    {error && <StateMessage kind='error' layout='inline' title='The workspace needs attention' description={error} />}
    {conflict && <StateMessage kind='stale' title={`Revision ${conflict.project.revision} is saved in the workspace`}
      description='Your unsaved scene edits are still visible below. Loading the saved revision will replace them.'
      action={<Button variant='glass' onClick={() => { acceptSaved(conflict); setError(''); }}>Discard my edits and load saved revision</Button>} />}
    {historical && <StateMessage kind='partial' layout='inline' title={`Viewing saved revision ${revision}`}
      action={<Link href={latestHref} className='rafii-focus rounded-sm underline underline-offset-4'>Open current project</Link>} />}
    <BlueprintDetails project={project} />
    {project.origin && <Link className='rafii-focus w-fit text-sm underline underline-offset-4'
      href={`/app/creative?project=${encodeURIComponent(project.origin.projectId)}&revision=${project.origin.revision}`}>Open source project · Revision {project.origin.revision}</Link>}
    <CutTimeline clips={timelineClips} selectedId={scene?.sceneId} onSelect={selectScene} positionMs={playheadMs} disabled={Boolean(busy)} />
    <div className='grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(14rem,0.7fr)_minmax(0,1.7fr)]'>
      <Surface as='section' material='quiet' aria-labelledby='scene-list-heading' className='grid gap-4'>
        <div>
          <h2 id='scene-list-heading' className='text-lg font-medium'>Scene list</h2>
          <p className='text-muted-foreground mt-1 text-sm'>{project.scenes.length} scenes · {durationMs / 1000} s saved</p>
        </div>
        <ol className='grid gap-2'>
          {timeline.map((s, index) => {
            const selected = s.sceneId === scene?.sceneId;
            return <li key={s.sceneId}><Button variant={selected ? 'glass' : 'quiet'} type='button' aria-pressed={selected}
              disabled={Boolean(busy)} className='h-auto min-h-12 w-full justify-start gap-3 whitespace-normal px-3 py-2 text-left'
              onClick={() => selectScene(s.sceneId)}>
              <span className='font-mono text-xs tabular-nums'>{String(index + 1).padStart(2, '0')}</span>
              <span className='grid min-w-0 gap-0.5'>
                <span className='font-medium'>{s.purpose}</span>
                <span className='text-xs text-muted-foreground'>{timelineClips[index].durationMs / 1000} s · {changes.some(c => c.sceneId === s.sceneId) ? 'Unsaved edit'
                  : s.clipId ? (s.clipOrigin === 'composed' ? 'Composed storyboard' : sourceLabels[s.sourceMediaKind ?? (s.clipOrigin === 'generated' ? 'generated' : 'unknown')]) : s.generation?.state === 'unknown' ? 'Needs reconciliation'
                  : unresolved(s) ? 'Generation in progress' : 'Needs footage'}</span>
              </span>
            </Button></li>;
          })}
        </ol>
        {canEdit && !historical && scene && timeline.length > 1 && <div className='flex flex-wrap gap-2' aria-label='Selected scene position'>
          <Button variant='glass' size='sm' disabled={readOnly || timeline[0].sceneId === scene.sceneId}
            onClick={() => moveScene(scene.sceneId, -1)}>Move earlier</Button>
          <Button variant='glass' size='sm' disabled={readOnly || timeline.at(-1)?.sceneId === scene.sceneId}
            onClick={() => moveScene(scene.sceneId, 1)}>Move later</Button>
          {sceneOrder && <span role='status' className='basis-full text-xs text-muted-foreground'>Scene order has unsaved changes.</span>}
        </div>}
        {!historical && (canEdit || canApprove) && <ProjectPlan key={String(canApprove)} id={project.id} revision={revision} scenes={project.scenes}
          localOnly={!canApprove} overrides={sceneSettings} disabled={Boolean(busy || conflict) || dirty} onScene={selectScene} />}
        <details className='border-t pt-3 text-sm'>
          <summary className='rafii-focus cursor-pointer rounded-sm font-medium'>Saved revisions</summary>
          <ol className='mt-2 grid gap-1 text-muted-foreground'>{project.history.map(h => <li key={h.revision}>
            {h.revision === revision ? <span>Revision {h.revision} · viewing</span> :
              <Link href={h.revision === project.headRevision ? latestHref : `${latestHref}&revision=${h.revision}`}
                onClick={event => { if (dirty && !window.confirm('View this revision and discard your unsaved scene edits?')) event.preventDefault(); }}
                className='rafii-focus rounded-sm underline underline-offset-4'>Revision {h.revision}</Link>}
            {' · '}{h.sceneCount} scenes
          </li>)}</ol>
        </details>
        {canEdit && <ProjectVariants key={JSON.stringify([workspaceId, project.id, revision])} projectId={project.id}
          revision={revision} disabled={Boolean(busy || conflict) || dirty} />}
      </Surface>
      <div className='grid min-w-0 gap-5'>
        {selectedSceneId && !scene && <StateMessage kind='partial' layout='inline'
          title='This scene is unavailable in this revision' description='Choose a scene from the timeline.' />}
        {scene && draft && <Surface as='section' material='paper' padding='lg' aria-labelledby='scene-heading' className='grid gap-5'>
          <div className='grid gap-2'>
            <h2 className='text-xl font-medium' id='scene-heading'>{scene.purpose}</h2>
            <p className='text-muted-foreground whitespace-pre-line text-sm'>{project.brief}</p>
            {project.referenceAssetId && scene.sourceStartMs != null && scene.sourceEndMs != null && <p className='text-xs text-muted-foreground'>
              Reference timing · {scene.sourceStartMs / 1000}–{scene.sourceEndMs / 1000} s{scene.evidence ? ` · ${scene.evidence}` : ''}
            </p>}
          </div>
          <div className='grid gap-2'>
            <Label htmlFor='scene-direction'>Visual direction</Label>
            <Textarea id='scene-direction' maxLength={600} value={draft.direction} disabled={readOnly} onChange={e => modify({ direction: e.target.value })} />
          </div>
          <div className='grid gap-4 sm:grid-cols-[minmax(0,1fr)_9rem]'>
            <div className='grid content-start gap-2'>
              <Label htmlFor='scene-caption'>Timed caption</Label>
              <Input id='scene-caption' maxLength={120} value={draft.caption} disabled={readOnly} onChange={e => modify({ caption: e.target.value })} />
            </div>
            <div className='grid content-start gap-2'>
              <Label htmlFor='scene-duration'>Duration (seconds)</Label>
              <Input id='scene-duration' type='number' min='0.042' max='8' step='0.001' value={draft.seconds} disabled={readOnly} onChange={e => modify({ seconds: e.target.value })} />
            </div>
          </div>
          <VideoSelect id='scene-footage' label='Original footage' library={library} value={draft.clipId} currentClip={scene.clipId}
            footage exclude={project.referenceAssetId ?? undefined} disabled={readOnly} onChange={id => modify({ clipId: id, clipRightsConfirmed: false, startSeconds: '0' })} />
          {draft.clipId && <div className='grid max-w-xs gap-2'>
            <Label htmlFor='footage-start'>Start in source footage (seconds)</Label>
            <Input id='footage-start' type='number' min='0' max='89.999' step='0.001' value={draft.startSeconds}
              disabled={readOnly} onChange={event => modify({ startSeconds: event.target.value })} />
          </div>}
          {draft.clipId && draft.clipId !== scene.clipId &&
            <div className='flex items-start gap-3'>
              <Checkbox id='scene-footage-rights' checked={draft.clipRightsConfirmed} disabled={readOnly} onCheckedChange={value => modify({ clipRightsConfirmed: value === true })} />
              <Label htmlFor='scene-footage-rights' className='leading-snug'>I have the rights to use this footage in the finished video.</Label>
            </div>}
          {(draft.direction.trim() !== scene.direction || (Number(draft.seconds) * 1000 > scene.durationMs &&
            (Number(draft.startSeconds) + Number(draft.seconds)) * 1000 > (scene.clipDurationMs ?? scene.durationMs) + 1)) &&
            (scene.clipOrigin === 'generated' || scene.clipOrigin === 'composed') && draft.clipId === scene.clipId &&
            <p className='text-sm text-muted-foreground'>These edits will require a new take of this scene.</p>}
          {draft.clipId && !issue && <PrivateVideo key={previewKey}
            assetId={draft.clipId} label='Preview selected cut' cut={{ start: Number(draft.startSeconds), duration: Number(draft.seconds) }}
            onCutPositionChange={elapsedMs => setPlayback(current => current.key === previewKey && current.elapsedMs !== elapsedMs
              ? { key: previewKey, elapsedMs } : current)} />}
          {scene.clipId && scene.generation?.state === 'completed' && !historical && <div className='grid gap-2 text-sm'>
            <p className='font-medium'>{scene.generation.accepted == null ? 'Review this take' : scene.generation.accepted ? 'Take accepted' : 'Take needs revision'}</p>
            {canEdit && <div className='flex flex-wrap gap-2'>
              {[true, false].map(accepted => <Button key={String(accepted)} variant='glass' size='lg'
                aria-pressed={scene.generation?.accepted === accepted} disabled={readOnly || dirty || scene.generation?.accepted === accepted}
                onClick={() => void perform('Saving take review…', () => api.creativeVideoReview(workspaceId, project.id, { revision, sceneId: scene.sceneId, accepted }))}>
                {accepted ? 'Accept take' : 'Needs revision'}
              </Button>)}
            </div>}
          </div>}
          {canEdit && !historical && (scene.clipOrigin === 'generated' || scene.clipOrigin === 'composed' || scene.generation?.state === 'failed' || scene.generation?.state === 'cancelled') &&
            <div className='grid gap-1.5'>
              <Button className='w-fit' variant='glass' size='lg' disabled={readOnly || dirty || project.scenes.some(unresolved)}
                onClick={() => void perform('Preparing another take…', () => api.creativeVideoEdit(workspaceId, project.id,
                  { revision, scenes: [{ sceneId: scene.sceneId, retake: true }] }))}>Prepare another take</Button>
              <p className='text-sm text-muted-foreground'>Save this direction in a new revision. Generating new footage requires a separate approval.</p>
            </div>}
          {dirty && <div className='grid gap-2'>
            {issue && <p className='text-sm text-destructive' role='alert'>{issue}</p>}
            <div className='flex flex-wrap gap-2'>
              <Button variant='action' size='control' disabled={readOnly || Boolean(issue) || (!sceneOrder && changes.length === 0)}
                onClick={() => void perform('Saving scene edits…', () => api.creativeVideoEdit(workspaceId, project.id, { revision, scenes: changes, ...(sceneOrder && { sceneOrder }) }))}>
                Save {sceneOrder ? 'timeline' : changes.length > 1 ? `${changes.length} scene edits` : 'scene edit'}
              </Button>
              <Button variant='quiet' size='control' disabled={Boolean(busy || conflict)} onClick={() => { setDrafts({}); setSceneOrder(null); }}>Discard edits</Button>
            </div>
          </div>}
          <SceneGeneration key={JSON.stringify([scene.sceneId, revision, project.context.cloudAllowed, canApprove])}
            scene={scene} provider={provider} cloudAllowed={project.context.cloudAllowed} canApprove={canApprove} canEdit={canEdit}
            savedSettings={sceneSettings[scene.sceneId]} onSettings={settings => setSceneSettings(previous => ({ ...previous, [scene.sceneId]: settings }))}
            busy={Boolean(busy || conflict)} dirty={dirty} pending={pending} historical={historical} aspect={project.aspectRatio} hasReference={Boolean(project.referenceAssetId)}
            onQuote={quote} onGenerate={quoteId => void perform('Requesting the approved take…', () => api.creativeVideoGenerate(workspaceId, project.id, { revision, sceneId: scene.sceneId, quoteId, confirmed: true }))}
            onCancel={() => void perform('Requesting cancellation…', () => api.creativeVideoCancel(workspaceId, project.id, { revision, sceneId: scene.sceneId }))}
            onPoll={() => void perform('Checking the provider…', () => api.creativeVideoPoll(workspaceId, project.id, { revision, sceneId: scene.sceneId }))} />
          {canEdit && !historical && <CampaignPhoto key={JSON.stringify([project.id, revision, scene.sceneId])}
            project={project} scene={scene} disabled={readOnly || dirty} />}
        </Surface>}
        <Surface as='section' material='quiet' aria-labelledby='export-heading' className='grid gap-3'>
          <h2 id='export-heading' className='text-lg font-medium'>Final video</h2>
          {exported ? <>
            <p className='text-sm text-muted-foreground'>MP4 from saved revision {revision}{dirty ? ' · Includes only saved edits' : ''}</p>
            {project.export?.manifest && <p className='text-xs text-muted-foreground'>{project.export.manifest.width} × {project.export.manifest.height} · {project.export.manifest.fps} fps · {project.export.manifest.durationMs / 1000} s</p>}
            <PrivateVideo key={exported} assetId={exported} label='Preview final MP4' downloadName={`video-revision-${revision}.mp4`} captions={project.export?.manifest?.scenes}
              exportFrames={project.export?.manifest ? { projectId: project.id, revision, fps: project.export.manifest.fps, count: project.export.manifest.frameCount } : undefined} />
            <Link className='rafii-focus w-fit rounded-sm text-sm underline underline-offset-4'
              href={`/app/creative/performance?project=${encodeURIComponent(project.id)}&revision=${revision}`}>View this revision’s performance</Link>
          </> : <>
            <p className='text-sm text-muted-foreground'>{readyCount} of {project.scenes.length} scenes have footage.{dirty ? ' Save your edits before rendering.' : ''}</p>
            {canEdit && !historical && <Button className='w-fit' variant='action' size='control' disabled={Boolean(busy || conflict) || dirty || readyCount !== project.scenes.length || !readyCount}
              onClick={() => void perform('Rendering the saved timeline…', () => api.creativeVideoRender(workspaceId, project.id, { revision }))}>
              <Icons.video aria-hidden />Render MP4
            </Button>}
          </>}
        </Surface>
        <Link href='/app/library' className='rafii-focus w-fit rounded-sm text-sm underline underline-offset-4'>Open workspace Library</Link>
      </div>
    </div>
  </PageContainer>;
}
