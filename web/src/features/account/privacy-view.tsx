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
import { RetentionSection, WhereItGoesSection } from './privacy/where-it-goes';

const infoContent = {
  title: 'Your data, your call',
  sections: [
    {
      title: 'Export with a fingerprint',
      description:
        'An export is a zip of drafts, sources, approvals and receipts, recorded in Data requests. After the download this page shows the SHA-256 fingerprint of the exact file you received, so you can show later that it is unchanged.'
    },
    {
      title: 'Diagnostics stay with you',
      description:
        'A diagnostics package holds counts and states only: never prompts, post text, tokens or files. You see all of it before downloading, and PostRiff does not send it anywhere.'
    },
    {
      title: 'Retraction',
      description:
        'Retracting a source blanks its text and facts. Drafts that used it keep their text but stay blocked until you draft them again. Every draft in the workspace must be drafted again before it can be reviewed or scheduled, and posts waiting in the Queue are held until approved again.'
    },
    {
      title: 'Deletion',
      description:
        'Only the workspace owner can delete the account. Publications already handed to a platform must have an outcome first. Content-free receipts and a trial record stay.'
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
      <PageContainer pageTitle='Privacy & data' pageDescription='What PostRiff holds, where it goes, and what you can do about it.'>
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
    <PageContainer
      pageTitle='Privacy & data'
      pageDescription='What PostRiff holds, where it goes, and what you can do about it.'
      infoContent={infoContent}
    >
      <div className='flex min-w-0 flex-col gap-10'>
        <HoldingsSection snapshot={snapshot} memory={memory} />

        <WhereItGoesSection memory={memory} notice={notice} canEdit={canEdit} />

        <PrivacySection id='privacy-actions' title='What you can do' description='Each card says what you get and what it records.'>
          <div className='grid min-w-0 gap-4 md:grid-cols-2'>
            <ExportCard busy={busy} setBusy={setBusy} />
            <VoiceProfileCard busy={busy} setBusy={setBusy} />
            <DiagnosticsCard busy={busy} setBusy={setBusy} />
            <RetractCard snapshot={snapshot} canEdit={canEdit} busy={busy} setBusy={setBusy} />
          </div>
        </PrivacySection>

        <RequestsSection requests={requests} />

        <RetentionSection notice={notice} />

        <DeleteCard snapshot={snapshot} owner={owner} role={access.role} busy={busy} />
      </div>
    </PageContainer>
  );
}
