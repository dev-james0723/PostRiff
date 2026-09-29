'use client';

import { useEffect, useState } from 'react';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import type { SkillPreview } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';

import type { PickerItem, SkillLike } from './picker-items';

export function SkillPreviewReader({
  skill,
  onBack,
  onUse
}: {
  skill: SkillLike;
  onBack: () => void;
  onUse: (item: PickerItem) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const [preview, setPreview] = useState<SkillPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setPreview(null);
    setError(null);
    api.skillPreview(workspaceId, skill.id).then(
      (result) => {
        if (alive) setPreview(result);
      },
      () => {
        if (alive) setError('This skill could not be opened right now.');
      }
    );
    return () => {
      alive = false;
    };
  }, [api, skill.id, workspaceId]);

  const useSkill = () =>
    onUse({
      kind: 'skill',
      id: skill.id,
      label: skill.name,
      sublabel: skill.description || skill.version,
      search: [skill.description, skill.version].filter(Boolean).join('\n')
    });

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div className='flex items-start gap-3 border-b border-foreground/8 px-1 pb-3'>
        <Button
          variant='glass'
          size='icon-control'
          className='shrink-0 rounded-full'
          aria-label='Back to skills'
          onClick={onBack}
        >
          <Icons.chevronLeft aria-hidden className='size-4' />
        </Button>
        <div className='min-w-0 flex-1 pt-1'>
          <div className='flex items-center gap-2'>
            <Icons.sparkles aria-hidden className='text-muted-foreground size-4 shrink-0' />
            <h2 className='truncate text-base font-semibold'>{skill.name}</h2>
          </div>
          <p className='text-muted-foreground mt-1 text-xs leading-relaxed'>
            {skill.description || 'Installed Rafii skill'}
          </p>
          <p className='text-muted-foreground/75 mt-1 text-[11px]'>Version {skill.version}</p>
        </div>
      </div>

      <div className='min-h-0 flex-1 overflow-y-auto px-1 py-4'>
        {!preview && !error ? (
          <p role='status' className='text-muted-foreground py-8 text-center text-sm'>
            Opening skill...
          </p>
        ) : error ? (
          <p role='alert' className='text-muted-foreground py-8 text-center text-sm'>
            {error}
          </p>
        ) : preview ? (
          <article aria-label={skill.name + ' Markdown'} className='rounded-xl border border-foreground/8 bg-foreground/[0.025] p-4'>
            <pre className='m-0 whitespace-pre-wrap break-words font-sans text-sm leading-6 text-foreground/90'>
              {preview.body}
            </pre>
          </article>
        ) : null}
      </div>

      <div className='border-t border-foreground/8 pt-3'>
        <Button className='w-full' disabled={!preview} onClick={useSkill}>
          Use skill
        </Button>
      </div>
    </div>
  );
}
