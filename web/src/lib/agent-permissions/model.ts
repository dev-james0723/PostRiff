/**
 * Pure helpers for Settings → Rafii Agent → Permissions and the onboarding step (rafii-agent-authz/1, CF-2 §17). No React,
 * no network: what a choice sends, how a state reads in plain words, and whether the surfaces are mounted at all.
 *
 * The server decides everything. This module only builds requests the server validates (epoch, wording digest,
 * confirmation, fresh sign-in) and turns its answers into sentences.
 */
import type {
  AgentPermissionsPut,
  AgentPermissionsReceipt,
  AgentPermissionsView,
  Autonomy,
  CategoryId,
  EffectiveState,
  PermissionSource,
  PresetId,
  ScopeChanges,
  SpendConfirmation,
  StatePreset
} from '@/lib/api/agent-permissions-types';

export const CATEGORY_ORDER: CategoryId[] = ['read_analyze', 'navigate_interact', 'create_edit', 'manage_settings', 'manage_connected_services', 'execute_automations'];
export const SENSITIVE_CATEGORIES: CategoryId[] = ['manage_settings', 'manage_connected_services', 'execute_automations'];
export const PRESET_ORDER: PresetId[] = ['recommended', 'full', 'custom', 'none'];
export const SPEND_ORDER: SpendConfirmation[] = ['all', 'media', 'none'];
export type CategoryChoice = Autonomy | 'off';

/**
 * Whether this build shows the permission surfaces outside their own page (nav entry, onboarding step, reminder).
 * Off unless NEXT_PUBLIC_RAFII_AGENT_PERMISSIONS_UI is "1": with it off, the app makes no extra request and renders
 * nothing new. When on, the server still answers 404 for every workspace whose permissions mode is off.
 */
export function permissionsUiEnabled(value: string | undefined = process.env.NEXT_PUBLIC_RAFII_AGENT_PERMISSIONS_UI): boolean {
  return value === '1';
}

/** A fresh request id the server stores with the change (16–120 letters, digits or . _ : -). */
export function newRequestKey(random: () => string = () => crypto.randomUUID()): string {
  return `perm-${random().replace(/[^A-Za-z0-9]/g, '').slice(0, 40)}`.padEnd(21, '0');
}

export const STATE_LABEL: Record<EffectiveState, string> = {
  on: 'Does it, then shows you',
  asks: 'Asks first',
  off: 'Off',
  clipped: 'Limited by your role',
  unavailable: 'Nothing here yet'
};

export const CHOICE_LABEL: Record<CategoryChoice, string> = { assist: 'Does it', ask: 'Asks first', off: 'Off' };

export function presetTitle(view: Pick<AgentPermissionsView, 'copy'>, preset: StatePreset): string {
  return view.copy.presets[preset]?.title ?? preset;
}

/** The preset a person is on, as the page's radio group shows it ("legacy" reads as the current way Rafii works). */
export function currentPreset(view: Pick<AgentPermissionsView, 'state'>): StatePreset {
  return view.state.needsChoice ? 'legacy' : view.state.preset;
}

/** What a category is set to for this person (Custom edits start from this). */
export function categoryChoice(view: Pick<AgentPermissionsView, 'categories'>, id: CategoryId): CategoryChoice {
  return view.categories.find((c) => c.id === id)?.mode ?? 'off';
}

/** Whether a choice needs a fresh sign-in on the server (Full, or "Does it" on a sensitive area newly set). */
export function needsFreshSignIn(view: Pick<AgentPermissionsView, 'categories' | 'state'>, preset: PresetId, changes: ScopeChanges = {}): boolean {
  if (preset === 'full') return true;
  if (preset !== 'custom') return false;
  return SENSITIVE_CATEGORIES.some((id) => changes[`category:${id}`] === 'assist' && (view.state.needsChoice || categoryChoice(view, id) !== 'assist'));
}

/** The PUT body for a choice. The server re-checks every field; `confirmed` and `stepUp` are only ever set by a person's click. */
export function putBody(
  view: Pick<AgentPermissionsView, 'state' | 'consentVersion' | 'copyDigest'> & Partial<Pick<AgentPermissionsView, 'categories'>>,
  choice: { preset: PresetId; changes?: ScopeChanges; spend?: SpendConfirmation | null; confirmed?: boolean; stepUp?: boolean; source: PermissionSource },
  key: string
): AgentPermissionsPut {
  const body: AgentPermissionsPut = {
    preset: choice.preset,
    expectedEpoch: view.state.epoch,
    consentVersion: view.consentVersion,
    copyDigest: view.copyDigest,
    source: choice.source,
    idempotencyKey: key
  };
  if (choice.preset === 'custom') {
    const changes = Object.fromEntries(Object.entries(choice.changes ?? {}).filter(([scope]) => /^(category|domain|capability):/.test(scope)));
    if (Object.keys(changes).length) body.scopes = changes;
    if (choice.spend) body.spendConfirmation = choice.spend;
  }
  if (choice.confirmed) body.confirmed = true;
  if (choice.stepUp) body.stepUp = true;
  return body;
}

const KIND_LABEL: Record<AgentPermissionsReceipt['kind'], string> = {
  preset_applied: 'Chose',
  custom_changed: 'Changed',
  revoked: 'Turned off',
  revoked_all: 'Turned off all of Rafii’s access',
  autopilot_enabled: 'Turned on autopilot',
  autopilot_revoked: 'Turned off autopilot',
  autopilot_expired: 'Autopilot ended',
  membership_ended: 'Left the workspace',
  workspace_consent_narrowed: 'Workspace sharing narrowed'
};

/** One plain sentence for a history row. */
export function historyLine(view: Pick<AgentPermissionsView, 'copy'>, item: AgentPermissionsReceipt): string {
  const label = KIND_LABEL[item.kind] ?? 'Changed';
  if (item.kind === 'preset_applied' && item.presetAfter) return `${label} ${presetTitle(view, item.presetAfter)}`;
  if (item.kind === 'revoked' || item.kind === 'custom_changed') {
    const scopes = item.changes.filter((c) => c.scope !== 'spend').length;
    return scopes ? `${label} ${scopes} ${scopes === 1 ? 'setting' : 'settings'}` : label;
  }
  return label;
}

/** Plain explanations of what a narrowing could not take back (CF-2 §7.5). */
export function notRecallable(view: Pick<AgentPermissionsView, 'copy'>, item: Pick<AgentPermissionsReceipt, 'notRecallable'>): string[] {
  return item.notRecallable.map((key) => view.copy.notRecallable[key]).filter((line): line is string => Boolean(line));
}

/** The scope a category row's "Turn off" revokes. */
export function categoryScope(id: CategoryId): string {
  return `category:${id}`;
}
