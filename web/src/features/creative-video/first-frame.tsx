'use client';

import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { useAssetImage } from '@/features/library/asset-card';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import type { CreativeSettings } from '@/lib/api/creative-video';
import type { Asset } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { isPostableImage } from '@/lib/media/asset-kinds';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export const firstFrameModel = 'veo-3.1-fast-generate-001';

function PhotoPreview({ photo }: { photo: Asset }) {
  const preview = useAssetImage(photo.id);
  return preview.data ? <Image src={preview.data} alt={photo.displayTitle || 'Selected first frame'} unoptimized
    width={160} height={100} className='h-24 w-40 rounded object-contain' /> : null;
}

export function FirstFramePicker({ enabled, disabled, settings, onChange }: {
  enabled: boolean; disabled: boolean; settings: CreativeSettings; onChange: (value: CreativeSettings) => void;
}) {
  const snapshot = useSnapshot();
  const { workspaceId } = useWorkspaceApi();
  const owner = checkAccess(useWorkspaceAccess(), { permission: 'owner' });
  const action = useAct();
  const state = snapshot.data?.state;
  const decision = state?.mediaEgress as { firstFrame?: { processor?: string; grantId?: string } } | undefined;
  const grant = decision?.firstFrame;
  const allowed = Boolean(grant?.grantId && grant.processor === `vertex-veo:${firstFrameModel}`);
  if (!enabled && !allowed && !settings.firstFrameAssetId) return null;
  const photos = (state?.phase2?.assets ?? []).filter(photo => isPostableImage(photo) && !photo.sourceId &&
    photo.mime === 'image/jpeg' && photo.storagePath === `${workspaceId}/media/${photo.id}-${photo.hash}.jpg`);
  const selected = photos.find(photo => photo.id === settings.firstFrameAssetId);
  function select(assetId: string) {
    const { firstFrameAssetId: _old, firstFrameConsent: _consent, ...rest } = settings;
    onChange(assetId ? { ...rest, firstFrameAssetId: assetId, firstFrameConsent: false } : rest);
  }
  function permission(cloud: boolean) {
    if (!snapshot.data || !owner) return;
    const message = cloud
      ? 'Allow workspace approvers to send a selected private Library photo to Google Cloud Veo 3.1 Fast as the first frame of an explicitly approved video take?'
      : 'Revoke Google Cloud Veo first-frame permission for this workspace? Outstanding first-frame quotes will expire.';
    if (!window.confirm(message)) return;
    action.mutate({ revision: snapshot.data.revision, action: 'media_egress', payload: { purpose: 'video_first_frame', cloud, confirmed: true } },
      { onSuccess: () => { if (!cloud && settings.firstFrameAssetId) select(''); } });
  }
  return <details className='rounded-xl border px-4'>
    <summary className='rafii-focus cursor-pointer rounded-sm py-3 text-sm font-medium'>First frame from Library</summary>
    <fieldset className='grid gap-3 pb-4' disabled={disabled || action.isPending}>
      {allowed && enabled && <>
        <Label htmlFor='scene-first-frame'>Opening photo</Label>
        <NativeSelect id='scene-first-frame' value={settings.firstFrameAssetId ?? ''} onChange={e => select(e.target.value)}>
          <NativeSelectOption value=''>Generate from direction only</NativeSelectOption>
          {settings.firstFrameAssetId && !selected && <NativeSelectOption value={settings.firstFrameAssetId}>Selected photo unavailable</NativeSelectOption>}
          {photos.map(photo => <NativeSelectOption key={photo.id} value={photo.id}>
            {photo.displayTitle || photo.originalFilename || `Photo ${photo.id.slice(0, 8)}`} · {photo.width} × {photo.height}
          </NativeSelectOption>)}
        </NativeSelect>
        {!photos.length && <a href='/app/library' target='_blank' rel='noopener noreferrer' className='text-sm underline'>Upload a product photo in Library</a>}
        {selected && <><PhotoPreview photo={selected} /><div className='flex items-start gap-3'>
          <Checkbox id='first-frame-rights' checked={settings.firstFrameConsent === true}
            onCheckedChange={value => onChange({ ...settings, firstFrameConsent: value === true })} />
          <Label htmlFor='first-frame-rights' className='min-h-8 leading-snug'>
            I have permission to send this photo to Google Cloud Veo for this scene.
          </Label>
        </div></>}
      </>}
      {!allowed && <p className='text-sm'>A workspace owner can allow Google Cloud Veo to use selected Library photos as opening frames.</p>}
      {!enabled && allowed && <p className='text-sm'>Google Cloud Veo is currently unavailable for this scene.</p>}
      {settings.firstFrameAssetId && (!allowed || !enabled) && <Button type='button' variant='quiet' className='w-fit'
        onClick={() => select('')}>Remove first frame</Button>}
      {owner && <Button type='button' variant='quiet' className='w-fit' disabled={!snapshot.data || (!enabled && !allowed)}
        onClick={() => permission(!allowed)}>{allowed ? 'Revoke workspace first-frame permission' : 'Allow first frames for this workspace'}</Button>}
      {action.isError && <p className='text-sm text-destructive' role='alert'>{action.error instanceof Error ? action.error.message : 'The permission could not be saved.'}</p>}
    </fieldset>
  </details>;
}
