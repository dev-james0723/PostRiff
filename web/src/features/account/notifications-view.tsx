'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { keys, useMe } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspace } from '@/lib/workspace/provider';

const EMAILS = [
  { kind: 'Invitation', when: 'When someone invites you to a workspace', to: 'The invitee' },
  { kind: 'Welcome', when: 'Once, when your first workspace is created', to: 'You' },
  { kind: 'New device sign-in', when: 'The first time your account is used on a device we have not seen — only if you turn it on below', to: 'You' },
  { kind: 'Trial ending', when: '2–3 days before the trial ends', to: 'Workspace owner' },
  { kind: 'Trial ended', when: 'Within a day after the trial ends', to: 'Workspace owner' },
  { kind: 'Subscription active', when: 'When a plan is activated or changed', to: 'Workspace owner' },
  { kind: 'Payment failed', when: 'When a renewal payment fails (7-day grace)', to: 'Workspace owner' }
];

/** The one optional email: a person-level preference (`PATCH /api/me`), off until they ask for it. */
function SecurityAlerts() {
  const me = useMe();
  const { api } = useWorkspace();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const on = me.data?.preferences.alertNewDevice ?? false;

  async function toggle(next: boolean) {
    setBusy(true);
    try {
      await api.updateProfile({ alertNewDevice: next });
      await client.invalidateQueries({ queryKey: keys.me });
      toast.success(next ? 'You will get an email when a new device signs in.' : 'New-device alerts are off.');
    } catch (err) {
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : 'The preference could not be saved.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className='lg:col-span-2'>
      <CardHeader>
        <CardTitle>Security alerts</CardTitle>
        <CardDescription>Optional. Sent to your sign-in email the first time your account is used on a device we have not seen before.</CardDescription>
      </CardHeader>
      <CardContent>
        <Label className='flex items-start justify-between gap-4'>
          <span className='flex flex-col gap-1'>
            <span className='text-sm font-medium'>Email me when a new device signs in</span>
            <span className='text-muted-foreground text-xs font-normal'>
              One email per new device, with a link to review your sessions and sign the others out. Each alert also appears in your account history.
            </span>
          </span>
          {me.isLoading ? (
            <Skeleton className='h-5 w-9 shrink-0' />
          ) : (
            <Switch checked={on} disabled={busy} onCheckedChange={(checked) => void toggle(checked)} aria-label='Email me when a new device signs in' />
          )}
        </Label>
      </CardContent>
    </Card>
  );
}

export function NotificationsView() {
  const auth = useAuth();
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { permission: 'owner' });
  return (
    <PageContainer
      pageTitle='Notifications'
      pageDescription='PostRiff sends a small number of transactional emails and nothing else. No marketing, no tracking pixels.'
    >
      <div className='grid gap-4 lg:grid-cols-3'>
        <Card className='lg:col-span-2'>
          <CardHeader>
            <CardTitle>Emails we send</CardTitle>
            <CardDescription>
              Delivered to {auth.user?.email ?? 'your sign-in email'}. Each one is sent at most once per event.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className='divide-y'>
              {EMAILS.map((item) => (
                <li key={item.kind} className='flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between'>
                  <div>
                    <p className='text-sm font-medium'>{item.kind}</p>
                    <p className='text-muted-foreground text-xs'>{item.when}</p>
                  </div>
                  <Badge variant='outline'>{item.to}</Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>In the app</CardTitle>
            <CardDescription>Anything that needs a decision shows on the Overview.</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-col gap-3 text-sm'>
            <p className='text-muted-foreground'>
              Approvals waiting, connections that need re-authorisation, and plan limits appear under “Needs your attention”. Nothing publishes on a notification alone.
            </p>
            <Link href='/app' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
              <Icons.dashboard className='size-4' /> Open Overview
            </Link>
            {owner && (
              <p className='text-muted-foreground text-xs'>
                Billing emails go to the owner. Change the owner by transferring the workspace from Members.
              </p>
            )}
          </CardContent>
        </Card>
        <SecurityAlerts />
      </div>
    </PageContainer>
  );
}
