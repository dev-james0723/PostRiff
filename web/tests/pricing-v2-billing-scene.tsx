// Synthetic surrounding app reads; the BillingView and its controls render unchanged.
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BillingView } from '../src/features/billing/billing-view';
import { registerPackReads, scene } from './pricing-v2-billing-scene-mocks';

const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
client.setQueryData(['credit-packs', 'synthetic-billing'], scene.packs);
registerPackReads(
  () => client.getQueryCache().find({ queryKey: ['credit-packs', 'synthetic-billing'] })!.setState({ status: 'error', error: new Error('Synthetic failed pack refresh') }),
  () => client.setQueryData(['credit-packs', 'synthetic-billing'], scene.packs)
);
createRoot(document.getElementById('scene')!).render(<QueryClientProvider client={client}><BillingView /></QueryClientProvider>);
