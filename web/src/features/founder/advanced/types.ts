import type { Envelope } from '../customers/kit/types';
import type { CheckSnapshot, EngineeringEvidenceRow } from './engineering-model';

/**
 * Payloads the Advanced → Engineering tab reads (CONTRACTS §8.D), as the server sends them: `GET /engineering` and
 * `GET /engineering/checks`, both `engineering.read`, both read-only (no dispatch, re-run or patch flags are ever true).
 */
export interface EngineeringEvidenceData {
  evidence?: EngineeringEvidenceRow[];
  stages?: string[];
  checksDispatchEnabled?: boolean;
  patchEnabled?: boolean;
}

export type EvidenceEnvelope = Envelope<EngineeringEvidenceData>;

export interface CheckSnapshotsData {
  snapshots?: CheckSnapshot[];
  readOnly?: boolean;
}

export type SnapshotsEnvelope = Envelope<CheckSnapshotsData>;
