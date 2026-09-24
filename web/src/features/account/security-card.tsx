'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { SupabaseClient } from '@supabase/supabase-js';
import { toast } from 'sonner';
import { rafiiDialog, rafiiDialogFooter, rafiiIconWell } from '@/components/auth/form-styles';
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
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { InputOTP, InputOTPGroup, InputOTPSlot } from '@/components/ui/input-otp';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { keys, useMe, useSecurityEvents, useSessions } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { describeSecurityEvent } from './profile-model';
import {
  enrollTotp,
  listFactors,
  passkeysSupported,
  registerPasskey,
  unenrollFactor,
  verifyPasskey,
  verifyTotp,
  type FactorKind,
  type SecondFactor
} from '@/lib/auth/mfa';
import { useChangeError } from '@/lib/auth/use-sign-in-again';
import { useAuth } from '@/lib/auth/session';
import { formatDate, formatDateTime, relativeTime } from '@/lib/time';
import { useWorkspace } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { SettingsGroup, SettingsSection } from './settings-section';

const FACTORS_KEY = ['mfa-factors'] as const;

const KIND_LABEL: Record<FactorKind, string> = { totp: 'Authenticator app', webauthn: 'Passkey · Face ID / Touch ID' };
const DIALOG_TITLE = 'text-foreground text-xl font-medium tracking-tight';

function message(err: unknown, fallback: string) {
  return err instanceof ApiError || err instanceof Error ? err.message : fallback;
}

function CodeInput({ id, value, onChange }: { id: string; value: string; onChange: (value: string) => void }) {
  return (
    <InputOTP id={id} maxLength={6} value={value} onChange={onChange}>
      <InputOTPGroup>
        {Array.from({ length: 6 }).map((_, i) => (
          <InputOTPSlot key={i} index={i} />
        ))}
      </InputOTPGroup>
    </InputOTP>
  );
}

/**
 * Step-up: the person proves they hold a factor right now (passkey or code), then `action` runs
 * on the fresh AAL2 session. The passkey route is offered first when one exists.
 */
function StepUpDialog({
  open,
  onOpenChange,
  title,
  description,
  actionLabel,
  destructive = false,
  factors,
  action
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  actionLabel: string;
  destructive?: boolean;
  factors: SecondFactor[];
  action: () => Promise<void>;
}) {
  const auth = useAuth();
  const [mode, setMode] = useState<'auto' | 'code' | 'passkey'>('auto');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasPasskey = passkeysSupported() && factors.some((factor) => factor.kind === 'webauthn');
  const hasCode = factors.some((factor) => factor.kind === 'totp');
  const showCode = mode === 'code' || (mode === 'auto' && !hasPasskey);

  function close() {
    setCode('');
    setError(null);
    setMode('auto');
    onOpenChange(false);
  }

  async function confirm(prove: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await prove();
      await action();
      close();
    } catch (err) {
      setError(message(err, 'That did not work. Try again.'));
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  const client = auth.supabase;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && close()}>
      <DialogContent className={rafiiDialog}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (client) void confirm(() => verifyTotp(client, code));
          }}
          className='flex flex-col gap-5'
        >
          <DialogHeader className='gap-1.5 pr-8'>
            <DialogTitle className={DIALOG_TITLE}>{title}</DialogTitle>
            <DialogDescription className='leading-relaxed'>{description}</DialogDescription>
          </DialogHeader>
          {error && <StateMessage kind='error' layout='inline' title={error} />}
          {showCode ? (
            <div className='flex flex-col gap-2'>
              <Label htmlFor='step-up-code'>Code from your authenticator app</Label>
              <CodeInput id='step-up-code' value={code} onChange={setCode} />
              {hasPasskey && (
                <Button type='button' variant='quiet' size='sm' className='min-h-9 w-fit' disabled={busy} onClick={() => setMode('passkey')}>
                  Use Face ID / Touch ID instead
                </Button>
              )}
            </div>
          ) : (
            <div className='flex flex-col gap-2'>
              <Button
                type='button'
                variant='glass'
                size='control'
                disabled={busy}
                onClick={() => {
                  if (client) void confirm(() => verifyPasskey(client));
                }}
              >
                <Icons.key className='size-4' aria-hidden />
                {busy ? 'Waiting for your device…' : 'Confirm with Face ID / Touch ID'}
              </Button>
              {hasCode && (
                <Button type='button' variant='quiet' size='sm' className='min-h-9 w-fit' disabled={busy} onClick={() => setMode('code')}>
                  Use a code from my authenticator app instead
                </Button>
              )}
            </div>
          )}
          <DialogFooter className={rafiiDialogFooter}>
            <Button type='button' variant='quiet' size='control' disabled={busy} onClick={close}>
              Cancel
            </Button>
            {showCode && (
              <Button type='submit' variant={destructive ? 'destructive' : 'action'} size='control' disabled={busy || code.trim().length < 6}>
                {busy ? 'Verifying…' : actionLabel}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Enrol an authenticator app: QR + secret, then the first code. Abandoning it discards the factor. */
function AuthenticatorDialog({
  open,
  onOpenChange,
  friendlyName,
  onVerified
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  friendlyName: string;
  onVerified: () => Promise<void>;
}) {
  const auth = useAuth();
  const [enrolment, setEnrolment] = useState<{ id: string; qrCode: string; secret: string } | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !auth.supabase || enrolment) return;
    let cancelled = false;
    enrollTotp(auth.supabase, friendlyName)
      .then((started) => {
        if (!cancelled) setEnrolment(started);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(message(err, 'Enrolment could not start. Try again in a moment.'));
      });
    return () => {
      cancelled = true;
    };
  }, [open, auth.supabase, friendlyName, enrolment]);

  function close(verified: boolean) {
    if (!verified && enrolment && auth.supabase) {
      void unenrollFactor(auth.supabase, enrolment.id).catch(() => undefined);
    }
    setEnrolment(null);
    setCode('');
    setError(null);
    onOpenChange(false);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!auth.supabase || !enrolment) return;
    setBusy(true);
    setError(null);
    try {
      await verifyTotp(auth.supabase, code, enrolment.id);
      await onVerified();
      close(true);
    } catch (err) {
      setError(message(err, 'That code did not work. Wait for the next one and try again.'));
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && close(false)}>
      <DialogContent className={rafiiDialog}>
        <form onSubmit={submit} className='flex flex-col gap-5'>
          <DialogHeader className='gap-1.5 pr-8'>
            <DialogTitle className={DIALOG_TITLE}>Set up an authenticator app</DialogTitle>
            <DialogDescription className='leading-relaxed'>
              Scan the code with Google Authenticator, 1Password, Authy or any TOTP app, then enter the 6-digit code it shows.
            </DialogDescription>
          </DialogHeader>
          {error && <StateMessage kind='error' layout='inline' title={error} />}
          {enrolment ? (
            <div className='flex flex-col gap-4 sm:flex-row sm:items-start'>
              {/* Supabase returns the QR as an SVG data URI; nothing to optimise, so the loader is skipped. */}
              <Image
                src={enrolment.qrCode}
                alt='QR code for your authenticator app'
                width={176}
                height={176}
                unoptimized
                className='rafii-paper size-44 shrink-0 rounded-[var(--rafii-radius-control)] bg-white p-2'
              />
              <div className='flex min-w-0 flex-col gap-2 text-sm'>
                <span className='text-muted-foreground'>Cannot scan? Enter this key by hand:</span>
                <code className='rafii-quiet rounded-[var(--rafii-radius-micro)] px-2 py-1.5 text-xs break-all'>{enrolment.secret}</code>
                <Button
                  type='button'
                  size='sm'
                  variant='glass'
                  className='min-h-9 w-fit'
                  onClick={() => {
                    void navigator.clipboard.writeText(enrolment.secret).then(() => toast.success('Key copied.'));
                  }}
                >
                  <Icons.copy className='size-4' />
                  Copy key
                </Button>
              </div>
            </div>
          ) : (
            <StateMessage kind='loading' title='Preparing your enrolment' />
          )}
          <div className='flex flex-col gap-2'>
            <Label htmlFor='enrol-code'>Code from the app</Label>
            <CodeInput id='enrol-code' value={code} onChange={setCode} />
          </div>
          <DialogFooter className={rafiiDialogFooter}>
            <Button type='button' variant='quiet' size='control' disabled={busy} onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type='submit' variant='action' size='control' disabled={busy || !enrolment || code.trim().length < 6}>
              {busy ? 'Verifying…' : 'Verify and turn on'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Register a passkey. The device prompt (Face ID, Touch ID, Windows Hello, a key) is the whole flow. */
function PasskeyDialog({
  open,
  onOpenChange,
  friendlyName,
  onVerified
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  friendlyName: string;
  onVerified: () => Promise<void>;
}) {
  const auth = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setError(null);
    onOpenChange(false);
  }

  async function start() {
    if (!auth.supabase) return;
    setBusy(true);
    setError(null);
    try {
      await registerPasskey(auth.supabase, friendlyName);
      await onVerified();
      close();
    } catch (err) {
      setError(message(err, 'Your device did not complete the passkey setup.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && !busy && close()}>
      <DialogContent className={cn(rafiiDialog, 'gap-5')}>
        <DialogHeader className='gap-1.5 pr-8'>
          <DialogTitle className={DIALOG_TITLE}>Set up Face ID / Touch ID</DialogTitle>
          <DialogDescription className='leading-relaxed'>
            Your device will ask you to confirm with Face ID, Touch ID, Windows Hello or a security key. PostRiff keeps only a public key; the
            biometric never leaves your device. Passkeys saved to iCloud Keychain or Google Password Manager also work on your other devices.
          </DialogDescription>
        </DialogHeader>
        {error && <StateMessage kind='error' layout='inline' title={error} />}
        <DialogFooter className={rafiiDialogFooter}>
          <Button type='button' variant='quiet' size='control' disabled={busy} onClick={close}>
            Cancel
          </Button>
          <Button type='button' variant='action' size='control' disabled={busy} onClick={() => void start()}>
            <Icons.key className='size-4' aria-hidden />
            {busy ? 'Waiting for your device…' : 'Continue'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** "How do you want to confirm sign-ins?" — one row per method; a passkey needs WebAuthn in this browser. */
function MethodChooser({
  open,
  onOpenChange,
  onChoose,
  backup
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (kind: FactorKind) => void;
  backup: boolean;
}) {
  const passkeys = passkeysSupported();
  const options: { kind: FactorKind; title: string; note: string; icon: React.ReactNode; disabled?: boolean }[] = [
    {
      kind: 'webauthn',
      title: 'Face ID / Touch ID',
      note: passkeys ? 'A passkey on this device. Fastest, and phishing-resistant.' : 'This browser cannot create passkeys.',
      icon: <Icons.key className='size-5' aria-hidden />,
      disabled: !passkeys
    },
    {
      kind: 'totp',
      title: 'Authenticator app',
      note: 'Six-digit codes from Google Authenticator, 1Password, Authy…',
      icon: <Icons.phone className='size-5' aria-hidden />
    }
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(rafiiDialog, 'gap-5')}>
        <DialogHeader className='gap-1.5 pr-8'>
          <DialogTitle className={DIALOG_TITLE}>{backup ? 'Add a backup method' : 'How do you want to confirm sign-ins?'}</DialogTitle>
          <DialogDescription className='leading-relaxed'>
            {backup
              ? 'A second method keeps you signed in if you lose the first. There are no recovery codes.'
              : 'Every sign-in will ask for this after your email or Google account. You can add a backup afterwards.'}
          </DialogDescription>
        </DialogHeader>
        <div className='grid gap-2'>
          {options.map((option) => (
            <button
              key={option.kind}
              type='button'
              disabled={option.disabled}
              onClick={() => onChoose(option.kind)}
              className={cn(
                'rafii-quiet rafii-focus hover:rafii-glass-selected flex min-h-14 items-center gap-3 rounded-[var(--rafii-radius-control)] p-3 text-left transition-colors',
                option.disabled && 'cursor-not-allowed opacity-60 hover:rafii-quiet'
              )}
            >
              <span className={rafiiIconWell}>{option.icon}</span>
              <span className='flex min-w-0 flex-col'>
                <span className='text-foreground text-sm font-medium'>{option.title}</span>
                <span className='text-muted-foreground text-xs'>{option.note}</span>
              </span>
              <Icons.chevronRight className='text-muted-foreground ml-auto size-4' aria-hidden />
            </button>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TwoFactor() {
  const auth = useAuth();
  const me = useMe();
  const { api } = useWorkspace();
  const client = useQueryClient();
  const factors = useQuery({
    queryKey: FACTORS_KEY,
    queryFn: () => listFactors(auth.supabase as SupabaseClient),
    enabled: Boolean(auth.supabase)
  });
  const [choosing, setChoosing] = useState(false);
  const [enrolling, setEnrolling] = useState<FactorKind | null>(null);
  const [turningOff, setTurningOff] = useState(false);
  const [removing, setRemoving] = useState<SecondFactor | null>(null);

  const available = Boolean(auth.supabase) && (me.data?.mfa.available ?? false);
  const enforced = me.data?.mfa.enforced ?? false;
  const verified = (factors.data ?? []).filter((factor) => factor.verified);
  const count = (kind: FactorKind) => verified.filter((factor) => factor.kind === kind).length;
  const friendlyName =
    enrolling === 'webauthn'
      ? count('webauthn') === 0
        ? 'Passkey'
        : `Passkey ${count('webauthn') + 1}`
      : count('totp') === 0
        ? 'Authenticator app'
        : `Authenticator ${count('totp') + 1}`;

  async function refresh() {
    await Promise.all([client.invalidateQueries({ queryKey: keys.me }), client.invalidateQueries({ queryKey: FACTORS_KEY })]);
  }

  async function afterEnrol() {
    if (enforced) {
      toast.success('Backup method added.');
    } else {
      // The session is AAL2 now; the API records that this account must present a factor from here on.
      await api.enableMfa();
      toast.success('Two-factor authentication is on.');
    }
    await refresh();
  }

  async function turnOff() {
    await api.disableMfa();
    if (auth.supabase) {
      for (const factor of verified) await unenrollFactor(auth.supabase, factor.id);
    }
    toast.success('Two-factor authentication is off.');
    await refresh();
  }

  async function removeFactor(factor: SecondFactor) {
    if (auth.supabase) await unenrollFactor(auth.supabase, factor.id);
    toast.success(`${factor.name} removed.`);
    await refresh();
  }

  const methods = [count('webauthn') > 0 && 'Face ID / Touch ID', count('totp') > 0 && 'your authenticator app'].filter(Boolean).join(' or ');
  const explanation = !available
    ? 'Not available with a dev identity. Two-factor authentication needs a real sign-in provider.'
    : enforced
      ? `On since ${formatDate(me.data?.mfa.enforcedAt)}. Every sign-in needs ${methods || 'a second factor'}, and the API refuses sessions that have not shown one.`
      : 'Confirm every sign-in with Face ID / Touch ID or an authenticator app. Once on, the API refuses any session that has not shown one.';

  return (
    <SettingsGroup
      icon={<Icons.shieldCheck className='size-4' />}
      title={
        <span className='flex flex-wrap items-center gap-2'>
          Two-factor authentication
          {me.isLoading ? <Skeleton className='h-5 w-10' /> : <Badge variant={enforced ? 'default' : 'secondary'}>{enforced ? 'On' : 'Off'}</Badge>}
        </span>
      }
      description={me.isLoading ? <Skeleton className='h-4 w-64 max-w-full' /> : explanation}
      action={
        enforced ? (
          <Button variant='glass' size='control' disabled={!available} onClick={() => setTurningOff(true)}>
            Turn off
          </Button>
        ) : (
          <Button variant='action' size='control' disabled={!available || me.isLoading} onClick={() => setChoosing(true)}>
            Turn on
          </Button>
        )
      }
    >
      {available && enforced && (
        <div className='flex flex-col gap-3'>
          {factors.isLoading ? (
            <StateMessage kind='loading' title='Loading your methods' className='bg-transparent p-0' />
          ) : (
            <ul className='flex flex-col gap-1.5'>
              {verified.map((factor) => (
                <CollectionRow
                  key={factor.id}
                  as='li'
                  className='rafii-glass'
                  leading={
                    <span className={rafiiIconWell}>
                      {factor.kind === 'webauthn' ? <Icons.key className='size-4' aria-hidden /> : <Icons.phone className='size-4' aria-hidden />}
                    </span>
                  }
                  title={factor.name}
                  meta={`${KIND_LABEL[factor.kind]} · added ${formatDate(Date.parse(factor.createdAt) / 1000)}`}
                  state={verified.length > 1 ? undefined : 'Your only method'}
                  actions={
                    verified.length > 1 ? (
                      <Button variant='quiet' size='sm' className='min-h-9' onClick={() => setRemoving(factor)}>
                        Remove
                      </Button>
                    ) : undefined
                  }
                />
              ))}
            </ul>
          )}
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-muted-foreground max-w-[52ch] text-xs leading-relaxed'>
              This account has no recovery codes. A second method — a passkey on another device, or an authenticator app — is your backup.
            </p>
            <Button size='sm' variant='glass' className='min-h-10 px-3.5' onClick={() => setChoosing(true)}>
              <Icons.add className='size-4' />
              Add backup method
            </Button>
          </div>
        </div>
      )}

      <MethodChooser
        open={choosing}
        onOpenChange={setChoosing}
        backup={enforced}
        onChoose={(kind) => {
          setChoosing(false);
          setEnrolling(kind);
        }}
      />
      <AuthenticatorDialog
        open={enrolling === 'totp'}
        onOpenChange={(open) => !open && setEnrolling(null)}
        friendlyName={friendlyName}
        onVerified={afterEnrol}
      />
      <PasskeyDialog
        open={enrolling === 'webauthn'}
        onOpenChange={(open) => !open && setEnrolling(null)}
        friendlyName={friendlyName}
        onVerified={afterEnrol}
      />
      <StepUpDialog
        open={turningOff}
        onOpenChange={setTurningOff}
        title='Turn off two-factor authentication?'
        description='Sign-ins will need only your email or Google account. Confirm with your current method; every passkey and authenticator app is removed.'
        actionLabel='Turn off'
        destructive
        factors={verified}
        action={turnOff}
      />
      <StepUpDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.name ?? 'this method'}?`}
        description='Confirm with any of your current methods first.'
        actionLabel='Remove'
        destructive
        factors={verified}
        action={() => (removing ? removeFactor(removing) : Promise.resolve())}
      />
    </SettingsGroup>
  );
}

/** The two session marks: which row is this browser, and which have been revoked. */
function SessionBadges({ session }: { session: { current: boolean; revoked: boolean } }) {
  return (
    <>
      {session.current && <Badge variant='secondary'>this device</Badge>}
      {session.revoked && <Badge variant='secondary'>revoked</Badge>}
    </>
  );
}

function Sessions() {
  const { api } = useWorkspace();
  const sessions = useSessions();
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmOthers, setConfirmOthers] = useState(false);
  const list = sessions.data?.sessions ?? [];
  const others = list.filter((session) => !session.current && !session.revoked).length;

  const reportChangeError = useChangeError();

  async function revoke(sessionId: string) {
    setBusy(sessionId);
    try {
      await api.revokeSession(sessionId);
      toast.success('Session revoked.');
      await client.invalidateQueries({ queryKey: keys.sessions });
    } catch (err) {
      reportChangeError(err, 'The session could not be revoked.');
    } finally {
      setBusy(null);
    }
  }

  async function revokeOthers() {
    setBusy('others');
    try {
      const result = await api.revokeOtherSessions();
      toast.success(result.revoked === 1 ? '1 other session signed out.' : `${result.revoked} other sessions signed out.`);
      await client.invalidateQueries({ queryKey: keys.sessions });
    } catch (err) {
      reportChangeError(err, 'Other sessions could not be signed out.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <SettingsGroup
      icon={<Icons.laptop className='size-4' />}
      title='Where you are signed in'
      description='Every browser or device that used this account. Revoke any you do not recognise.'
      action={
        <Button variant='glass' size='control' disabled={others === 0 || busy !== null} onClick={() => setConfirmOthers(true)}>
          Sign out all other sessions
        </Button>
      }
    >
      {sessions.isLoading ? (
        <StateMessage kind='loading' title='Loading your sessions' className='bg-transparent p-0' />
      ) : sessions.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title='Sessions could not be loaded.'
          action={
            <Button size='sm' variant='glass' className='min-h-9' onClick={() => void sessions.refetch()}>
              Retry
            </Button>
          }
        />
      ) : (
        <>
          {/* Phones: one row per session (DNA §19.3); the table returns from md up. */}
          <ul className='flex flex-col gap-1.5 md:hidden'>
            {list.map((session) => (
              <CollectionRow
                key={session.sessionId}
                as='li'
                className='rafii-glass flex-wrap'
                title={
                  <span className='flex flex-wrap items-center gap-2'>
                    {session.client || 'Unknown device'}
                    <SessionBadges session={session} />
                  </span>
                }
                meta={`Last seen ${relativeTime(session.lastSeen)}`}
                actions={
                  !session.current && !session.revoked ? (
                    <Button variant='quiet' size='sm' className='min-h-9' disabled={busy !== null} onClick={() => void revoke(session.sessionId)}>
                      Revoke
                    </Button>
                  ) : undefined
                }
              />
            ))}
          </ul>
          <div className='relative rafii-glass hidden overflow-x-auto rounded-[var(--rafii-radius-card)] px-2 md:block'>
            <Table>
              <TableHeader>
                <TableRow className='hover:bg-transparent'>
                  <TableHead>Device</TableHead>
                  <TableHead>Last seen</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((session) => (
                  <TableRow key={session.sessionId} className='hover:bg-transparent'>
                    <TableCell>
                      <span className='inline-flex flex-wrap items-center gap-2'>
                        {session.client || 'Unknown device'}
                        <SessionBadges session={session} />
                      </span>
                    </TableCell>
                    <TableCell className='text-muted-foreground text-xs'>{relativeTime(session.lastSeen)}</TableCell>
                    <TableCell className='text-right'>
                      {!session.current && !session.revoked && (
                        <Button variant='quiet' size='sm' className='min-h-9' disabled={busy !== null} onClick={() => void revoke(session.sessionId)}>
                          Revoke
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
      <AlertDialog open={confirmOthers} onOpenChange={setConfirmOthers}>
        <AlertDialogContent className={rafiiDialog}>
          <AlertDialogHeader>
            <AlertDialogTitle className='text-foreground text-lg font-medium tracking-tight'>Sign out every other session?</AlertDialogTitle>
            <AlertDialogDescription className='leading-relaxed'>
              {others === 1 ? '1 other device' : `${others} other devices`} will be signed out. This device stays signed in. A recent sign-in is required; if yours is older, sign in again first.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className={rafiiDialogFooter}>
            <AlertDialogCancel variant='quiet' size='control'>Keep them</AlertDialogCancel>
            <AlertDialogAction
              variant='action'
              size='control'
              onClick={() => {
                setConfirmOthers(false);
                void revokeOthers();
              }}
            >
              Sign out others
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsGroup>
  );
}

const ACTIVITY_PREVIEW = 8;

/** The person's own account history, read from the audit trail; workspace content activity is not here. */
function SecurityActivity() {
  const events = useSecurityEvents();
  const [expanded, setExpanded] = useState(false);
  const list = events.data?.events ?? [];
  const shown = expanded ? list : list.slice(0, ACTIVITY_PREVIEW);

  return (
    <SettingsGroup
      icon={<Icons.history className='size-4' />}
      title='Recent security activity'
      description='Sign-ins, two-factor changes, revoked sessions and changes to your memberships. What happens to content lives in each workspace’s audit log.'
    >
      {events.isLoading ? (
        <StateMessage kind='loading' title='Loading your account history' className='bg-transparent p-0' />
      ) : events.isError ? (
        <StateMessage
          kind='error'
          layout='inline'
          title='Activity could not be loaded.'
          action={
            <Button size='sm' variant='glass' className='min-h-9' onClick={() => void events.refetch()}>
              Retry
            </Button>
          }
        />
      ) : list.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='Nothing recorded yet.' />
      ) : (
        <ol className='rafii-glass flex flex-col rounded-[var(--rafii-radius-card)] px-4 py-1'>
          {shown.map((event) => {
            const described = describeSecurityEvent(event);
            return (
              <li key={event.id} className='flex min-h-11 items-center justify-between gap-3 py-2 text-sm'>
                <span className='text-foreground flex min-w-0 items-center gap-2'>
                  {described.tone === 'warning' && <Icons.warning className='text-muted-foreground size-4 shrink-0' aria-label='Worth a second look' />}
                  <span className='min-w-0'>{described.label}</span>
                </span>
                <time
                  dateTime={new Date(event.at * 1000).toISOString()}
                  title={formatDateTime(event.at)}
                  className='text-muted-foreground shrink-0 text-xs'
                >
                  {relativeTime(event.at)}
                </time>
              </li>
            );
          })}
        </ol>
      )}
      {list.length > ACTIVITY_PREVIEW && (
        <Button variant='quiet' size='sm' className='min-h-9 w-fit' onClick={() => setExpanded((value) => !value)}>
          {expanded ? 'Show fewer' : `Show all ${list.length}`}
        </Button>
      )}
    </SettingsGroup>
  );
}

/** One quiet settings surface with three groups; spacing, not rules, separates them (DNA §5.5). */
export function SecurityCard() {
  return (
    <SettingsSection id='profile-security' title='Security' description='How this account is protected, where it is signed in, and what has happened to it.' bodyClassName='gap-8'>
      <TwoFactor />
      <Sessions />
      <SecurityActivity />
    </SettingsSection>
  );
}
