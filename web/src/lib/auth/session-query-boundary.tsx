'use client';
import { useEffect, useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { WorkspaceBootstrap } from '@/lib/workspace/bootstrap';
import { makeQueryClient } from '@/lib/query-client';

/** A different identity remounts workspace state and receives an empty, separate cache. */
export function SessionQueryBoundary({ identity, children, initial }: { identity: string; children: ReactNode; initial?: WorkspaceBootstrap | null }) {
  return <IdentityQueries key={identity} initial={initial?.me.userId === identity ? initial : null}>{children}</IdentityQueries>;
}
function IdentityQueries({ children, initial }: { children: ReactNode; initial?: WorkspaceBootstrap | null }) {
  const [client] = useState(() => { const client = makeQueryClient(); if (initial) client.setQueryData(['me'], initial.me, { updatedAt: initial.fetchedAt }); return client; });
  useEffect(() => () => { void client.cancelQueries(); client.clear(); }, [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
