import { headers } from 'next/headers';
import { notFound } from 'next/navigation';
import { localDemoAccessAllowed } from './access-gate.mjs';
import DemoAccess from './access';

export const dynamic = 'force-dynamic';

export default async function Page() {
  const host = (await headers()).get('host');
  if (!localDemoAccessAllowed(host, process.env)) notFound();
  return <main id="main" className="signin">
    <p className="eyebrow">Rafii / Local review preview</p>
    <h1>Local Demo access</h1>
    <p>Enter the fictional Admin workspace with a simulated founder session.</p>
    <p>Rafii&apos;s session, permissions and PostgreSQL boundaries are active. This login is a local simulation; it does not verify your real identity.</p>
    <DemoAccess token={process.env.RAFII_CONTROL_LOCAL_PREVIEW_TOKEN!}/>
    <p className="muted">Demo customers, AI responses and delivery states are simulated. No customer email, phone call or production fault is triggered.</p>
  </main>;
}
