/** Server-owned evidence projection shared by metrics and source/FactPack views. */
import { z } from 'zod';
const text = z.string().min(1).max(1000).nullable();
const instant = z.string().datetime({ offset: true }).nullable();
export const evidenceEnvelopeSchema = z.object({
  schema: z.literal('rafii.evidence.v1'),
  workspaceId: z.string().min(1).max(160),
  classification: z.enum(['observed', 'inferred', 'recommended']),
  availability: z.string().min(1).max(40),
  source: z.object({ platform: text, provider: text, entityType: text, entityId: text, connectionId: text, document: text, href: text }),
  collectionPeriod: z.object({ start: instant, end: instant, basis: z.enum(['provider_reading', 'source_retrieval']) }),
  lastSuccessfulSync: instant,
  definition: z.object({ name: text, version: text, description: text, unit: text }),
  uncertainty: z.array(z.string().max(400)).max(12),
});
export type EvidenceEnvelope = z.infer<typeof evidenceEnvelopeSchema>;
export function scopedEvidence(value: unknown, workspaceId: string | null | undefined): EvidenceEnvelope | null {
  const parsed = evidenceEnvelopeSchema.safeParse(value);
  return parsed.success && workspaceId && parsed.data.workspaceId === workspaceId ? parsed.data : null;
}
