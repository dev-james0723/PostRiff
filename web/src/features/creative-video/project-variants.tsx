'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import type { CreativeAspect, CreativePlatform } from '@/lib/api/creative-video';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const platforms: readonly CreativePlatform[] = ['Instagram', 'TikTok', 'YouTube'];
const labels = { Instagram: 'Instagram Reels', TikTok: 'TikTok', YouTube: 'YouTube' };
type Variant = { id: string; platform: CreativePlatform; aspectRatio: CreativeAspect };

export function ProjectVariants({ projectId, revision, disabled }: { projectId: string; revision: number; disabled: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [choices, setChoices] = useState<Partial<Record<CreativePlatform, CreativeAspect>>>({});
  const [rights, setRights] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState<Variant[]>([]);
  const request = useRef<{ signature: string; id: string } | null>(null);
  const submitting = useRef(false);
  const targets = platforms.flatMap(platform => choices[platform] ? [{ platform, aspectRatio: choices[platform]! }] : []);

  async function create() {
    if (disabled || submitting.current || !rights || !targets.length || saved.length) return;
    const signature = JSON.stringify([workspaceId, projectId, revision, targets]);
    if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
    submitting.current = true;
    setPending(true);
    setError('');
    try {
      const reply = await api.creativeVideoVariants(workspaceId, projectId, { revision, targets, requestId: request.current.id, reuseRightsConfirmed: true });
      setSaved(reply.projects);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The versions could not be saved.');
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  return <details className='border-t pt-3 text-sm'>
    <summary className='rafii-focus cursor-pointer rounded-sm font-medium'>Create platform versions</summary>
    <div className='mt-3 grid gap-3'>
      <p className='text-muted-foreground'>Start from revision {revision}. Each project reuses the assigned Library footage and accepted takes. You can edit its hook, captions and framing separately.</p>
      {platforms.map(platform => <div key={platform} className='grid gap-1'>
        <Label htmlFor={`variant-${platform}`}>{labels[platform]}</Label>
        <NativeSelect id={`variant-${platform}`} value={choices[platform] ?? ''} disabled={pending || disabled}
          onChange={event => { setChoices(previous => ({ ...previous, [platform]: event.target.value || undefined })); setRights(false); setSaved([]); setError(''); }}>
          <NativeSelectOption value=''>Skip this platform</NativeSelectOption>
          <NativeSelectOption value='9:16'>Portrait · 9:16</NativeSelectOption>
          <NativeSelectOption value='1:1'>Square · 1:1</NativeSelectOption>
          <NativeSelectOption value='16:9'>Landscape · 16:9</NativeSelectOption>
        </NativeSelect>
      </div>)}
      <div className='flex items-start gap-2'>
        <Checkbox id='variant-rights' checked={rights} disabled={pending || disabled || !targets.length || Boolean(saved.length)}
          onCheckedChange={value => setRights(value === true)} />
        <Label htmlFor='variant-rights'>I can reuse these materials for the selected destinations.</Label>
      </div>
      <Button variant='glass' className='w-fit' disabled={disabled || pending || !rights || !targets.length || Boolean(saved.length)}
        onClick={() => void create()}>{pending ? 'Saving versions…' : 'Create editable versions'}</Button>
      {error && <p role='alert' className='text-destructive'>{error}</p>}
      {saved.length > 0 && <ul aria-label='Saved versions' className='grid gap-1'>
        {saved.map(item => <li key={item.id}><Link href={`/app/creative?project=${encodeURIComponent(item.id)}`}
          className='rafii-focus rounded-sm underline underline-offset-4'>Open {labels[item.platform]} · {item.aspectRatio}</Link></li>)}
      </ul>}
    </div>
  </details>;
}
