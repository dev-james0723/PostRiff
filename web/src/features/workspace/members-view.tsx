'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { CollectionRow, StateMessage, Surface } from '@/components/rafii';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button, buttonVariants } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SuccessCheck } from '@/components/ui/success-check';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useFlash } from '@/hooks/use-flash';
import { useIsMobile } from '@/hooks/use-mobile';
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
import { FIELD_CLASS, Panel, SectionHeading, SELECT_TRIGGER_CLASS, StatusChip } from './rafii-parts';
import { useChangeError } from './use-change-error';

const infoContent = {
  title: 'Members and invitations',
  sections: [
    {
      title: 'Roles set the baseline',
      description: 'Owner, admin, editor, approver and viewer. A grant adds one right (approve, reply, moderate, manage connections) to anyone but a viewer.',
      links: [{ title: 'Roles', url: '/app/workspace/roles' }]
    },
    {
      title: 'Some changes need a recent sign-in',
      description:
        'Inviting, changing someone’s access and removing a member only work shortly after a fresh sign-in. If yours is too old, sign out, sign in again and retry. Revoking an invitation does not need it.'
    },
    {
      title: 'Invitations',
      description: 'Links work once and expire after 7 days. When email is set up the invitee gets the link by email; you can always copy it after sending.'
    }
  ]
};

const DIALOG_CLASS = 'rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] p-5 ring-0 md:rounded-[var(--rafii-radius-dialog)] md:p-6';
const HEAD_CLASS = 'text-muted-foreground h-11 px-3 text-xs font-medium first:pl-4 last:pr-4';
const CELL_CLASS = 'px-3 py-3 first:pl-4 last:pr-4';

function LoadError({ title, error, onRetry, retrying }: { title: string; error: unknown; onRetry: () => void; retrying: boolean }) {
  return (
    <StateMessage
      kind='error'
      title={title}
      description={error instanceof ApiError ? error.message : 'The server did not answer.'}
      action={
        <Button size='default' variant='glass' onClick={onRetry} disabled={retrying}>
          <Icons.refresh className={cn(retrying && 'motion-safe:animate-spin')} /> Retry
        </Button>
      }
    />
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
        <div className='flex flex-col gap-2'>
          <Label htmlFor='invite-email'>Email address</Label>
          <Input id='invite-email' type='email' required value={email} onChange={(e) => setEmail(e.target.value)} className={FIELD_CLASS} />
        </div>
        <div className='flex flex-col gap-2'>
          <Label htmlFor='invite-role'>Role</Label>
          <Select value={role} onValueChange={(value) => setRole(value as WorkspaceRole)}>
            <SelectTrigger id='invite-role' className={SELECT_TRIGGER_CLASS}>
              <SelectValue>{ROLE_LABELS[role]}</SelectValue>
            </SelectTrigger>
            <SelectContent className='rafii-elevated rounded-[var(--rafii-radius-control)] ring-0'>
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
          <legend className='text-foreground mb-2 text-sm font-medium'>Extra grants</legend>
          <div className='grid gap-2 sm:grid-cols-2'>
            {FLAGS.map((flag) => {
              const disabled = busy || rules[flag.key].cannotAdd;
              return (
                <Label key={flag.key} className='flex min-h-11 items-center gap-2 text-sm font-normal'>
                  <Checkbox checked={payload[flag.key]} disabled={disabled} onCheckedChange={(checked) => setFlags({ ...flags, [flag.key]: checked === true })} />
                  <span className={disabled ? 'text-muted-foreground' : undefined}>{flag.label}</span>
                </Label>
              );
            })}
          </div>
          {unheld && <p className='text-muted-foreground text-xs'>Greyed-out grants are ones you do not hold, so you cannot hand them out.</p>}
        </fieldset>
      )}
      <Button type='submit' variant='action' size='control' disabled={busy || !email.includes('@')} className='w-fit'>
        {busy ? (
          <>
            <Icons.spinner className='motion-safe:animate-spin' /> Sending…
          </>
        ) : (
          'Send invitation'
        )}
      </Button>
    </form>
  );
}

/** "Change access" and "Remove" for one member, with the confirmation the removal needs. Shared by the table row and the phone card. */
function MemberActions({ member, onEdit }: { member: Member; onEdit: (member: Member) => void }) {
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
      await Promise.all([client.invalidateQueries({ queryKey: keys.members(workspaceId) }), client.invalidateQueries({ queryKey: keys.audit(workspaceId) })]);
    } catch (err) {
      reportError(err, 'The member could not be removed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant='glass' size='default' disabled={busy} onClick={() => onEdit(member)}>
        Change access
      </Button>
      <Button variant='quiet' size='default' className='text-destructive hover:text-destructive' disabled={busy} onClick={() => setConfirmRemove(true)}>
        Remove
      </Button>
      <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
        <AlertDialogContent className={DIALOG_CLASS}>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove this member?</AlertDialogTitle>
            <AlertDialogDescription>
              They lose access immediately. Drafts they wrote stay in the workspace.
              {holdsApprovals && ` ${APPROVAL_HOLD_NOTE}`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel variant='glass' size='control'>
              Keep
            </AlertDialogCancel>
            <AlertDialogAction
              variant='action'
              size='control'
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
  );
}

function memberFacts(member: Member) {
  const flags = FLAGS.filter((f) => member[f.key]).map((f) => f.label.replace('Can ', ''));
  // An owner already holds every right, and a viewer's grants never apply (`Membership.allows`).
  const grants = member.role === 'owner' ? 'Not needed' : flags.length === 0 ? '—' : `${flags.join(', ')}${member.role === 'viewer' ? ' (inactive for a viewer)' : ''}`;
  return { grants };
}

function MemberName({ member }: { member: Member }) {
  return (
    <span className='inline-flex flex-wrap items-center gap-2'>
      {member.displayName ? <span className='text-foreground'>{member.displayName}</span> : <span className='font-mono text-xs'>{member.userId.slice(0, 8)}…</span>}
      {member.you && <StatusChip icon='user'>you</StatusChip>}
    </span>
  );
}

function MemberRow({ member, canManage, justSaved, onEdit }: { member: Member; canManage: boolean; justSaved: boolean; onEdit: (member: Member) => void }) {
  const { grants } = memberFacts(member);
  const editable = canManage && !member.you && member.role !== 'owner' && member.status === 'active';
  return (
    <TableRow className='hover:bg-foreground/[0.04] border-0'>
      <TableCell className={CELL_CLASS}>
        <MemberName member={member} />
      </TableCell>
      <TableCell className={CELL_CLASS}>
        <span className='inline-flex items-center gap-1.5'>
          {ROLE_LABELS[member.role]}
          {justSaved && <SuccessCheck className='text-foreground size-4' />}
        </span>
      </TableCell>
      <TableCell className={cn(CELL_CLASS, 'text-muted-foreground text-xs whitespace-normal')}>{grants}</TableCell>
      <TableCell className={CELL_CLASS}>
        <StatusChip icon={member.status === 'active' ? 'check' : 'circle'}>{member.status}</StatusChip>
      </TableCell>
      <TableCell className={cn(CELL_CLASS, 'text-muted-foreground text-xs')}>{relativeTime(member.updatedAt)}</TableCell>
      <TableCell className={cn(CELL_CLASS, 'text-right')}>{editable && <MemberActions member={member} onEdit={onEdit} />}</TableCell>
    </TableRow>
  );
}

/** Below 768px each member is a quiet row with the same facts and actions. */
function MemberCard({ member, canManage, justSaved, onEdit }: { member: Member; canManage: boolean; justSaved: boolean; onEdit: (member: Member) => void }) {
  const { grants } = memberFacts(member);
  const editable = canManage && !member.you && member.role !== 'owner' && member.status === 'active';
  return (
    <li className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <MemberName member={member} />
        <StatusChip icon={member.status === 'active' ? 'check' : 'circle'}>{member.status}</StatusChip>
      </div>
      <dl className='grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm'>
        <dt className='text-muted-foreground text-xs'>Role</dt>
        <dd className='inline-flex items-center gap-1.5'>
          {ROLE_LABELS[member.role]}
          {justSaved && <SuccessCheck className='text-foreground size-4' />}
        </dd>
        <dt className='text-muted-foreground text-xs'>Extra grants</dt>
        <dd className='text-muted-foreground text-xs'>{grants}</dd>
        <dt className='text-muted-foreground text-xs'>Updated</dt>
        <dd className='text-muted-foreground text-xs'>{relativeTime(member.updatedAt)}</dd>
      </dl>
      {editable && (
        <div className='flex flex-wrap gap-2'>
          <MemberActions member={member} onEdit={onEdit} />
        </div>
      )}
    </li>
  );
}

function RevokeInvitation({ invitation }: { invitation: Invitation }) {
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
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) void client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
      reportError(err, 'The invitation could not be revoked.');
    } finally {
      setBusy(false);
    }
  }

  if (invitation.state !== 'pending') return null;
  return (
    <>
      <Button variant='quiet' size='default' disabled={busy} onClick={() => setConfirming(true)}>
        {busy ? 'Revoking…' : 'Revoke'}
      </Button>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent className={DIALOG_CLASS}>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke the invitation for {invitation.email}?</AlertDialogTitle>
            <AlertDialogDescription>The link stops working immediately. You can invite the same address again later.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel variant='glass' size='control'>
              Keep
            </AlertDialogCancel>
            <AlertDialogAction
              variant='action'
              size='control'
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
  );
}

function InvitationRow({ invitation }: { invitation: Invitation }) {
  return (
    <TableRow className='hover:bg-foreground/[0.04] border-0'>
      <TableCell className={cn(CELL_CLASS, 'whitespace-normal break-all')}>{invitation.email}</TableCell>
      <TableCell className={CELL_CLASS}>{ROLE_LABELS[invitation.role as WorkspaceRole] ?? invitation.role}</TableCell>
      <TableCell className={CELL_CLASS}>
        <StatusChip icon={invitation.state === 'pending' ? 'hourglass' : 'circle'}>{invitation.state}</StatusChip>
      </TableCell>
      <TableCell className={cn(CELL_CLASS, 'text-muted-foreground text-xs')}>{formatDate(invitation.expiresAt)}</TableCell>
      <TableCell className={cn(CELL_CLASS, 'text-right')}>
        <RevokeInvitation invitation={invitation} />
      </TableCell>
    </TableRow>
  );
}

function InvitationCard({ invitation }: { invitation: Invitation }) {
  return (
    <CollectionRow
      as='li'
      className='flex-wrap py-3'
      title={<span className='break-all'>{invitation.email}</span>}
      meta={`${ROLE_LABELS[invitation.role as WorkspaceRole] ?? invitation.role} · expires ${formatDate(invitation.expiresAt)}`}
      state={<StatusChip icon={invitation.state === 'pending' ? 'hourglass' : 'circle'}>{invitation.state}</StatusChip>}
      actions={<RevokeInvitation invitation={invitation} />}
    />
  );
}

const targetLabel = (member: Member) => member.displayName || `${member.userId.slice(0, 8)}…`;

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

  async function transfer() {
    if (!target) return;
    setBusy(true);
    try {
      await api.transferOwnership(workspaceId, target.userId);
      toast.success(`${targetLabel(target)} is now the owner.`);
      setNewOwnerId('');
      await Promise.all([client.invalidateQueries({ queryKey: keys.members(workspaceId) }), client.invalidateQueries({ queryKey: keys.audit(workspaceId) })]);
    } catch (err) {
      reportError(err, 'Ownership could not be transferred.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className='flex flex-col gap-3' aria-labelledby='ownership-heading'>
      <SectionHeading id='ownership-heading' title='Ownership' description='A lower-priority change kept apart from everyday member management.' />
      <Panel data-tour='members-transfer-ownership' title='Transfer ownership' titleId='members-transfer-heading' description='Make an active admin the owner. You become an admin with every grant. This needs a recent sign-in.'>
        {admins.length === 0 ? (
          <StateMessage kind='empty' layout='inline' title='Make someone an admin first' description='Ownership can only move to an active admin.' />
        ) : (
          <div className='flex flex-col gap-3 sm:flex-row sm:items-center'>
            <Select value={newOwnerId} onValueChange={(value) => setNewOwnerId(value ?? '')}>
              <SelectTrigger aria-label='Choose the new owner' className={cn(SELECT_TRIGGER_CLASS, 'sm:w-72')}>
                <SelectValue placeholder='Choose the new owner' />
              </SelectTrigger>
              <SelectContent className='rafii-elevated rounded-[var(--rafii-radius-control)] ring-0'>
                {admins.map((admin) => (
                  <SelectItem key={admin.userId} value={admin.userId}>
                    {targetLabel(admin)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant='glass' size='control' disabled={!target || busy} onClick={() => setConfirming(true)}>
              Transfer ownership
            </Button>
          </div>
        )}
        <AlertDialog open={confirming} onOpenChange={setConfirming}>
          <AlertDialogContent className={DIALOG_CLASS}>
            <AlertDialogHeader>
              <AlertDialogTitle>Make {target ? targetLabel(target) : 'this admin'} the owner?</AlertDialogTitle>
              <AlertDialogDescription>They get billing, deletion and full member control. You become an admin with every grant instead.</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel variant='glass' size='control'>
                Keep ownership
              </AlertDialogCancel>
              <AlertDialogAction
                variant='action'
                size='control'
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
      </Panel>
    </section>
  );
}

/** Mounted only for owners and admins, so the member and invitation queries never fire for anyone else. */
function MembersContent() {
  const members = useMembers();
  const invitations = useInvitations();
  const { workspaceId } = useWorkspaceApi();
  const { membership } = useWorkspace();
  const client = useQueryClient();
  const isMobile = useIsMobile();
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
  const memberList = members.data?.members ?? [];
  const onEdit = (target: Member) => {
    setEditing(target);
    setSheetOpen(true);
  };

  return (
    <>
      <div className='flex flex-col gap-6 md:gap-8'>
        <Panel material='glass' data-tour='members-invite' title='Invite someone' titleId='members-invite-heading' description='They get a one-time link. You can copy it below after sending.'>
          <InviteForm
            actor={actor}
            onCreated={(result, email) => {
              setCreated({ result, email, workspaceId });
              void client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
              void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
            }}
          />
          {shown && (
            <div className='rafii-quiet rounded-[var(--rafii-radius-control)] px-4 py-3'>
              <StateMessage
                kind='success'
                layout='inline'
                title={`Invitation for ${shown.email} ${shown.result.emailSent ? 'sent' : 'created'}`}
                description={`${shown.result.emailSent ? 'An email is on its way. The link below works once and expires ' : 'Email delivery is not configured on this deployment, so share the link directly. It works once and expires '}${formatDate(shown.result.expiresAt)}.`}
                action={
                  <span className='flex max-w-full flex-wrap items-center gap-2'>
                    <code className='rafii-field text-foreground max-w-full truncate rounded-[var(--rafii-radius-micro)] px-2 py-1 text-xs'>{acceptLink}</code>
                    <Button
                      size='default'
                      variant='glass'
                      onClick={() => {
                        navigator.clipboard.writeText(acceptLink).then(
                          () => toast.success('Link copied.'),
                          () => toast.error('Copy failed. Select the link and copy it manually.')
                        );
                      }}
                    >
                      <Icons.copy /> Copy link
                    </Button>
                  </span>
                }
              />
            </div>
          )}
        </Panel>

        <section className='flex flex-col gap-3' aria-labelledby='members-heading' data-tour='members-table'>
          <SectionHeading
            id='members-heading'
            title='Members'
            actions={
              <Link href='/app/workspace/roles' className={cn('t-learn', buttonVariants({ variant: 'quiet', size: 'default' }), '-mr-2.5')}>
                What each role can do <LearnMoreChevron />
              </Link>
            }
          />
          {members.isPending ? (
            <StateMessage kind='loading' title='Loading members…' />
          ) : members.error ? (
            <LoadError title='Members could not be loaded.' error={members.error} onRetry={() => void members.refetch()} retrying={members.isFetching} />
          ) : isMobile ? (
            <ul className='flex flex-col gap-2'>
              {memberList.map((member) => (
                <MemberCard key={member.userId} member={member} canManage justSaved={justSaved === member.userId} onEdit={onEdit} />
              ))}
            </ul>
          ) : (
            <Surface material='quiet' padding='none' className='relative overflow-x-auto'>
              <Table className='text-sm'>
                <TableHeader className='[&_tr]:border-0'>
                  <TableRow className='border-0 hover:bg-transparent'>
                    <TableHead className={HEAD_CLASS}>User</TableHead>
                    <TableHead className={HEAD_CLASS}>Role</TableHead>
                    <TableHead className={HEAD_CLASS}>Extra grants</TableHead>
                    <TableHead className={HEAD_CLASS}>Status</TableHead>
                    <TableHead className={HEAD_CLASS}>Updated</TableHead>
                    <TableHead className={HEAD_CLASS}>
                      <span className='sr-only'>Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {memberList.map((member) => (
                    <MemberRow key={member.userId} member={member} canManage justSaved={justSaved === member.userId} onEdit={onEdit} />
                  ))}
                </TableBody>
              </Table>
            </Surface>
          )}
        </section>

        <section className='flex flex-col gap-3' aria-labelledby='invites-heading' data-tour='members-invitations'>
          <SectionHeading id='invites-heading' title='Invitations' />
          {invitations.isPending ? (
            <StateMessage kind='loading' title='Loading invitations…' />
          ) : invitations.error ? (
            <LoadError title='Invitations could not be loaded.' error={invitations.error} onRetry={() => void invitations.refetch()} retrying={invitations.isFetching} />
          ) : invitationList.length === 0 ? (
            <StateMessage kind='empty' title='No invitations yet.' description='Invite someone above; their one-time link appears here until it is used or revoked.' />
          ) : isMobile ? (
            <ul className='flex flex-col gap-2'>
              {invitationList.map((invitation) => (
                <InvitationCard key={invitation.invitationId} invitation={invitation} />
              ))}
            </ul>
          ) : (
            <Surface material='quiet' padding='none' className='relative overflow-x-auto'>
              <Table className='text-sm'>
                <TableHeader className='[&_tr]:border-0'>
                  <TableRow className='border-0 hover:bg-transparent'>
                    <TableHead className={HEAD_CLASS}>Email</TableHead>
                    <TableHead className={HEAD_CLASS}>Role</TableHead>
                    <TableHead className={HEAD_CLASS}>State</TableHead>
                    <TableHead className={HEAD_CLASS}>Expires</TableHead>
                    <TableHead className={HEAD_CLASS}>
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
            </Surface>
          )}
        </section>

        {actor?.role === 'owner' && <TransferOwnershipCard members={memberList} />}
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
        <StateMessage
          kind='permission'
          className='w-full max-w-md'
          title='Only owners and admins manage members.'
          description={membership ? `Your role here is ${ROLE_LABELS[membership.role]}. Ask the owner or an admin to invite people or change access.` : undefined}
          action={
            <Link href='/app/workspace/roles' className={cn('t-learn', buttonVariants({ variant: 'glass', size: 'default' }))}>
              See what each role can do <LearnMoreChevron />
            </Link>
          }
        />
      }
    >
      <MembersContent />
    </PageContainer>
  );
}
