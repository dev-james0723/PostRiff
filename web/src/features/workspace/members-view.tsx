'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
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
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { SuccessCheck } from '@/components/ui/success-check';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useFlash } from '@/hooks/use-flash';
import { keys, useInvitations, useMembers } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Invitation, InvitationCreated, Member, Membership } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { allows, ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { formatDate, relativeTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { useWorkspace, useWorkspaceApi } from '@/lib/workspace/provider';
import type { WorkspaceRole } from '@/types';
import { APPROVAL_HOLD_NOTE, ASSIGNABLE_ROLES, canAssignRole, FLAGS, grantRules, NO_FLAGS, type Flags } from './access-model';
import { MemberAccessSheet } from './member-access-sheet';
import { useChangeError } from './use-change-error';

const infoContent = {
  title: 'Members and invitations',
  sections: [
    {
      title: 'Roles set the baseline',
      description:
        'Owner, admin, editor, approver and viewer. A grant adds one right (approve, reply, moderate, manage connections) to anyone but a viewer.',
      links: [{ title: 'Roles', url: '/app/workspace/roles' }]
    },
    {
      title: 'Some changes need a recent sign-in',
      description:
        'Inviting, changing someone’s access and removing a member only work shortly after a fresh sign-in. If yours is too old, sign out, sign in again and retry. Revoking an invitation does not need it.'
    },
    {
      title: 'Invitations',
      description:
        'Links work once and expire after 7 days. When email is set up the invitee gets the link by email; you can always copy it after sending.'
    }
  ]
};

function LoadError({ title, error, onRetry, retrying }: { title: string; error: unknown; onRetry: () => void; retrying: boolean }) {
  return (
    <Alert variant='destructive'>
      <Icons.alertCircle className='size-4' />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className='flex flex-wrap items-center gap-2'>
        <span>{error instanceof ApiError ? error.message : 'The server did not answer.'}</span>
        <Button size='sm' variant='outline' onClick={onRetry} disabled={retrying}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function InviteForm({ actor, onCreated }: { actor: Membership | null; onCreated: (result: InvitationCreated, email: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const reportError = useChangeError();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WorkspaceRole>('editor');
  const [flags, setFlags] = useState<Flags>(NO_FLAGS);
  const [busy, setBusy] = useState(false);

  // A viewer cannot carry grants, and `validate_grant` refuses any grant the inviter does not hold.
  const payload = role === 'viewer' ? NO_FLAGS : flags;
  const rules = grantRules(actor, payload);
  const unheld = FLAGS.some((flag) => rules[flag.key].cannotAdd);
  const roles = ASSIGNABLE_ROLES.filter((r) => canAssignRole(actor, r));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await api.invite(workspaceId, email.trim(), role, payload);
      onCreated(result, email.trim());
      setEmail('');
      setFlags(NO_FLAGS);
    } catch (err) {
      reportError(err, 'The invitation could not be created.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className='flex flex-col gap-4'>
      <div className='grid gap-4 sm:grid-cols-[1fr_12rem]'>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='invite-email'>Email address</Label>
          <Input id='invite-email' type='email' required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='invite-role'>Role</Label>
          <Select value={role} onValueChange={(value) => setRole(value as WorkspaceRole)}>
            <SelectTrigger id='invite-role'>
              <SelectValue>{ROLE_LABELS[role]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {roles.map((r) => (
                <SelectItem key={r} value={r}>
                  {ROLE_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
      {role !== 'viewer' && (
        <fieldset className='flex flex-col gap-2'>
          <legend className='mb-1 text-sm font-medium'>Extra grants</legend>
          <div className='grid gap-2 sm:grid-cols-2'>
            {FLAGS.map((flag) => {
              const disabled = busy || rules[flag.key].cannotAdd;
              return (
                <Label key={flag.key} className='flex items-center gap-2 text-sm font-normal'>
                  <Checkbox
                    checked={payload[flag.key]}
                    disabled={disabled}
                    onCheckedChange={(checked) => setFlags({ ...flags, [flag.key]: checked === true })}
                  />
                  <span className={disabled ? 'text-muted-foreground' : undefined}>{flag.label}</span>
                </Label>
              );
            })}
          </div>
          {unheld && (
            <p className='text-muted-foreground text-xs'>Greyed-out grants are ones you do not hold, so you cannot hand them out.</p>
          )}
        </fieldset>
      )}
      <Button type='submit' disabled={busy || !email.includes('@')} className='w-fit'>
        {busy ? 'Sending…' : 'Send invitation'}
      </Button>
    </form>
  );
}

function MemberRow({
  member,
  canManage,
  justSaved,
  onEdit
}: {
  member: Member;
  canManage: boolean;
  justSaved: boolean;
  onEdit: (member: Member) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const reportError = useChangeError();
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Removing someone who can approve holds what they already approved (hosted.py `remove_member` note).
  const holdsApprovals = allows(member, 'approve');

  async function remove() {
    setBusy(true);
    try {
      const result = await api.removeMember(workspaceId, member.userId);
      const note = result.note;
      toast.success('Member removed.', note && holdsApprovals ? { description: APPROVAL_HOLD_NOTE } : undefined);
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.members(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.audit(workspaceId) })
      ]);
    } catch (err) {
      reportError(err, 'The member could not be removed.');
    } finally {
      setBusy(false);
    }
  }

  const flags = FLAGS.filter((f) => member[f.key]).map((f) => f.label.replace('Can ', ''));
  // An owner already holds every right, and a viewer's grants never apply (`Membership.allows`).
  const grants =
    member.role === 'owner' ? 'Not needed' : flags.length === 0 ? '—' : `${flags.join(', ')}${member.role === 'viewer' ? ' (inactive for a viewer)' : ''}`;
  const editable = canManage && !member.you && member.role !== 'owner' && member.status === 'active';

  return (
    <TableRow>
      <TableCell>
        {member.displayName ? <span>{member.displayName}</span> : <span className='font-mono text-xs'>{member.userId.slice(0, 8)}…</span>}
        {member.you && (
          <Badge variant='outline' className='ml-2'>
            you
          </Badge>
        )}
      </TableCell>
      <TableCell>
        <span className='inline-flex items-center gap-1.5'>
          {ROLE_LABELS[member.role]}
          {justSaved && <SuccessCheck className='size-4 text-emerald-500' />}
        </span>
      </TableCell>
      <TableCell className='text-muted-foreground text-xs'>{grants}</TableCell>
      <TableCell>
        <Badge variant={member.status === 'active' ? 'outline' : 'secondary'}>{member.status}</Badge>
      </TableCell>
      <TableCell className='text-muted-foreground text-xs'>{relativeTime(member.updatedAt)}</TableCell>
      <TableCell className='text-right'>
        {editable && (
          <>
            <Button variant='ghost' size='sm' disabled={busy} onClick={() => onEdit(member)}>
              Change access
            </Button>
            <Button variant='ghost' size='sm' className='text-destructive' disabled={busy} onClick={() => setConfirmRemove(true)}>
              Remove
            </Button>
            <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Remove this member?</AlertDialogTitle>
                  <AlertDialogDescription>
                    They lose access immediately. Drafts they wrote stay in the workspace.
                    {holdsApprovals && ` ${APPROVAL_HOLD_NOTE}`}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => {
                      setConfirmRemove(false);
                      void remove();
                    }}
                  >
                    Remove
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        )}
      </TableCell>
    </TableRow>
  );
}

function InvitationRow({ invitation }: { invitation: Invitation }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const reportError = useChangeError();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

  async function revoke() {
    setBusy(true);
    try {
      await api.revokeInvitation(workspaceId, invitation.invitationId);
      toast.success('Invitation revoked.');
      await client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) void client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
      reportError(err, 'The invitation could not be revoked.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <TableRow>
      <TableCell>{invitation.email}</TableCell>
      <TableCell>{ROLE_LABELS[invitation.role as WorkspaceRole] ?? invitation.role}</TableCell>
      <TableCell>
        <Badge variant={invitation.state === 'pending' ? 'default' : 'outline'}>{invitation.state}</Badge>
      </TableCell>
      <TableCell className='text-muted-foreground text-xs'>{formatDate(invitation.expiresAt)}</TableCell>
      <TableCell className='text-right'>
        {invitation.state === 'pending' && (
          <>
            <Button variant='ghost' size='sm' disabled={busy} onClick={() => setConfirming(true)}>
              {busy ? 'Revoking…' : 'Revoke'}
            </Button>
            <AlertDialog open={confirming} onOpenChange={setConfirming}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Revoke the invitation for {invitation.email}?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The link stops working immediately. You can invite the same address again later.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => {
                      setConfirming(false);
                      void revoke();
                    }}
                  >
                    Revoke invitation
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </>
        )}
      </TableCell>
    </TableRow>
  );
}

/** Owner-only: hand the role to an active admin. Both memberships swap in one step-up transaction. */
function TransferOwnershipCard({ members }: { members: Member[] }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const reportError = useChangeError();
  const [newOwnerId, setNewOwnerId] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const admins = members.filter((m) => m.role === 'admin' && m.status === 'active');
  const target = admins.find((m) => m.userId === newOwnerId) ?? null;
  const targetLabel = (member: Member) => member.displayName || `${member.userId.slice(0, 8)}…`;

  async function transfer() {
    if (!target) return;
    setBusy(true);
    try {
      await api.transferOwnership(workspaceId, target.userId);
      toast.success(`${targetLabel(target)} is now the owner.`);
      setNewOwnerId('');
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.members(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.audit(workspaceId) })
      ]);
    } catch (err) {
      reportError(err, 'Ownership could not be transferred.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-tour='members-transfer-ownership'>
      <CardHeader>
        <CardTitle>Transfer ownership</CardTitle>
        <CardDescription>Make an active admin the owner. You become an admin with every grant. This needs a recent sign-in.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-wrap items-center gap-2'>
        {admins.length === 0 ? (
          <p className='text-muted-foreground text-sm'>Make someone an admin first — ownership can only move to an active admin.</p>
        ) : (
          <>
            <Select value={newOwnerId} onValueChange={(value) => setNewOwnerId(value ?? '')}>
              <SelectTrigger className='w-64'>
                <SelectValue placeholder='Choose the new owner' />
              </SelectTrigger>
              <SelectContent>
                {admins.map((admin) => (
                  <SelectItem key={admin.userId} value={admin.userId}>
                    {targetLabel(admin)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant='outline' disabled={!target || busy} onClick={() => setConfirming(true)}>
              Transfer ownership
            </Button>
          </>
        )}
        <AlertDialog open={confirming} onOpenChange={setConfirming}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Make {target ? targetLabel(target) : 'this admin'} the owner?</AlertDialogTitle>
              <AlertDialogDescription>
                They get billing, deletion and full member control. You become an admin with every grant instead.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Keep ownership</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  setConfirming(false);
                  void transfer();
                }}
              >
                Transfer ownership
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}

/** Mounted only for owners and admins, so the member and invitation queries never fire for anyone else. */
function MembersContent() {
  const members = useMembers();
  const invitations = useInvitations();
  const { workspaceId } = useWorkspaceApi();
  const { membership } = useWorkspace();
  const client = useQueryClient();
  // The one-time link belongs to the workspace it was created in; switching workspaces hides it.
  const [created, setCreated] = useState<{ result: InvitationCreated; email: string; workspaceId: string } | null>(null);
  const [editing, setEditing] = useState<Member | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [justSaved, flashSaved] = useFlash<string>();

  const actor = members.data?.membership ?? membership;
  // Sections key off `isPending`: a query paused between retries (offline, hidden tab) has no data and must not look empty.
  const shown = created && created.workspaceId === workspaceId ? created : null;
  const acceptLink = shown ? `${window.location.origin}/invite/${shown.result.token}` : '';
  const invitationList = invitations.data?.invitations ?? [];

  return (
    <>
      <div className='flex flex-col gap-6'>
        <Card data-tour='members-invite'>
          <CardHeader>
            <CardTitle>Invite someone</CardTitle>
            <CardDescription>They get a one-time link. You can copy it below after sending.</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-4'>
            <InviteForm
              actor={actor}
              onCreated={(result, email) => {
                setCreated({ result, email, workspaceId });
                void client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
              }}
            />
            {shown && (
              <Alert>
                <Icons.checks className='size-4' />
                <AlertTitle>
                  Invitation for {shown.email} {shown.result.emailSent ? 'sent' : 'created'}
                </AlertTitle>
                <AlertDescription className='flex flex-col gap-2'>
                  <span>
                    {shown.result.emailSent
                      ? 'An email is on its way. The link below works once and expires '
                      : 'Email delivery is not configured on this deployment, so share the link directly. It works once and expires '}
                    {formatDate(shown.result.expiresAt)}.
                  </span>
                  <div className='flex flex-wrap items-center gap-2'>
                    <code className='bg-muted max-w-full truncate rounded px-2 py-1 text-xs'>{acceptLink}</code>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => {
                        navigator.clipboard.writeText(acceptLink).then(
                          () => toast.success('Link copied.'),
                          () => toast.error('Copy failed. Select the link and copy it manually.')
                        );
                      }}
                    >
                      Copy link
                    </Button>
                  </div>
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        <section className='flex flex-col gap-3' aria-labelledby='members-heading' data-tour='members-table'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h3 id='members-heading' className='text-lg font-semibold'>
              Members
            </h3>
            <Link href='/app/workspace/roles' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }), '-mr-2')}>
              What each role can do <LearnMoreChevron />
            </Link>
          </div>
          {members.isPending ? (
            <Skeleton className='h-32 w-full' />
          ) : members.error ? (
            <LoadError title='Members could not be loaded.' error={members.error} onRetry={() => void members.refetch()} retrying={members.isFetching} />
          ) : (
            <div className='overflow-x-auto rounded-lg border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Extra grants</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Updated</TableHead>
                    <TableHead>
                      <span className='sr-only'>Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(members.data?.members ?? []).map((member) => (
                    <MemberRow
                      key={member.userId}
                      member={member}
                      canManage
                      justSaved={justSaved === member.userId}
                      onEdit={(target) => {
                        setEditing(target);
                        setSheetOpen(true);
                      }}
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        {actor?.role === 'owner' && <TransferOwnershipCard members={members.data?.members ?? []} />}

        <section className='flex flex-col gap-3' aria-labelledby='invites-heading' data-tour='members-invitations'>
          <h3 id='invites-heading' className='text-lg font-semibold'>
            Invitations
          </h3>
          {invitations.isPending ? (
            <Skeleton className='h-24 w-full' />
          ) : invitations.error ? (
            <LoadError
              title='Invitations could not be loaded.'
              error={invitations.error}
              onRetry={() => void invitations.refetch()}
              retrying={invitations.isFetching}
            />
          ) : invitationList.length === 0 ? (
            <p className='text-muted-foreground text-sm'>No invitations yet.</p>
          ) : (
            <div className='overflow-x-auto rounded-lg border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead>
                      <span className='sr-only'>Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invitationList.map((invitation) => (
                    <InvitationRow key={invitation.invitationId} invitation={invitation} />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </div>
      <MemberAccessSheet member={editing} actor={actor} open={sheetOpen} onOpenChange={setSheetOpen} onSaved={flashSaved} />
    </>
  );
}

export function MembersView() {
  const access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission: 'manage_members' });
  const { membership } = useWorkspace();

  return (
    <PageContainer
      pageTitle='Members'
      pageDescription='Who can do what in this workspace.'
      infoContent={infoContent}
      access={canManage}
      accessFallback={
        <div className='flex max-w-md flex-col items-center gap-2 text-center'>
          <p className='font-medium'>Only owners and admins manage members.</p>
          {membership && (
            <p className='text-muted-foreground text-sm'>
              Your role here is {ROLE_LABELS[membership.role]}. Ask the owner or an admin to invite people or change access.
            </p>
          )}
          <Link href='/app/workspace/roles' className={cn('t-learn', buttonVariants({ variant: 'ghost', size: 'sm' }))}>
            See what each role can do <LearnMoreChevron />
          </Link>
        </div>
      }
    >
      <MembersContent />
    </PageContainer>
  );
}
