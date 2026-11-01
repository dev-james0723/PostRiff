'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import { useChangeError } from '@/lib/auth/use-sign-in-again';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CONTROL_44, SHEET_ELEVATED } from './rafii-materials';

/** Identity/board consent has a useful read-only destination view without opening a publishing form. */
export function PinterestBoardsSheet(props: { channelId: string; account: string }) {
  const { workspaceId } = useWorkspaceApi();
  return <BoundPinterestBoards key={`${workspaceId}:${props.channelId}`} {...props} />;
}

function BoundPinterestBoards({ channelId, account }: { channelId: string; account: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const mobile = useIsMobile();
  const reportChangeError = useChangeError();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshed, setRefreshed] = useState(false);
  const boards = useQuery({
    queryKey: ['pinterest-readonly-boards', workspaceId, channelId],
    queryFn: () => api.channelDestinations(workspaceId, channelId),
    enabled: open, retry: false, staleTime: 0
  });

  async function refreshAuthorization() {
    setRefreshing(true);
    setRefreshed(false);
    try {
      const result = await api.refreshPinterestAuthorization(workspaceId, channelId);
      if (!alive.current) return;
      if (!result.authorizationRefreshed || !result.identityVerified) throw new Error('Authorization was not confirmed.');
      setRefreshed(true);
      await boards.refetch();
    } catch (error) {
      if (!alive.current) return;
      reportChangeError(error, 'Could not refresh Pinterest authorization. Reconnect this account.');
    } finally { if (alive.current) setRefreshing(false); }
  }

  return <>
    <Button variant='quiet' className={CONTROL_44} onClick={() => { setRefreshed(false); setOpen(true); }}>View boards</Button>
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side={mobile ? 'bottom' : 'right'} className={cn(SHEET_ELEVATED, 'data-[side=bottom]:max-h-[80dvh] data-[side=right]:sm:max-w-md')}>
        <SheetHeader className='gap-1.5 px-5 pt-5 pr-14 pb-4'>
          <SheetTitle>Pinterest boards</SheetTitle>
          <SheetDescription>Boards for {account}. Reading them does not approve or publish a Pin.</SheetDescription>
        </SheetHeader>
        <div className='flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-5 pb-5'>
          <div className='flex flex-wrap gap-2'>
            <Button variant='glass' disabled={boards.isFetching || refreshing} onClick={() => void boards.refetch()}>Reload boards</Button>
            <Button variant='glass' disabled={refreshing || boards.isFetching} onClick={() => void refreshAuthorization()}>
              {refreshing ? 'Refreshing authorization…' : 'Refresh authorization'}
            </Button>
          </div>
          {refreshed && <p role='status' className='text-sm'>Authorization refreshed and the same Pinterest account verified.</p>}
          {boards.isFetching ? <StateMessage kind='loading' title='Reading your boards…' />
            : boards.isError ? <StateMessage kind='error' title='Could not read your boards' description={boards.error instanceof ApiError ? boards.error.message : 'Try again or reconnect the account.'} />
            : boards.data?.destinations.length === 0 ? <StateMessage kind='empty' title='No boards returned by Pinterest.' description='Check this account and its board access, then reload.' />
            : <ul className='flex flex-col gap-2' aria-label='Pinterest boards'>
                {boards.data?.destinations.map((item) => <li key={item.id} className='rounded-[var(--rafii-radius-control)] border p-3'>
                  <p className='text-sm font-medium'>{item.name}</p>
                  <p className='text-muted-foreground text-xs'>{item.eligible === true ? 'Public board' : 'Unavailable as a publishing destination'}</p>
                </li>)}
              </ul>}
        </div>
      </SheetContent>
    </Sheet>
  </>;
}
