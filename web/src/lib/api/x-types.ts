export type XFieldSpec = { kind: string; required?: boolean; maximum?: number | null; choices?: string[] };
export type XCapability = {
  id: string; title: string; method: string | null; path: string | null; scopes: string[];
  input_path_params: string[]; actor_path_params?: string[]; body_schema: Record<string, XFieldSpec>;
  query_schema: Record<string, XFieldSpec>; mutates: boolean; collection?: boolean; notes?: string;
};
export type XDecision = {
  status: 'direct' | 'unavailable'; reason_code: string; reason: string;
  capability: XCapability; ready_for_preview: boolean;
};
export type XActionInput = {
  operation: string; path: Record<string, string>; body: Record<string, unknown>;
  query: Record<string, unknown>; maxBillableResources: number; requestKey?: string; scheduleAt?: number;
};
export type XOperation = {
  id: string; connectionId: string; accountId: string; operation: string;
  request: Omit<XActionInput, 'requestKey'> & { normalizedFingerprint: string; estimatedCostMicros: number | null; estimatedMaxCostMicros: number | null; maximumApiRequests: number };
  digest: string; state: string; createdAt: number; expiresAt?: number | null; scheduledAt?: number | null;
  receipts: unknown[]; reason?: string | null; reasonCode?: string | null; cancelRequested: boolean;
};
export type XOverview = {
  connectionId: string; accountId: string; capabilities: XDecision[]; operations: XOperation[];
  costReady: boolean; journalReady: boolean; directOnly: boolean;
  mediaAssets?: { id: string; mime: string; bytes: number }[];
  uploadedMedia?: { id: string; mediaKey: string; mime: string; expiresAt: number; altText: string }[];
};
