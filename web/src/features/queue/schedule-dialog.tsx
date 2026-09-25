'use client';

import { publishingSupport } from '@/lib/channels/publishing-support';

import { useMemo, useState, type ReactNode } from 'react';
import { useTimeZone } from '@/lib/preferences';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { now as zonedNow, parseDateTime, toCalendarDateTime, toZoned } from '@internationalized/date';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Asset, SnapshotVariant } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { AssetPicker } from '@/components/application/asset-picker';
import { languageLabel } from '@/lib/locales';
import { workflowKey } from '@/lib/time-back/active-time';
import { useActiveWorkTimer } from '@/lib/time-back/use-active-work-timer';

interface ScheduleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Preselect a draft (from a draft card in Queue → Drafts). */
  variantId?: string | null;
  assetId?: string | null;
  /**
   * Called once the review exists, instead of the default of opening the Queue (where it waits for approval).
   * Lets a page that shows reviews itself, such as the Calendar, keep the person where they are.
   */
  onPrepared?: () => void;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** "an Instagram account", "a LinkedIn account". */
const withArticle = (word: string) => `${/^[aeiou]/i.test(word) ? 'an' : 'a'} ${word}`;

/** A caution beside a field: icon + plain text in the monochrome system (DNA §11.4, §20.4), never a tinted line. */
function Note({ children, role, className }: { children: ReactNode; role?: 'status'; className?: string }) {
  return (
    <p role={role} className={`text-muted-foreground flex items-start gap-1.5 text-xs ${className ?? ''}`}>
      <Icons.warning aria-hidden className='mt-0.5 size-3.5 shrink-0' />
      <span className='min-w-0'>{children}</span>
    </p>
  );
}

/** The next whole hour on the wall clock of the zone the review is prepared in (the person's zone, not the browser's). */
function defaultLocalTime(timeZone: string) {
  try {
    const next = zonedNow(timeZone).add({ hours: 1 }).set({ minute: 0, second: 0, millisecond: 0 });
    return `${next.year}-${pad(next.month)}-${pad(next.day)}T${pad(next.hour)}:${pad(next.minute)}`;
  } catch {
    const next = new Date(Date.now() + 60 * 60 * 1000);
    next.setMinutes(0, 0, 0);
    return `${next.getFullYear()}-${pad(next.getMonth() + 1)}-${pad(next.getDate())}T${pad(next.getHours())}:${pad(next.getMinutes())}`;
  }
}

type WallTime =
  | { kind: 'invalid' }
  /** Clocks jump over this local time (the server refuses it). */
  | { kind: 'gap' }
  | { kind: 'exact'; at: number }
  /** Clocks fall back over this local time, so it happens twice (the server asks which one: `fold` 0 or 1). */
  | { kind: 'ambiguous'; first: number; second: number };

/** Where a `datetime-local` value lands in an IANA zone, read the way `contracts.resolve_time` reads it. */
function resolveWallTime(local: string, timeZone: string): WallTime {
  try {
    const wall = parseDateTime(local);
    const earlier = toZoned(wall, timeZone, 'earlier');
    const later = toZoned(wall, timeZone, 'later');
    if (earlier.offset === later.offset) return { kind: 'exact', at: earlier.toDate().getTime() };
    const lands = (zoned: typeof earlier) => toCalendarDateTime(zoned).compare(wall) === 0;
    if (lands(earlier) && lands(later)) return { kind: 'ambiguous', first: earlier.toDate().getTime(), second: later.toDate().getTime() };
    return { kind: 'gap' };
  } catch {
    return { kind: 'invalid' };
  }
}

function offsetLabel(at: number, timeZone: string) {
  try {
    return new Intl.DateTimeFormat(undefined, { timeZone, hour: '2-digit', minute: '2-digit', timeZoneName: 'shortOffset' }).format(at);
  } catch {
    return null;
  }
}

interface EditSteps {
  /** A version written with the current voice profile is waiting to become the draft text. */
  updateWaiting: boolean;
  /** The review is made from that waiting version, accepted first. */
  usesUpdate: boolean;
  /** The unknowns and warnings of the text the review is made from. */
  unknowns: string[];
  warnings: string[];
  /** The draft (or its unknowns) must be confirmed before a review of it can exist. */
  confirmUnknowns: boolean;
  /** Edit steps this person cannot take, in plain words; empty when nothing stands in the way. */
  needsEditor: string[];
  blocked: boolean;
}

/**
 * The edit-class steps a draft needs before `p2_review`, and which of them this person cannot take. Someone who can
 * edit accepts a waiting version first (its unknowns and warnings then apply); someone who cannot reviews the draft
 * as it is, which only works when that draft was written with the current voice profile. Checked up front so nobody
 * is left halfway through the steps after a 403.
 */
function editSteps(variant: SnapshotVariant | undefined, activeVoice: number | null, canEdit: boolean): EditSteps {
  if (!variant) return { updateWaiting: false, usesUpdate: false, unknowns: [], warnings: [], confirmUnknowns: false, needsEditor: [], blocked: false };
  const update = variant.proposedUpdate && variant.proposedUpdate.voiceRevision === activeVoice ? variant.proposedUpdate : null;
  const acceptRequired = Boolean(update) && variant.voiceRevision !== activeVoice;
  const usesUpdate = Boolean(update) && (canEdit || acceptRequired);
  const unknowns = usesUpdate && update ? update.unknowns : variant.unknowns;
  const warnings = usesUpdate && update ? update.warnings : variant.warnings;
  // Accepting a version clears `needsReview` (`domain.py` accept_update); its own unknowns still need confirming.
  const confirmUnknowns = usesUpdate ? unknowns.length > 0 : variant.needsReview || unknowns.length > 0;
  const steps = { updateWaiting: Boolean(update), usesUpdate, unknowns, warnings, confirmUnknowns };
  if (canEdit) return { ...steps, needsEditor: [], blocked: false };
  const needsEditor: string[] = [];
  if (acceptRequired) needsEditor.push('accept the updated version');
  if (confirmUnknowns) {
    needsEditor.push(
      unknowns.length > 0
        ? `confirm ${unknowns.length === 1 ? 'its unknown detail stays' : `its ${unknowns.length} unknown details stay`} out`
        : 'confirm the draft as written'
    );
  }
  return { ...steps, needsEditor, blocked: needsEditor.length > 0 };
}

/**
 * Prepares an exact review (`p2_review`): draft + channel + time (+ optional image).
 * The result is a review waiting in the Queue; approving it is a separate, explicit step.
 */
export function ScheduleDialog({ open, onOpenChange, variantId: preselected, assetId: preselectedAsset, onPrepared }: ScheduleDialogProps) {
  const snapshot = useSnapshot();
  const access = useWorkspaceAccess();
  // Preparing a review is in the server's approve class (`permissions.py`); say so before anyone fills the form in.
  const canPrepare = checkAccess(access, { permission: 'approve' });
  // Accepting a waiting version (`accept_update`) and confirming unknowns (`p2_variant_review`) are not in
  // ACTION_CLASSES, so the server treats them as edits: an approver who cannot edit is refused both.
  const canEdit = checkAccess(access, { permission: 'edit' });
  const act = useAct();
  const router = useRouter();
  const pathname = usePathname();
  const state = snapshot.data?.state;
  const revision = snapshot.data?.revision ?? 0;

  const activeVoice = state?.speaker?.activeRevision ?? null;
  const usable = (v: SnapshotVariant) => v.voiceRevision === activeVoice || v.proposedUpdate?.voiceRevision === activeVoice;
  const drafts = useMemo(() => (state?.variants ?? []).filter((v) => !v.blockedByRetraction && usable(v)), [state?.variants, activeVoice]); // eslint-disable-line react-hooks/exhaustive-deps
  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const assets = useMemo(() => (state?.phase2?.assets ?? []).filter((a) => !a.deleted), [state?.phase2?.assets]);
  const voiceActive = Boolean(state?.speaker?.activeRevision);
  const staleDrafts = (state?.variants ?? []).filter((v) => !v.blockedByRetraction && !usable(v)).length;

  const [variantId, setVariantId] = useState<string>(preselected ?? '');
  // Time back: reviewing and scheduling this draft is part of its work; measured only while the dialog is open.
  useActiveWorkTimer({ workflowKey: workflowKey('variant', variantId || preselected), taskKind: 'draft', enabled: open });
  const [chosenChannelId, setChannelId] = useState<string>('');
  const [assetId, setAssetId] = useState<string>(preselectedAsset ?? '');
  const [alt, setAlt] = useState('');
  const [rights, setRights] = useState(false);
  const [acknowledge, setAcknowledge] = useState(false);
  const [resolveUnknowns, setResolveUnknowns] = useState(true);
  const timeZone = useTimeZone();
  const [localTime, setLocalTime] = useState(() => defaultLocalTime(timeZone));
  const [fold, setFold] = useState<0 | 1>(0);
  // The server's own word that the time occurs twice, for a zone rule this browser resolves differently.
  const [serverAsksFold, setServerAsksFold] = useState(false);
  const wallTime = useMemo(() => resolveWallTime(localTime, timeZone), [localTime, timeZone]);
  const askFold = wallTime.kind === 'ambiguous' || serverAsksFold;
  const chosenAt = wallTime.kind === 'exact' ? wallTime.at : wallTime.kind === 'ambiguous' ? (fold === 0 ? wallTime.first : wallTime.second) : null;
  const timePassed = chosenAt !== null && chosenAt <= Date.now();

  const variant: SnapshotVariant | undefined = drafts.find((v) => v.id === (variantId || preselected));
  // A draft written for one account can only be scheduled to that account; a platform-level draft needs an explicit choice.
  const channelsForVariant = channels.filter((c) => !variant || (c.platform === variant.platform && (!variant.channelId || c.id === variant.channelId)));
  const channelId = variant?.channelId ?? chosenChannelId;
  const asset: Asset | undefined = assets.find((a) => a.id === assetId);
  const channel = channelsForVariant.find((c) => c.id === channelId);
  const steps = editSteps(variant, activeVoice, canEdit);
  const ready = Boolean(
    variant &&
      channel &&
      localTime &&
      rights &&
      !steps.blocked &&
      (!steps.warnings.length || acknowledge) &&
      (!asset || alt.trim()) &&
      (!steps.confirmUnknowns || resolveUnknowns)
  );

  async function submit() {
    if (!variant) return;
    try {
      let currentRevision = revision;
      let current: SnapshotVariant = variant;
      // 1. A regenerated version (e.g. written after the voice profile changed) is accepted first. Someone who cannot
      //    edit never sends it: `ready` only lets them through when the draft as it stands can be reviewed.
      if (canEdit && steps.usesUpdate && current.proposedUpdate && current.proposedUpdate.voiceRevision === activeVoice) {
        const accepted = await act.mutateAsync({ revision: currentRevision, action: 'accept_update', payload: { variantId: current.id } });
        currentRevision = accepted.revision;
        current = accepted.state.variants?.find((v) => v.id === current.id) ?? current;
      }
      // 2. Unknown facts must be confirmed as excluded before an exact review can exist (`store.py` refuses a draft
      //    that still needs review or still lists unknowns).
      if (canEdit && (current.needsReview || current.unknowns.length > 0) && resolveUnknowns) {
        const reviewed = await act.mutateAsync({
          revision: currentRevision,
          action: 'p2_variant_review',
          payload: { variantId: current.id, variantRevision: current.revision, confirmed: true, excludedUnknowns: current.unknowns }
        });
        currentRevision = reviewed.revision;
        current = reviewed.state.variants?.find((v) => v.id === current.id) ?? current;
      }
      // 3. Freeze text, media, account and time into a review.
      await act.mutateAsync({
        revision: currentRevision,
        action: 'p2_review',
        payload: {
          variantId: current.id,
          channelId,
          assetId: assetId || undefined,
          alt: alt.trim(),
          rightsConfirmed: rights,
          localTime,
          timeZone,
          acknowledgedWarnings: acknowledge ? current.warnings : [],
          fold: askFold ? fold : undefined
        }
      });
      // The Queue (or the Calendar) shows the new review; a short toast says where it went.
      toast.success('Ready for review');
      onOpenChange(false);
      if (onPrepared) onPrepared();
      else if (pathname !== '/app/queue') router.push('/app/queue');
    } catch (err) {
      if (err instanceof ApiError && /occurs twice/i.test(err.message)) {
        setServerAsksFold(true);
        toast.error('This time happens twice that day. Pick one, then try again.');
        return;
      }
      toast.error('Couldn’t prepare this post', { description: err instanceof ApiError ? err.message : undefined });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] p-5 ring-0 sm:max-w-lg sm:rounded-[var(--rafii-radius-dialog)] sm:p-6 [&_[data-slot=dialog-close]]:top-3 [&_[data-slot=dialog-close]]:right-3 [&_[data-slot=dialog-close]]:size-10 [&_[data-slot=dialog-close]]:rounded-full'>
        <DialogHeader>
          <DialogTitle className='text-lg font-medium tracking-tight'>Schedule a draft</DialogTitle>
          <DialogDescription>Nothing publishes until you approve it.</DialogDescription>
        </DialogHeader>
        {!state ? (
          // Without the workspace there is nothing to choose from yet, and no reason to ask for a voice profile.
          snapshot.isError ? (
            <div className='flex flex-col items-start gap-2 text-sm'>
              <p>
                Couldn’t load your drafts
                {snapshot.error instanceof ApiError && <span className='text-muted-foreground block text-xs'>{snapshot.error.message}</span>}
              </p>
              <Button variant='glass' size='control' className='h-11' onClick={() => void snapshot.refetch()}>
                Try again
              </Button>
            </div>
          ) : (
            <div className='flex flex-col gap-3' aria-hidden>
              <Skeleton className='h-9 w-full' />
              <Skeleton className='h-9 w-full' />
              <Skeleton className='h-9 w-2/3' />
            </div>
          )
        ) : (
        <div className='flex flex-col gap-4'>
          {!voiceActive && (
            <Note className='text-sm'>
              No voice profile yet. Check the wording.{' '}
              <Link href='/app/workspace/brand' onClick={() => onOpenChange(false)} className='text-foreground underline underline-offset-2'>
                Set up your voice
              </Link>
            </Note>
          )}
          {!canPrepare && <Note>Only approvers can schedule posts.</Note>}
          {staleDrafts > 0 && (
            <p className='text-muted-foreground text-xs'>
              {staleDrafts} draft{staleDrafts === 1 ? ' uses' : 's use'} an older voice and can’t be scheduled.
            </p>
          )}
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='schedule-draft'>Draft</Label>
            <Select value={variantId || preselected || ''} onValueChange={(value) => { setVariantId(String(value)); setChannelId(''); }}>
              <SelectTrigger id='schedule-draft' className='h-12 w-full text-base'>
                {/* The draft's language exactly as stored, never folded into a two-language label. One line, cut to the field's width. */}
                <SelectValue className='min-w-0'>
                  <span className='truncate'>{variant ? `${variant.platform} · ${languageLabel(variant.language)} — ${variant.text.slice(0, 40)}…` : 'Choose a draft'}</span>
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {drafts.length === 0 && <SelectItem value='__none' disabled>No drafts yet</SelectItem>}
                {drafts.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    <span className='flex items-center gap-2'>
                      <ChannelIcon platform={d.platform} name={d.platform} size='xs' />
                      {d.platform} · {languageLabel(d.language)} — {d.text.slice(0, 48)}…
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {steps.updateWaiting && canEdit && <p className='text-muted-foreground text-xs'>Uses the updated version in your current voice.</p>}
            {steps.updateWaiting && !canEdit && !steps.blocked && <p className='text-muted-foreground text-xs'>Uses the draft as it is; an editor can accept the update.</p>}
            {canPrepare && steps.blocked && (
              // Accepting a version and confirming unknowns are edits, which this person cannot make; nothing is sent.
              <Note role='status'>An editor needs to {steps.needsEditor.join(' and ')} first.</Note>
            )}
            {variant && canEdit && steps.confirmUnknowns && (
              <Label className='flex items-start gap-2 text-xs font-normal'>
                <Checkbox checked={resolveUnknowns} onCheckedChange={(v) => setResolveUnknowns(v === true)} />
                <span>
                  {steps.unknowns.length > 0
                    ? `Leave out ${steps.unknowns.length === 1 ? 'the unknown detail' : `the ${steps.unknowns.length} unknown details`} (required)`
                    : 'Confirm the draft as written (required)'}
                </span>
              </Label>
            )}
          </div>

          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='schedule-channel'>Account</Label>
            <Select value={channelId} onValueChange={(value) => setChannelId(String(value))}>
              <SelectTrigger id='schedule-channel' disabled={!variant || Boolean(variant.channelId)} className='h-12 w-full text-base'>
                <SelectValue className='min-w-0'>
                  <span className='truncate'>{channelsForVariant.find((c) => c.id === channelId)?.account ?? (variant ? `Choose ${withArticle(variant.platform)} account` : 'Choose a draft first')}</span>
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {channelsForVariant.length === 0 && <SelectItem value='__none' disabled>{variant?.channelId ? `The ${variant.platform} account this draft was written for is not connected` : `No ${variant?.platform ?? ''} account connected`}</SelectItem>}
                {channelsForVariant.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    <span className='flex items-center gap-2'>
                      <ChannelIcon platform={c.platform} name={c.platform} size='xs' />
                      {c.platform} · {c.account}{c.displayState ? ` · ${c.displayState}` : ''}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {variant && channelsForVariant.length === 0 && (
              <Link href='/app/channels' className='text-muted-foreground hover:text-foreground w-fit text-xs underline underline-offset-2' onClick={() => onOpenChange(false)}>
                Connect {withArticle(variant.platform)} account
              </Link>
            )}
            {channel?.displayState && channel.displayState !== 'Ready for posting' ? (
              <Note>
                Not ready to post ({channel.displayState}).{' '}
                <Link href='/app/channels' className='text-foreground underline underline-offset-2' onClick={() => onOpenChange(false)}>
                  Open Channels
                </Link>
              </Note>
            ) : (
              channel && <p className='text-muted-foreground text-xs'>{publishingSupport(channel.platform)}</p>
            )}
          </div>

          <div className='grid gap-4 sm:grid-cols-2'>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='schedule-time'>Publish at</Label>
              <Input
                id='schedule-time'
                type='datetime-local'
                className='text-base md:text-sm'
                value={localTime}
                onChange={(e) => {
                  setLocalTime(e.target.value);
                  setServerAsksFold(false);
                }}
              />
              <span className='text-muted-foreground text-xs'>{timeZone}</span>
              {timePassed && <Note>Pick a future time.</Note>}
              {wallTime.kind === 'gap' && <Note>Clocks skip this time. Pick another.</Note>}
            </div>
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='schedule-asset'>Image (optional)</Label>
              <AssetPicker id='schedule-asset' assets={assets} value={assetId} onValueChange={setAssetId} />
            </div>
          </div>

          {askFold && (
            <div className='flex flex-col gap-1.5'>
              <Label id='schedule-fold-label'>This time happens twice that day</Label>
              <RadioGroup aria-labelledby='schedule-fold-label' value={String(fold)} onValueChange={(value) => setFold(value === '1' ? 1 : 0)}>
                {([0, 1] as const).map((option) => {
                  const at = wallTime.kind === 'ambiguous' ? (option === 0 ? wallTime.first : wallTime.second) : null;
                  const detail = at !== null ? offsetLabel(at, timeZone) : null;
                  return (
                    <Label key={option} className='flex items-center gap-2 text-sm font-normal'>
                      <RadioGroupItem value={String(option)} />
                      <span>
                        {option === 0 ? 'First occurrence' : 'Second occurrence'}
                        {detail && <span className='text-muted-foreground'> · {detail}</span>}
                      </span>
                    </Label>
                  );
                })}
              </RadioGroup>
            </div>
          )}

          {asset && (
            <div className='flex flex-col gap-1.5'>
              <Label htmlFor='schedule-alt'>Alt text</Label>
              <Input id='schedule-alt' className='text-base md:text-sm' value={alt} onChange={(e) => setAlt(e.target.value)} maxLength={300} placeholder='Hands on piano keys under a warm light' />
            </div>
          )}

          <Label className='flex items-start gap-2 text-sm font-normal'>
            <Checkbox checked={rights} onCheckedChange={(v) => setRights(v === true)} />
            <span>I have the rights to publish this text{asset ? ' and image' : ''} on this account.</span>
          </Label>
          {variant && steps.warnings.length > 0 && (
            <Label className='flex items-start gap-2 text-sm font-normal'>
              <Checkbox checked={acknowledge} onCheckedChange={(v) => setAcknowledge(v === true)} />
              <span>
                I acknowledge: {steps.warnings.join('; ')}
              </span>
            </Label>
          )}
        </div>
        )}
        <DialogFooter>
          <Button variant='glass' size='control' onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {/* The server refuses `p2_review` without the approve permission; the sentence above says who can. */}
          <Button variant='action' size='control' disabled={!ready || !canPrepare || act.isPending} onClick={() => void submit()}>
            {act.isPending ? 'Preparing…' : 'Prepare review'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
