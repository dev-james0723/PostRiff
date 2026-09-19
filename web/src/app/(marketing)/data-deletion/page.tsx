import type { Metadata } from 'next';
import Link from 'next/link';
import { LegalLayout } from '@/components/marketing/legal-layout';
import { LEGAL_CONTACT_EMAIL } from '@/config/legal';
import { siteConfig } from '@/config/site';

export const metadata: Metadata = {
  title: 'Data Deletion',
  description: 'How to delete your PostRiff account and data, or disconnect a single platform, and what is removed.',
  openGraph: { title: 'Data Deletion · PostRiff', url: '/data-deletion' }
};

const sections = [
  { id: 'account', title: 'Delete your account' },
  { id: 'platform', title: 'Disconnect one platform' },
  { id: 'source', title: 'Remove a single source' },
  { id: 'what', title: 'What is deleted and what is kept' },
  { id: 'timing', title: 'Timing' },
  { id: 'email', title: 'Requesting by email' }
];

export default function DataDeletionPage() {
  return (
    <LegalLayout
      eyebrow='Legal'
      title='Data deletion'
      intro='You can delete everything, disconnect one platform, or remove one source — from inside the app, without asking us. This page is also the deletion instructions we register with each platform.'
      sections={sections}
    >
      <h2 id='account'>1. Delete your account</h2>
      <ul>
        <li>
          Sign in and open <strong>Account → Privacy &amp; data</strong> (<code>{siteConfig.url}/app/account/privacy</code>).
        </li>
        <li>Optionally export first: “Export drafts” gives you a zip with a receipt.</li>
        <li>
          Choose <strong>Delete account…</strong>, type <code>DELETE</code> to confirm, and confirm again.
        </li>
        <li>Only the workspace owner can do this. Publications already handed to a platform must be resolved first; they cannot be recalled by cancelling. The app shows any unresolved publications. Waiting posts are removed unpublished when the workspace is deleted.</li>
      </ul>

      <h2 id='platform'>2. Disconnect one platform</h2>
      <ul>
        <li>
          Open <strong>Channels</strong> and choose <strong>Disconnect</strong> on the account.
        </li>
        <li>The stored access token is wiped immediately and revoked with the platform where the platform supports it.</li>
        <li>Metrics and comments for that account stop being collected. Approved jobs for it are held, not published.</li>
        <li>You can also revoke PostRiff from the platform’s own settings (for example LinkedIn → Settings → Permitted services, or Meta → Apps and websites); the next PostRiff request will then fail and the connection will be shown as needing re-authorisation.</li>
      </ul>

      <h2 id='source'>3. Remove a single source</h2>
      <p>
        In <strong>Ideas</strong> or <strong>Account → Privacy &amp; data</strong> you can retract a source. Retraction removes its text and facts and blocks drafts that depend on it until drafted again. Waiting posts for those drafts are held until approved again. Retraction from Privacy &amp; data also records a data request with a receipt.
      </p>

      <h2 id='what'>4. What is deleted and what is kept</h2>
      <table>
        <thead>
          <tr>
            <th>On account deletion</th>
            <th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Account, memberships, sessions</td>
            <td>Deleted; the Supabase Auth user is removed.</td>
          </tr>
          <tr>
            <td>Workspace state: sources, drafts, approvals, schedules</td>
            <td>Deleted.</td>
          </tr>
          <tr>
            <td>Uploaded and generated media</td>
            <td>Deleted from private storage.</td>
          </tr>
          <tr>
            <td>Provider tokens</td>
            <td>Wiped and revoked where supported.</td>
          </tr>
          <tr>
            <td>Platform data (post ids, metrics, comments)</td>
            <td>Deleted with the workspace.</td>
          </tr>
          <tr>
            <td>Publication receipts and audit events</td>
            <td>Kept as content-free tombstones (ids, hashes, timestamps) where audit rules require it. They contain no post text, media or tokens.</td>
          </tr>
          <tr>
            <td>Billing records</td>
            <td>Kept for as long as tax and accounting law requires; Stripe keeps its own records under its policy.</td>
          </tr>
          <tr>
            <td>Backups</td>
            <td>Rotate out within 30 days.</td>
          </tr>
        </tbody>
      </table>

      <h2 id='timing'>5. Timing</h2>
      <p>In-app deletion is immediate for live data. Backups holding a copy rotate out within 30 days and are never restored into the live service except to recover from an outage.</p>

      <h2 id='email'>6. Requesting by email</h2>
      <p>
        If you cannot sign in, email <a href={`mailto:${LEGAL_CONTACT_EMAIL}`} className='underline'>{LEGAL_CONTACT_EMAIL}</a> from the address on the account with the subject “Delete my data”. We will verify it is you and complete the deletion within 30 days, confirming by reply. Platform users who never had a PostRiff account but whose comment on a PostRiff-published post was collected can use the same address; we remove the comment record and keep only a tombstone.
      </p>
      <p>
        See also the{' '}
        <Link href={siteConfig.links.privacy} className='underline'>
          Privacy Policy
        </Link>
        .
      </p>
    </LegalLayout>
  );
}
