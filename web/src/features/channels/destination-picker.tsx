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
import { discordCopy } from '@/lib/channels/discord-copy';
import { discordRefusal } from '@/lib/channels/discord-refusal';
import { usePreferences } from '@/lib/preferences';
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
  const dc = discordCopy(usePreferences().locale);
  // Discord requests here can be refused by the shared request coordinator: say it in the person's language.
  const reason = (err: unknown) => (err instanceof ApiError ? (platform === 'Discord' ? discordRefusal(err, dc) : err.message) : 'Try again in a moment.');
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
      setError(reason(err));
    }
  }

  async function choose(id: string) {
    setSaving(id);
    try {
      await api.chooseChannelDestination(workspaceId, channelId, id);
      setItems((current) => current?.map((item) => ({ ...item, selected: item.id === id, ...(item.id === id && platform === 'Discord' ? { authorizedId: item.stableId } : {}) })) ?? null);
      toast.success(platform === 'Discord' ? 'Channel authorized and set as the default. Existing approvals keep their frozen destination.' : `${label} selected. Publishing requires its own permission and approval.`);
      void client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    } catch (err) {
      toast.error(reason(err));
    } finally {
      setSaving(null);
    }
  }

  async function remove(item: ChannelDestination) {
    if (!item.authorizedId) return;
    setSaving(item.id);
    try {
      await api.removeDiscordDestination(workspaceId, channelId, item.authorizedId);
      setItems((current) => current?.map((destination) => destination.id === item.id ? { ...destination, authorizedId: undefined, selected: false } : destination) ?? null);
      toast.success('Channel authorization removed. Pending posts to this channel are held.');
      void client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    } catch (err) {
      toast.error(reason(err));
    } finally {
      setSaving(null);
    }
  }

  return (
    <>
      <Button variant='quiet' className={CONTROL_44} disabled={disabled} onClick={() => void load()}>
        <Icons.send className='size-4' aria-hidden />
        {platform === 'Discord' ? 'Authorize Discord channel' : label === 'Page' ? 'Choose Facebook Page' : label === 'Channel' ? 'Posting channel' : `Posting ${label}`}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={isMobile ? 'bottom' : 'right'} className={cn(SHEET_ELEVATED, 'data-[side=bottom]:max-h-[80dvh] data-[side=right]:sm:max-w-md')}>
          <SheetHeader className='gap-1.5 px-5 pt-5 pr-14 pb-4'>
            <SheetTitle className='text-xl font-medium tracking-tight'>{label === 'Location' ? 'Choose a business location' : 'Where Rafii posts'}</SheetTitle>
            <SheetDescription>
              {platform === 'Discord' ? 'Authorize individual server channels here, then choose the exact destination on each post. Changing the default keeps existing approvals on their original channel.' : label === 'Page' ? 'Select the Page for this connection. Publishing, comments and analytics each need their own permissions.' : label === 'Location' ? 'Choose the exact Business Profile location for this connection.' : `Rafii posts on ${platform} only in the ${label === 'Channel' ? 'channel' : label} you choose.`}
            </SheetDescription>
          </SheetHeader>
          <div className='flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-5 pb-[max(1rem,env(safe-area-inset-bottom))]'>
            {error && <StateMessage kind='error' layout='inline' title={label === 'Location' ? "Couldn't load locations" : "Couldn't load channels"} description={error} />}
            {!items && !error && <StateMessage kind='loading' layout='inline' title={label === 'Location' ? 'Loading locations…' : 'Loading channels…'} />}
            {items?.length === 0 && (
              <StateMessage kind='empty' layout='inline' title={label === 'Location' ? 'No Business Profile locations available to this Google account.' : label === 'Page' ? 'No Pages you can post to.' : 'No text channels the bot can post in.'} />
            )}
            {items?.map((item) => (
              <div key={item.id} className='flex flex-col gap-1'>
              <Button
                variant={item.selected ? 'action' : 'glass'}
                className={cn(CONTROL_44, 'justify-between')}
                disabled={saving !== null}
                aria-pressed={item.selected}
                onClick={() => void choose(item.id)}
              >
                <span className='truncate'>
                  {platform === 'Discord' ? `${item.guildName} · ${item.name} (${item.id})` : item.name}
                  {item.kind === 'announcement' ? ' · announcements' : ''}
                </span>
                {item.selected && <Icons.check className='size-4 shrink-0' aria-hidden />}
              </Button>
              {platform === 'Discord' && item.authorizedId && <Button variant='quiet' className={CONTROL_44} disabled={saving !== null} onClick={() => void remove(item)}>Remove channel authorization</Button>}
              </div>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
