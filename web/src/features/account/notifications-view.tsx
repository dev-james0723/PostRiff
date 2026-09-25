'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { InfoTip } from '@/components/rafii';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { keys, useMe } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspace } from '@/lib/workspace/provider';
import { NotificationSettings } from '@/features/coworker/notifications/notification-settings';
import { useCoworkerFlag } from '@/lib/coworker/hooks';
import { SettingsSection } from './settings-section';

const EMAILS = [
  { kind: 'Invitation', when: 'When someone is invited', to: 'The invitee' },
  { kind: 'Welcome', when: 'After your first workspace', to: 'You' },
  { kind: 'New device sign-in', when: 'Only if turned on above', to: 'You' },
  { kind: 'Trial ending', when: '2–3 days before it ends', to: 'Owner' },
  { kind: 'Trial ended', when: 'Within a day after it ends', to: 'Owner' },
  { kind: 'Subscription active', when: 'When a plan starts or changes', to: 'Owner' },
  { kind: 'Payment failed', when: 'When a renewal fails (7-day grace)', to: 'Owner' }
];

/** The one optional email: a person-level preference (`PATCH /api/me`), off until they ask for it. The switch shows the result, so success is silent. */
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
    } catch (err) {
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : 'Couldn’t save. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsSection id='notifications-security' title='Security alerts'>
      <Label className='flex min-h-11 items-center justify-between gap-4'>
        <span className='flex items-center gap-0.5'>
          <span className='text-sm font-medium'>Email me when a new device signs in</span>
          <InfoTip
            label='About new-device alerts'
            className='-my-2 size-9'
            description='One email per new device, with a link to review your sessions. Each alert also appears in your account history.'
          />
        </span>
        {me.isLoading ? (
          <Skeleton className='h-5 w-9 shrink-0' />
        ) : (
          <Switch checked={on} disabled={busy} onCheckedChange={(checked) => void toggle(checked)} aria-label='Email me when a new device signs in' />
        )}
      </Label>
    </SettingsSection>
  );
}

export function NotificationsView() {
  const auth = useAuth();
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { permission: 'owner' });
  // With Rafii's notification centre on, the person chooses what reaches them; otherwise only transactional email exists.
  const centre = useCoworkerFlag('RAFII_NOTIFICATIONS_V2_ENABLED') === true;
  return (
    <PageContainer
      pageTitle='Notifications'
      pageDescription={centre ? 'Choose what reaches you, where and when. No marketing, no tracking pixels.' : 'No marketing emails. No tracking pixels.'}
      width='reading'
    >
      <div className='flex flex-col gap-8'>
        <SecurityAlerts />

        <SettingsSection
          id='notifications-emails'
          title='Emails we send'
          description={
            <>
              Sent to {auth.user?.email ?? 'your sign-in email'}.{owner ? ' To change who gets billing emails, transfer ownership in Members.' : ''}
            </>
          }
          padding='sm'
        >
          <ul className='flex flex-col gap-1'>
            {EMAILS.map((item) => (
              <li key={item.kind} className='flex min-h-12 items-center justify-between gap-4 rounded-[var(--rafii-radius-control)] px-2 py-2'>
                <div className='min-w-0'>
                  <p className='text-foreground text-sm font-medium'>{item.kind}</p>
                  <p className='text-muted-foreground hidden text-xs sm:block'>{item.when}</p>
                </div>
                <Badge variant='secondary' className='shrink-0'>
                  {item.to}
                </Badge>
              </li>
            ))}
          </ul>
        </SettingsSection>

        <p className='text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-2 px-1 text-sm'>
          Approvals, reconnects and plan limits show on Overview.
          <Link href='/app/overview' className={buttonVariants({ variant: 'glass', size: 'sm' }) + ' min-h-10 px-3.5'}>
            <Icons.dashboard className='size-4' aria-hidden /> Open Overview
          </Link>
        </p>

        <NotificationSettings />
      </div>
    </PageContainer>
  );
}
