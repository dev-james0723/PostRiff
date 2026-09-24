import type { Metadata } from 'next';
import { Suspense } from 'react';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { ContactForm } from './contact-form';

export const metadata: Metadata = {
  title: 'Contact',
  description: 'Support, billing, design partner applications, press and security contact for Rafii.',
  openGraph: { title: 'Contact · Rafii', url: '/contact' }
};

export default function ContactPage() {
  return (
    <>
      <PageHero eyebrow='Contact' title='We read every message.' description='Pick a topic so it reaches the right person. Replies come by email.' />
      <Section>
        <Suspense fallback={null}>
          <ContactForm />
        </Suspense>
      </Section>
    </>
  );
}
