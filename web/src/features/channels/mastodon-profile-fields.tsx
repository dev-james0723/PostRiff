'use client';

import { useQuery } from '@tanstack/react-query';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useId, useState } from 'react';
import { AssetPicker } from '@/components/application/asset-picker';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useSnapshot } from '@/lib/api/hooks';

export type ProfileEdit = { profile: Record<string, unknown>; profileMedia: Record<string, { assetId: string; rightsConfirmed: boolean }> };

export function MastodonProfileFields({ onChange, connectionId }: { onChange: (value: ProfileEdit) => void; connectionId: string }) {
  const id = useId();
  const snapshot = useSnapshot();
  const { api, workspaceId } = useWorkspaceApi();
  const capability = useQuery({ queryKey: ['mastodon-capabilities', workspaceId, connectionId], queryFn: () => api.mastodonRead(workspaceId, connectionId, 'capabilities'), enabled: Boolean(workspaceId), staleTime: 60000, retry: false });
  const capabilities = capability.data?.capabilities as Record<string, unknown> | undefined;
  const version = String(capabilities?.version ?? '');
  const profileLimits = capabilities?.profileLimits as Record<string, unknown> | undefined;
  function limit(key: string, fallback: number) {
    const value = profileLimits?.[key];
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 100000 ? value : fallback;
  }
  function supports([major, minor, patch = 0]: readonly [number, number, number?]) {
    const found = /^(\d+)\.(\d+)\.(\d+)/.exec(version); if (!found) return false;
    const current = found.slice(1).map(Number), minimum = [major, minor, patch];
    for (let index = 0; index < 3; index++) if (current[index] !== minimum[index]) return current[index] > minimum[index];
    return true;
  }
  const [edit, setEdit] = useState<ProfileEdit>({ profile: {}, profileMedia: {} });
  const [rights, setRights] = useState(false);
  const [domainsText, setDomainsText] = useState('');
  const images = (snapshot.data?.state.phase2?.assets ?? []).filter((asset) => typeof asset.bytes === 'number' && asset.bytes <= 2 * 1024 ** 2 && ['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(asset.mime));
  function update(next: ProfileEdit) { setEdit(next); onChange(next); }
  function field(key: string, value: unknown) {
    const profile = { ...edit.profile };
    if (value === undefined) delete profile[key]; else profile[key] = value;
    update({ ...edit, profile });
  }
  function source(key: string, value: unknown) {
    const current = { ...(edit.profile.source as Record<string, unknown> | undefined) };
    if (value === undefined) delete current[key]; else current[key] = value;
    field('source', Object.keys(current).length ? current : undefined);
  }
  return <div className='flex min-w-0 flex-col gap-3 rounded border p-3'>
    <p className='text-muted-foreground text-xs'>{version ? `Server version ${version}. Unavailable preferences stay disabled.` : 'Checking server preferences…'}</p>
    <p className='text-muted-foreground text-xs'>Only selected fields change. Read “profile” above to inspect existing values. Server versions may limit available preferences.</p>
    {([['display_name', 'Display name', limit('max_display_name_length', 30)], ['note', 'Profile description', limit('max_note_length', 500)],
      ['avatar_description', 'Profile picture description', limit('max_avatar_description_length', 1500)],
      ['header_description', 'Header image description', limit('max_header_description_length', 1500)]] as const).map(([key, label, max]) => <div key={key} className='flex flex-col gap-2'>
      <Label htmlFor={`${id}-${key}-change`} className='flex items-center gap-2'><Checkbox id={`${id}-${key}-change`} checked={key in edit.profile} disabled={key.endsWith('_description') && !supports([4, 6, 1])} onCheckedChange={(checked) => field(key, checked === true ? '' : undefined)} />Change {label.toLowerCase()}</Label>
      {key in edit.profile && <label htmlFor={`${id}-${key}`} className='flex flex-col gap-1 text-sm'>{label}<Input id={`${id}-${key}`} maxLength={max} value={String(edit.profile[key] ?? '')} onChange={(event) => field(key, event.target.value)} /></label>}
    </div>)}
    {([['locked', 'Require approval for follows'], ['bot', 'Mark as bot'], ['discoverable', 'Show in profile directory'], ['hide_collections', 'Hide followers and following'], ['indexable', 'Allow public post search']] as const).map(([key, label]) => <div key={key} className='flex flex-col gap-1'>
      <Label htmlFor={`${id}-${key}`}>{label}</Label><Select value={key in edit.profile ? String(edit.profile[key]) : 'keep'} onValueChange={(value) => field(key, value === 'keep' ? undefined : value === 'true')}><SelectTrigger id={`${id}-${key}`} disabled={!supports((key === 'indexable' ? [4, 2] as const : key === 'hide_collections' ? [4, 1] as const : key === 'discoverable' ? [2, 7] as const : key === 'bot' ? [1, 1, 1] as const : [2, 3] as const))}><SelectValue /></SelectTrigger><SelectContent><SelectItem value='keep'>Keep current setting</SelectItem><SelectItem value='true'>Yes</SelectItem><SelectItem value='false'>No</SelectItem></SelectContent></Select>
    </div>)}
    {([['privacy', 'Default post visibility', [['public', 'Public'], ['unlisted', 'Unlisted'], ['private', 'Followers-only']]], ['sensitive', 'Sensitive media by default', [['true', 'Yes'], ['false', 'No']]], ['quote_policy', 'Who can quote new posts', [['public', 'Anyone'], ['followers', 'Followers'], ['nobody', 'Nobody']]]] as const).map(([key, label, choices]) => <div key={key} className='flex flex-col gap-1'>
      <Label htmlFor={`${id}-source-${key}`}>{label}</Label><Select value={String((edit.profile.source as Record<string, unknown> | undefined)?.[key] ?? 'keep')} onValueChange={(value) => source(key, value === 'keep' ? undefined : key === 'sensitive' ? value === 'true' : value)}><SelectTrigger id={`${id}-source-${key}`} disabled={!supports((key === 'quote_policy' ? [4, 5] as const : [2, 4] as const))}><SelectValue /></SelectTrigger><SelectContent><SelectItem value='keep'>Keep current setting</SelectItem>{choices.map(([value, text]) => <SelectItem key={value} value={value}>{text}</SelectItem>)}</SelectContent></Select>
    </div>)}
    <div className='flex flex-col gap-2'>
      <Label htmlFor={`${id}-language-change`} className='flex items-center gap-2'><Checkbox id={`${id}-language-change`} checked={'language' in ((edit.profile.source as Record<string, unknown> | undefined) ?? {})} disabled={!supports([2, 4, 2])} onCheckedChange={(checked) => source('language', checked === true ? '' : undefined)} />Change default post language</Label>
      {'language' in ((edit.profile.source as Record<string, unknown> | undefined) ?? {}) && <label htmlFor={`${id}-language`} className='flex flex-col gap-1 text-sm'>Default post language (two-letter code; blank clears it)<Input id={`${id}-language`} maxLength={2} value={String((edit.profile.source as Record<string, unknown>).language)} onChange={(event) => source('language', event.target.value.trim().toLowerCase())} /></label>}
    </div>
    <div className='flex flex-col gap-2'>
      <Label htmlFor={`${id}-metadata-change`} className='flex items-center gap-2'><Checkbox id={`${id}-metadata-change`} checked={'fields_attributes' in edit.profile} disabled={!supports([2, 4, 0])} onCheckedChange={(checked) => field('fields_attributes', checked === true ? [] : undefined)} />Replace profile metadata</Label>
      {'fields_attributes' in edit.profile && <>
        <p className='text-sm text-muted-foreground'>These rows replace all current profile metadata. Leaving no rows clears it.</p>
        {(edit.profile.fields_attributes as Array<{ name: string; value: string }>).map((row, index, rows) => <div key={index} className='flex flex-col gap-2 rounded border p-3'>
          {(['name', 'value'] as const).map((key) => <label key={key} htmlFor={`${id}-metadata-${index}-${key}`} className='flex flex-col gap-1 text-sm'>Metadata {index + 1} {key}<Input id={`${id}-metadata-${index}-${key}`} maxLength={limit(`profile_field_${key}_limit`, 255)} value={row[key]} onChange={(event) => field('fields_attributes', rows.map((item, at) => at === index ? { ...item, [key]: event.target.value } : item))} /></label>)}
          <Button type='button' variant='outline' onClick={() => field('fields_attributes', rows.filter((_item, at) => at !== index))}>Remove metadata {index + 1}</Button>
        </div>)}
        <Button type='button' variant='outline' disabled={(edit.profile.fields_attributes as unknown[]).length >= limit('max_profile_fields', 4)} onClick={() => field('fields_attributes', [...edit.profile.fields_attributes as object[], { name: '', value: '' }])}>Add metadata row</Button>
      </>}
    </div>
    <div className='flex flex-col gap-2'>
      <Label htmlFor={`${id}-attribution-change`} className='flex items-center gap-2'><Checkbox id={`${id}-attribution-change`} checked={'attribution_domains' in edit.profile} disabled={!supports([4, 4, 0])} onCheckedChange={(checked) => { setDomainsText(''); field('attribution_domains', checked === true ? [] : undefined); }} />Replace website attribution</Label>
      {'attribution_domains' in edit.profile && <label htmlFor={`${id}-attribution`} className='flex flex-col gap-1 text-sm'>Up to ten domains, one per line. Blank clears the current list.<textarea id={`${id}-attribution`} aria-label='Website attribution domains' className='min-h-24 rounded border p-2' maxLength={2540} value={domainsText} onChange={(event) => { setDomainsText(event.target.value); field('attribution_domains', event.target.value.split(/\r?\n/).map(domain => domain.trim()).filter(Boolean)); }} /></label>}
    </div>
    {(['avatar', 'header'] as const).map((role) => <div key={role} className='flex flex-col gap-1'><Label htmlFor={`${id}-${role}`}>{role === 'avatar' ? 'Profile picture' : 'Header image'} (up to 2 MB)</Label><AssetPicker id={`${id}-${role}`} aria-label={`${role} Library image`} assets={images} value={edit.profileMedia[role]?.assetId ?? ''} noneLabel='Keep current image' onValueChange={(assetId) => {
      const profileMedia = { ...edit.profileMedia }; if (assetId) profileMedia[role] = { assetId, rightsConfirmed: rights }; else delete profileMedia[role]; update({ ...edit, profileMedia });
    }} /></div>)}
    <Label htmlFor={`${id}-rights`} className='flex items-center gap-2'><Checkbox id={`${id}-rights`} checked={rights} onCheckedChange={(checked) => {
      const confirmed = checked === true; setRights(confirmed); update({ ...edit, profileMedia: Object.fromEntries(Object.entries(edit.profileMedia).map(([key, value]) => [key, { ...value, rightsConfirmed: confirmed }])) });
    }} />I have rights to use these profile images</Label>
  </div>;
}
