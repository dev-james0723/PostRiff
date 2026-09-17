'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
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
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { keys, useMe, useMyChannels, useMyInvitations } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { MyChannel, PendingInvitation, WorkspaceListItem } from '@/lib/api/types';
import type { WorkspaceRole } from '@/types';
import { allows, ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { useAuth } from '@/lib/auth/session';
import { formatDate } from '@/lib/time';
import { useWorkspace } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import {
  canLeave,
  channelBadge,
  extraGrants,
  groupByWorkspace,
  isStaff,
  memberTiers,
  needsReconnect,
  planLabel,
  SIGN_IN_METHODS
} from './profile-model';
import { PasskeysCard } from './passkeys-card';
import { PreferencesCard } from './preferences-card';
import { SecurityCard } from './security-card';

const infoContent = {
  title: 'What lives here',
  sections: [
    {
      title: 'You, not the workspace',
      description:
        'Profile covers your identity, how your account is secured and what you can reach. Workspace settings stay on the Workspace pages; this page summarises them and links across.'
    },
    {
      title: 'Two-factor authentication',
      description:
        'Once it is on, every sign-in needs Face ID / Touch ID or a code from your authenticator app, and the API refuses sessions without one. Add a second method as a backup: there are no recovery codes.'
    },
    {
      title: 'Owner, staff, members',
      description:
        'Each workspace has one owner (billing and deletion), staff (the owner plus admins, who manage members, roles and connections) and members (editors, approvers and viewers who do the content work).'
    }
  ]
};

function message(err: unknown, fallback: string) {
  return err instanceof ApiError || err instanceof Error ? err.message : fallback;
}

/**
 * Change the sign-in email through the auth provider. Supabase mails a confirmation link to the new
 * address (and, with secure email change, to the current one); nothing changes until they are opened.
 * The API never stores the address, so there is nothing to update on our side.
 */
function EmailChangeDialog({
  open,
  onOpenChange,
  current,
  pending
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  current?: string;
  pending?: string;
}) {
  const auth = useAuth();
  const [email, setEmail] = useState(pending ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setEmail(pending ?? '');
      setError(null);
    }
  }, [open, pending]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!auth.supabase) return;
    const next = email.trim().toLowerCase();
    if (next === (current ?? '').toLowerCase()) {
      setError('That is already your sign-in email.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { error: updateError } = await auth.supabase.auth.updateUser({ email: next });
      if (updateError) throw updateError;
      toast.success(`Confirmation sent to ${next}. Open the links in both inboxes to finish.`);
      onOpenChange(false);
    } catch (err) {
      setError(message(err, 'The email could not be changed.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent>
        <form onSubmit={submit} className='flex flex-col gap-4'>
          <DialogHeader>
            <DialogTitle>Change sign-in email</DialogTitle>
            <DialogDescription>
              A confirmation link goes to the new address{current ? ` and to ${current}` : ''}. Your sign-in email changes only after the links are
              opened; until then everything keeps working as it does now.
            </DialogDescription>
          </DialogHeader>
          {error && (
            <Alert variant='destructive'>
              <Icons.alertCircle className='size-4' />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className='flex flex-col gap-1.5'>
            <Label htmlFor='new-email'>New email address</Label>
            <Input id='new-email' type='email' autoComplete='email' required value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
          <DialogFooter>
            <Button type='button' variant='ghost' disabled={busy} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type='submit' disabled={busy || !email.includes('@')}>
              {busy ? 'Sending…' : pending ? 'Resend confirmation' : 'Send confirmation'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function IdentityCard() {
  const auth = useAuth();
  const me = useMe();
  const { api } = useWorkspace();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [changingEmail, setChangingEmail] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const dev = auth.mode === 'dev';
  const displayName = me.data?.displayName || auth.user?.name || '';

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const name = draft.trim();
      // The API copy is what other members see (workspace owner name); the provider copy feeds the avatar.
      await api.updateProfile({ displayName: name });
      if (auth.supabase) {
        const { error } = await auth.supabase.auth.updateUser({ data: { full_name: name } });
        if (error) throw error;
      }
      await client.invalidateQueries({ queryKey: keys.me });
      toast.success('Name updated.');
      setEditing(false);
    } catch (err) {
      toast.error(message(err, 'Your name could not be saved.'));
    } finally {
      setBusy(false);
    }
  }

  const method = dev
    ? 'Local dev identity'
    : (SIGN_IN_METHODS[auth.user?.provider ?? ''] ?? auth.user?.provider ?? 'Sign-in provider');
  const since = auth.user?.createdAt ? formatDate(Date.parse(auth.user.createdAt) / 1000) : null;

  return (
    <Card>
      <CardHeader>
        <div className='flex items-start justify-between gap-2'>
          <div className='flex flex-col gap-1.5'>
            <CardTitle>Identity</CardTitle>
            <CardDescription>Who you are, in every workspace.</CardDescription>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant='ghost' size='icon' aria-label='More about this account' />}>
              <Icons.dots className='size-4' />
            </DropdownMenuTrigger>
            <DropdownMenuContent align='end'>
              <DropdownMenuItem
                onClick={() => {
                  void navigator.clipboard.writeText(auth.user?.id ?? '').then(() => toast.success('User ID copied.'));
                }}
              >
                <Icons.copy className='mr-2 size-4' />
                Copy user ID (for support)
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>
      <CardContent className='flex flex-col gap-5'>
        <div className='flex items-start gap-3'>
          <UserAvatarProfile
            className='size-14 rounded-lg'
            user={{ name: displayName || auth.user?.name, email: auth.user?.email, imageUrl: auth.user?.imageUrl }}
          />
          <div className='flex min-w-0 flex-1 flex-col gap-1'>
            {editing ? (
              <form onSubmit={save} className='flex flex-wrap items-end gap-2'>
                <div className='flex min-w-0 flex-1 flex-col gap-1.5'>
                  <Label htmlFor='display-name'>Display name</Label>
                  <Input id='display-name' value={draft} maxLength={80} autoFocus onChange={(event) => setDraft(event.target.value)} />
                </div>
                <Button type='submit' size='sm' disabled={busy}>
                  {busy ? 'Saving…' : 'Save'}
                </Button>
                <Button type='button' size='sm' variant='ghost' disabled={busy} onClick={() => setEditing(false)}>
                  Cancel
                </Button>
              </form>
            ) : (
              <div className='flex flex-wrap items-center gap-2'>
                {me.isLoading ? (
                  <Skeleton className='h-6 w-32' />
                ) : (
                  <span className={cn('truncate text-lg font-semibold', !displayName && 'text-muted-foreground font-normal')}>
                    {displayName || 'Add your name'}
                  </span>
                )}
                <Button
                  variant='ghost'
                  size='sm'
                  aria-label='Edit display name'
                  onClick={() => {
                    setDraft(displayName);
                    setEditing(true);
                  }}
                >
                  <Icons.edit className='size-4' />
                  Edit
                </Button>
                {dev && <Badge variant='secondary'>Dev identity</Badge>}
              </div>
            )}
            <div className='text-muted-foreground flex flex-wrap items-center gap-2 text-sm'>
              <span className='truncate'>{auth.user?.email}</span>
              {!dev &&
                (auth.user?.emailVerified ? (
                  <Badge variant='outline' className='gap-1'>
                    <Icons.check className='size-3' aria-hidden />
                    Verified
                  </Badge>
                ) : (
                  <Badge variant='secondary'>Unverified</Badge>
                ))}
              {!dev && auth.supabase && (
                <Button variant='link' size='sm' className='h-auto px-0' onClick={() => setChangingEmail(true)}>
                  Change
                </Button>
              )}
            </div>
            {!dev && auth.user?.pendingEmail && (
              <p className='text-muted-foreground text-xs'>
                Changing to <span className='text-foreground font-medium'>{auth.user.pendingEmail}</span> — open the confirmation links sent to
                both addresses.{' '}
                <Button variant='link' size='sm' className='h-auto px-0 text-xs' onClick={() => setChangingEmail(true)}>
                  Resend
                </Button>
              </p>
            )}
          </div>
        </div>
        {!dev && (
          <EmailChangeDialog open={changingEmail} onOpenChange={setChangingEmail} current={auth.user?.email} pending={auth.user?.pendingEmail} />
        )}
        <dl className='grid grid-cols-[7rem_1fr] gap-y-1.5 text-sm'>
          <dt className='text-muted-foreground'>Sign-in</dt>
          <dd>{method}</dd>
          {since && (
            <>
              <dt className='text-muted-foreground'>Member since</dt>
              <dd>{since}</dd>
            </>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

/** "connected by you · 3 Sep" / "connected by Ada · 3 Sep" / "connected 3 Sep" when the trail has no actor. */
function connectedLine(channel: MyChannel, selfId: string | undefined) {
  const who = channel.connectedBy;
  if (!who) return channel.verifiedAt ? ` · connected ${formatDate(channel.verifiedAt)}` : '';
  const name = who.userId === selfId ? 'you' : who.displayName || 'a member';
  return ` · connected by ${name} ${formatDate(who.at)}`;
}

function ChannelsCard() {
  const auth = useAuth();
  const channels = useMyChannels();
  const router = useRouter();
  const { workspaceId, switchTo, membership } = useWorkspace();
  const canConnectHere = membership ? allows(membership, 'manage_connections') : false;
  const groups = groupByWorkspace(channels.data?.channels ?? []);

  function open(target: string) {
    if (target !== workspaceId) switchTo(target);
    router.push('/app/channels');
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connected channels</CardTitle>
        <CardDescription>
          Every account PostRiff can reach, in every workspace you belong to. Connecting and disconnecting happen on each workspace&apos;s Channels page.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        {channels.isLoading ? (
          <Skeleton className='h-24 w-full' />
        ) : channels.isError ? (
          <Alert variant='destructive'>
            <Icons.alertCircle className='size-4' />
            <AlertDescription className='flex items-center justify-between gap-2'>
              Channels could not be loaded.
              <Button size='sm' variant='outline' onClick={() => void channels.refetch()}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ) : groups.length === 0 ? (
          <Empty className='border py-8'>
            <EmptyHeader>
              <EmptyMedia variant='icon'>
                <Icons.broadcast />
              </EmptyMedia>
              <EmptyTitle>No channels connected</EmptyTitle>
              <EmptyDescription>
                {canConnectHere ? 'Connect an account to start publishing.' : 'An owner or admin connects accounts for this workspace.'}
              </EmptyDescription>
            </EmptyHeader>
            {canConnectHere && (
              <Link href='/app/channels' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
                Open channels
              </Link>
            )}
          </Empty>
        ) : (
          groups.map((group) => (
            <section key={group.workspaceId} aria-label={group.workspaceName} className='flex flex-col gap-2'>
              <div className='flex items-center gap-2 text-sm font-medium'>
                <Icons.workspace className='text-muted-foreground size-4' aria-hidden />
                {group.workspaceName}
                {group.workspaceId === workspaceId && <Badge variant='outline'>Current</Badge>}
              </div>
              <ul className='divide-y rounded-lg border'>
                {group.channels.map((channel) => {
                  const badge = channelBadge(channel);
                  const reconnect = needsReconnect(channel);
                  return (
                    <li key={channel.id} className='flex flex-wrap items-center gap-3 px-3 py-2.5'>
                      <ChannelIcon platform={channel.platform} name={channel.platform} />
                      <div className='min-w-0 flex-1'>
                        <div className='truncate text-sm font-medium'>{channel.account || channel.platform}</div>
                        <div className='text-muted-foreground text-xs'>
                          {channel.platform}
                          {connectedLine(channel, auth.user?.id)}
                          {channel.expiresAt && badge.status === 'success' ? ` · valid until ${formatDate(channel.expiresAt)}` : ''}
                        </div>
                      </div>
                      <AnimatedBadge status={badge.status} size='sm'>
                        {badge.label}
                      </AnimatedBadge>
                      <Button variant={reconnect ? 'default' : 'ghost'} size='sm' onClick={() => open(channel.workspaceId)}>
                        {reconnect ? 'Reconnect' : 'Open'}
                        <Icons.arrowRight className='size-4' aria-hidden />
                      </Button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function Tier({ label, count, note }: { label: string; count: number; note: string }) {
  return (
    <div className='bg-muted/40 flex flex-col gap-0.5 rounded-md px-3 py-2'>
      <div className='flex items-baseline justify-between gap-2'>
        <span className='text-sm font-medium'>{label}</span>
        <span className='text-lg font-semibold tabular-nums'>{count}</span>
      </div>
      <span className='text-muted-foreground text-xs'>{note}</span>
    </div>
  );
}

/** Invitations addressed to the person's verified email, settled here instead of through the emailed link. */
function PendingInvitations() {
  const invitations = useMyInvitations();
  const { api, refresh } = useWorkspace();
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [declining, setDeclining] = useState<PendingInvitation | null>(null);
  const list = invitations.data?.invitations ?? [];
  if (list.length === 0) return null;

  async function settle() {
    // `me` is the prefix for invitations, channels and the activity feed.
    await client.invalidateQueries({ queryKey: keys.me });
  }

  async function accept(invitation: PendingInvitation) {
    setBusy(invitation.invitationId);
    try {
      const joined = await api.acceptMyInvitation(invitation.invitationId);
      toast.success(`You joined ${invitation.workspaceName} as ${ROLE_LABELS[joined.role as WorkspaceRole] ?? joined.role}.`);
      await refresh(joined.workspaceId);
      await settle();
    } catch (err) {
      toast.error(message(err, 'The invitation could not be accepted.'));
    } finally {
      setBusy(null);
    }
  }

  async function decline(invitation: PendingInvitation) {
    setBusy(invitation.invitationId);
    try {
      await api.declineMyInvitation(invitation.invitationId);
      toast.success(`Declined the invitation to ${invitation.workspaceName}.`);
      await settle();
    } catch (err) {
      toast.error(message(err, 'The invitation could not be declined.'));
    } finally {
      setBusy(null);
      setDeclining(null);
    }
  }

  return (
    <section aria-label='Invitations waiting for you' className='border-primary/30 bg-primary/5 flex flex-col gap-2 rounded-lg border p-4'>
      <div className='flex items-center gap-2 text-sm font-medium'>
        <Icons.send className='text-primary size-4' aria-hidden />
        Invitations waiting for you
      </div>
      <ul className='divide-y'>
        {list.map((invitation) => {
          const role = invitation.role as WorkspaceRole;
          return (
            <li key={invitation.invitationId} className='flex flex-wrap items-center justify-between gap-3 py-2'>
              <div className='min-w-0'>
                <div className='truncate text-sm font-medium'>{invitation.workspaceName}</div>
                <div className='text-muted-foreground text-xs'>
                  {ROLE_LABELS[role] ?? invitation.role} · {ROLE_DESCRIPTIONS[role] ?? ''}
                </div>
                <div className='text-muted-foreground text-xs'>
                  Invited by {invitation.invitedBy.displayName || 'a workspace admin'} · expires {formatDate(invitation.expiresAt)}
                </div>
              </div>
              <div className='flex gap-2'>
                <Button size='sm' disabled={busy !== null} onClick={() => void accept(invitation)}>
                  {busy === invitation.invitationId ? 'Joining…' : 'Accept'}
                </Button>
                <Button size='sm' variant='ghost' disabled={busy !== null} onClick={() => setDeclining(invitation)}>
                  Decline
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      <AlertDialog open={declining !== null} onOpenChange={(open) => !open && setDeclining(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Decline the invitation to {declining?.workspaceName}?</AlertDialogTitle>
            <AlertDialogDescription>The link stops working. A workspace admin can invite you again later.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction disabled={busy !== null} onClick={() => declining && void decline(declining)}>
              Decline
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

function WorkspaceRow({ item, current }: { item: WorkspaceListItem; current: boolean }) {
  const auth = useAuth();
  const router = useRouter();
  const client = useQueryClient();
  const { api, switchTo, refresh } = useWorkspace();
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [busy, setBusy] = useState(false);
  const role = item.membership.role;
  const tiers = memberTiers(item.memberCounts);
  const grants = extraGrants(item.membership);
  const owner = item.owner ? (item.owner.userId === auth.user?.id ? 'you' : item.owner.displayName || 'the owner') : '—';

  function go(path: string) {
    if (!current) switchTo(item.workspaceId);
    router.push(path);
  }

  async function leave() {
    setBusy(true);
    try {
      await api.leaveWorkspace(item.workspaceId);
      toast.success(`You left ${item.name}.`);
      await refresh();
      void client.invalidateQueries({ queryKey: keys.me });
    } catch (err) {
      toast.error(message(err, 'You could not leave this workspace.'));
    } finally {
      setBusy(false);
      setConfirmLeave(false);
    }
  }

  return (
    <div className='flex flex-col gap-4 rounded-lg border p-4'>
      <div className='flex flex-wrap items-start justify-between gap-2'>
        <div className='flex min-w-0 flex-col gap-1'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='truncate font-medium'>{item.name}</span>
            {current && <Badge variant='outline'>Current</Badge>}
            <Badge variant='secondary'>{planLabel(item)}</Badge>
          </div>
          <div className='text-muted-foreground text-xs'>
            Owned by {owner} · {tiers.total} {tiers.total === 1 ? 'person' : 'people'}
          </div>
        </div>
        <div className='flex flex-wrap gap-2'>
          {!current && (
            <Button size='sm' variant='outline' onClick={() => switchTo(item.workspaceId)}>
              Switch
            </Button>
          )}
          {isStaff(role) && (
            <Button size='sm' variant='outline' onClick={() => go('/app/workspace/members')}>
              <Icons.teams className='size-4' aria-hidden />
              Manage members
            </Button>
          )}
        </div>
      </div>

      <div className='grid gap-2 sm:grid-cols-3'>
        <Tier label='Owner' count={tiers.owners} note='Billing, deletion, member roles' />
        <Tier label='Staff' count={tiers.staff} note='Owner and admins: members, roles, connections' />
        <Tier label='Members' count={tiers.members} note='Editors, approvers and viewers' />
      </div>

      <div className='flex flex-col gap-0.5 text-sm'>
        <div>
          <span className='text-muted-foreground'>Your role: </span>
          <span className='font-medium'>{ROLE_LABELS[role]}</span>
          {grants.length > 0 && <span className='text-muted-foreground'> · can also {grants.join(', ')}</span>}
        </div>
        <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
      </div>

      <div className='flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs'>
        {canLeave(role) ? (
          <>
            <span className='text-muted-foreground'>Leaving removes your access. Drafts you wrote stay in the workspace.</span>
            <Button size='sm' variant='ghost' className='text-destructive' disabled={busy} onClick={() => setConfirmLeave(true)}>
              Leave workspace
            </Button>
          </>
        ) : (
          <span className='text-muted-foreground'>You own this workspace. Transfer ownership first if you want to leave it.</span>
        )}
      </div>

      <AlertDialog open={confirmLeave} onOpenChange={setConfirmLeave}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Leave {item.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              You lose access immediately and can only return by invitation. Nothing you wrote is deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Stay</AlertDialogCancel>
            <AlertDialogAction disabled={busy} onClick={() => void leave()}>
              {busy ? 'Leaving…' : 'Leave'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function WorkspacesCard() {
  const { workspaces, workspaceId, status } = useWorkspace();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Workspaces &amp; access</CardTitle>
        <CardDescription>
          Each workspace has one owner, staff who run it (the owner and admins) and members who do the content work. Your role sets what you can do in each.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        <PendingInvitations />
        {status !== 'ready' ? (
          <Skeleton className='h-40 w-full' />
        ) : (
          workspaces.map((item) => <WorkspaceRow key={item.workspaceId} item={item} current={item.workspaceId === workspaceId} />)
        )}
      </CardContent>
    </Card>
  );
}

function AccountActions() {
  const auth = useAuth();
  const router = useRouter();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);

  function signOut() {
    setBusy(true);
    void auth.signOut().then(() => router.replace('/auth/sign-in'));
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>Signing out ends the session on this device only; other devices stay signed in unless you revoke them above.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-wrap items-center gap-3'>
        <Button
          variant='destructive'
          className='bg-destructive hover:bg-destructive/90 dark:bg-destructive dark:hover:bg-destructive/90 text-white'
          disabled={busy}
          onClick={() => setConfirm(true)}
        >
          <Icons.logout className='size-4' aria-hidden />
          {busy ? 'Signing out…' : 'Sign out'}
        </Button>
        <Link href='/app/account/privacy' className={cn(buttonVariants({ variant: 'ghost' }), 'text-muted-foreground')}>
          Delete account
          <Icons.arrowRight className='size-4' aria-hidden />
        </Link>
        <AlertDialog open={confirm} onOpenChange={setConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Sign out on this device?</AlertDialogTitle>
              <AlertDialogDescription>
                Your drafts, schedule and settings stay exactly where they are. You will need to sign in again here; other devices are not affected.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Stay signed in</AlertDialogCancel>
              <AlertDialogAction
                className='bg-destructive hover:bg-destructive/90 text-white'
                onClick={() => {
                  setConfirm(false);
                  signOut();
                }}
              >
                Sign out
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}

export function ProfileView() {
  return (
    <PageContainer
      pageTitle='Profile'
      pageDescription='Your identity, how your account is secured, and what you can reach.'
      infoContent={infoContent}
    >
      <div className='grid gap-4 lg:grid-cols-2'>
        <div className='flex flex-col gap-4'>
          <IdentityCard />
          <PreferencesCard />
        </div>
        <div className='flex flex-col gap-4'>
          <SecurityCard />
          <PasskeysCard />
        </div>
        <div className='lg:col-span-2'>
          <ChannelsCard />
        </div>
        <div className='lg:col-span-2'>
          <WorkspacesCard />
        </div>
        <div className='lg:col-span-2'>
          <AccountActions />
        </div>
      </div>
    </PageContainer>
  );
}
