'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import type { Snapshot } from '@/lib/api/types';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { BusyProps } from './export-cards';
import { jobCounts, needsFreshSignIn, plural } from './privacy-model';
import { RetryButton, type Refetchable } from './section';

const PAGE = '/app/account/privacy';
const linkClass = 't-learn text-foreground inline-flex items-center gap-0.5 font-medium hover:underline';

function Check({ label, badge, children }: { label: string; badge: { text: string; status: AnimatedBadgeStatus }; children?: ReactNode }) {
  return (
    <div className='flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between sm:gap-4'>
      <div className='flex min-w-0 flex-col gap-0.5'>
        <span className='text-sm font-medium'>{label}</span>
        {children && <span className='text-muted-foreground text-xs'>{children}</span>}
      </div>
      <AnimatedBadge size='sm' status={badge.status} contentKey={badge.text} pulse={false} className='w-fit'>
        {badge.text}
      </AnimatedBadge>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = { owner: 'the owner', admin: 'an admin', editor: 'an editor', approver: 'an approver', viewer: 'a viewer' };

export function DeleteCard({
  snapshot,
  owner,
  role,
  busy
}: Pick<BusyProps, 'busy'> & {
  snapshot: Refetchable & { data?: Snapshot; isPending: boolean };
  owner: boolean;
  role: string;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const auth = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const counts = snapshot.data ? jobCounts(snapshot.data.state) : null;
  const blocked = !counts || counts.inFlight > 0;

  async function deleteAccount() {
    setDeleting(true);
    setStepUp(false);
    try {
      await api.deleteAccount(workspaceId, confirmation.trim());
      toast.success('Your account and workspace were deleted.');
      await auth.signOut();
      router.replace('/');
    } catch (err) {
      setDeleting(false);
      if (err instanceof ApiError && needsFreshSignIn(err)) {
        setStepUp(true);
        return;
      }
      toast.error(err instanceof ApiError ? err.message : 'The account could not be deleted.');
      if (err instanceof ApiError && err.status === 409) void snapshot.refetch();
    }
  }

  /** A signed-in visit to the sign-in page redirects straight back, so a fresh sign-in has to start signed out. */
  async function signInAgain() {
    setSigningOut(true);
    try {
      await auth.signOut();
    } finally {
      router.replace(`/auth/sign-in?next=${encodeURIComponent(PAGE)}`);
    }
  }

  return (
    <Card data-tour='privacy-delete' className='ring-destructive/40 min-w-0'>
      <CardHeader>
        <CardTitle>Delete account</CardTitle>
        <CardDescription>
          Removes this workspace, its media, its memberships and your sign-in. Content-free receipts and a trial record stay, so the trial cannot be
          restarted.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className='divide-y'>
          <Check
            label='Who can delete'
            badge={owner ? { text: 'You are the owner', status: 'success' } : { text: `You are ${ROLE_LABEL[role] ?? role}`, status: 'neutral' }}
          >
            Only the workspace owner.
          </Check>
          {snapshot.isPending ? (
            <div className='flex flex-col gap-2 py-3' aria-hidden>
              <Skeleton className='h-9 w-full' />
              <Skeleton className='h-9 w-full' />
            </div>
          ) : !counts ? (
            <div role='status' className='flex flex-wrap items-center gap-x-3 gap-y-2 py-3'>
              <p className='text-muted-foreground text-sm'>Publications could not be read. Reload them before deleting.</p>
              <RetryButton query={snapshot} />
            </div>
          ) : (
            <>
              <Check
                label='Publications in flight'
                badge={counts.inFlight > 0 ? { text: `Waiting for ${counts.inFlight} to confirm`, status: 'warning' } : { text: 'None in flight', status: 'success' }}
              >
                {counts.inFlight > 0 ? (
                  <>
                    A post already sent to a platform cannot be recalled. Deletion unlocks once each one is confirmed or marked failed.{' '}
                    <Link href='/app/queue' className={linkClass}>
                      See Queue <LearnMoreChevron className='size-3.5' />
                    </Link>
                  </>
                ) : (
                  'Nothing has been handed to a platform without an outcome.'
                )}
              </Check>
              <Check
                label='Posts waiting to publish'
                badge={counts.waiting > 0 ? { text: `${counts.waiting} will not publish`, status: 'warning' } : { text: 'None waiting', status: 'neutral' }}
              >
                {counts.waiting > 0
                  ? `${plural(counts.waiting, 'approved post')} not sent yet ${counts.waiting === 1 ? 'is' : 'are'} removed with the workspace and never published.`
                  : 'No approved post is waiting to be sent.'}
              </Check>
            </>
          )}
        </div>
      </CardContent>
      <CardFooter className='flex flex-wrap items-center gap-2'>
        {owner ? (
          <AlertDialog
            open={open}
            onOpenChange={(next) => {
              setOpen(next);
              if (next) {
                setConfirmation('');
                setStepUp(false);
                void snapshot.refetch();
              }
            }}
          >
            <AlertDialogTrigger
              render={<Button variant='outline' className='text-destructive' />}
              disabled={blocked || busy !== null}
            >
              Delete account…
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete your account?</AlertDialogTitle>
                <AlertDialogDescription>
                  This cannot be undone. Export first if you want a copy.
                  {counts && counts.waiting > 0 ? ` ${plural(counts.waiting, 'scheduled post')} will never be published.` : ''} Type{' '}
                  <strong>DELETE</strong> to confirm.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <Input
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                aria-label='Type DELETE to confirm'
                placeholder='DELETE'
                autoComplete='off'
              />
              {stepUp && (
                <Alert>
                  <Icons.lock />
                  <AlertTitle>Sign in again to confirm</AlertTitle>
                  <AlertDescription className='flex flex-col items-start gap-2'>
                    <span>Deleting needs a sign-in from the last 10 minutes. Nothing was deleted.</span>
                    <Button size='sm' variant='outline' disabled={signingOut} onClick={() => void signInAgain()}>
                      {signingOut ? 'Signing out…' : 'Sign out and sign in again'}
                    </Button>
                  </AlertDescription>
                </Alert>
              )}
              <AlertDialogFooter>
                <AlertDialogCancel>Keep my account</AlertDialogCancel>
                <AlertDialogAction
                  variant='destructive'
                  disabled={confirmation.trim() !== 'DELETE' || deleting || blocked}
                  onClick={() => void deleteAccount()}
                >
                  {deleting ? 'Deleting…' : 'Delete everything'}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : (
          <p className='text-muted-foreground text-sm'>Only the workspace owner can delete the account and workspace.</p>
        )}
        {owner && counts && counts.inFlight > 0 && <p className='text-muted-foreground text-xs'>Available once every publication has an outcome.</p>}
      </CardFooter>
    </Card>
  );
}
