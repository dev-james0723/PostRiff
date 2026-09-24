import type { Metadata } from 'next';
import Link from 'next/link';
import { LegalLayout } from '@/components/marketing/legal-layout';
import { LEGAL_CONTACT_EMAIL } from '@/config/legal';
import { siteConfig } from '@/config/site';

export const metadata: Metadata = {
  title: 'Security',
  description: 'How Rafii protects your workspace, your connected accounts and your content.',
  openGraph: { title: 'Security · Rafii', url: '/security' }
};

const sections = [
  { id: 'architecture', title: 'Architecture' },
  { id: 'tenancy', title: 'Tenant isolation' },
  { id: 'tokens', title: 'Connected-account tokens' },
  { id: 'approvals', title: 'Nothing publishes without you' },
  { id: 'sessions', title: 'Sessions and step-up' },
  { id: 'money', title: 'Money and limits' },
  { id: 'not', title: 'What we do not do' },
  { id: 'disclosure', title: 'Responsible disclosure' }
];

export default function SecurityPage() {
  return (
    <LegalLayout
      eyebrow='Trust'
      title='Security'
      intro='Rafii holds the keys to your social accounts, so we built it to act only on an explicit approval and to leave a receipt every time it does.'
      sections={sections}
    >
      <h2 id='architecture'>1. Architecture</h2>
      <p>
        The web app runs on Vercel; the API is a Python service on Vercel Functions; authentication, PostgreSQL and private object storage are Supabase; release regions still require verification. Authenticated API calls use a server-verified session or an explicitly scoped API token; a browser-supplied user ID grants no access.
      </p>

      <h2 id='tenancy'>2. Tenant isolation</h2>
      <p>
        Every workspace table uses PostgreSQL row-level security keyed on membership. The API derives your workspace from that membership, never from the request body, and a foreign workspace is indistinguishable from a missing one (“Workspace unavailable”). Local isolation tests exercise cross-tenant reads and writes. Remote CI and release-environment isolation still require verification.
      </p>

      <h2 id='tokens'>3. Connected-account tokens</h2>
      <ul>
        <li>OAuth with PKCE and per-transaction state; the public callback never exchanges codes — the signed-in app completes the exchange.</li>
        <li>Tokens are encrypted at the application layer (Fernet) with a server-held key before they reach the database; the key id is stored with each ciphertext so a rotation is detectable and forces re-authorisation rather than failing silently.</li>
        <li>Tokens are decrypted only inside server-side provider operations and are never returned by any API, logged, or written to audit rows.</li>
        <li>Minimum scopes per capability; the connection card shows exactly which were granted.</li>
        <li>Disconnect wipes the ciphertext and revokes remotely where the platform supports it.</li>
      </ul>

      <h2 id='approvals'>4. Nothing publishes without you</h2>
      <p>
        A review freezes text, media hashes, account, capability and time into a manifest with a digest. Only an approval of that exact digest creates a job. Jobs use manifest idempotency plus reconciliation-before-retry so an uncertain provider response never becomes a duplicate post. Every approval, publication and cancellation is recorded content-free in the audit log.
      </p>

      <h2 id='sessions'>5. Sessions and step-up</h2>
      <p>
        You can see and revoke every session from Profile. Disconnecting a channel, changing members, revoking sessions and deleting the account require a sign-in from the last 10 minutes. Sign-in and invitation acceptance are rate-limited per address and per account.
      </p>

      <h2 id='money'>6. Money and limits</h2>
      <p>
        Card details go to Stripe only. Billing webhooks are signature-verified, replay-safe and out-of-order safe. Usage is metered in an append-only ledger with a reserve-then-settle model and hard stop-lines per workspace and globally, which refuse new paid work when the approved budget cannot cover its reservation. Uncertain provider usage remains reserved until reconciled.
      </p>

      <h2 id='not'>7. What we do not do</h2>
      <ul>
        <li>We do not store passwords (Supabase Auth handles sign-in).</li>
        <li>We do not train models on your content.</li>
        <li>We do not publish, reply or moderate automatically.</li>
        <li>We do not put post bodies, prompts, tokens or files in logs.</li>
        <li>We do not present a capability as “Direct” before the provider has approved it.</li>
      </ul>

      <h2 id='disclosure'>8. Responsible disclosure</h2>
      <p>
        Found a vulnerability? Email <a href={`mailto:${LEGAL_CONTACT_EMAIL}`} className='underline'>{LEGAL_CONTACT_EMAIL}</a> with the subject “Security”. The support mailbox, response commitment and disclosure policy are pending release review; no response-time guarantee is active yet. Avoid other customers’ data and service disruption when reporting a concern.
      </p>
      <p>
        Related:{' '}
        <Link href={siteConfig.links.privacy} className='underline'>
          Privacy Policy
        </Link>{' '}
        ·{' '}
        <Link href={siteConfig.links.dataDeletion} className='underline'>
          Data deletion
        </Link>
      </p>
    </LegalLayout>
  );
}
