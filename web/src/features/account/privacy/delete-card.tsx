'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { rafiiDialog, rafiiDialogFooter, rafiiInput } from '@/components/auth/form-styles';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { StateMessage } from '@/components/rafii';
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
import { Input } from '@/components/ui/input';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Skeleton } from '@/components/ui/skeleton';
import { useSignInAgain } from '@/lib/auth/use-sign-in-again';
import { ApiError } from '@/lib/api/client';
import type { Snapshot } from '@/lib/api/types';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SettingsSection } from '../settings-section';
import type { BusyProps } from './export-cards';
import { jobCounts, needsFreshSignIn, plural } from './privacy-model';
import { RetryButton, type Refetchable } from './section';

const linkClass = 't-learn rafii-focus text-foreground inline-flex items-center gap-0.5 rounded-sm font-medium hover:underline';

function Check({ label, badge, children }: { label: string; badge: { text: string; status: AnimatedBadgeStatus }; children?: ReactNode }) {
  return (
    <div className='flex flex-col gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-4'>
      <div className='flex min-w-0 flex-col gap-0.5'>
        <span className='text-foreground text-sm font-medium'>{label}</span>
        {children && <span className='text-muted-foreground text-xs leading-relaxed'>{children}</span>}
      </div>
      <AnimatedBadge size='sm' status={badge.status} contentKey={badge.text} pulse={false} className='w-fit'>
        {badge.text}
      </AnimatedBadge>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = { owner: 'the owner', admin: 'an admin', editor: 'an editor', approver: 'an approver', viewer: 'a viewer' };

/** The destructive action in its own, clearly named lower section (DNA §21.15); the confirm dialog stages it. */
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
  const reauthenticate = useSignInAgain();
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
      const result = await api.deleteAccount(workspaceId, confirmation.trim());
      if (result.identityDeleted && result.deleted) toast.success('Your account and workspace were deleted.');
      else toast.warning(`Your workspace was removed. Sign-in deletion is still pending. Contact support with receipt ${result.receiptId}.`, { duration: Infinity });
      if (result.providerRevocationPending?.length) toast.warning(`Remove Rafii access in your platform settings: ${result.providerRevocationPending.join(', ')}. Stored credentials were deleted.`, { duration: Infinity });
      await auth.signOut();
      router.replace('/');
    } catch (err) {
      setDeleting(false);
      if (err instanceof ApiError && needsFreshSignIn(err)) {
        setStepUp(true);
        return;
      }
      toast.error(err instanceof ApiError ? err.message : 'The account could not be deleted.');
      if (err instanceof ApiError && (err.status === 409 || err.code === 'account_deletion_pending')) void snapshot.refetch();
    }
  }

  async function signInAgain() {
    setSigningOut(true);
    await reauthenticate();
    setSigningOut(false);
  }

  return (
    <SettingsSection
      id='privacy-delete'
      title='Delete account'
      description='Removes this workspace, its media, its memberships and your sign-in. A deletion receipt and a trial record stay, so the trial cannot be restarted. Cancel any renewing subscription and transfer other workspace ownership first.'
      bodyClassName='gap-5'
      data-tour='privacy-delete'
    >
      {Boolean(snapshot.data?.state.accountDeletion) && (
        <StateMessage kind='partial' layout='inline' title='Deletion is pending' description='This workspace is frozen. Retry deletion to finish cleanup; some private files may already have been removed.' />
      )}
      <div className='flex flex-col gap-4'>
        <Check
          label='Who can delete'
          badge={owner ? { text: 'You are the owner', status: 'success' } : { text: `You are ${ROLE_LABEL[role] ?? role}`, status: 'neutral' }}
        >
          Only the workspace owner.
        </Check>
        {snapshot.isPending ? (
          <div className='flex flex-col gap-2' aria-hidden>
            <Skeleton className='h-9 w-full' />
            <Skeleton className='h-9 w-full' />
          </div>
        ) : !counts ? (
          <StateMessage kind='error' layout='inline' title='Publications could not be read. Reload them before deleting.' action={<RetryButton query={snapshot} />} />
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
      <div className='flex flex-wrap items-center gap-3'>
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
            <AlertDialogTrigger render={<Button variant='glass' size='control' className='text-destructive' />} disabled={blocked || busy !== null}>
              Delete account…
            </AlertDialogTrigger>
            <AlertDialogContent className={rafiiDialog}>
              <AlertDialogHeader>
                <AlertDialogTitle className='text-foreground text-lg font-medium tracking-tight'>Delete your account?</AlertDialogTitle>
                <AlertDialogDescription className='leading-relaxed'>
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
                className={rafiiInput}
              />
              {stepUp && (
                <StateMessage
                  kind='permission'
                  layout='inline'
                  title='Sign in again to confirm'
                  description='Deleting needs a sign-in from the last 10 minutes. Nothing was deleted.'
                  action={
                    <Button size='sm' variant='glass' className='min-h-9' disabled={signingOut} onClick={() => void signInAgain()}>
                      {signingOut ? 'Signing out…' : 'Sign out and sign in again'}
                    </Button>
                  }
                />
              )}
              <AlertDialogFooter className={rafiiDialogFooter}>
                <AlertDialogCancel variant='quiet' size='control'>Keep my account</AlertDialogCancel>
                <AlertDialogAction variant='destructive' size='control' disabled={confirmation.trim() !== 'DELETE' || deleting || blocked} onClick={() => void deleteAccount()}>
                  {deleting ? 'Deleting…' : 'Delete everything'}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : (
          <p className='text-muted-foreground text-sm'>Only the workspace owner can delete the account and workspace.</p>
        )}
        {owner && counts && counts.inFlight > 0 && <p className='text-muted-foreground text-xs'>Available once every publication has an outcome.</p>}
      </div>
    </SettingsSection>
  );
}
