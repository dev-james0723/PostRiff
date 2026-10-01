import { jsonLdOffers } from '@/config/plans';
import { siteConfig } from '@/config/site';

/**
 * Organization + SoftwareApplication structured data for the public site. Offers list only plans a customer
 * can buy right now in the active catalog (legacy: active terms; Pricing v2: Creator once checkout opens).
 */
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
      offers: jsonLdOffers()
    }
  ];
  return <script type='application/ld+json' dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}
