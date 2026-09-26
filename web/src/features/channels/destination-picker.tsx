'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { ChannelDestination } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CONTROL_44, SHEET_ELEVATED } from './rafii-materials';

/**
 * Where a server-level connection posts (a Discord channel). The list and the choice are the API's own:
 * channels the bot can see, and a compare-and-swap save on the stored grant.
 */
export function DestinationPicker({ channelId, platform, label = 'Channel', disabled }: { channelId: string; platform: string; label?: string; disabled?: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ChannelDestination[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function load() {
    setOpen(true);
    setItems(null);
    setError(null);
    try {
      setItems((await api.channelDestinations(workspaceId, channelId)).destinations);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Try again in a moment.');
    }
  }

  async function choose(id: string) {
    setSaving(id);
    try {
      await api.chooseChannelDestination(workspaceId, channelId, id);
      setItems((current) => current?.map((item) => ({ ...item, selected: item.id === id })) ?? null);
      toast.success('Rafii will post in this channel');
      void client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Try again in a moment.');
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <Button variant='quiet' className={CONTROL_44} disabled={disabled} onClick={() => void load()}>
        <Icons.send className='size-4' aria-hidden />
        {label === 'Channel' ? 'Posting channel' : `Posting ${label}`}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={isMobile ? 'bottom' : 'right'} className={cn(SHEET_ELEVATED, 'data-[side=bottom]:max-h-[80dvh] data-[side=right]:sm:max-w-md')}>
          <SheetHeader className='gap-1.5 px-5 pt-5 pr-14 pb-4'>
            <SheetTitle className='text-xl font-medium tracking-tight'>Where Rafii posts</SheetTitle>
            <SheetDescription>
              Rafii posts on {platform} only in the {label === 'Channel' ? 'channel' : label} you choose.
            </SheetDescription>
          </SheetHeader>
          <div className='flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-5 pb-[max(1rem,env(safe-area-inset-bottom))]'>
            {error && <StateMessage kind='error' layout='inline' title="Couldn't load channels" description={error} />}
            {!items && !error && <StateMessage kind='loading' layout='inline' title='Loading channels…' />}
            {items?.length === 0 && (
              <StateMessage kind='empty' layout='inline' title={label === 'Page' ? 'No Pages you can post to.' : 'No text channels the bot can post in.'} />
            )}
            {items?.map((item) => (
              <Button
                key={item.id}
                variant={item.selected ? 'action' : 'glass'}
                className={cn(CONTROL_44, 'justify-between')}
                disabled={saving !== null}
                aria-pressed={item.selected}
                onClick={() => void choose(item.id)}
              >
                <span className='truncate'>
                  {item.name}
                  {item.kind === 'announcement' ? ' · announcements' : ''}
                </span>
                {item.selected && <Icons.check className='size-4 shrink-0' aria-hidden />}
              </Button>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
