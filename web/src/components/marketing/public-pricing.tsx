'use client';

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { createApi } from '@/lib/api/client';
import type { PublicCatalog } from '@/lib/api/types';

const CatalogContext = createContext<PublicCatalog | null>(null);
export function PublicPricing({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<PublicCatalog | null>(null);
  useEffect(() => {
    let current = true;
    createApi(async () => null).plans().then(value => { if (current && value.pricing === 'v2') setCatalog(value); }).catch(() => {});
    return () => { current = false; };
  }, []);
  return <CatalogContext.Provider value={catalog}>{children}</CatalogContext.Provider>;
}
export const usePublicPricing = () => useContext(CatalogContext);
