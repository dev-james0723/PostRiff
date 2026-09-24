import type { Metadata } from 'next';
import Link from 'next/link';
import { LegalLayout } from '@/components/marketing/legal-layout';
import { GOVERNING_LAW, LEGAL_CONTACT_EMAIL } from '@/config/legal';
import { TRIAL } from '@/config/plans';
import { siteConfig } from '@/config/site';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description: 'The agreement between you and Rafii for using the service.',
  openGraph: { title: 'Terms of Service · Rafii', url: '/terms' }
};

const sections = [
  { id: 'service', title: 'The service' },
  { id: 'accounts', title: 'Accounts and eligibility' },
  { id: 'use', title: 'Acceptable use' },
  { id: 'content', title: 'Your content and AI output' },
  { id: 'platforms', title: 'Third-party platforms' },
  { id: 'billing', title: 'Trial, subscriptions and billing' },
  { id: 'ip', title: 'Intellectual property' },
  { id: 'disclaimers', title: 'Disclaimers' },
  { id: 'liability', title: 'Limitation of liability' },
  { id: 'termination', title: 'Termination' },
  { id: 'law', title: 'Governing law' },
  { id: 'contact', title: 'Contact' }
];

export default function TermsPage() {
  return (
    <LegalLayout
      eyebrow='Legal'
      title='Terms of Service'
      intro='These terms govern your use of Rafii. By creating an account you agree to them. They are written to be read, not skimmed; the important parts are short.'
      sections={sections}
    >
      <h2 id='service'>1. The service</h2>
      <p>
        Rafii helps you turn sources into platform-specific drafts, review them, and publish or export them. Nothing is published without an explicit approval from a member of your workspace with the right to approve. Available hosted connectors use official APIs. Other channels may offer export only. The desktop companion is not included in this release. Each channel shows its verified capabilities.
      </p>

      <h2 id='accounts'>2. Accounts and eligibility</h2>
      <p>You must be at least 18 and able to enter a binding contract. Keep your sign-in method secure; you are responsible for activity in your workspace, including by members you invite. Tell us promptly if you believe your account was used without permission.</p>

      <h2 id='use'>3. Acceptable use</h2>
      <p>You agree not to use Rafii to:</p>
      <ul>
        <li>send spam, run engagement schemes, or post content that violates a platform’s rules;</li>
        <li>publish content you do not have the right to publish, or that is unlawful, defamatory or infringing;</li>
        <li>attempt to access other customers’ workspaces or probe the service’s security;</li>
        <li>resell the service or automate it beyond what your plan permits.</li>
      </ul>

      <h2 id='content'>4. Your content and AI output</h2>
      <p>
        Your sources, drafts and media remain yours. You grant us only the licence needed to store, process and publish them on your instruction. AI-assisted drafts are suggestions: you are responsible for reviewing and approving anything that is published under your name, including checking facts, rights and platform rules. When you mark a source as your own writing you confirm you have the right to quote it publicly.
      </p>

      <h2 id='platforms'>5. Third-party platforms</h2>
      <p>
        Connecting a platform account is your own authorisation to that platform, subject to its terms. Platforms change their APIs and review status; where a platform has not yet approved Rafii for direct publishing, the capability is shown as Assisted (export only) and we will not represent it as more than that. We are not responsible for a platform suspending, rate-limiting or removing content.
      </p>

      <h2 id='billing'>6. Trial, subscriptions and billing</h2>
      <p>
        New workspaces get a {TRIAL.days}-day trial with {TRIAL.connectedAccounts} connected accounts and {TRIAL.writingBatches} writing batches. No payment method is required and the trial never converts into a paid plan automatically. Paid plans remain proposed until commercial approval and payment verification are complete. If enabled, they are billed monthly in advance through Stripe at the price shown when you subscribe. Plan allowances stop when they are used up; there is no automatic overage charge. You can cancel at any time from the billing portal; access to paid features continues until the end of the paid period, and your drafts stay readable and exportable afterwards. We may change prices with at least 30 days’ notice by email; a change applies from your next renewal. [Refund policy — to be confirmed by counsel.] Taxes are shown at checkout where applicable.
      </p>

      <h2 id='ip'>7. Intellectual property</h2>
      <p>Rafii, its software, design and documentation are ours or our licensors’. We give you a limited, non-exclusive, non-transferable right to use the service while these terms apply. Feedback you send us may be used without obligation.</p>

      <h2 id='disclaimers'>8. Disclaimers</h2>
      <p>The service is provided “as is”. We do not promise that a platform will accept a post, that metrics are complete, or that the service is uninterrupted. Metrics are shown with the provider’s own definitions and “Unavailable” is never presented as zero.</p>

      <h2 id='liability'>9. Limitation of liability</h2>
      <p>
        To the extent permitted by law, we are not liable for indirect or consequential loss, lost profits or lost audience, and our total liability for any claim is limited to the fees you paid us in the 12 months before the claim arose. Nothing limits liability that cannot be limited by law.
      </p>

      <h2 id='termination'>10. Termination</h2>
      <p>You can delete your account at any time from Account → Privacy &amp; data. We may suspend or end access for a material breach of these terms, with notice where practical. Sections 4, 7, 8, 9 and 11 survive termination.</p>

      <h2 id='law'>11. Governing law</h2>
      <p>These terms are governed by the laws of {GOVERNING_LAW}, and disputes will be resolved in its courts, without prejudice to mandatory consumer protections where you live.</p>

      <h2 id='contact'>12. Contact</h2>
      <p>
        Questions about these terms: <a href={`mailto:${LEGAL_CONTACT_EMAIL}`} className='underline'>{LEGAL_CONTACT_EMAIL}</a>. See also our{' '}
        <Link href={siteConfig.links.privacy} className='underline'>
          Privacy Policy
        </Link>
        .
      </p>
    </LegalLayout>
  );
}
