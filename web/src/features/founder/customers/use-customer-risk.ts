'use client';

import { useQuery } from '@tanstack/react-query';
import { founderFetch } from '@/lib/founder/api';
import { useFounderScope } from './kit/api';
import type { Envelope } from './kit/types';
import { canReadRisk, riskPath, verifyRisk, type CustomerRiskData, type ServerRiskView } from './customer-risk';

/**
 * `GET /customers/risk?mode=&view=` (CONTRACTS §8.C, `customers.read`; Live also `workspaces.read`): one saved view's
 * workspaces with every flag each carries, evaluated on the server. Asked for only when the operator holds what the
 * route checks, so the page never earns a 403; a refusal is not retried. Keys follow `['founder', mode, environment, …]`.
 */
export function useCustomerRisk(view: ServerRiskView | null) {
  const scope = useFounderScope();
  const allowed = canReadRisk(scope.capabilities, scope.mode);
  const query = useQuery({
    queryKey: scope.key('customers-risk', view),
    enabled: scope.ready && allowed && view !== null,
    retry: false,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const result = await founderFetch<Envelope<CustomerRiskData>>(riskPath(scope.mode, view as ServerRiskView), { signal });
      return { ...result, data: verifyRisk(result?.data, scope.mode, view as ServerRiskView) };
    }
  });
  return { allowed, query };
}
