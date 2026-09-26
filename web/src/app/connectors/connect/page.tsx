import type { Metadata } from 'next';
import { Suspense } from 'react';
import { ConnectorConnectForwarder } from './forwarder';

export const metadata: Metadata = { title: 'Connecting…', robots: { index: false } };

export default function ConnectorConnectPage() {
  return (
    <Suspense fallback={null}>
      <ConnectorConnectForwarder />
    </Suspense>
  );
}
