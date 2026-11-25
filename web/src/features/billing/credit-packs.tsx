'use client';

import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useUsage } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';

interface Pack { id: string; label: string; amountCents: number; currency: string; milliCredits: number }
const NO_PACKS: readonly Pack[] = [];
function price(pack: Pack) {
  const formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency: pack.currency.toUpperCase() });
  return formatter.format(pack.amountCents / 10 ** (formatter.resolvedOptions().maximumFractionDigits ?? 2));
}

function CreditPacksBody() {
  const { api, workspaceId } = useWorkspaceApi();
  const usage = useUsage();
  const access = useWorkspaceAccess();
  const enabled = usage.isSuccess && !usage.isError && usage.data?.billingMode === 'managed_credits' && checkAccess(access, { permission: 'owner' });
  const query = useQuery({ queryKey: ['credit-packs', workspaceId], queryFn: () => api.creditPacks(workspaceId), enabled });
  const purchaseReady = enabled && query.isSuccess && !query.isError && query.data?.available === true;
  const packs = purchaseReady && query.data ? query.data.packs : NO_PACKS;
  const returned = useSearchParams().get('creditCheckout') === 'returned';
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = packs.find(pack => pack.id === selectedId) ?? null;
  const eligibility = useRef({ purchaseReady, packs, selectedId });
  eligibility.current = { purchaseReady, packs, selectedId };
  useEffect(() => {
    if (selectedId !== null && (!purchaseReady || !packs.some(pack => pack.id === selectedId))) setSelectedId(null);
  }, [purchaseReady, packs, selectedId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const requestIds = useRef(new Map<string, string>());
  const sending = useRef(false);
  async function purchase() {
    const current = eligibility.current;
    const pack = current.packs.find(pack => pack.id === selectedId);
    if (!mounted.current || !current.purchaseReady || !pack || current.selectedId !== selectedId || sending.current) return;
    sending.current = true; setBusy(true); setError(null);
    try {
      const requestId = requestIds.current.get(pack.id) ?? crypto.randomUUID();
      requestIds.current.set(pack.id, requestId);
      const result = await api.creditCheckout(workspaceId, pack.id, requestId);
      if (!mounted.current) return;
      const target = new URL(result.url);
      if (target.protocol !== 'https:' || target.host !== 'checkout.stripe.com' || target.username || target.password) throw new Error('Unexpected checkout destination.');
      window.location.assign(result.url);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Checkout could not be opened.'); }
    finally { sending.current = false; setBusy(false); }
  }
  if (!enabled) return null;
  if (packs.length === 0 && !returned) return null;
  return <section className='flex flex-col gap-3' aria-label='Credit packs'>
    {packs.length > 0 && <h2 className='text-lg font-medium'>Add credits</h2>}
    {returned && <div className='rafii-quiet rounded-xl p-4'><p className='text-sm'>Payment confirmation may still be processing. Only the verified balance below is available to spend.</p><Button variant='quiet' onClick={() => void usage.refetch()}>Refresh balance</Button></div>}
    {query.isError && <p role='status' className='text-muted-foreground text-sm'>Credit packs could not be loaded. <button className='underline' onClick={() => void query.refetch()}>Retry</button></p>}
    <div className='flex flex-wrap gap-3'>{packs.map(pack => <Button key={pack.id} variant='glass' className='min-h-14' onClick={() => {
      const current = eligibility.current;
      if (!mounted.current || !current.purchaseReady || !current.packs.some(row => row.id === pack.id)) return;
      setSelectedId(pack.id); setError(null);
    }}>{(pack.milliCredits / 1000).toLocaleString()} credits · {price(pack)}</Button>)}</div>
    <Dialog open={selected !== null} onOpenChange={open => { if (!open && !busy) setSelectedId(null); }}>
      <DialogContent><DialogHeader><DialogTitle>Confirm purchase</DialogTitle><DialogDescription>One-time credit purchase. You will review payment details on Stripe.</DialogDescription></DialogHeader>
        {selected && <p className='text-base'>{(selected.milliCredits / 1000).toLocaleString()} credits · {price(selected)}</p>}
        {error && <p role='alert' className='text-sm'>{error}</p>}
        <DialogFooter><Button variant='glass' disabled={busy} onClick={() => setSelectedId(null)}>Cancel</Button><Button variant='action' disabled={busy} onClick={() => void purchase()}>{busy ? 'Opening checkout…' : 'Continue to Stripe'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </section>;
}

export function CreditPacks() {
  const { workspaceId } = useWorkspaceApi();
  return <CreditPacksBody key={workspaceId} />;
}
