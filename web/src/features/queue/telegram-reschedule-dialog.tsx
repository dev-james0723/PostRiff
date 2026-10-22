'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import type { QueueJob } from './job-state';
import { defaultLocalTime, resolveWallTime } from './schedule-dialog';

/** A time-only replacement of frozen content. Approval and worker claiming remain server-atomic. */
export function TelegramRescheduleDialog({ job, onClose }: { job: QueueJob; onClose: () => void }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const [timeZone, setTimeZone] = useState(job.manifest.timing.timeZone);
  const [localTime, setLocalTime] = useState(() => defaultLocalTime(job.manifest.timing.timeZone));
  const [fold, setFold] = useState<number | undefined>();
  const wall = resolveWallTime(localTime, timeZone);
  const at = wall.kind === 'exact' ? wall.at : wall.kind === 'ambiguous' && fold !== undefined ? (fold === 0 ? wall.first : wall.second) : 0;
  const valid = at > Date.now() && ['scheduled', 'approved'].includes(job.state);
  async function prepare() {
    if (!valid || !snapshot.data) return;
    try {
      await act.mutateAsync({ revision: snapshot.data.revision, action: 'p2_telegram_reschedule', payload: { jobId: job.id, localTime, timeZone, fold } });
      toast.success('Replacement review prepared. The original stays scheduled until approval.');
      onClose();
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not prepare replacement review'); }
  }
  return <Dialog open onOpenChange={open => { if (!open && !act.isPending) onClose(); }}>
    <DialogContent className='max-h-[90dvh] overflow-y-auto'>
      <DialogHeader><DialogTitle>Reschedule Telegram post</DialogTitle><DialogDescription>Prepare a time-only replacement. Approving its review cancels the original schedule and queues the replacement together. Rafii refuses replacement if publishing has started.</DialogDescription></DialogHeader>
      <p className='text-sm'>{job.manifest.account}</p><p className='max-h-40 overflow-y-auto text-sm whitespace-pre-wrap'>{job.manifest.payload.text}</p>
      <p className='text-muted-foreground text-xs'>The approved text, media and Telegram options stay frozen. The original remains queued until you approve.</p>
      <Label htmlFor='telegram-reschedule-time'>New publication time</Label><Input id='telegram-reschedule-time' type='datetime-local' value={localTime} onChange={e => { setLocalTime(e.target.value); setFold(undefined); }} />
      <Label htmlFor='telegram-reschedule-zone'>Time zone</Label><Input id='telegram-reschedule-zone' value={timeZone} onChange={e => { setTimeZone(e.target.value); setFold(undefined); }} />
      {wall.kind === 'ambiguous' && <><Label htmlFor='telegram-reschedule-fold'>This time occurs twice</Label><select id='telegram-reschedule-fold' value={fold ?? ''} onChange={e => setFold(e.target.value === '' ? undefined : Number(e.target.value))}><option value=''>Choose an occurrence</option><option value='0'>First occurrence</option><option value='1'>Second occurrence</option></select></>}
      {!valid && <p role='status' className='text-muted-foreground text-xs'>{wall.kind === 'gap' ? 'Clocks skip this local time.' : wall.kind === 'ambiguous' && fold === undefined ? 'Choose which occurrence to use.' : 'Choose a valid future time and IANA time zone.'}</p>}
      <DialogFooter><Button variant='quiet' disabled={act.isPending} onClick={onClose}>Cancel</Button><Button disabled={!valid || act.isPending || !snapshot.data} onClick={prepare}>Prepare replacement review</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
}
