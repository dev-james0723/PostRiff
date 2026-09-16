'use client';

import { useState } from 'react';
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
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { keys, useInvitations, useMembers } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { InvitationCreated, Member } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { WorkspaceRole } from '@/types';

const INVITE_ROLES: WorkspaceRole[] = ['admin', 'editor', 'approver', 'viewer'];
const FLAGS: { key: 'can_publish' | 'can_reply' | 'can_moderate' | 'can_manage_connections'; label: string }[] = [
  { key: 'can_publish', label: 'Can approve publications' },
  { key: 'can_reply', label: 'Can reply to comments' },
  { key: 'can_moderate', label: 'Can moderate' },
  { key: 'can_manage_connections', label: 'Can manage connections' }
];

const infoContent = {
  title: 'Roles and step-up',
  sections: [
    {
      title: 'Five roles, four extra grants',
      description:
        'Owner, admin, editor, approver and viewer. Flags add a single right (approve, reply, moderate, manage connections) to a non-viewer without changing the role.'
    },
    {
      title: 'Recent sign-in required',
      description:
        'Inviting, changing or removing members needs a sign-in from the last 10 minutes. If it is older, sign in again and retry.'
    },
    {
      title: 'Invitations',
      description: 'Links expire after 7 days and can be used once. The invitee gets an email; you can also copy the link.'
    }
  ]
};

function InviteForm({ onCreated }: { onCreated: (result: InvitationCreated, email: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WorkspaceRole>('editor');
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await api.invite(workspaceId, email.trim(), role, flags);
      onCreated(result, email.trim());
      setEmail('');
      setFlags({});
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The invitation could not be created.');
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
              {INVITE_ROLES.map((r) => (
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
        <fieldset className='grid gap-2 sm:grid-cols-2'>
          <legend className='mb-1 text-sm font-medium'>Extra grants</legend>
          {FLAGS.map((flag) => (
            <Label key={flag.key} className='flex items-center gap-2 text-sm font-normal'>
              <Checkbox
                checked={Boolean(flags[flag.key])}
                onCheckedChange={(checked) => setFlags({ ...flags, [flag.key]: checked === true })}
              />
              {flag.label}
            </Label>
          ))}
        </fieldset>
      )}
      <Button type='submit' disabled={busy || !email.includes('@')} className='w-fit'>
        {busy ? 'Sending…' : 'Send invitation'}
      </Button>
    </form>
  );
}

function MemberRow({ member, canManage }: { member: Member; canManage: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);

  async function change(role: WorkspaceRole) {
    setBusy(true);
    try {
      await api.updateMember(workspaceId, member.userId, role, {
        can_publish: member.can_publish,
        can_reply: member.can_reply,
        can_moderate: member.can_moderate,
        can_manage_connections: member.can_manage_connections
      });
      toast.success('Role updated.');
      await client.invalidateQueries({ queryKey: keys.members(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The role could not be changed.');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.removeMember(workspaceId, member.userId);
      toast.success('Member removed.');
      await client.invalidateQueries({ queryKey: keys.members(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The member could not be removed.');
    } finally {
      setBusy(false);
    }
  }

  const flags = FLAGS.filter((f) => member[f.key]).map((f) => f.label.replace('Can ', ''));
  const editable = canManage && !member.you && member.role !== 'owner';

  return (
    <TableRow>
      <TableCell>
        <span className='font-mono text-xs'>{member.userId.slice(0, 8)}…</span>
        {member.you && (
          <Badge variant='outline' className='ml-2'>
            you
          </Badge>
        )}
      </TableCell>
      <TableCell>
        {editable ? (
          <Select value={member.role} onValueChange={(value) => void change(value as WorkspaceRole)}>
            <SelectTrigger className='h-8 w-32' aria-label='Role' disabled={busy}>
              <SelectValue>{ROLE_LABELS[member.role]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {INVITE_ROLES.map((r) => (
                <SelectItem key={r} value={r}>
                  {ROLE_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          ROLE_LABELS[member.role]
        )}
      </TableCell>
      <TableCell className='text-muted-foreground text-xs'>{flags.length ? flags.join(', ') : '—'}</TableCell>
      <TableCell>
        <Badge variant={member.status === 'active' ? 'outline' : 'secondary'}>{member.status}</Badge>
      </TableCell>
      <TableCell className='text-muted-foreground text-xs'>{relativeTime(member.updatedAt)}</TableCell>
      <TableCell className='text-right'>
        {editable && (
          <>
            <Button variant='ghost' size='sm' className='text-destructive' disabled={busy} onClick={() => setConfirmRemove(true)}>
              Remove
            </Button>
            <AlertDialog open={confirmRemove} onOpenChange={setConfirmRemove}>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Remove this member?</AlertDialogTitle>
                  <AlertDialogDescription>They lose access immediately. Drafts they wrote stay in the workspace.</AlertDialogDescription>
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

export function MembersView() {
  const access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission: 'manage_members' });
  const members = useMembers();
  const invitations = useInvitations();
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [created, setCreated] = useState<{ result: InvitationCreated; email: string } | null>(null);

  async function revoke(id: string) {
    try {
      await api.revokeInvitation(workspaceId, id);
      toast.success('Invitation revoked.');
      await client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not revoke.');
    }
  }

  const acceptLink = created ? `${window.location.origin}/invite/${created.result.token}` : '';

  return (
    <PageContainer
      pageTitle='Members'
      pageDescription='Who can do what in this workspace.'
      infoContent={infoContent}
      access={canManage}
      accessFallback={<p className='text-muted-foreground text-sm'>Only owners and admins manage members.</p>}
    >
      <div className='flex flex-col gap-6'>
        <Card>
          <CardHeader>
            <CardTitle>Invite someone</CardTitle>
            <CardDescription>They receive an email with a one-time link. You can also copy it below after sending.</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-4'>
            <InviteForm
              onCreated={(result, email) => {
                setCreated({ result, email });
                void client.invalidateQueries({ queryKey: keys.invitations(workspaceId) });
              }}
            />
            {created && (
              <Alert>
                <Icons.checks className='size-4' />
                <AlertTitle>
                  Invitation for {created.email} {created.result.emailSent ? 'sent' : 'created'}
                </AlertTitle>
                <AlertDescription className='flex flex-col gap-2'>
                  <span>
                    {created.result.emailSent
                      ? 'An email is on its way. The link below works once and expires '
                      : 'Email delivery is not configured on this deployment, so share the link directly. It works once and expires '}
                    {formatDate(created.result.expiresAt)}.
                  </span>
                  <div className='flex flex-wrap items-center gap-2'>
                    <code className='bg-muted max-w-full truncate rounded px-2 py-1 text-xs'>{acceptLink}</code>
                    <Button
                      size='sm'
                      variant='outline'
                      onClick={() => {
                        void navigator.clipboard.writeText(acceptLink).then(() => toast.success('Link copied.'));
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

        <section className='flex flex-col gap-3' aria-labelledby='members-heading'>
          <h3 id='members-heading' className='text-lg font-semibold'>
            Members
          </h3>
          {members.isLoading ? (
            <Skeleton className='h-32 w-full' />
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
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(members.data?.members ?? []).map((member) => (
                    <MemberRow key={member.userId} member={member} canManage={canManage} />
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        <section className='flex flex-col gap-3' aria-labelledby='invites-heading'>
          <h3 id='invites-heading' className='text-lg font-semibold'>
            Invitations
          </h3>
          {invitations.isLoading ? (
            <Skeleton className='h-24 w-full' />
          ) : (invitations.data?.invitations ?? []).length === 0 ? (
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
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(invitations.data?.invitations ?? []).map((inv) => (
                    <TableRow key={inv.invitationId}>
                      <TableCell>{inv.email}</TableCell>
                      <TableCell>{ROLE_LABELS[inv.role as WorkspaceRole] ?? inv.role}</TableCell>
                      <TableCell>
                        <Badge variant={inv.state === 'pending' ? 'default' : 'outline'}>{inv.state}</Badge>
                      </TableCell>
                      <TableCell className='text-muted-foreground text-xs'>{formatDate(inv.expiresAt)}</TableCell>
                      <TableCell className='text-right'>
                        {inv.state === 'pending' && (
                          <Button variant='ghost' size='sm' onClick={() => void revoke(inv.invitationId)}>
                            Revoke
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </section>
      </div>
    </PageContainer>
  );
}
