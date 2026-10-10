import { z } from 'zod';

export const publicSourceSchema = z.object({
  provider: z.enum(['instagram', 'threads', 'facebook']),
  operation: z.enum(['hashtag_discovery', 'keyword_search', 'page_public_posts']),
  label: z.string(),
  status: z.enum(['APP_REVIEW_REQUIRED', 'AUTHORIZATION_REQUIRED', 'UNVERIFIED', 'LIVE', 'STALE', 'PAUSED', 'REVOKED']),
  authorization_id: z.string().uuid().nullable(),
  latest_successful_read: z.string().datetime().nullable(),
  expires_at: z.string().datetime().nullable(),
  dispatch_enabled: z.boolean(),
  coverage: z.string(),
  semantic_evaluation: z.string()
}).strict();
