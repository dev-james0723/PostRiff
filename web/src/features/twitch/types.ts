/** Server-owned Twitch capability and approval projections. No credentials belong in this model. */
import type { WorkspacePermission } from '@/types';
export type TwitchValue = string | number | boolean | null | TwitchValue[] | { [key: string]: TwitchValue };
export type TwitchPayload = Record<string, TwitchValue>;
export type TwitchVerification = 'verified' | 'unverified' | 'blocked';

export interface TwitchField {
  type: 'string' | 'integer' | 'number' | 'boolean' | 'array' | 'object';
  label?: string;
  description?: string;
  required?: boolean | string[];
  min?: number;
  max?: number;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  enum?: (string | number | boolean)[];
  format?: string;
  pattern?: string;
  items?: TwitchField;
  properties?: Record<string, TwitchField>;
}

export interface TwitchCapability {
  action: string;
  label: string;
  group: string;
  write: boolean;
  fields: Record<string, TwitchField>;
  requiredScopes: string[] | string[][];
  subjectPolicy?: string;
  eligibility?: string | string[];
  risk?: string;
  effects?: string | string[];
  status?: string;
  liveVerified?: boolean;
  verification?: TwitchVerification;
  availability?: { state: 'available' | 'blocked' | 'unverified'; reasons: string[] };
  schedulable?: boolean;
  canUpgrade?: boolean;
  workspacePermission?: WorkspacePermission;
  interactiveAvailable?: boolean;
}

export interface TwitchConnection {
  id: string;
  account: string;
  handle?: string;
  providerAccountId?: string;
  status: string;
  scopes?: string[];
  authorizationGeneration?: number | string;
}

export interface TwitchReadiness {
  available?: boolean;
  publicConnect: boolean;
  productionVerified: boolean;
  commercialApproved: boolean;
  reasons?: string[];
}

export interface TwitchAction {
  id: string;
  actorId: string;
  action: string;
  payload: TwitchPayload;
  payloadHash: string;
  state: string;
  executeAt?: string | number | null;
  scheduled?: boolean;
  expiresAt?: string | number | null;
  effects?: string | string[];
  risk?: string;
  generation: number | string;
  error?: string;
  result?: unknown;
  createdAt?: string | number;
  declarations?: { rightsConfirmed?: boolean; pastBroadcastsEnabled?: boolean };
}

export interface TwitchOverview {
  connection: TwitchConnection;
  capabilities: TwitchCapability[];
  actions: TwitchAction[];
  readiness: TwitchReadiness;
  limitations: string[];
  eventSub?: Record<string, unknown>;
}

export interface TwitchConnectionList {
  connections: TwitchConnection[];
  capabilities?: TwitchCapability[];
  readiness: TwitchReadiness;
  limitations: string[];
}

export interface TwitchReadResult {
  action?: string;
  data?: unknown;
  observedAt?: string | number;
  source?: string;
  [key: string]: unknown;
}

export interface TwitchPreviewInput {
  action: string;
  payload: TwitchPayload;
  executeAt?: string;
  rightsConfirmed?: true;
  pastBroadcastsEnabled?: true;
}

export interface TwitchSecretResult {
  action: string;
  secretResult: { data: unknown; [key: string]: unknown };
  stored: false;
  displayOnce: true;
}
