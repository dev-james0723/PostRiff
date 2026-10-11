/**
 * Shapes of /api/workspaces/{id}/agent/permissions (rafii-agent-authz/1, CF-2 §16). The server is the authority: these
 * types describe what it returns; nothing the browser sends can widen a permission without the server's checks.
 */

export type PermissionsMode = 'shadow' | 'enforce';
export type PresetId = 'recommended' | 'full' | 'custom' | 'none';
export type StatePreset = PresetId | 'legacy';
export type Autonomy = 'ask' | 'assist';
export type CategoryId = 'read_analyze' | 'navigate_interact' | 'create_edit' | 'manage_settings' | 'manage_connected_services' | 'execute_automations';
export type SpendConfirmation = 'none' | 'media' | 'all';
export type EffectiveState = 'on' | 'asks' | 'off' | 'clipped' | 'unavailable';
export type DecisionOutcome = 'allow' | 'confirm' | 'approve' | 'step_up' | 'deny';
export type Confirmation = 'none' | 'native' | 'proposal' | 'approval_step_up';
export type PermissionSource = 'onboarding' | 'settings' | 'reminder' | 'chat_link';

export interface AgentPermissionsState {
  source: 'legacy' | 'explicit';
  preset: StatePreset;
  baseline: 'legacy_v1' | null;
  epoch: number;
  spendConfirmation: SpendConfirmation;
  decidedAt: number | null;
  consentVersion: string | null;
  /** No choice on record (never chose, chose "Not now", or re-invited): Rafii works as it always has. */
  needsChoice: boolean;
  ended: boolean;
  newSinceDecision: number;
  token: string;
}

export interface CategoryView {
  id: CategoryId;
  mode: Autonomy | null;
  effective: { state: EffectiveState; reasons: { code: string }[] };
  capabilityCount: number;
}

export interface CapabilityView {
  capabilityId: string;
  category: CategoryId;
  risk: 'R0' | 'R1' | 'R2' | 'R3';
  cost: 'free' | 'text_credits' | 'media_credits';
  dataGrants: string[] | null;
  requirement: string;
  baseline: boolean;
  label: string;
  effective: { outcome: DecisionOutcome; reason: string; required: Confirmation; detail?: string };
}

export interface PresetView {
  id: Exclude<PresetId, 'custom'>;
  version: number;
  scopes: Record<string, Autonomy | true>;
  spendConfirmation: SpendConfirmation;
  stepUp: boolean;
}

export interface PermissionCopy {
  consentVersion: string;
  intro?: string;
  modes: Record<'ask' | 'assist' | 'off', string>;
  categories: Record<CategoryId, { title: string; summary: string }>;
  domains: Record<string, string>;
  presets: Record<StatePreset, { title: string; summary: string }>;
  spend: Record<SpendConfirmation, string>;
  revoke: { title: string; summary: string; confirm: string };
  notRecallable: Record<string, string>;
  reminder: { title: string; summary: string; save: string; notNow: string };
  shadow: string;
  enforce: string;
}

export interface AgentPermissionsReceipt {
  id: string;
  at: number;
  kind: 'preset_applied' | 'custom_changed' | 'revoked' | 'revoked_all' | 'autopilot_enabled' | 'autopilot_revoked' | 'autopilot_expired' | 'membership_ended' | 'workspace_consent_narrowed';
  source: PermissionSource | 'system';
  epochBefore: number;
  epochAfter: number;
  presetBefore: StatePreset | null;
  presetAfter: StatePreset | null;
  changes: { scope: string; from: unknown; to: unknown }[];
  widened: boolean;
  invalidated: Record<string, number>;
  notRecallable: string[];
  stepUp: boolean;
  actorIsYou?: boolean;
}

export interface AgentPermissionsView {
  available: true;
  mode: PermissionsMode;
  state: AgentPermissionsState;
  reminder: { due: boolean; nextAt: number | null };
  role: { role: string } & Record<string, unknown>;
  categories: CategoryView[];
  domains: { id: string; granted: boolean; clippedBy: string | null }[];
  capabilities: CapabilityView[];
  presets: PresetView[];
  autopilot: { available: boolean; policies: { id: string; capabilityIds: string[]; expiresAt: number }[] };
  pendingApprovals: number;
  consentVersion: string;
  copyDigest: string;
  catalogueDigest: string;
  copy: PermissionCopy;
  receipt?: AgentPermissionsReceipt;
}

/** Custom scopes are changes on top of the current choice (or Recommended): `null` removes a choice. */
export type ScopeChanges = Record<string, Autonomy | 'off' | boolean | null>;

export interface AgentPermissionsPut {
  preset: PresetId;
  scopes?: ScopeChanges;
  spendConfirmation?: SpendConfirmation;
  expectedEpoch: number;
  consentVersion: string;
  copyDigest: string;
  confirmed?: boolean;
  /** The person picked Full or Assist on a sensitive area and is ready to sign in again if asked. */
  stepUp?: boolean;
  source: PermissionSource;
  idempotencyKey: string;
}

export interface AgentPermissionHistory {
  items: AgentPermissionsReceipt[];
  next: string | null;
}

export interface AgentPermissionMembers {
  members: { userId: string; displayName: string; role: string; source: 'legacy' | 'explicit'; preset: StatePreset; epoch: number; decidedAt: number | null; spendConfirmation: SpendConfirmation | null }[];
}
