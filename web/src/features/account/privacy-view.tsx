'use client';

import { useState } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useDataRequests, useMemory, usePrivacyNotice, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { DeleteCard } from './privacy/delete-card';
import { DiagnosticsCard } from './privacy/diagnostics-card';
import { ExportCard, VoiceProfileCard } from './privacy/export-cards';
import { HoldingsSection } from './privacy/holdings-section';
import { RetractCard } from './privacy/retract-card';
import { RequestsSection } from './privacy/requests-section';
import { PrivacySection } from './privacy/section';
import { PrivacyNoticeSection, WhereItGoesSection } from './privacy/where-it-goes';

const infoContent = {
  title: 'Your data, your call',
  sections: [
    {
      title: 'Export with a fingerprint',
      description: 'A zip of drafts, sources, approvals and receipts. After the download you get its SHA-256 fingerprint, to show later that the file is unchanged.'
    },
    {
      title: 'Diagnostics stay with you',
      description: 'Counts and states only: never prompts, post text, tokens or files. You see it all before downloading, and nothing is sent anywhere.'
    },
    {
      title: 'Retraction',
      description:
        'Retracting a source blanks its text and facts. Drafts that used it are blocked until drafted again. Every draft must be drafted again before review or scheduling, and queued posts wait for approval again.'
    },
    {
      title: 'Deletion',
      description: 'Only the workspace owner can delete the account. Posts already sent to a platform need an outcome first. Content-free receipts and a trial record stay.'
    }
  ]
};

/** A removed membership answers "Workspace unavailable." — the whole page then has nothing to show. */
function workspaceGone(error: unknown) {
  return error instanceof ApiError && (error.status === 403 || error.status === 404) && /workspace unavailable/i.test(error.message);
}

export function PrivacyView() {
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { permission: 'owner' });
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const memory = useMemory();
  const notice = usePrivacyNotice();
  const requests = useDataRequests();
  const [busy, setBusy] = useState<string | null>(null);

  if (workspaceGone(snapshot.error)) {
    return (
      <PageContainer pageTitle='Privacy & data'>
        <StateMessage
          kind='permission'
          title={(snapshot.error as ApiError).message}
          action={
            <Link href='/app' className={buttonVariants({ variant: 'glass', size: 'control' })}>
              Back to Home
            </Link>
          }
          className='max-w-md'
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer pageTitle='Privacy & data' infoContent={infoContent}>
      <div className='flex min-w-0 flex-col gap-10'>
        <HoldingsSection snapshot={snapshot} memory={memory} />

        <WhereItGoesSection memory={memory} canEdit={canEdit} />

        <PrivacySection id='privacy-actions' title='What you can do'>
          <div className='grid min-w-0 gap-4 md:grid-cols-2'>
            <ExportCard busy={busy} setBusy={setBusy} />
            <VoiceProfileCard busy={busy} setBusy={setBusy} />
            <DiagnosticsCard busy={busy} setBusy={setBusy} />
            <RetractCard snapshot={snapshot} canEdit={canEdit} busy={busy} setBusy={setBusy} />
          </div>
        </PrivacySection>

        <RequestsSection requests={requests} />

        <PrivacyNoticeSection notice={notice} />

        <DeleteCard snapshot={snapshot} owner={owner} role={access.role} busy={busy} />
      </div>
    </PageContainer>
  );
}
