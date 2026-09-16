'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { UserAvatarProfile } from '@/components/user-avatar-profile';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { keys, useSessions } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { ROLE_LABELS } from '@/lib/auth/permissions';
import { relativeTime } from '@/lib/time';
import { useWorkspace } from '@/lib/workspace/provider';

export function ProfileView() {
  const auth = useAuth();
  const router = useRouter();
  const { membership, workspaces, api } = useWorkspace();
  const sessions = useSessions();
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);

  async function revoke(sessionId: string) {
    setBusy(sessionId);
    try {
      await api.revokeSession(sessionId);
      toast.success('Session revoked.');
      await client.invalidateQueries({ queryKey: keys.sessions });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The session could not be revoked.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <PageContainer pageTitle='Profile' pageDescription='Your account, your workspaces, and where you are signed in.'>
      <div className='grid gap-4 lg:grid-cols-2'>
        <Card>
          <CardHeader>
            <CardTitle>Account</CardTitle>
            <CardDescription>
              {auth.mode === 'dev'
                ? 'Dev-synthetic identity: exists only in this browser.'
                : 'Name and email come from your sign-in provider.'}
            </CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-4'>
            <UserAvatarProfile className='size-12 rounded-lg' showInfo user={auth.user} />
            <dl className='grid grid-cols-[8rem_1fr] gap-y-1 text-sm'>
              <dt className='text-muted-foreground'>User id</dt>
              <dd className='font-mono text-xs'>{auth.user?.id}</dd>
              <dt className='text-muted-foreground'>Identity</dt>
              <dd>{auth.mode === 'supabase' ? 'Supabase Auth' : 'Local dev harness'}</dd>
              <dt className='text-muted-foreground'>Workspaces</dt>
              <dd>
                {workspaces.length} · you are {membership ? ROLE_LABELS[membership.role].toLowerCase() : '—'} here
              </dd>
            </dl>
            <Button
              variant='outline'
              className='w-fit'
              onClick={() => void auth.signOut().then(() => router.replace('/auth/sign-in'))}
            >
              Sign out
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sessions</CardTitle>
            <CardDescription>Every browser or device that signed in. Revoke any you do not recognise.</CardDescription>
          </CardHeader>
          <CardContent>
            {sessions.isLoading ? (
              <Skeleton className='h-24 w-full' />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Client</TableHead>
                    <TableHead>Last seen</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(sessions.data?.sessions ?? []).map((session) => (
                    <TableRow key={session.sessionId}>
                      <TableCell>
                        {session.client || 'Unknown client'}
                        {session.current && (
                          <Badge variant='outline' className='ml-2'>
                            this one
                          </Badge>
                        )}
                        {session.revoked && (
                          <Badge variant='secondary' className='ml-2'>
                            revoked
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className='text-muted-foreground text-xs'>{relativeTime(session.lastSeen)}</TableCell>
                      <TableCell className='text-right'>
                        {!session.current && !session.revoked && (
                          <Button variant='ghost' size='sm' disabled={busy === session.sessionId} onClick={() => void revoke(session.sessionId)}>
                            Revoke
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
