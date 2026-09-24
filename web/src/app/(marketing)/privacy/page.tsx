import type { Metadata } from 'next';
import Link from 'next/link';
import { LegalLayout } from '@/components/marketing/legal-layout';
import { LEGAL_CONTACT_EMAIL } from '@/config/legal';
import { siteConfig } from '@/config/site';
import { RETENTION, RIGHTS, SUBPROCESSORS } from '@/content/legal-shared';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description: 'What Rafii collects, why, how long it is kept, and the rights you have over it.',
  openGraph: { title: 'Privacy Policy · Rafii', url: '/privacy' }
};

const sections = [
  { id: 'who', title: 'Who we are' },
  { id: 'collect', title: 'What we collect' },
  { id: 'use', title: 'How we use it' },
  { id: 'ai', title: 'AI processing' },
  { id: 'platforms', title: 'Connected platforms' },
  { id: 'retention', title: 'Retention' },
  { id: 'subprocessors', title: 'Subprocessors' },
  { id: 'rights', title: 'Your rights' },
  { id: 'transfers', title: 'International transfers' },
  { id: 'security', title: 'Security' },
  { id: 'children', title: 'Children' },
  { id: 'changes', title: 'Changes' },
  { id: 'contact', title: 'Contact' }
];

export default function PrivacyPage() {
  return (
    <LegalLayout
      eyebrow='Legal'
      title='Privacy Policy'
      intro='Rafii turns your ideas into posts for the platforms you connect. This policy explains, in plain language, what we hold about you and what we do with it.'
      sections={sections}
    >
      <h2 id='who'>1. Who we are</h2>
      <p>
        Rafii (“we”, “us”) operates the service at {siteConfig.url}. [Legal entity name, registered address and registration number — to be confirmed by counsel.] We are the controller of the account and workspace data described below.
      </p>

      <h2 id='collect'>2. What we collect</h2>
      <h3>Account data</h3>
      <p>Your email address and, if you sign in with Google, the name and profile image your provider shares. Authentication is handled by Supabase Auth. We do not store passwords.</p>
      <h3>Workspace content</h3>
      <p>Sources you paste or upload, the drafts generated from them, your edits, approvals, scheduling times, media you upload, and the receipts produced when a post is published. This content belongs to you.</p>
      <h3>Connected-account data</h3>
      <p>
        When you connect a social account through its official login, we receive an access token, the account’s identity (id and handle), and — only for capabilities you enable — the ids of posts published through Rafii, their native metrics, and comments on those posts. Tokens are encrypted at the application layer before storage and are decrypted only by authorized server operations for the enabled capability.
      </p>
      <h3>Billing data</h3>
      <p>If you subscribe, Stripe processes your payment. We store your Stripe customer and subscription identifiers and the plan you chose. Card numbers never reach our systems.</p>
      <h3>Operational data</h3>
      <p>Request logs with timestamps, IP-derived throttling counters, session identifiers and a content-free audit trail of actions in your workspace (for example “invitation.created”). Application audit events omit prompts, post bodies, tokens and files. Hosting and error-tracking configuration still requires verification before public launch.</p>

      <h2 id='use'>3. How we use it</h2>
      <ul>
        <li>To run the service: drafting, previews, approvals, scheduling and publishing on your instruction.</li>
        <li>To send transactional email: invitations, a welcome message, trial reminders and billing notices. We do not send marketing email.</li>
        <li>To keep the service safe: rate limiting, abuse prevention, session revocation and the audit trail.</li>
        <li>To bill you, if you subscribe.</li>
      </ul>
      <p>We do not sell your data, and we do not use your content or your audience’s data for advertising.</p>

      <h2 id='ai'>4. AI processing</h2>
      <p>
        The deterministic preview makes no model request. When a configured cloud writer is selected, your instruction and permitted source context are sent to that writer through the configured model route. A local CLI can also send data to its cloud provider. Sources require the applicable egress consent; writing samples require separate purpose and exact writer-route permission. Only bounded style observations are used for sample-based drafting. Workspace memory reaches a cloud writer only when its owner allows it. Paid routes use a workspace reservation and record reported or estimated usage; unknown usage remains reserved until reconciled. Provider contracts, data retention and processing regions require review before a paid beta.
      </p>
      <p>
        Web research is off for every hosted workspace until its owner turns it on. When it is on and a draft needs facts you have not supplied, we send a search query derived from your message to Exa and fetch the public pages it finds through Jina Reader; a link you paste is fetched the same way. Your sources, memory files and drafts are never sent, facts found this way are marked in the draft for you to check, and turning research off stops it immediately. Both services are listed under Subprocessors.
      </p>

      <h2 id='platforms'>5. Connected platforms</h2>
      <p>
        Rafii connects to LinkedIn, Threads, Instagram and other platforms only through your own authorisation, requesting the minimum permissions for the capability you enable. Data received from a platform (account identity, post ids, metrics, comments) is used solely to provide the service to you — showing your results, letting you reply, and reconciling publications. It is not sold, shared with third parties, or combined across customers. When you disconnect an account, the stored token is wiped and revoked with the platform where supported, and platform data for that account stops being collected. Your use of each platform remains subject to that platform’s own terms and privacy policy.
      </p>

      <h2 id='retention'>6. Retention</h2>
      <table>
        <thead>
          <tr>
            <th>Data</th>
            <th>Kept</th>
            <th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {RETENTION.map((row) => (
            <tr key={row.data}>
              <td>{row.data}</td>
              <td>{row.retention}</td>
              <td>{row.note}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 id='subprocessors'>7. Subprocessors</h2>
      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>Purpose</th>
            <th>Region</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {SUBPROCESSORS.map((row) => (
            <tr key={row.name}>
              <td>{row.name}</td>
              <td>{row.purpose}</td>
              <td>{row.region}</td>
              <td>{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2 id='rights'>8. Your rights</h2>
      <p>Wherever you live, you can exercise these from the app (Account → Privacy &amp; data) or by emailing us:</p>
      <ul>
        {RIGHTS.map((right) => (
          <li key={right}>{right}</li>
        ))}
      </ul>
      <p>
        Deleting your account removes your workspace and media; content-free receipts may survive as tombstones where audit rules require it. The full procedure is on the{' '}
        <Link href={siteConfig.links.dataDeletion} className='underline'>
          data deletion page
        </Link>
        . If you are in the EEA, UK or Switzerland you also have the right to lodge a complaint with your supervisory authority.
      </p>

      <h2 id='transfers'>9. International transfers</h2>
      <p>
        Database, storage and authentication use the configured Supabase project; API functions run on Vercel. Actual processing regions and any international transfers must be confirmed for the release environment. [Transfer mechanism (for example Standard Contractual Clauses) — to be confirmed by counsel.]
      </p>

      <h2 id='security'>10. Security</h2>
      <p>
        Row-level security on every workspace table, application-layer encryption of provider tokens with a server-held key, minimum OAuth scopes, session revocation, step-up authentication for sensitive actions, and a content-free audit log. Details are on the{' '}
        <Link href={siteConfig.links.security} className='underline'>
          security page
        </Link>
        .
      </p>

      <h2 id='children'>11. Children</h2>
      <p>Rafii is not directed at anyone under 18 and we do not knowingly collect data from them.</p>

      <h2 id='changes'>12. Changes</h2>
      <p>We will post changes here with a new “last updated” date and, for material changes, email account holders before they take effect.</p>

      <h2 id='contact'>13. Contact</h2>
      <p>
        Privacy questions and requests: <a href={`mailto:${LEGAL_CONTACT_EMAIL}`} className='underline'>{LEGAL_CONTACT_EMAIL}</a>.
      </p>
    </LegalLayout>
  );
}
