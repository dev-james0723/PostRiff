'use client';

import { createContext, useCallback, useContext, useMemo, type ReactNode } from 'react';
import type { FounderAskRequest, FounderSection, FounderSectionProps } from '../../sections';

/**
 * How a page hands a question to the founder Rafii panel (CONTRACTS §6, PRD §6.2). The shell passes `onAsk` into
 * the section; without it the request goes out as a `rafii:founder-ask` CustomEvent on `window` so the panel store
 * can subscribe. The request carries opaque ids and plain view values only, never a record body.
 */
export const FOUNDER_ASK_EVENT = 'rafii:founder-ask';

export type AskFn = (request: Omit<FounderAskRequest, 'section'> & { section?: FounderSection }) => void;

const AskContext = createContext<AskFn>(() => undefined);

export function dispatchAsk(request: FounderAskRequest, onAsk?: FounderSectionProps['onAsk']) {
  if (onAsk) {
    onAsk(request);
    return;
  }
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<FounderAskRequest>(FOUNDER_ASK_EVENT, { detail: request }));
}

export function FounderAskProvider({ section, onAsk, children }: { section: FounderSection; onAsk?: FounderSectionProps['onAsk']; children: ReactNode }) {
  const ask = useCallback<AskFn>((request) => dispatchAsk({ ...request, section: request.section ?? section }, onAsk), [section, onAsk]);
  const value = useMemo(() => ask, [ask]);
  return <AskContext.Provider value={value}>{children}</AskContext.Provider>;
}

export function useAsk(): AskFn {
  return useContext(AskContext);
}
