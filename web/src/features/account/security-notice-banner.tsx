'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { keys, useMe } from '@/lib/api/hooks';
import { useWorkspace } from '@/lib/workspace/provider';

/**
 * RAPv2 decision 5: after a "This wasn't me" report, the person's next sign-in shows this banner (the email goes out
 * too). It stays until they dismiss it; dismissing never changes the report or the hold. The session that filed the
 * report never gets it (the server leaves `securityNotice` empty there).
 */
export function SecurityNoticeBanner() {
  const me = useMe();
  const { api } = useWorkspace();
  const queries = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const notice = me.data?.securityNotice;
  if (!notice) return null;

  async function dismiss() {
    if (!notice) return;
    setBusy(true);
    setFailed(false);
    try {
      await api.dismissSecurityNotice(notice.incidentId);
      await queries.invalidateQueries({ queryKey: keys.me });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const when = notice.reportedAt ? new Date(notice.reportedAt).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : null;
  return (
    <section
      aria-labelledby='security-notice-title'
      data-testid='security-notice-banner'
      className='rafii-glass mx-4 mt-4 flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4 md:mx-8 md:flex-row md:items-start'
    >
      <span aria-hidden className='text-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full'>
        <Icons.shieldCheck className='size-5' />
      </span>
      <div className='flex min-w-0 flex-1 flex-col gap-1'>
        <h2 id='security-notice-title' className='text-foreground text-sm font-medium'>
          You reported a sign-in that wasn’t you{when ? ` (${when})` : ''}
        </h2>
        <p className='text-muted-foreground text-sm leading-relaxed text-pretty'>
          {notice.accountHold
            ? 'Your account is on a security hold. Scheduled posts, automations, Agent tasks and API tokens are paused until you end it in Security. We also sent you an email.'
            : 'The security hold on your account has ended. Check your sessions and two-step sign-in in Security. We also sent you an email.'}
        </p>
        {failed && (
          <p role='alert' className='text-destructive text-sm'>
            Couldn’t dismiss this right now. Try again.
          </p>
        )}
      </div>
      <div className='flex shrink-0 flex-wrap gap-2'>
        <Link href={notice.href || '/app/account/profile'} className={buttonVariants({ variant: 'action', size: 'control' })}>
          Review security
        </Link>
        <Button variant='quiet' size='control' disabled={busy} onClick={() => void dismiss()}>
          {busy ? 'Dismissing…' : 'Dismiss'}
        </Button>
      </div>
    </section>
  );
}
