import type { Metadata } from 'next';
import { PageHero } from '@/components/marketing/page-hero';
import { Section } from '@/components/marketing/section';
import { StatusPanel } from './status-panel';

export const metadata: Metadata = {
  title: 'Status',
  description: 'Live status of the Rafii web app, API, authentication and publishing workers.',
  openGraph: { title: 'Status · Rafii', url: '/status' }
};

export default function StatusPage() {
  return (
    <>
      <PageHero eyebrow='Status' title='Is Rafii up?' description='Checked live from this page. No historical uptime figures are shown until we have enough real history to be honest about.' />
      <Section>
        <StatusPanel />
      </Section>
    </>
  );
}
