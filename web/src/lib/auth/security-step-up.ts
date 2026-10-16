'use client';

/**
 * RAPv2 decision 3: a workspace read refused by the high-risk `private_data` gate (403
 * `security_step_up_required`) opens one "Confirm it's you" screen instead of a generic error.
 *
 * Any query that fails that way reports here; AppGate shows the screen while a request is open and
 * clears it once the person has confirmed (every query is then fetched again with the fresh token).
 * The next step is the server's own (`complete_mfa`, `enroll_mfa`, `sign_in`); nothing is guessed.
 */

import { useEffect, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';

export type StepUpNext = 'complete_mfa' | 'enroll_mfa' | 'sign_in';
export interface StepUpRequest {
  nextAction: StepUpNext;
}

let current: StepUpRequest | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isSecurityStepUp(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403 && error.code === 'security_step_up_required';
}

/** Open the screen for this error; false (and nothing changes) for any other error. */
export function reportStepUp(error: unknown): boolean {
  if (!isSecurityStepUp(error)) return false;
  const nextAction: StepUpNext = error.nextAction === 'enroll_mfa' ? 'enroll_mfa' : error.nextAction === 'sign_in' ? 'sign_in' : 'complete_mfa';
  if (current?.nextAction !== nextAction) {
    current = { nextAction };
    emit();
  }
  return true;
}

export function clearStepUp() {
  if (current) {
    current = null;
    emit();
  }
}

/** The open request, or null. Also listens to this session's queries for refused reads. */
export function useStepUp(): StepUpRequest | null {
  const client = useQueryClient();
  useEffect(
    () =>
      client.getQueryCache().subscribe((event) => {
        if (event.type === 'updated' && event.action.type === 'error') reportStepUp(event.action.error);
      }),
    [client]
  );
  return useSyncExternalStore(subscribe, () => current, () => null);
}
