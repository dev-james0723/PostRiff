'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { SupabaseClient } from '@supabase/supabase-js';
import { toast } from 'sonner';
import { rafiiDialog, rafiiDialogFooter, rafiiIconWell, rafiiInput } from '@/components/auth/form-styles';
import { Icons } from '@/components/icons';
import { CollectionRow, StateMessage } from '@/components/rafii';
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
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
import { SettingsSection } from './settings-section';

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
      <DialogContent className={rafiiDialog}>
        <form onSubmit={submit} className='flex flex-col gap-5'>
          <DialogHeader className='gap-1.5 pr-8'>
            <DialogTitle className='text-foreground text-xl font-medium tracking-tight'>Rename passkey</DialogTitle>
            <DialogDescription className='leading-relaxed'>A name you will recognise later, such as the device it lives on.</DialogDescription>
          </DialogHeader>
          {error && <StateMessage kind='error' layout='inline' title={error} />}
          <div className='flex flex-col gap-2'>
            <Label htmlFor='passkey-name'>Name</Label>
            <Input id='passkey-name' value={name} maxLength={60} autoFocus onChange={(event) => setName(event.target.value)} className={rafiiInput} />
          </div>
          <DialogFooter className={rafiiDialogFooter}>
            <Button type='button' variant='quiet' size='control' disabled={busy} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type='submit' variant='action' size='control' disabled={busy || name.trim().length === 0}>
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
    <SettingsSection
      id='profile-passkeys'
      title='Passkeys for sign-in'
      description='Sign in with Face ID, Touch ID or a security key instead of an email code. Separate from the two-factor methods above: if two-factor authentication is on, you still confirm with it after a passkey sign-in.'
    >
      {dev ? (
        <StateMessage kind='unsupported' layout='inline' title='Not available with a dev identity.' description='Passkeys need a real sign-in provider.' />
      ) : passkeys.isLoading ? (
        <StateMessage kind='loading' title='Loading passkeys' className='bg-transparent p-0' />
      ) : passkeys.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title={message(passkeys.error, 'Passkeys could not be loaded.')}
          action={
            <Button size='sm' variant='glass' className='min-h-9' onClick={() => void passkeys.refetch()}>
              Retry
            </Button>
          }
        />
      ) : list.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No passkeys yet.' description='Add one on this device to skip the email code next time.' />
      ) : (
        <ul className='flex flex-col gap-1.5'>
          {list.map((passkey) => (
            <CollectionRow
              key={passkey.id}
              as='li'
              className='rafii-glass'
              leading={
                <span className={rafiiIconWell}>
                  <Icons.key className='size-4' aria-hidden />
                </span>
              }
              title={passkey.name}
              meta={
                <>
                  Added {formatDate(Date.parse(passkey.createdAt) / 1000)}
                  {passkey.lastUsedAt ? ` · last used ${relativeTime(Date.parse(passkey.lastUsedAt) / 1000)}` : ' · not used yet'}
                </>
              }
              actions={
                <>
                  <Button variant='quiet' size='sm' className='min-h-9' disabled={busy} onClick={() => setRenaming(passkey)}>
                    Rename
                  </Button>
                  <Button variant='quiet' size='sm' className='text-destructive min-h-9' disabled={busy} onClick={() => setRemoving(passkey)}>
                    Remove
                  </Button>
                </>
              }
            />
          ))}
        </ul>
      )}
      {!dev && (
        <Button variant='glass' size='control' className='w-fit' disabled={busy || !passkeysSupported()} onClick={() => void add()}>
          <Icons.add className='size-4' aria-hidden />
          {busy ? 'Waiting for your device…' : 'Add a passkey on this device'}
        </Button>
      )}
      {!dev && !passkeysSupported() && <p className='text-muted-foreground text-xs'>This browser cannot create passkeys.</p>}

      <RenameDialog passkey={renaming} onOpenChange={(open) => !open && setRenaming(null)} onRenamed={refresh} />
      <AlertDialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <AlertDialogContent className={rafiiDialog}>
          <AlertDialogHeader>
            <AlertDialogTitle className='text-foreground text-lg font-medium tracking-tight'>Remove {removing?.name ?? 'this passkey'}?</AlertDialogTitle>
            <AlertDialogDescription className='leading-relaxed'>
              That device can no longer sign you in with it. Your email code and Google sign-in keep working; delete the passkey from the device
              too if you want it gone everywhere.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className={rafiiDialogFooter}>
            <AlertDialogCancel variant='quiet' size='control'>Keep</AlertDialogCancel>
            <AlertDialogAction variant='action' size='control' disabled={busy} onClick={() => removing && void remove(removing)}>
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsSection>
  );
}

/** Rendered only when the deployment has turned passkey sign-in on; hooks live in the body. */
export function PasskeysCard() {
  if (!passkeySignInEnabled()) return null;
  return <PasskeysCardBody />;
}
