export type RecipeSettings = {
  templateId: 'weekly_performance' | 'library_review'; name: string; trigger: 'weekly' | 'new_asset';
  planningDay: number; planningHour: number; timeZone: string; connectionId: string | null; collectionId: string | null;
  expiresAt: number; actionsPerDay: number; actionsTotal: number; usdMicroPerDay: number;
  notificationPolicy: 'none' | 'failures_and_approvals' | 'all';
};
export type Recipe = { id: string; version: number; status: string; config: RecipeSettings; policyId: string | null; policyCurrent: boolean; usedOperations: number | null; consecutiveFailures: number; nextAttemptAt: number | null };
export type RecipeTemplate = { id: RecipeSettings['templateId']; version: number; name: string; description: string; triggerNote?: string; triggers: RecipeSettings['trigger'][]; steps: string[]; preconditions: string[]; domains: string[]; approvalPolicy: string };
export type RecipeRun = { id: string; recipeId: string; taskId: string; state: string; reasonCode: string | null; hasReport: boolean; createdAt: number };
export type RecipeList = { available: boolean; permissionToken: string; explicitPermissions: boolean; templates: RecipeTemplate[]; recipes: Recipe[]; runs: RecipeRun[]; connections: { id: string; name: string }[]; collections: { id: string; name: string }[] };
export type RecipeReport = { id: string; taskId: string; inputs: Record<string, unknown>; report: null | { kind: string; state: string; asOf: string | number; truncated: boolean; note?: string; warnings?: string[]; coverage?: { known: number | null; total: number | null; note: string }; items?: { assetId: string; title: string | null; tags: string[]; href: string; kind: string }[]; data?: { posts: { jobId: string; platform: string; publishedAt: string; metrics: Record<string, { value: number | null; availability: string; unit: string }> }[] } } };
