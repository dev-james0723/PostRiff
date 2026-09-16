'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Asset, SnapshotVariant } from '@/lib/api/types';

interface ScheduleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Preselect a draft (from the Pipeline card). */
  variantId?: string | null;
}

const pad = (n: number) => String(n).padStart(2, '0');

function defaultLocalTime() {
  const next = new Date(Date.now() + 60 * 60 * 1000);
  next.setMinutes(0, 0, 0);
  return `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}T${pad(next.getHours())}:${pad(next.getMinutes())}`;
}

/**
 * Prepares an exact review (`p2_review`): draft + channel + time (+ optional image).
 * The result is a review waiting in the Queue; approving it is a separate, explicit step.
 */
export function ScheduleDialog({ open, onOpenChange, variantId: preselected }: ScheduleDialogProps) {
  const snapshot = useSnapshot();
  const act = useAct();
  const router = useRouter();
  const state = snapshot.data?.state;
  const revision = snapshot.data?.revision ?? 0;

  const drafts = useMemo(() => (state?.variants ?? []).filter((v) => !v.blockedByRetraction), [state?.variants]);
  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const assets = useMemo(() => (state?.phase2?.assets ?? []).filter((a) => !a.deleted), [state?.phase2?.assets]);

  const [variantId, setVariantId] = useState<string>(preselected ?? '');
  const [channelId, setChannelId] = useState<string>('');
  const [assetId, setAssetId] = useState<string>('');
  const [alt, setAlt] = useState('');
  const [rights, setRights] = useState(false);
  const [acknowledge, setAcknowledge] = useState(false);
  const [resolveUnknowns, setResolveUnknowns] = useState(true);
  const [localTime, setLocalTime] = useState(defaultLocalTime);
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  const variant: SnapshotVariant | undefined = drafts.find((v) => v.id === (variantId || preselected));
  const channelsForVariant = channels.filter((c) => !variant || c.platform === variant.platform);
  const asset: Asset | undefined = assets.find((a) => a.id === assetId);
  const ready = Boolean(variant && channelId && localTime && rights && (!variant.warnings.length || acknowledge) && (!asset || alt.trim()));

  async function submit() {
    if (!variant) return;
    try {
      let currentRevision = revision;
      if (variant.needsReview && variant.unknowns.length && resolveUnknowns) {
        const reviewed = await act.mutateAsync({
          revision: currentRevision,
          action: 'p2_variant_review',
          payload: { variantId: variant.id, variantRevision: variant.revision, confirmed: true, excludedUnknowns: variant.unknowns }
        });
        currentRevision = reviewed.revision;
      }
      const result = await act.mutateAsync({
        revision: currentRevision,
        action: 'p2_review',
        payload: {
          variantId: variant.id,
          channelId,
          assetId: assetId || undefined,
          alt: alt.trim(),
          rightsConfirmed: rights,
          localTime,
          timeZone,
          acknowledgedWarnings: acknowledge ? variant.warnings : []
        }
      });
      const created = result.state.phase2?.reviews.at(-1);
      toast.success(created ? 'Review prepared. Approve it in the Queue to schedule.' : 'Review prepared.');
      onOpenChange(false);
      router.push('/app/queue');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The review could not be prepared.');
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='max-w-lg'>
        <DialogHeader>
          <DialogTitle>Schedule a draft</DialogTitle>
          <DialogDescription>Choose the draft, the account and the exact time. This prepares a review; nothing publishes until you approve it.</DialogDescription>
        </DialogHeader>
        <div className='flex flex-col gap-4'>
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='schedule-draft'>Draft</Label>
            <Select value={variantId || preselected || ''} onValueChange={(value) => { setVariantId(String(value)); setChannelId(''); }}>
              <SelectTrigger id='schedule-draft'>
                <SelectValue>{variant ? `${variant.platform} · ${variant.language === '繁體中文' ? '繁中' : 'EN'} — ${variant.text.slice(0, 40)}…` : 'Choose a draft'}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {drafts.length === 0 && <SelectItem value='__none' disabled>No drafts yet — add candidates from Ideas</SelectItem>}
                {drafts.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.platform} · {d.language === '繁體中文' ? '繁中' : 'EN'} — {d.text.slice(0, 48)}…
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {variant && variant.needsReview && variant.unknowns.length > 0 && (
              <Label className='flex items-start gap-2 text-xs font-normal'>
                <Checkbox checked={resolveUnknowns} onCheckedChange={(v) => setResolveUnknowns(v === true)} />
                <span>Confirm the {variant.unknowns.length} unknown{variant.unknowns.length === 1 ? '' : 's'} stay out of the draft (required before review)</span>
              </Label>
            )}
          </div>

          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='schedule-channel'>Account</Label>
            <Select value={channelId} onValueChange={(value) => setChannelId(String(value))}>
              <SelectTrigger id='schedule-channel' disabled={!variant}>
                <SelectValue>{channelsForVariant.find((c) => c.id === channelId)?.account ?? (variant ? `Choose a ${variant.platform} account` : 'Choose a draft first')}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {channelsForVariant.length === 0 && <SelectItem value='__none' disabled>No {variant?.platform ?? ''} account connected</SelectItem>}
                {channelsForVariant.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.platform} · {c.account}{c.displayState ? ` · ${c.displayState}` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className='grid gap-4 sm:grid-cols-2'>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='schedule-time'>Publish at</Label>
              <Input id='schedule-time' type='datetime-local' value={localTime} onChange={(e) => setLocalTime(e.target.value)} />
              <span className='text-muted-foreground text-xs'>{timeZone}</span>
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='schedule-asset'>Image (optional)</Label>
              <Select value={assetId} onValueChange={(value) => setAssetId(String(value) === '__none' ? '' : String(value))}>
                <SelectTrigger id='schedule-asset'>
                  <SelectValue>{asset ? `${asset.mime} · ${asset.hash.slice(0, 8)}…` : 'No image'}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value='__none'>No image</SelectItem>
                  {assets.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.mime} · {a.hash.slice(0, 8)}…
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {asset && (
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='schedule-alt'>Alt text</Label>
              <Input id='schedule-alt' value={alt} onChange={(e) => setAlt(e.target.value)} maxLength={300} placeholder='Describe the image for people who cannot see it' />
            </div>
          )}

          <Label className='flex items-start gap-2 text-sm font-normal'>
            <Checkbox checked={rights} onCheckedChange={(v) => setRights(v === true)} />
            <span>I have the rights to publish this text{asset ? ' and image' : ''} on this account.</span>
          </Label>
          {variant && variant.warnings.length > 0 && (
            <Label className='flex items-start gap-2 text-sm font-normal'>
              <Checkbox checked={acknowledge} onCheckedChange={(v) => setAcknowledge(v === true)} />
              <span>
                I acknowledge: {variant.warnings.join('; ')}
              </span>
            </Label>
          )}
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!ready || act.isPending} onClick={() => void submit()}>
            {act.isPending ? 'Preparing…' : 'Prepare review'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
