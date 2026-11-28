'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth/session';
import { takeFirstBrief } from '@/features/onboarding/first-goal';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { CollectionRow, StateMessage, Surface } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { CreateCreativeProject, CreativeAspect, CreativePlatform, CreativeVideoReply } from '@/lib/api/creative-video';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { PrivateVideo, useVideoLibrary, VideoSelect } from './media';
import { ProjectEditor } from './project-editor';

const studioPath = '/app/creative';
const projectPath = (id: string) => `${studioPath}?project=${encodeURIComponent(id)}`;
const listKey = (workspace: string) => ['creative-video-projects', workspace];
const projectKey = (workspace: string, id: string, revision?: number) => ['creative-video-project', workspace, id, revision ?? 'current'];

export function CreativeStudio({ projectId, referenceId, revision, selectedSceneId }: { projectId: string; referenceId: string; revision?: number; selectedSceneId?: string }) {
  const access = useWorkspaceAccess();
  const { workspaceId } = useWorkspaceApi();
  if (!checkAccess(access, { permission: 'read' })) return <PageContainer access={false} />;
  return projectId
    ? <OpenProject key={`${workspaceId}/${projectId}/${revision ?? 'current'}`} id={projectId} revision={revision} selectedSceneId={selectedSceneId} />
    : <NewProject key={`${workspaceId}/${referenceId}`} initialReference={referenceId} canEdit={checkAccess(access, { permission: 'edit' })} />;
}

function OpenProject({ id, revision, selectedSceneId }: { id: string; revision?: number; selectedSceneId?: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const project = useQuery({
    queryKey: projectKey(workspaceId, id, revision), queryFn: () => api.creativeVideoProject(workspaceId, id, revision),
    retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false, staleTime: 0, gcTime: 0
  });
  if (!project.data) return <PageContainer pageTitle='Video Studio'>
    <Link href={studioPath} className='w-fit text-sm underline underline-offset-4'>All projects</Link>
    <StateMessage kind={project.isError ? 'error' : 'loading'} title={project.isError ? 'This project could not be opened' : 'Opening project…'}
      description={project.isError ? project.error.message : undefined}
      action={project.isError && <Button variant='glass' onClick={() => void project.refetch()}>Try again</Button>} />
  </PageContainer>;
  return <ProjectEditor initial={project.data} pinnedRevision={revision} selectedSceneId={selectedSceneId} onUpdate={(next: CreativeVideoReply) => {
    client.setQueryData(projectKey(workspaceId, id, revision), next);
    void client.invalidateQueries({ queryKey: listKey(workspaceId) });
  }} />;
}

function NewProject({ initialReference, canEdit: editPermission }: { initialReference: string; canEdit: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const router = useRouter();
  const client = useQueryClient();
  const library = useVideoLibrary();
  const canEdit = editPermission && !library.sample;
  const projects = useQuery({ queryKey: listKey(workspaceId), queryFn: () => api.creativeVideoList(workspaceId), retry: false });
  const [reference, setReference] = useState(initialReference);
  const [url, setUrl] = useState('');
  const [linked, setLinked] = useState<{ id: string; duration: number; url: string } | null>(null);
  const [linkError, setLinkError] = useState('');
  const [resolving, setResolving] = useState(false);
  const linkInFlight = useRef(false);
  const [rights, setRights] = useState(false);
  const [speechLanguage, setSpeechLanguage] = useState<CreateCreativeProject['speechTimingLanguage']>();
  const [title, setTitle] = useState('');
  const [brief, setBrief] = useState('');
  const { user } = useAuth();
  const params = useSearchParams();
  useEffect(() => {
    if (!canEdit || !user?.id) return;
    const incoming = takeFirstBrief(params?.get('briefTicket') ?? null, 'video', user.id, workspaceId);
    if (incoming) setBrief(current => current || incoming);
  }, [canEdit, params, user?.id, workspaceId]);
  const [platform, setPlatform] = useState<CreativePlatform>('Instagram');
  const [aspect, setAspect] = useState<CreativeAspect>('9:16');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const active = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const request = useRef<{ body: string; id: string } | null>(null);
  const selected = library.videos.find(asset => asset.id === reference && (asset.duration ?? 0) <= 90) ??
    (linked?.id === reference ? linked : undefined);
  const eligible = !resolving && (!url.trim() || Boolean(linked)) && (!reference || Boolean(selected && rights)) && title.trim() && brief.trim();

  async function findReference() {
    if (!canEdit || busy || linkInFlight.current || !url.trim()) return;
    linkInFlight.current = true;
    setReference('');
    setLinked(null);
    setRights(false);
    setSpeechLanguage(undefined);
    setError('');
    setResolving(true);
    setLinkError('');
    try {
      const result = await api.creativeReferenceLink(workspaceId, url.trim());
      if (!active.current) return;
      setReference(result.assetId);
      setLinked({ id: result.assetId, duration: result.durationSeconds, url: url.trim() });
      setRights(false);
      setSpeechLanguage(undefined);
    } catch (reason) {
      if (active.current) setLinkError(reason instanceof Error ? reason.message : 'The workspace could not match this link.');
    } finally {
      linkInFlight.current = false;
      if (active.current) setResolving(false);
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!canEdit || !eligible || inFlight.current) return;
    const body = { referenceAssetId: reference || null, rightsConfirmed: Boolean(reference && rights), ...(linked && { referenceLink: linked.url }),
      ...(reference && speechLanguage && { speechTimingLanguage: speechLanguage }),
      title: title.trim(), brief: brief.trim(), platform, aspectRatio: aspect };
    const signature = JSON.stringify(body);
    if (request.current?.body !== signature) request.current = { body: signature, id: crypto.randomUUID() };
    inFlight.current = true;
    setBusy(true);
    setError('');
    try {
      const result = await api.creativeVideoCreate(workspaceId, { ...body, requestId: request.current.id });
      if (!active.current) return;
      client.setQueryData(projectKey(workspaceId, result.project.id), result);
      void client.invalidateQueries({ queryKey: listKey(workspaceId) });
      router.push(projectPath(result.project.id));
    } catch (reason) {
      if (!active.current) return;
      setError(reason instanceof Error ? reason.message : 'The blueprint could not be opened.');
      await projects.refetch();
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  return <PageContainer pageTitle='Video Studio' density='creative'
    pageHeaderAction={<Link href='/app/creative/example' className={buttonVariants({ variant: 'quiet', size: 'sm' })}>Compare a sample edit</Link>}
    pageDescription='Plan a brand video, produce the shots you need and edit the final cut.'>
    <div className={canEdit ? 'grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(18rem,0.85fr)]' : 'max-w-3xl'}>
      {canEdit && <Surface as='section' material='paper' padding='lg' aria-labelledby='new-video-heading'>
        <h2 className='mb-5 text-xl font-medium' id='new-video-heading'>New video</h2>
        <form onSubmit={event => void create(event)} className='grid gap-5'>
          <div className='grid gap-2'>
            <Label htmlFor='video-title'>Project name</Label>
            <Input id='video-title' required maxLength={120} disabled={busy} value={title} onChange={e => setTitle(e.target.value)} />
          </div>
          <div className='grid gap-2'>
            <Label htmlFor='video-brief'>What should your video show?</Label>
            <Textarea id='video-brief' required maxLength={1200} disabled={busy} value={brief} onChange={e => setBrief(e.target.value)}
              placeholder='Describe your product, who you want to reach and what they should do next.' />
          </div>
          <div className='rafii-quiet grid gap-1 rounded-xl p-3 text-sm'>
            <h3 className='font-medium'>Workspace brand</h3>
            <p>{[library.brand, library.product].filter(Boolean).join(' · ') || 'Use the product and audience in your brief.'}</p>
            <Link href='/app/workspace/brand' target='_blank' rel='noopener noreferrer'
              className='rafii-focus w-fit rounded-sm text-xs underline underline-offset-4'>Review Brand Brain (new tab)</Link>
          </div>
          <details className='rounded-xl border px-4' open={initialReference ? true : undefined}>
            <summary className='rafii-focus cursor-pointer rounded-sm py-3 text-sm font-medium'>Use a reference video (optional)</summary>
            <div className='grid gap-3 pb-4'>
              <VideoSelect id='reference-video' label='Reference video' library={library} value={selected ? reference : ''}
                linkedReference={linked?.id} disabled={busy || resolving} onChange={value => {
                  setReference(value); setRights(false); setSpeechLanguage(undefined); setError(''); setUrl(''); setLinked(null); setLinkError('');
                }} />
              <p className='text-xs text-muted-foreground'>Use the structure of a verified MP4 or MOV, up to 90 seconds and 64 MiB.</p>
              <div className='grid gap-2'>
                <Label htmlFor='reference-link'>Or find a video by YouTube link</Label>
                <div className='flex flex-wrap gap-2'>
                  <Input id='reference-link' type='url' maxLength={2048} className='min-w-0 flex-1'
                    placeholder='https://www.youtube.com/shorts/…' value={url} disabled={busy || resolving}
                    onChange={event => { setUrl(event.target.value); setLinkError(''); setReference(''); setRights(false); setSpeechLanguage(undefined); setLinked(null); }} />
                  <Button variant='glass' type='button' disabled={busy || resolving || !url.trim()}
                    onClick={() => void findReference()}>{resolving ? 'Finding video…' : linked ? 'Recheck link' : 'Find in workspace'}</Button>
                </div>
                <p className='text-xs text-muted-foreground'>Finds the original Library video for a verified public post on this workspace’s YouTube channel. For other references, upload a file you may analyze.</p>
                {linkError && <p role='alert' className='text-sm text-destructive'>{linkError}</p>}
                {linked && <p role='status' className='text-sm'>Matched your published video · {linked.duration} s</p>}
              </div>
              {reference && !selected && !library.query.isFetching && <div className='grid gap-2'>
                <p className='text-muted-foreground text-sm'>This reference is unavailable in the current workspace.</p>
                <Button type='button' variant='quiet' className='w-fit' onClick={() => { setReference(''); setRights(false); }}>Continue with my brief</Button>
              </div>}
              {selected && <>
                <PrivateVideo assetId={selected.id} key={selected.id} label='Play reference' />
                <div className='grid gap-2'>
                  <Label htmlFor='speech-timing-language'>Estimate speech timing in the first 15 seconds</Label>
                  <NativeSelect id='speech-timing-language' value={speechLanguage ?? ''} disabled={busy}
                    onChange={event => setSpeechLanguage(event.target.value as CreateCreativeProject['speechTimingLanguage'] || undefined)}>
                    <NativeSelectOption value=''>Off</NativeSelectOption>
                    <NativeSelectOption value='auto'>Detect language locally</NativeSelectOption>
                    <NativeSelectOption value='zh'>Chinese</NativeSelectOption>
                    <NativeSelectOption value='en'>English</NativeSelectOption>
                  </NativeSelect>
                </div>
                <div className='flex items-start gap-3'>
                  <Checkbox id='reference-rights' checked={rights} disabled={busy} onCheckedChange={value => setRights(value === true)} />
                  <Label htmlFor='reference-rights' className='leading-snug'>I have permission to analyze this reference and adapt its creative approach.</Label>
                </div>
              </>}
            </div>
          </details>
          <div className='grid gap-4 sm:grid-cols-2'>
            <div className='grid gap-2'>
              <Label htmlFor='video-platform'>Platform</Label>
              <NativeSelect id='video-platform' className='w-full [&_select]:h-10' value={platform} disabled={busy} onChange={e => setPlatform(e.target.value as CreativePlatform)}>
                <NativeSelectOption value='Instagram'>Instagram Reels</NativeSelectOption>
                <NativeSelectOption value='TikTok'>TikTok</NativeSelectOption>
                <NativeSelectOption value='YouTube'>YouTube</NativeSelectOption>
              </NativeSelect>
            </div>
            <div className='grid gap-2'>
              <Label htmlFor='video-aspect'>Frame</Label>
              <NativeSelect id='video-aspect' className='w-full [&_select]:h-10' value={aspect} disabled={busy} onChange={e => setAspect(e.target.value as CreativeAspect)}>
                <NativeSelectOption value='9:16'>Portrait · 9:16</NativeSelectOption>
                <NativeSelectOption value='1:1'>Square · 1:1</NativeSelectOption>
                <NativeSelectOption value='16:9'>Landscape · 16:9</NativeSelectOption>
              </NativeSelect>
            </div>
          </div>
          {error && <StateMessage kind='error' layout='inline' title='Could not open the new blueprint' description={error} />}
          <Button type='submit' variant='action' size='control' className='w-fit' disabled={!eligible || busy}>
            {busy ? 'Preparing blueprint…' : reference ? 'Analyze and create blueprint' : 'Create blueprint'}<Icons.arrowRight aria-hidden />
          </Button>
        </form>
      </Surface>}
      <Surface as='section' material='quiet' padding='lg' aria-labelledby='saved-video-heading'>
        <div className='mb-3 flex flex-wrap items-center justify-between gap-2'>
          <h2 className='text-lg font-medium' id='saved-video-heading'>Saved projects</h2>
          <Button variant='quiet' size='sm' disabled={projects.isFetching} onClick={() => void projects.refetch()}>Refresh</Button>
        </div>
        {projects.isError ? <StateMessage kind='error' layout='inline' title='Projects could not be loaded' description={projects.error.message} />
          : projects.isPending ? <StateMessage kind='loading' layout='inline' title='Loading projects…' />
          : projects.data.projects.length === 0 ? <p className='text-muted-foreground text-sm'>Your first blueprint will appear here.</p>
          : <ul className='grid gap-2'>
            {projects.data.projects.map(project => <CollectionRow as='li' key={project.id} leading={<Icons.video aria-hidden />}
              title={<Link href={projectPath(project.id)} className='rafii-focus rounded-sm underline-offset-4 hover:underline'>{project.title}</Link>}
              meta={`${project.sceneCount} ${project.sceneCount === 1 ? 'scene' : 'scenes'} · Revision ${project.revision}`} />)}
          </ul>}
        {canEdit && <div className='mt-6 flex flex-wrap gap-2 border-t pt-4'>
          <Link href='/app/workspace/brand' className={buttonVariants({ variant: 'glass', size: 'lg' })}>Brand Brain</Link>
          <Link href='/app/workspace/memory' className={buttonVariants({ variant: 'quiet', size: 'lg' })}>Creative Memory</Link>
        </div>}
      </Surface>
    </div>
  </PageContainer>;
}
