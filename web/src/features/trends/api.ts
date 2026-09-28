import { z } from 'zod';
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
