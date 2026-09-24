/**
 * Single source of truth for site-wide identity and public links.
 * Every page, metadata block and email footer reads from here.
 */
export const siteConfig = {
  name: 'Rafii',
  url: process.env.NEXT_PUBLIC_APP_URL ?? 'https://postriff-phase2-private.vercel.app',
  description:
    'Your AI teammate for social media. Prepare drafts from approved sources, review every version, then publish through an available connector or export for manual posting.',
  // TODO: confirm the support mailbox before general availability.
  supportEmail: 'support@postriff.app',
  links: {
    docs: '/docs',
    pricing: '/pricing',
    channels: '/channels',
    contact: '/contact',
    changelog: '/changelog',
    status: '/status',
    security: '/security',
    privacy: '/privacy',
    terms: '/terms',
    dataDeletion: '/data-deletion',
    signIn: '/auth/sign-in',
    signUp: '/auth/sign-up',
    app: '/app'
  },
  /** Top navigation shown in the marketing header and mobile sheet. */
  mainNav: [
    { title: 'Product', href: '/#how-it-works' },
    { title: 'Channels', href: '/channels' },
    { title: 'Pricing', href: '/pricing' },
    { title: 'Docs', href: '/docs' }
  ],
  /** Footer columns. Keep in sync with the public routes in the spec (§5). */
  footerNav: [
    {
      title: 'Product',
      items: [
        { title: 'How it works', href: '/#how-it-works' },
        { title: 'Pricing', href: '/pricing' },
        { title: 'Docs', href: '/docs' },
        { title: 'Security', href: '/security' }
      ]
    },
    {
      title: 'Channels',
      items: [
        { title: 'All channels', href: '/channels' },
        { title: 'LinkedIn', href: '/channels/linkedin' },
        { title: 'Threads', href: '/channels/threads' },
        { title: 'Instagram', href: '/channels/instagram' },
        { title: '小紅書 Xiaohongshu', href: '/channels/xiaohongshu' }
      ]
    },
    {
      title: 'Company',
      items: [
        { title: 'Contact', href: '/contact' },
        { title: 'Changelog', href: '/changelog' },
        { title: 'Status', href: '/status' }
      ]
    },
    {
      title: 'Legal',
      items: [
        { title: 'Privacy', href: '/privacy' },
        { title: 'Terms', href: '/terms' },
        { title: 'Data deletion', href: '/data-deletion' },
        { title: 'Security', href: '/security' }
      ]
    }
  ]
} as const;

export type SiteConfig = typeof siteConfig;
