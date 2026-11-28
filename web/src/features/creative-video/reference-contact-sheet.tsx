'use client';

import Image from 'next/image';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import type { CreativeProject, ReferenceFrames } from '@/lib/api/creative-video';
import { useWorkspaceApi } from '@/lib/workspace/provider';

type Shot = Omit<ReferenceFrames['frames'][number], 'jpeg'> & { url: string | null };
const seconds = (ms: number) => `${ms / 1000} s`;

function FramePage({ id, revision, page, onPage }: {
  id: string; revision: number; page: number; onPage: (page: number) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const [read, setRead] = useState<{ shots: Shot[]; pages: number } | null>(null);
  const [problem, setProblem] = useState('');
  useEffect(() => {
    const request = new AbortController();
    const urls: string[] = [];
    function release() { for (const url of urls.splice(0)) URL.revokeObjectURL(url); }
    async function load() {
      try {
        const result = await api.creativeReferenceFrames(workspaceId, id, revision, page, request.signal);
        if (request.signal.aborted) return;
        const shots = result.frames.map(({ jpeg, ...shot }) => {
          if (!jpeg) return { ...shot, url: null };
          const bytes = Uint8Array.from(atob(jpeg), char => char.charCodeAt(0));
          const url = URL.createObjectURL(new Blob([bytes], { type: 'image/jpeg' }));
          urls.push(url);
          return { ...shot, url };
        });
        setRead({ shots, pages: result.pageCount });
      } catch (e) {
        release();
        if (!request.signal.aborted) setProblem(e instanceof Error ? e.message : 'The reference frames could not be loaded.');
      }
    }
    void load();
    return () => { request.abort(); release(); };
  }, [api, workspaceId, id, revision, page]);
  if (problem) return <p role='alert' className='text-destructive'>{problem}</p>;
  if (!read) return <p role='status'>Reading reference frames…</p>;
  return <div className='grid gap-3'>
    <div className='grid grid-cols-2 gap-3'>
      {read.shots.map(shot => <figure key={shot.shotIndex} className='grid content-start gap-1'>
        {shot.url && <Image src={shot.url} width={shot.width} height={shot.height} alt={`Reference shot ${shot.shotIndex + 1}`}
          unoptimized className='h-28 w-full rounded bg-black object-contain' />}
        <figcaption className='text-xs'><strong>Shot {shot.shotIndex + 1}</strong> · {seconds(shot.startMs)}–{seconds(shot.endMs)}<br />
          {shot.timeMs == null ? 'No decoded frame in this interval' : `Frame at ${seconds(shot.timeMs)}`}</figcaption>
      </figure>)}
    </div>
    {read.pages > 1 && <nav aria-label='Reference frame pages' className='flex flex-wrap items-center gap-2'>
      <Button type='button' variant='quiet' size='sm' disabled={page === 0} onClick={() => onPage(page - 1)}>Previous shots</Button>
      <span>Page {page + 1} of {read.pages}</span>
      <Button type='button' variant='quiet' size='sm' disabled={page + 1 >= read.pages} onClick={() => onPage(page + 1)}>Next shots</Button>
    </nav>}
  </div>;
}

function Sheet({ id, revision }: { id: string; revision: number }) {
  const [page, setPage] = useState<number | null>(null);
  return <div className='grid gap-2'>
    <Button type='button' variant='quiet' size='sm' className='w-fit' aria-expanded={page != null}
      onClick={() => setPage(page == null ? 0 : null)}>{page == null ? 'Show shot frames' : 'Hide shot frames'}</Button>
    {page != null && <FramePage key={page} id={id} revision={revision} page={page} onPage={setPage} />}
  </div>;
}

export function ReferenceContactSheet({ project }: { project: CreativeProject }) {
  const { workspaceId } = useWorkspaceApi();
  return <Sheet key={JSON.stringify([workspaceId, project.id, project.revision, project.referenceAssetId])}
    id={project.id} revision={project.revision} />;
}
