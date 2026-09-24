'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { keys, useMe } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/session';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspace } from '@/lib/workspace/provider';
import { SettingsSection } from './settings-section';

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
    <SettingsSection
      id='notifications-security'
      title='Security alerts'
      description='Optional. Sent to your sign-in email the first time your account is used on a device we have not seen before.'
    >
      <Label className='flex min-h-11 items-start justify-between gap-4'>
        <span className='flex flex-col gap-1'>
          <span className='text-sm font-medium'>Email me when a new device signs in</span>
          <span className='text-muted-foreground text-xs leading-relaxed font-normal'>
            One email per new device, with a link to review your sessions and sign the others out. Each alert also appears in your account history.
          </span>
        </span>
        {me.isLoading ? (
          <Skeleton className='h-5 w-9 shrink-0' />
        ) : (
          <Switch checked={on} disabled={busy} onCheckedChange={(checked) => void toggle(checked)} aria-label='Email me when a new device signs in' className='mt-0.5' />
        )}
      </Label>
    </SettingsSection>
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
      width='reading'
    >
      <div className='flex flex-col gap-8'>
        <SettingsSection
          id='notifications-emails'
          title='Emails we send'
          description={<>Delivered to {auth.user?.email ?? 'your sign-in email'}. Each one is sent at most once per event.</>}
          padding='sm'
        >
          <ul className='flex flex-col gap-1'>
            {EMAILS.map((item) => (
              <li key={item.kind} className='flex min-h-12 flex-col gap-1 rounded-[var(--rafii-radius-control)] px-2 py-2 sm:flex-row sm:items-center sm:justify-between sm:gap-4'>
                <div className='min-w-0'>
                  <p className='text-foreground text-sm font-medium'>{item.kind}</p>
                  <p className='text-muted-foreground text-xs leading-relaxed'>{item.when}</p>
                </div>
                <Badge variant='secondary' className='shrink-0'>
                  {item.to}
                </Badge>
              </li>
            ))}
          </ul>
        </SettingsSection>

        <SettingsSection id='notifications-in-app' title='In the app' description='Anything that needs a decision shows on the Overview.'>
          <p className='text-muted-foreground text-sm leading-relaxed'>
            Approvals waiting, connections that need re-authorisation, and plan limits appear under “Needs your attention”. Nothing publishes on a notification alone.
          </p>
          <Link href='/app' className={buttonVariants({ variant: 'glass', size: 'control' }) + ' self-start'}>
            <Icons.dashboard className='size-4' /> Open Overview
          </Link>
          {owner && (
            <p className='text-muted-foreground text-xs leading-relaxed'>
              Billing emails go to the owner. Change the owner by transferring the workspace from Members.
            </p>
          )}
        </SettingsSection>

        <SecurityAlerts />
      </div>
    </PageContainer>
  );
}
