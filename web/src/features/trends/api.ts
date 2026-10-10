import { z } from 'zod';
import { publicSourceSchema } from './public-source-types';
import { ApiError, APP_GUARD_HEADER, type TokenSource } from '@/lib/api/client';
import {
  envelopeSchema,
  angleGenerationSchema,
  trendMetricChoiceInputSchema,
  trendMetricChoiceResponseSchema,
  type TrendMetricChoiceInput,
  trendSchema,
  receiptSchema,
  methodologySchema,
  calibrationSchema,
  languagePatternSchema,
  genomeSchema,
  propagationSchema,
  saturationSchema,
  opportunitiesResponseSchema,
  whitespaceResponseSchema,
  forecastResponseSchema,
  exposureInputSchema,
  exposureSchema,
  dismissOpportunityInputSchema,
  dismissedOpportunitySchema,
  type ExposureInput,
  type DismissOpportunityInput,
  watchSchema,
  watchInputSchema,
  labInputSchema,
  labRunSchema,
  acceptOpportunitySchema,
  acceptedOpportunitySchema,
  type AcceptOpportunityInput,
  type LabInput,
  type WatchInput
} from '@/lib/coworker/trend-types';

export type TrendFilters = {
  view: string;
  query?: string;
  platform?: string;
  language?: string;
  region?: string;
  niche?: string;
  since?: string;
  cursor?: string;
};

const discoveryProvider = z.enum(['instagram', 'threads', 'facebook']);
const discoveryText = (max: number) => z.string().min(1).max(max).refine(
  (value) => value.trim().length > 0 && Array.from(value).every((character) => {
    const code = character.charCodeAt(0);
    return code >= 32 && code !== 127;
  })
);
const discoverySelections = {
  instagram: z.object({ hashtag: discoveryText(80) }).strict(),
  threads: z.object({ query: discoveryText(160), search_type: z.enum(['TOP', 'RECENT']) }).strict(),
  facebook: z.object({ reviewed_page_id: z.string().regex(/^[0-9]{1,40}$/) }).strict()
};
const discoveryKey = z.string().min(1).max(200);
export const discoveryRequestInputSchema = z.discriminatedUnion('provider', [
  z.object({ provider: z.literal('instagram'), selection: discoverySelections.instagram, idempotency_key: discoveryKey }).strict(),
  z.object({ provider: z.literal('threads'), selection: discoverySelections.threads, idempotency_key: discoveryKey }).strict(),
  z.object({ provider: z.literal('facebook'), selection: discoverySelections.facebook, idempotency_key: discoveryKey }).strict()
]);
export type DiscoveryRequestInput = z.infer<typeof discoveryRequestInputSchema>;

const discoveryTime = z.string().datetime({ offset: true }).nullable();
export const discoveryReceiptSchema = z.object({
  request_id: z.string().uuid(),
  provider: discoveryProvider,
  selection: z.union([discoverySelections.instagram, discoverySelections.threads, discoverySelections.facebook]).nullable(),
  status: z.enum(['queued', 'running', 'completed', 'failed', 'unavailable']),
  sample_size: z.number().int().min(0).max(1000).nullable(),
  earliest_source_at: discoveryTime,
  latest_source_at: discoveryTime,
  retrieved_at: discoveryTime,
  created_at: z.string().datetime({ offset: true }),
  expires_at: z.string().datetime({ offset: true }),
  completeness: z.enum(['partial', 'gap', 'unknown']),
  coverage: z.string().min(1).max(2000)
}).strict().superRefine((receipt, context) => {
  const reject = (path: string, message: string) => context.addIssue({ code: 'custom', path: [path], message });
  if (receipt.selection === null) {
    if (receipt.status !== 'unavailable') reject('selection', 'A current request must identify its selection.');
  } else if (!discoverySelections[receipt.provider].safeParse(receipt.selection).success) {
    reject('selection', 'The selection must match its source.');
  }
  if (receipt.status !== 'completed') {
    for (const key of ['sample_size', 'earliest_source_at', 'latest_source_at', 'retrieved_at'] as const)
      if (receipt[key] !== null) reject(key, 'A pending or unavailable sample has no verified measurement.');
    if (receipt.completeness !== 'unknown') reject('completeness', 'Sample coverage is unknown before completion.');
  } else if (receipt.sample_size === null || receipt.retrieved_at === null) {
    reject('sample_size', 'Completion requires a recorded sample and retrieval time.');
  }
});
export type DiscoveryRequestReceipt = z.infer<typeof discoveryReceiptSchema>;
const discoveryOptionsSchema = z.object({
  requests: z.array(discoveryReceiptSchema).max(20),
  options: z.array(z.object({
    provider: discoveryProvider,
    enabled: z.boolean(),
    reviewed_page_ids: z.array(z.string().regex(/^[0-9]{1,40}$/)).max(100)
  }).strict()).length(3)
}).strict().refine((value) => new Set(value.options.map((item) => item.provider)).size === 3);

export function createTrendApi(getToken: TokenSource) {
  async function request<T>(
    workspace: string,
    path: string,
    schema: z.ZodType<T>,
    signal?: AbortSignal,
    method = 'GET',
    body?: unknown
  ): Promise<T> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401, 'unauthenticated');
    const res = await fetch(
      `/api/workspaces/${encodeURIComponent(workspace)}/coworker/trends${path}`,
      {
        method,
        cache: 'no-store',
        signal,
        headers: {
          ...APP_GUARD_HEADER,
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
      }
    );
    if (!res.ok) {
      let code: string | undefined;
      try {
        const error: unknown = await res.json();
        if (error && typeof error === 'object' && 'code' in error && typeof error.code === 'string')
          code = error.code;
      } catch {
        /* safe status below */
      }
      throw new ApiError('The trend service could not complete this request.', res.status, code);
    }
    const result = schema.safeParse(await res.json());
    if (!result.success)
      throw new ApiError(
        'The trend response could not be verified. Try again after the service is updated.',
        502,
        'invalid_response'
      );
    return result.data;
  }
  const seg = encodeURIComponent;
  return {
    publicSources: (w: string, signal?: AbortSignal) =>
      request(w, '/public-sources', envelopeSchema(z.array(publicSourceSchema)), signal),
    discoveryRequests: (w: string, signal?: AbortSignal) =>
      request(w, '/public-sources/discovery-requests', envelopeSchema(discoveryOptionsSchema), signal),
    submitDiscoveryRequest: (w: string, input: DiscoveryRequestInput) =>
      request(w, '/public-sources/discovery-requests', envelopeSchema(discoveryReceiptSchema), undefined,
        'POST', discoveryRequestInputSchema.parse(input)),
    revokePublicSource: (w: string, id: string) =>
      request(w, `/public-sources/${seg(id)}`, envelopeSchema(z.object({ authorization_id: z.string().uuid(), status: z.literal('REVOKED') }).strict()), undefined, 'DELETE'),
    generateAngles: (w: string, id: string, revision: number, key: string) =>
      request(w, `/opportunities/${seg(id)}/angles`, envelopeSchema(angleGenerationSchema), undefined, 'POST', { revision, idempotency_key: key }),
    generationStatus: (w: string, job: string, signal?: AbortSignal) =>
      request(w, `/generation-jobs/${seg(job)}`, envelopeSchema(angleGenerationSchema), signal),
    recordMetricChoice: (w: string, input: TrendMetricChoiceInput) =>
      request(w, '/learning/metric-choices', trendMetricChoiceResponseSchema, undefined, 'POST', trendMetricChoiceInputSchema.parse(input)),
    list: (w: string, filters: TrendFilters, signal?: AbortSignal) => {
      const params = new URLSearchParams({ limit: '20' });
      for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
      return request(w, `?${params}`, envelopeSchema(z.array(trendSchema)), signal);
    },
    detail: (w: string, id: string, signal?: AbortSignal) =>
      request(w, `/${seg(id)}`, envelopeSchema(trendSchema), signal),
    receipt: (w: string, id: string, receipt: string, signal?: AbortSignal) =>
      request(w, `/${seg(id)}/receipts/${seg(receipt)}`, envelopeSchema(receiptSchema), signal),
    methodology: (w: string, signal?: AbortSignal) =>
      request(w, '/methodology', envelopeSchema(methodologySchema), signal),
    calibration: (w: string, signal?: AbortSignal) =>
      request(w, '/calibration', envelopeSchema(calibrationSchema), signal),
    languages: (w: string, signal?: AbortSignal) =>
      request(w, '/language-patterns', envelopeSchema(z.array(languagePatternSchema)), signal),
    opportunities: (w: string, signal?: AbortSignal) =>
      request(w, '/opportunities', opportunitiesResponseSchema, signal),
    whitespace: (w: string, signal?: AbortSignal) =>
      request(w, '/opportunities/whitespace', whitespaceResponseSchema, signal),
    forecast: (w: string, id: string, signal?: AbortSignal) =>
      request(w, `/${seg(id)}/forecast`, forecastResponseSchema, signal),
    opportunityPool: (w: string, pool: 'home' | 'weekly', signal?: AbortSignal) =>
      request(w, `/opportunities?pool=${pool}&limit=3`, opportunitiesResponseSchema, signal),
    genome: (w: string, id: string, signal?: AbortSignal) =>
      request(w, `/${seg(id)}/genome`, envelopeSchema(genomeSchema), signal),
    propagation: (w: string, id: string, signal?: AbortSignal) =>
      request(w, `/${seg(id)}/propagation`, envelopeSchema(propagationSchema), signal),
    saturation: (w: string, id: string, signal?: AbortSignal) =>
      request(w, `/${seg(id)}/saturation`, envelopeSchema(saturationSchema), signal),
    watches: (w: string, signal?: AbortSignal) =>
      request(w, '/watches', envelopeSchema(z.array(watchSchema)), signal),
    watch: (w: string, body: WatchInput) =>
      request(
        w,
        '/watches',
        envelopeSchema(watchSchema),
        undefined,
        'POST',
        watchInputSchema.parse(body)
      ),
    disableWatch: (w: string, id: string, revision: number, key: string) =>
      request(
        w,
        `/watches/${seg(id)}?expected_revision=${revision}&idempotency_key=${seg(key)}`,
        envelopeSchema(watchSchema),
        undefined,
        'DELETE'
      ),
    recordExposure: (w: string, body: ExposureInput, signal?: AbortSignal) =>
      request(
        w,
        '/exposures',
        envelopeSchema(exposureSchema),
        signal,
        'POST',
        exposureInputSchema.parse(body)
      ),
    dismissOpportunity: (w: string, id: string, body: DismissOpportunityInput) =>
      request(
        w,
        `/opportunities/${seg(id)}/dismiss`,
        envelopeSchema(dismissedOpportunitySchema),
        undefined,
        'POST',
        dismissOpportunityInputSchema.parse(body)
      ),
    acceptOpportunity: (w: string, id: string, body: AcceptOpportunityInput) =>
      request(
        w,
        `/opportunities/${seg(id)}/accept`,
        envelopeSchema(acceptedOpportunitySchema),
        undefined,
        'POST',
        acceptOpportunitySchema.parse(body)
      ),
    runLab: (w: string, body: LabInput) =>
      request(
        w,
        '/opportunity-lab/runs',
        envelopeSchema(labRunSchema),
        undefined,
        'POST',
        labInputSchema.parse(body)
      ),
    labRun: (w: string, id: string, signal?: AbortSignal) =>
      request(w, `/opportunity-lab/runs/${seg(id)}`, envelopeSchema(labRunSchema), signal)
  };
}
export type TrendApi = ReturnType<typeof createTrendApi>;
