import type { ReactNode } from 'react';
import { useSyncExternalStore } from 'react';
import type { Usage } from '../src/lib/api/types';

declare global {
  interface Window {
    task8Scene: { usage: Usage; packs: { available: boolean; packs: { id: string; label: string; amountCents: number; currency: string; milliCredits: number }[] } };
    task8Reads?: { failUsage: () => void; recoverUsage: () => void; owner: (value: boolean) => void; failPacks: () => void; recoverPacks: () => void; calls: string[] };
  }
}
export const scene = window.task8Scene;
let query = { data: scene.usage, dataUpdatedAt: 1, errorUpdatedAt: 0, isError: false, isSuccess: true, isPending: false, error: null as Error | null, refetch: async () => ({ isError: false }) };
const listeners = new Set<() => void>();
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
const snapshot = () => query;
const publish = () => { for (const listener of listeners) listener(); };
const calls: string[] = [];
export const useUsage = () => useSyncExternalStore(subscribe, snapshot, snapshot);
export function registerPackReads(failPacks: () => void, recoverPacks: () => void) {
  window.task8Reads = {
    failUsage: () => { query = { ...query, isSuccess: false, isError: true, error: new Error('Synthetic failed Usage refresh'), errorUpdatedAt: query.errorUpdatedAt + 1 }; publish(); },
    recoverUsage: () => { query = { ...query, isSuccess: true, isError: false, error: null, dataUpdatedAt: query.dataUpdatedAt + 1 }; publish(); },
    owner: value => { scene.usage.membership = { ...scene.usage.membership, role: value ? 'owner' : 'viewer' }; query = { ...query }; publish(); },
    failPacks, recoverPacks, calls
  };
}
export const useChannels = () => ({ ...query, data: { channels: [], providers: [] } });
export const useMembers = () => ({ ...query, data: { members: [], membership: scene.usage.membership } });
export const useWorkspaceAccess = () => ({ ...scene.usage.membership, permissions: scene.usage.membership.role === 'owner' ? ['read', 'edit', 'owner'] : ['read'] });
export const checkAccess = (access: { permissions: string[] }, check: { permission: string }) => access.permissions.includes(check.permission);
export const useWorkspaceApi = () => ({ workspaceId: 'synthetic-billing', api: {
  creditPacks: async () => scene.packs,
  creditCheckout: async () => { calls.push('creditCheckout'); throw new Error('Synthetic scene refuses purchases'); },
  checkout: async () => { calls.push('checkout'); throw new Error('Synthetic scene refuses checkout'); },
  portal: async () => { throw new Error('Synthetic scene refuses portal'); }
} });
const params = new URLSearchParams();
const router = { replace() {} };
export const useSearchParams = () => params;
export const useRouter = () => router;
export const usePathname = () => '/app/account/billing';

// One shell mock serves PageContainer and Next Link; neither grants API or account authority.
export default function Shell({ children, pageTitle, infoContent: _info, ...props }: { children?: ReactNode; pageTitle?: string; infoContent?: unknown; href?: string }) {
  return pageTitle ? <main><h1>{pageTitle}</h1>{children}</main> : <a {...props}>{children}</a>;
}
