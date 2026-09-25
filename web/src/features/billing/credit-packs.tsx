'use client';

import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useUsage } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';

interface Pack { id: string; label: string; amountCents: number; currency: string; milliCredits: number }
function price(pack: Pack) {
  const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: pack.currency.toUpperCase() });
  return formatter.format(pack.amountCents / 10 ** (formatter.resolvedOptions().maximumFractionDigits ?? 2));
}

function CreditPacksBody() {
  const { api, workspaceId } = useWorkspaceApi();
  const query = useQuery({ queryKey: ['credit-packs', workspaceId], queryFn: () => api.creditPacks(workspaceId) });
  const usage = useUsage();
  const returned = useSearchParams().get('creditCheckout') === 'returned';
  const [selected, setSelected] = useState<Pack | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const requestIds = useRef(new Map<string, string>());
  const sending = useRef(false);
  async function purchase() {
    if (!selected || sending.current) return;
    sending.current = true; setBusy(true); setError(null);
    try {
      const requestId = requestIds.current.get(selected.id) ?? crypto.randomUUID();
      requestIds.current.set(selected.id, requestId);
      const result = await api.creditCheckout(workspaceId, selected.id, requestId);
      if (!mounted.current) return;
      const target = new URL(result.url);
      if (target.protocol !== 'https:' || target.host !== 'checkout.stripe.com' || target.username || target.password) throw new Error('Unexpected checkout destination.');
      window.location.assign(result.url);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Checkout could not be opened.'); }
    finally { sending.current = false; setBusy(false); }
  }
  if (!query.data?.available && !query.isError && !returned) return null;
  return <section className='flex flex-col gap-3' aria-label='Credit packs'>
    <h2 className='text-lg font-medium'>Add credits</h2>
    {returned && <div className='rafii-quiet rounded-xl p-4'><p className='text-sm'>Payment confirmation may still be processing. Only the verified balance below is available to spend.</p><Button variant='quiet' onClick={() => void usage.refetch()}>Refresh balance</Button></div>}
    {query.isError && <p role='status' className='text-muted-foreground text-sm'>Credit packs could not be loaded. <button className='underline' onClick={() => void query.refetch()}>Retry</button></p>}
    <div className='flex flex-wrap gap-3'>{query.data?.packs.map(pack => <Button key={pack.id} variant='glass' className='min-h-14' onClick={() => { setSelected(pack); setError(null); }}>{(pack.milliCredits / 1000).toLocaleString()} credits · {price(pack)}</Button>)}</div>
    <Dialog open={selected !== null} onOpenChange={open => { if (!open && !busy) setSelected(null); }}>
      <DialogContent><DialogHeader><DialogTitle>Confirm purchase</DialogTitle><DialogDescription>One-time credit purchase. You will review payment details on Stripe.</DialogDescription></DialogHeader>
        {selected && <p className='text-base'>{(selected.milliCredits / 1000).toLocaleString()} credits · {price(selected)}</p>}
        {error && <p role='alert' className='text-sm'>{error}</p>}
        <DialogFooter><Button variant='glass' disabled={busy} onClick={() => setSelected(null)}>Cancel</Button><Button variant='action' disabled={busy} onClick={() => void purchase()}>{busy ? 'Opening checkout…' : 'Continue to Stripe'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </section>;
}

export function CreditPacks() {
  const { workspaceId } = useWorkspaceApi();
  return <CreditPacksBody key={workspaceId} />;
}
