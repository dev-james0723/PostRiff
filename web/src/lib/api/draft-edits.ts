/**
 * Typed browser client for one-click draft edits (a tone change or a wording polish). One POST asks the writer for
 * a candidate; the candidate waits beside the draft (`proposedUpdate`) and the draft's own text is never replaced
 * until the person accepts it (`accept_update`). Same guard header, bearer session and error shape as `./client`;
 * kept separate so the shared client stays untouched. While the server has the feature off the route answers 404
 * `feature_disabled` and the writer catalogue carries no `draftEdits` entry, so the editor never offers it.
 */
import { ApiError, APP_GUARD_HEADER, type TokenSource } from './client';
import type { Snapshot, SnapshotVariant } from './types';

type ProposedUpdate = NonNullable<SnapshotVariant['proposedUpdate']>;

/** How a pending candidate was made, as the draft records it. */
export type DraftEditRecord = NonNullable<ProposedUpdate['edit']>;
/** The deterministic check of a candidate against its base: reminders, never a block. */
export type DraftEditFidelity = NonNullable<ProposedUpdate['fidelity']>;
export type DraftEditViolation = DraftEditFidelity['violations'][number];

export type DraftEditMode = 'tone' | 'polish';
export type DraftEditTone = 'warm' | 'professional' | 'direct' | 'playful' | 'custom';
export type DraftVoiceMode = 'neutral' | 'personalized';

/** Code-point offsets into the stored draft text (never UTF-16 offsets from a textarea). */
export interface DraftEditSelection {
  start: number;
  end: number;
}

export interface DraftEditRequest {
  /** The draft revision the person is looking at; a newer stored revision refuses the request (409). */
  variantRevision: number;
  mode: DraftEditMode;
  /** Required for a tone change. */
  tone?: DraftEditTone;
  /** The person's own tone, at most 200 characters; required when `tone` is `custom`. */
  instruction?: string;
  depth?: 'light' | 'standard' | 'deep';
  /** Absent means the whole draft. */
  selection?: DraftEditSelection;
  /** `original`: start from the wording before the last accepted edit when the draft is unchanged since. */
  base?: 'original' | 'current';
  voiceMode?: DraftVoiceMode;
  model?: string;
  /** Sent again unchanged after a lost answer, so one click never buys two runs. */
  idempotencyKey: string;
  /** The workspace revision, as for every action. */
  expectedRevision: number;
}

export interface DraftEditResult {
  status: 'candidate' | 'no_change' | 'failed';
  runId?: string | null;
  /** The draft that holds the result: a new draft's id when the edited one was already scheduled. */
  variantId: string;
  /** Which text the edit started from. */
  base?: { kind: 'original' | 'current'; revision: number } | null;
  fidelity?: DraftEditFidelity | null;
  voice?: { requested: DraftVoiceMode; effective: DraftVoiceMode } | null;
  usage?: { durationMs: number; costUsdMicro?: number } | null;
  /** Why the run failed, when the server says. */
  message?: string | null;
}

export interface DraftEditResponse {
  /** The workspace after the run: a candidate is on the draft's `proposedUpdate`. */
  snapshot: Snapshot;
  edit: DraftEditResult;
}

/** As long as a drafting request may take; past this the answer counts as lost and the same key is sent again. */
const EDIT_TIMEOUT_MS = 150_000;

/** 404 `feature_disabled`: the server has one-click edits off. The editor hides the control instead of showing an error. */
export function draftEditsDisabled(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && error.code === 'feature_disabled';
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = 'The workspace could not complete that request.';
    let code: string | undefined;
    try {
      const body = (await res.json()) as { error?: unknown; code?: unknown };
      if (typeof body?.error === 'string' && body.error) message = body.error;
      if (typeof body?.code === 'string') code = body.code;
    } catch {
      /* keep the generic message */
    }
    const requestId = res.headers.get('X-Request-ID') ?? undefined;
    throw new ApiError(message, res.status, code, requestId && /^[a-f0-9]{32}$/.test(requestId) ? requestId : undefined);
  }
  return res.json() as Promise<T>;
}

export function createDraftEditsApi(getToken: TokenSource) {
  async function headers(): Promise<Record<string, string>> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { 'Content-Type': 'application/json', ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` };
  }

  return {
    /** Ask for a tone or polish candidate. Resolves when the writer has answered; nothing is replaced. */
    request: async (workspaceId: string, variantId: string, body: DraftEditRequest) =>
      parse<DraftEditResponse>(
        await fetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/drafts/${encodeURIComponent(variantId)}/edits`, {
          method: 'POST',
          headers: await headers(),
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(EDIT_TIMEOUT_MS)
        })
      )
  };
}

export type DraftEditsApi = ReturnType<typeof createDraftEditsApi>;
