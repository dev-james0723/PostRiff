import type { Envelope } from '../customers/kit/types';
import type { OpsIncident } from './ops-model';

/**
 * Payloads the Operations, Support and data-health pages read beyond the kit's types (CONTRACTS §8.D). Values are
 * shown as the server sent them.
 */

/** `GET /incidents/{id}?mode=` (`founder_metrics_ops.incident_detail`): Live `public_incident` with its timeline, or the Demo payload. */
export interface IncidentDetailData {
  mode?: string;
  incident: OpsIncident & { version?: number | null; evidence?: Record<string, unknown> | null };
}

export type IncidentDetail = Envelope<IncidentDetailData>;
