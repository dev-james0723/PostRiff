import type { Metadata } from 'next';
import { CtaBand } from '@/components/marketing/cta-band';
import { JsonLd } from '@/components/marketing/json-ld';
import { Hero } from '@/components/marketing/landing/hero';
import { ProductPreview } from '@/components/marketing/landing/product-preview';
import { ChannelMatrix, DesignPartners, Faq, Honesty, HowItWorks, PricingSummary } from '@/components/marketing/landing/sections';
import { siteConfig } from '@/config/site';

const TITLE = 'Rafii — Your AI teammate for social media';
const DESCRIPTION = siteConfig.description;

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  openGraph: { title: TITLE, description: DESCRIPTION, url: '/', siteName: siteConfig.name },
  twitter: { card: 'summary_large_image', title: TITLE, description: DESCRIPTION }
};

export default function HomePage() {
  return (
    <>
      <JsonLd />
      <Hero />
      <ProductPreview />
      <ChannelMatrix />
      <HowItWorks />
      <Honesty />
      <DesignPartners />
      <PricingSummary />
      <Faq />
      <CtaBand />
    </>
  );
}
