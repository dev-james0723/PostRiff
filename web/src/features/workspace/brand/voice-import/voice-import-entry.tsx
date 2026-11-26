'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { CONTROL_44, SHEET_ELEVATED } from '@/features/channels/rafii-materials';
import { useIsMobile } from '@/hooks/use-mobile';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import { disconnectedByCustomer } from '@/lib/channels/state';
import { cn } from '@/lib/utils';
import { useBrainCopy } from '../brain-copy';
import { VoiceImportPanel } from './voice-import-panel';
import { useVoiceImports } from './use-voice-import';

/**
 * The way into voice import from one account's card on Channels. It does not depend on the Brand Brain build
 * flag: the panel opens in a sheet on this page. It is shown only when the workspace's list route answers and
 * lists this platform, so with voice import switched off the card is unchanged.
 */
export function VoiceImportEntry({ channel, provider }: { channel: ChannelView; provider?: ProviderView }) {
  const t = useBrainCopy();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const { view } = useVoiceImports();
  const id = (provider?.id ?? channel.platform).toLowerCase();
  if (!view?.routes?.some((row) => row.provider === id) || disconnectedByCustomer(channel)) return null;
  return (
    <>
      <Button variant='quiet' className={CONTROL_44} data-testid={`voice-import-entry-${id}`} onClick={() => setOpen(true)}>
        {t('Learn from this account’s posts', '從此帳戶的貼文學習', '从此账户的帖子学习')}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={isMobile ? 'bottom' : 'right'} className={cn(SHEET_ELEVATED, 'data-[side=bottom]:max-h-[92dvh] data-[side=right]:sm:max-w-xl')}>
          <SheetHeader className='gap-1 px-5 pt-5 pr-14 pb-3'>
            <SheetTitle>{t('Learn from this account’s posts', '從此帳戶的貼文學習', '从此账户的帖子学习')}</SheetTitle>
            <SheetDescription>
              {channel.platform} · {channel.account}
            </SheetDescription>
          </SheetHeader>
          <div className='flex min-h-0 flex-1 flex-col overflow-y-auto px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]'>{open && <VoiceImportPanel bare focus={{ provider: id, connectionId: channel.id }} />}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}
