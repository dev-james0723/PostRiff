import { plans } from '@/config/plans';
import { siteConfig } from '@/config/site';

/** Organization + SoftwareApplication structured data for the public site. */
export function JsonLd() {
  const data = [
    {
      '@context': 'https://schema.org',
      '@type': 'Organization',
      name: siteConfig.name,
      url: siteConfig.url,
      contactPoint: { '@type': 'ContactPoint', email: siteConfig.supportEmail, contactType: 'customer support' }
    },
    {
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      name: siteConfig.name,
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Web',
      url: siteConfig.url,
      description: siteConfig.description,
      offers: plans.map((plan) => ({
        '@type': 'Offer',
        name: plan.name,
        price: (plan.priceCents / 100).toFixed(2),
        priceCurrency: plan.currency,
        category: 'subscription'
      }))
    }
  ];
  return <script type='application/ld+json' dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}
