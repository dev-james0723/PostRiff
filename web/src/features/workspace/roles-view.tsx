'use client';

import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { allows, ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import type { WorkspacePermission, WorkspaceRole } from '@/types';

const ROLES: WorkspaceRole[] = ['owner', 'admin', 'editor', 'approver', 'viewer'];
const PERMISSIONS: { key: WorkspacePermission; label: string }[] = [
  { key: 'read', label: 'Read drafts, schedule, analytics' },
  { key: 'edit', label: 'Write and edit drafts' },
  { key: 'approve', label: 'Approve exact publications' },
  { key: 'reply', label: 'Reply to comments' },
  { key: 'moderate', label: 'Moderate comments' },
  { key: 'manage_connections', label: 'Connect and disconnect channels' },
  { key: 'manage_members', label: 'Invite and manage members' },
  { key: 'owner', label: 'Billing, deletion, ownership' }
];

export function RolesView() {
  return (
    <PageContainer
      pageTitle='Roles'
      pageDescription='What each role can do. Extra grants add a single right to a non-viewer.'
      pageHeaderAction={
        <Link href='/app/workspace/members' className={buttonVariants({ variant: 'outline' })}>
          Manage members
        </Link>
      }
    >
      <div className='flex flex-col gap-6'>
        <div className='grid gap-3 md:grid-cols-5'>
          {ROLES.map((role) => (
            <div key={role} className='rounded-lg border p-3'>
              <p className='font-medium'>{ROLE_LABELS[role]}</p>
              <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
            </div>
          ))}
        </div>
        <div className='overflow-x-auto rounded-lg border'>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Permission</TableHead>
                {ROLES.map((role) => (
                  <TableHead key={role} className='text-center'>
                    {ROLE_LABELS[role]}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {PERMISSIONS.map((permission) => (
                <TableRow key={permission.key}>
                  <TableCell>{permission.label}</TableCell>
                  {ROLES.map((role) => {
                    const base = allows(
                      { role, can_publish: false, can_reply: false, can_moderate: false, can_manage_connections: false },
                      permission.key
                    );
                    const withFlag =
                      !base &&
                      allows(
                        { role, can_publish: true, can_reply: true, can_moderate: true, can_manage_connections: true },
                        permission.key
                      );
                    return (
                      <TableCell key={role} className='text-center'>
                        {base ? (
                          <span aria-label='Yes'>✓</span>
                        ) : withFlag ? (
                          <Badge variant='outline'>with grant</Badge>
                        ) : (
                          <span className='text-muted-foreground' aria-label='No'>
                            —
                          </span>
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className='text-muted-foreground text-sm'>
          Sensitive changes (disconnecting a channel, deleting the account, changing members, revoking sessions) also require a sign-in from the last 10 minutes.
        </p>
      </div>
    </PageContainer>
  );
}
