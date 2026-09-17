'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { SupabaseClient } from '@supabase/supabase-js';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { passkeysSupported } from '@/lib/auth/mfa';
import {
  deleteSignInPasskey,
  listSignInPasskeys,
  passkeySignInEnabled,
  registerSignInPasskey,
  renameSignInPasskey,
  type SignInPasskey
} from '@/lib/auth/passkeys';
import { useAuth } from '@/lib/auth/session';
import { formatDate, relativeTime } from '@/lib/time';

const PASSKEYS_KEY = ['sign-in-passkeys'] as const;

function message(err: unknown, fallback: string) {
  return err instanceof ApiError || err instanceof Error ? err.message : fallback;
}

function RenameDialog({ passkey, onOpenChange, onRenamed }: { passkey: SignInPasskey | null; onOpenChange: (open: boolean) => void; onRenamed: () => Promise<void> }) {
  const auth = useAuth();
  const [name, setName] = useState(passkey?.name ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!auth.supabase || !passkey) return;
    setBusy(true);
    setError(null);
    try {
      await renameSignInPasskey(auth.supabase, passkey.id, name);
      await onRenamed();
      onOpenChange(false);
    } catch (err) {
      setError(message(err, 'The passkey could not be renamed.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={passkey !== null} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent>
        <form onSubmit={submit} className='flex flex-col gap-4'>
          <DialogHeader>
            <DialogTitle>Rename passkey</DialogTitle>
            <DialogDescription>A name you will recognise later, such as the device it lives on.</DialogDescription>
          </DialogHeader>
          {error && (
            <Alert variant='destructive'>
              <Icons.alertCircle className='size-4' />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='passkey-name'>Name</Label>
            <Input id='passkey-name' value={name} maxLength={60} autoFocus onChange={(event) => setName(event.target.value)} />
          </div>
          <DialogFooter>
            <Button type='button' variant='ghost' disabled={busy} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type='submit' disabled={busy || name.trim().length === 0}>
              {busy ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function PasskeysCardBody() {
  const auth = useAuth();
  const client = useQueryClient();
  const passkeys = useQuery({
    queryKey: PASSKEYS_KEY,
    queryFn: () => listSignInPasskeys(auth.supabase as SupabaseClient),
    enabled: Boolean(auth.supabase)
  });
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<SignInPasskey | null>(null);
  const [removing, setRemoving] = useState<SignInPasskey | null>(null);
  const dev = auth.mode === 'dev' || !auth.supabase;
  const list = passkeys.data ?? [];

  async function refresh() {
    await client.invalidateQueries({ queryKey: PASSKEYS_KEY });
  }

  async function add() {
    if (!auth.supabase) return;
    setBusy(true);
    try {
      await registerSignInPasskey(auth.supabase);
      toast.success('Passkey added. Next time, sign in with it.');
      await refresh();
    } catch (err) {
      toast.error(message(err, 'Your device did not complete the passkey setup.'));
    } finally {
      setBusy(false);
    }
  }

  async function remove(passkey: SignInPasskey) {
    if (!auth.supabase) return;
    setBusy(true);
    try {
      await deleteSignInPasskey(auth.supabase, passkey.id);
      toast.success(`${passkey.name} removed.`);
      await refresh();
    } catch (err) {
      toast.error(message(err, 'The passkey could not be removed.'));
    } finally {
      setBusy(false);
      setRemoving(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Passkeys for sign-in</CardTitle>
        <CardDescription>
          Sign in with Face ID, Touch ID or a security key instead of an email code. Separate from the two-factor methods above: if two-factor
          authentication is on, you still confirm with it after a passkey sign-in.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        {dev ? (
          <p className='text-muted-foreground text-sm'>Not available with a dev identity. Passkeys need a real sign-in provider.</p>
        ) : passkeys.isLoading ? (
          <Skeleton className='h-16 w-full' />
        ) : passkeys.isError ? (
          <Alert variant='destructive'>
            <Icons.alertCircle className='size-4' />
            <AlertDescription className='flex items-center justify-between gap-2'>
              {message(passkeys.error, 'Passkeys could not be loaded.')}
              <Button size='sm' variant='outline' onClick={() => void passkeys.refetch()}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ) : list.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No passkeys yet. Add one on this device to skip the email code next time.</p>
        ) : (
          <ul className='divide-y rounded-lg border'>
            {list.map((passkey) => (
              <li key={passkey.id} className='flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm'>
                <div className='flex min-w-0 items-center gap-3'>
                  <span className='bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md'>
                    <Icons.key className='size-4' aria-hidden />
                  </span>
                  <div className='min-w-0'>
                    <div className='truncate font-medium'>{passkey.name}</div>
                    <div className='text-muted-foreground text-xs'>
                      Added {formatDate(Date.parse(passkey.createdAt) / 1000)}
                      {passkey.lastUsedAt ? ` · last used ${relativeTime(Date.parse(passkey.lastUsedAt) / 1000)}` : ' · not used yet'}
                    </div>
                  </div>
                </div>
                <div className='flex gap-1'>
                  <Button variant='ghost' size='sm' disabled={busy} onClick={() => setRenaming(passkey)}>
                    Rename
                  </Button>
                  <Button variant='ghost' size='sm' className='text-destructive' disabled={busy} onClick={() => setRemoving(passkey)}>
                    Remove
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {!dev && (
          <Button variant='outline' className='w-fit' disabled={busy || !passkeysSupported()} onClick={() => void add()}>
            <Icons.add className='size-4' aria-hidden />
            {busy ? 'Waiting for your device…' : 'Add a passkey on this device'}
          </Button>
        )}
        {!dev && !passkeysSupported() && <p className='text-muted-foreground text-xs'>This browser cannot create passkeys.</p>}

        <RenameDialog passkey={renaming} onOpenChange={(open) => !open && setRenaming(null)} onRenamed={refresh} />
        <AlertDialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Remove {removing?.name ?? 'this passkey'}?</AlertDialogTitle>
              <AlertDialogDescription>
                That device can no longer sign you in with it. Your email code and Google sign-in keep working; delete the passkey from the device
                too if you want it gone everywhere.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep</AlertDialogCancel>
              <AlertDialogAction disabled={busy} onClick={() => removing && void remove(removing)}>
                Remove
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}

/** Rendered only when the deployment has turned passkey sign-in on; hooks live in the body. */
export function PasskeysCard() {
  if (!passkeySignInEnabled()) return null;
  return <PasskeysCardBody />;
}
