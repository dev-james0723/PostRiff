import type { Metadata } from 'next';
import { Suspense } from 'react';
import { ConnectForwarder } from './forwarder';

export const metadata: Metadata = { title: 'Connecting…', robots: { index: false } };

/**
 * Providers return to `/channels/connect` (the path the API registers). The
 * authenticated exchange lives inside the app shell, so forward there.
 */
export default function ChannelsConnectPage() {
  return (
    <Suspense fallback={null}>
      <ConnectForwarder />
    </Suspense>
  );
}
