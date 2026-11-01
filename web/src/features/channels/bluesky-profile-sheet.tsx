'use client';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { useBlueskyProfile } from '@/lib/api/hooks';
import { useIsMobile } from '@/hooks/use-mobile';
import { formatDateTime } from '@/lib/time';
import { SHEET_ELEVATED } from './rafii-materials';

export function BlueskyProfileSheet({ connectionId, open, onOpenChange }: { connectionId: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const result = useBlueskyProfile(connectionId, open);
  const mobile = useIsMobile();
  const profile = result.data?.profile;
  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent side={mobile ? 'bottom' : 'right'} className={`${SHEET_ELEVATED} max-h-[92dvh] overflow-y-auto p-5`}>
      <SheetHeader><SheetTitle>Bluesky public profile</SheetTitle><SheetDescription>Account details and public counts for this connection.</SheetDescription></SheetHeader>
      {result.isLoading ? <StateMessage kind='loading' title='Loading profile…' /> : result.error ? <StateMessage kind='error' title='Could not read this account' description={result.error.message} /> : profile ?
        <div className='flex flex-col gap-4 py-4'>
          <div><p className='break-words text-lg font-medium'>{profile.displayName || profile.handle}</p><p className='text-muted-foreground break-all text-sm'>@{profile.handle}</p></div>
          <p className='break-all text-xs'>{profile.did}</p>
          {profile.description && <p className='whitespace-pre-wrap break-words text-sm'>{profile.description}</p>}
          <dl className='flex flex-wrap gap-4 text-sm'>{([['followersCount', 'Followers'], ['followsCount', 'Following'], ['postsCount', 'Posts']] as const).map(([key, label]) => profile.publicCounts[key] !== undefined ? <div key={key}><dt className='text-muted-foreground'>{label}</dt><dd>{profile.publicCounts[key]?.toLocaleString()}</dd></div> : null)}</dl>
          <p className='text-muted-foreground text-xs'>{profile.coverageNote} Retrieved {formatDateTime(profile.observedAt)}.</p>
          <a className='text-sm underline' href={profile.permalink} target='_blank' rel='noopener noreferrer'>Open profile on Bluesky</a>
        </div> : null}
      <SheetFooter><Button variant='glass' onClick={() => onOpenChange(false)}>Close</Button></SheetFooter>
    </SheetContent>
  </Sheet>;
}
