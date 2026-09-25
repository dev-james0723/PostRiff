'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { rafiiDialog, rafiiDialogFooter, rafiiInput, rafiiMenu } from '@/components/auth/form-styles';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { CollectionRow, InfoTip, StateMessage, Surface } from '@/components/rafii';
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
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
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
import { SettingsSection } from './settings-section';

const infoContent = {
  title: 'What lives here',
  sections: [
    {
      title: 'You, not the workspace',
      description: 'Your identity, security and access. Workspace settings live on the Workspace pages.'
    },
    {
      title: 'Two-factor authentication',
      description: 'Once on, every sign-in needs Face ID / Touch ID or an authenticator code. Add a second method as a backup: there are no recovery codes.'
    },
    {
      title: 'Owner, staff, members',
      description: 'One owner (billing and deletion). Staff: the owner and admins, who manage members, roles and connections. Members: editors, approvers and viewers.'
    }
  ]
};

const DIALOG_TITLE = 'text-foreground text-xl font-medium tracking-tight';

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
      toast.success('Confirmation sent. Open the links in both inboxes.');
      onOpenChange(false);
    } catch (err) {
      setError(message(err, 'The email could not be changed.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className={rafiiDialog}>
        <form onSubmit={submit} className='flex flex-col gap-5'>
          <DialogHeader className='gap-1.5 pr-8'>
            <DialogTitle className={DIALOG_TITLE}>Change sign-in email</DialogTitle>
            <DialogDescription className='leading-relaxed'>
              We’ll email a link to the new address{current ? ` and to ${current}` : ''}. It changes once the links are opened.
            </DialogDescription>
          </DialogHeader>
          {error && <StateMessage kind='error' layout='inline' title={error} />}
          <div className='flex flex-col gap-2'>
            <Label htmlFor='new-email'>New email address</Label>
            <Input id='new-email' type='email' autoComplete='email' required value={email} onChange={(event) => setEmail(event.target.value)} className={rafiiInput} />
          </div>
          <DialogFooter className={rafiiDialogFooter}>
            <Button type='button' variant='quiet' size='control' disabled={busy} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type='submit' variant='action' size='control' disabled={busy || !email.includes('@')}>
              {busy ? 'Sending…' : pending ? 'Resend confirmation' : 'Send confirmation'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The page's identity block on the one glass surface: who you are, in every workspace. */
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
      setEditing(false);
    } catch (err) {
      toast.error(message(err, 'Couldn’t save your name.'));
    } finally {
      setBusy(false);
    }
  }

  const method = dev
    ? 'Local dev identity'
    : (SIGN_IN_METHODS[auth.user?.provider ?? ''] ?? auth.user?.provider ?? 'Unknown');
  const since = auth.user?.createdAt ? formatDate(Date.parse(auth.user.createdAt) / 1000) : null;

  return (
    <SettingsSection
      id='profile-identity'
      title='Identity'
      material='glass'
      action={
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant='quiet' size='icon-control' aria-label='More about this account' />}>
            <Icons.dots className='size-4' />
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className={cn(rafiiMenu, 'min-w-60 p-1.5')}>
            <DropdownMenuItem
              className='min-h-10 rounded-[0.625rem]'
              onClick={() => {
                void navigator.clipboard.writeText(auth.user?.id ?? '').then(() => toast.success('User ID copied.'));
              }}
            >
              <Icons.copy className='mr-2 size-4' />
              Copy user ID (for support)
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      }
      bodyClassName='gap-5'
    >
      <div className='flex items-start gap-4'>
        <UserAvatarProfile
          className='size-14 rounded-[var(--rafii-radius-control)]'
          user={{ name: displayName || auth.user?.name, email: auth.user?.email, imageUrl: auth.user?.imageUrl }}
        />
        <div className='flex min-w-0 flex-1 flex-col gap-1.5'>
          {editing ? (
            <form onSubmit={save} className='flex flex-wrap items-end gap-2'>
              <div className='flex min-w-0 flex-1 flex-col gap-2'>
                <Label htmlFor='display-name'>Display name</Label>
                <Input id='display-name' value={draft} maxLength={80} autoFocus onChange={(event) => setDraft(event.target.value)} className={rafiiInput} />
              </div>
              <Button type='submit' variant='action' size='control' disabled={busy}>
                {busy ? 'Saving…' : 'Save'}
              </Button>
              <Button type='button' variant='quiet' size='control' disabled={busy} onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </form>
          ) : (
            <div className='flex flex-wrap items-center gap-2'>
              {me.isLoading ? (
                <Skeleton className='h-6 w-32' />
              ) : (
                <span className={cn('text-foreground truncate text-lg font-medium tracking-tight', !displayName && 'text-muted-foreground font-normal')}>
                  {displayName || 'Add your name'}
                </span>
              )}
              <Button
                variant='quiet'
                size='sm'
                className='min-h-9'
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
                <Badge variant='secondary' className='gap-1'>
                  <Icons.check className='size-3' aria-hidden />
                  Verified
                </Badge>
              ) : (
                <Badge variant='secondary'>Unverified</Badge>
              ))}
            {!dev && auth.supabase && (
              <Button variant='quiet' size='sm' className='text-foreground h-auto min-h-9 px-2 underline underline-offset-4' onClick={() => setChangingEmail(true)}>
                Change
              </Button>
            )}
          </div>
          {!dev && auth.user?.pendingEmail && (
            <p className='text-muted-foreground text-xs leading-relaxed'>
              Changing to <span className='text-foreground font-medium'>{auth.user.pendingEmail}</span>. Confirm from both inboxes.{' '}
              <Button variant='quiet' size='sm' className='text-foreground h-auto min-h-8 px-1.5 text-xs underline underline-offset-4' onClick={() => setChangingEmail(true)}>
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
        <dd className='text-foreground'>{method}</dd>
        {since && (
          <>
            <dt className='text-muted-foreground'>Member since</dt>
            <dd className='text-foreground'>{since}</dd>
          </>
        )}
      </dl>
    </SettingsSection>
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
    <SettingsSection
      id='profile-channels'
      title='Connected channels'
      description='Across all your workspaces.'
      material='none'
      bodyClassName='gap-5'
    >
      {channels.isLoading ? (
        <StateMessage kind='loading' title='Loading your channels' />
      ) : channels.isError ? (
        <StateMessage
          kind='error'
          title='Couldn’t load channels'
          action={
            <Button size='sm' variant='glass' className='min-h-9' onClick={() => void channels.refetch()}>
              Retry
            </Button>
          }
        />
      ) : groups.length === 0 ? (
        <StateMessage
          kind='empty'
          media={
            <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
              <Icons.broadcast className='size-5' />
            </span>
          }
          title='No channels connected'
          description={canConnectHere ? 'Connect an account to start publishing.' : 'An owner or admin connects accounts for this workspace.'}
          action={
            canConnectHere ? (
              <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
                Open channels
              </Link>
            ) : undefined
          }
        />
      ) : (
        groups.map((group) => (
          <section key={group.workspaceId} aria-label={group.workspaceName} className='flex flex-col gap-2'>
            <div className='text-foreground flex items-center gap-2 px-1 text-sm font-medium'>
              <Icons.workspace className='text-muted-foreground size-4' aria-hidden />
              {group.workspaceName}
              {group.workspaceId === workspaceId && <Badge variant='secondary'>Current</Badge>}
            </div>
            <ul className='flex flex-col gap-1.5'>
              {group.channels.map((channel) => {
                const badge = channelBadge(channel);
                const reconnect = needsReconnect(channel);
                return (
                  <CollectionRow
                    key={channel.id}
                    as='li'
                    className='flex-wrap'
                    leading={<ChannelIcon platform={channel.platform} name={channel.platform} />}
                    title={channel.account || channel.platform}
                    meta={
                      <>
                        {channel.platform}
                        <span className='hidden md:inline'>{connectedLine(channel, auth.user?.id)}</span>
                      </>
                    }
                    state={
                      <AnimatedBadge status={badge.status} size='sm'>
                        {badge.label}
                      </AnimatedBadge>
                    }
                    actions={
                      <Button variant={reconnect ? 'action' : 'quiet'} size='sm' className='min-h-9' onClick={() => open(channel.workspaceId)}>
                        {reconnect ? 'Reconnect' : 'Open'}
                        <Icons.arrowRight className='size-4' aria-hidden />
                      </Button>
                    }
                  />
                );
              })}
            </ul>
          </section>
        ))
      )}
    </SettingsSection>
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
      await settle();
    } catch (err) {
      toast.error(message(err, 'The invitation could not be declined.'));
    } finally {
      setBusy(null);
      setDeclining(null);
    }
  }

  return (
    <Surface as='section' material='glass' radius='card' padding='md' aria-label='Invitations waiting for you' className='flex flex-col gap-3'>
      <div className='text-foreground flex items-center gap-2 text-sm font-medium'>
        <Icons.send className='text-muted-foreground size-4' aria-hidden />
        Invitations waiting for you
      </div>
      <ul className='flex flex-col gap-3'>
        {list.map((invitation) => {
          const role = invitation.role as WorkspaceRole;
          return (
            <li key={invitation.invitationId} className='flex flex-wrap items-center justify-between gap-3'>
              <div className='min-w-0'>
                <div className='text-foreground truncate text-sm font-medium'>{invitation.workspaceName}</div>
                <div className='text-muted-foreground text-xs' title={ROLE_DESCRIPTIONS[role]}>
                  {ROLE_LABELS[role] ?? invitation.role} · from {invitation.invitedBy.displayName || 'a workspace admin'}
                  <span className='hidden md:inline'> · expires {formatDate(invitation.expiresAt)}</span>
                </div>
              </div>
              <div className='flex gap-2'>
                <Button variant='action' size='sm' className='min-h-10 px-3.5' disabled={busy !== null} onClick={() => void accept(invitation)}>
                  {busy === invitation.invitationId ? 'Joining…' : 'Accept'}
                </Button>
                <Button variant='quiet' size='sm' className='min-h-10 px-3.5' disabled={busy !== null} onClick={() => setDeclining(invitation)}>
                  Decline
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      <AlertDialog open={declining !== null} onOpenChange={(open) => !open && setDeclining(null)}>
        <AlertDialogContent className={rafiiDialog}>
          <AlertDialogHeader>
            <AlertDialogTitle className='text-foreground text-lg font-medium tracking-tight'>Decline the invitation to {declining?.workspaceName}?</AlertDialogTitle>
            <AlertDialogDescription className='leading-relaxed'>The invitation link stops working.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className={rafiiDialogFooter}>
            <AlertDialogCancel variant='quiet' size='control'>Keep it</AlertDialogCancel>
            <AlertDialogAction variant='action' size='control' disabled={busy !== null} onClick={() => declining && void decline(declining)}>
              Decline
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Surface>
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
      toast.success(`You left ${item.name}`);
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
    <Surface material={current ? 'selected' : 'quiet'} radius='card' padding='md' className='flex flex-col gap-4'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='flex min-w-0 flex-col gap-1'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='text-foreground truncate text-base font-medium'>{item.name}</span>
            {current && <Badge variant='secondary'>Current</Badge>}
            <Badge variant='secondary'>{planLabel(item)}</Badge>
          </div>
          <div className='text-muted-foreground text-xs'>
            Owned by {owner} · {tiers.total} {tiers.total === 1 ? 'person' : 'people'}
            <span className='hidden md:inline'>
              {' '}
              ({tiers.staff} staff, {tiers.members} {tiers.members === 1 ? 'member' : 'members'})
            </span>
          </div>
        </div>
        <div className='flex flex-wrap gap-2'>
          {!current && (
            <Button size='sm' variant='glass' className='min-h-10 px-3.5' onClick={() => switchTo(item.workspaceId)}>
              Switch
            </Button>
          )}
          {isStaff(role) && (
            <Button size='sm' variant='glass' className='min-h-10 px-3.5' onClick={() => go('/app/workspace/members')}>
              <Icons.teams className='size-4' aria-hidden />
              Manage members
            </Button>
          )}
        </div>
      </div>

      <div className='flex flex-wrap items-center justify-between gap-2 text-sm'>
        <span className='flex items-center gap-0.5'>
          <span className='text-muted-foreground'>Your role:&nbsp;</span>
          <span className='text-foreground font-medium'>{ROLE_LABELS[role]}</span>
          {grants.length > 0 && <span className='text-muted-foreground'>&nbsp;· can also {grants.join(', ')}</span>}
          <InfoTip label={`About the ${ROLE_LABELS[role]} role`} className='-my-2 size-9' description={ROLE_DESCRIPTIONS[role]} />
        </span>
        {canLeave(role) ? (
          <Button size='sm' variant='quiet' className='text-destructive min-h-9' disabled={busy} onClick={() => setConfirmLeave(true)}>
            Leave workspace
          </Button>
        ) : (
          <span className='text-muted-foreground text-xs'>Transfer ownership to leave.</span>
        )}
      </div>

      <AlertDialog open={confirmLeave} onOpenChange={setConfirmLeave}>
        <AlertDialogContent className={rafiiDialog}>
          <AlertDialogHeader>
            <AlertDialogTitle className='text-foreground text-lg font-medium tracking-tight'>Leave {item.name}?</AlertDialogTitle>
            <AlertDialogDescription className='leading-relaxed'>
              You lose access now and need an invitation to return. Nothing you wrote is deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className={rafiiDialogFooter}>
            <AlertDialogCancel variant='quiet' size='control'>Stay</AlertDialogCancel>
            <AlertDialogAction variant='action' size='control' disabled={busy} onClick={() => void leave()}>
              {busy ? 'Leaving…' : 'Leave'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Surface>
  );
}

function WorkspacesCard() {
  const { workspaces, workspaceId, status } = useWorkspace();
  return (
    <SettingsSection
      id='profile-workspaces'
      title='Workspaces & access'
      material='none'
    >
      <PendingInvitations />
      {status !== 'ready' ? (
        <StateMessage kind='loading' title='Loading your workspaces' />
      ) : (
        workspaces.map((item) => <WorkspaceRow key={item.workspaceId} item={item} current={item.workspaceId === workspaceId} />)
      )}
    </SettingsSection>
  );
}

/** Account-level actions in their own, clearly named lower section (DNA §21.15). Signing out is harmless, so it needs no confirmation. */
function AccountActions() {
  const auth = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  function signOut() {
    setBusy(true);
    void auth.signOut().then(() => router.replace('/auth/sign-in'));
  }

  return (
    <SettingsSection
      id='profile-account'
      title='Account'
      bodyClassName='flex-row flex-wrap items-center gap-3'
    >
      <Button variant='glass' size='control' disabled={busy} onClick={signOut}>
        <Icons.logout className='size-4' aria-hidden />
        {busy ? 'Signing out…' : (
          <>
            Sign out<span className='sr-only'> on this device</span>
          </>
        )}
      </Button>
      <Link href='/app/account/privacy' className={cn(buttonVariants({ variant: 'quiet', size: 'control' }), 'text-muted-foreground')}>
        Delete account
        <Icons.arrowRight className='size-4' aria-hidden />
      </Link>
    </SettingsSection>
  );
}

export function ProfileView() {
  return (
    <PageContainer pageTitle='Profile' infoContent={infoContent}>
      <div className='grid gap-8 lg:grid-cols-2'>
        <div className='flex min-w-0 flex-col gap-8'>
          <IdentityCard />
          <PreferencesCard />
        </div>
        <div className='flex min-w-0 flex-col gap-8'>
          <SecurityCard />
          <PasskeysCard />
        </div>
        <div className='min-w-0 lg:col-span-2'>
          <ChannelsCard />
        </div>
        <div className='min-w-0 lg:col-span-2'>
          <WorkspacesCard />
        </div>
        <div className='min-w-0 lg:col-span-2'>
          <AccountActions />
        </div>
      </div>
    </PageContainer>
  );
}
