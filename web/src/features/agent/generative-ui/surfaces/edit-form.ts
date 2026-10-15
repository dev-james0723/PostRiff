/**
 * The "Change this view" form's rules (lane F), pure so they are tested without a DOM: who may change the view and when,
 * what a suggestion tap does to the field, which selection the request carries, and how a refusal reads.
 *
 * A suggestion tap only FILLS the field (no request, no cost); "Update view" stays the one billed step. The selection the
 * chips count and the request sends is the same object: the person's live `@selection` in this tab.
 */
import type { JsonValue } from '@/lib/agent-runtime/ui-contracts';
import type { GenUiMessageKey } from '../core/locale';
import type { ArtifactViewState } from '../state/artifact-machine';
import { SELECTION_KEY } from '../state/persisted-state';
import type { SuggestionRule } from './edit-suggestions';

/** The renderer shows an older revision than the latest: the person is choosing, or kept the earlier view. */
export type OlderRevision = 'choosing' | 'kept' | null;

export interface EditAccessInput {
  access: { canEdit?: boolean; isActor?: boolean } | null | undefined;
  /** The view on screen is an accepted generated revision. */
  accepted: boolean;
  /** Something is being built or updated right now. */
  live: boolean;
  older: OlderRevision;
}

/**
 * Only the person who asked can change a view (the server refuses anyone else with 403), and never while it is being
 * updated. While the renderer shows an older revision than the latest, changing is off and a note says why.
 */
export function editAccess({ access, accepted, live, older }: EditAccessInput): { canEdit: boolean; note: GenUiMessageKey | null } {
  const allowed = Boolean(access?.canEdit && access.isActor && accepted && !live);
  if (!allowed) return { canEdit: false, note: null };
  if (older === 'choosing') return { canEdit: false, note: 'newerVersion' };
  if (older === 'kept') return { canEdit: false, note: 'keptEarlier' };
  return { canEdit: true, note: null };
}

/** The live selection (this tab's, saved or not); the server snapshot's only when there is no controller yet. */
export function liveSelection(local: JsonValue | null | undefined, snapshot: Record<string, JsonValue> | null | undefined): Record<string, JsonValue> | null {
  const value = local ?? snapshot?.[SELECTION_KEY] ?? null;
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, JsonValue>) : null;
}

/**
 * How an HTTP refusal of the edit request reads (null: nothing to say, e.g. a second press while the first is in flight).
 * Budget and paused-AI refusals normally arrive on HTTP 200 as the stream's `ui.failed` (see `editRefusalOf`); their HTTP
 * codes are mapped here too, defensively. "Only the person who asked" is said only when the client knows this person did
 * not ask (`access.isActor === false`); any other 403 reads role-neutral.
 */
export function editProblemOf(result: { code: string | null; status: number }, access?: { isActor?: boolean } | null): GenUiMessageKey | null {
  const { code, status } = result;
  if (code === 'ui_in_flight') return null;
  if (code === 'ui_busy') return 'editBusy';
  if (code === 'ui_budget_unknown') return 'editBudgetUnknown';
  if (code === 'ui_budget' || status === 402) return 'editBudget';
  if (code === 'ui_ai_paused') return 'editPaused';
  if (code === 'ui_forbidden' || status === 403) return access?.isActor === false ? 'editNotActor' : 'editForbidden';
  if (status === 409) return 'editConflict';
  if (status === 404) return 'editUnavailable';
  return 'editFailed';
}

/**
 * The server refuses an edit's reservation after admission, before any model call, and says so as the stream's `ui.failed`
 * on HTTP 200 (`ui_metering.reason_for`: `budget` covers no allowance and an unsettled answer cost; `disabled` is the
 * operator's pause of paid AI; `price_unknown` means no verified price for the presenter, so paid updates are off).
 */
const EDIT_REFUSALS: Readonly<Record<string, GenUiMessageKey>> = { budget: 'editBudget', disabled: 'editPaused', price_unknown: 'editPaused' };

/**
 * What the status line says after an edit attempt this tab followed was refused (null: no refusal to report). Only on an
 * accepted view (an edit always has one; a first view that fails keeps its native fallback copy), and only from the
 * notice of the `ui.failed` this session received, so a reload never re-reports an old refusal.
 */
export function editRefusalOf(state: Pick<ArtifactViewState, 'view' | 'notice'>): GenUiMessageKey | null {
  const view = state.view;
  if (!view || view.display.mode !== 'generated' || view.artifact.revision < 1) return null;
  const notice = state.notice;
  if (!notice || notice.kind !== 'failed' || !notice.reason) return null;
  return Object.prototype.hasOwnProperty.call(EDIT_REFUSALS, notice.reason) ? EDIT_REFUSALS[notice.reason] : null;
}

// --- the field ---------------------------------------------------------------------------------------------------------------
export interface FilledSuggestion {
  id: string;
  rule: SuggestionRule;
  instruction: string;
}

/**
 * The same suggestion: same id AND same words. A chip keeps its id when only its words change (the selection count, the
 * dates), and then it is a different suggestion: it is not pressed, and a tap replaces the field instead of clearing it.
 */
export function sameSuggestion(a: { id: string; instruction: string } | null | undefined, b: { id: string; instruction: string } | null | undefined): boolean {
  return Boolean(a && b && a.id === b.id && a.instruction === b.instruction);
}

export interface EditField {
  text: string;
  /** The chip whose instruction is in the field, unchanged (aria-pressed while that chip still shows the same words). */
  filled: FilledSuggestion | null;
  /** What the person had typed before a chip replaced it ("Restore my text"). */
  saved: string | null;
}

export type EditFieldAction =
  | { type: 'type'; text: string }
  | { type: 'pick'; suggestion: FilledSuggestion }
  | { type: 'restore' }
  /** The filled chip no longer fits (selection, day or revision changed): empty the field; the person's own words stay restorable. */
  | { type: 'unfill' }
  | { type: 'reset' };

export const EMPTY_FIELD: EditField = { text: '', filled: null, saved: null };

export function editFieldReducer(state: EditField, action: EditFieldAction): EditField {
  switch (action.type) {
    case 'type':
      // Typing makes the words the person's own: no chip is pressed any more.
      return { text: action.text, filled: null, saved: null };
    case 'pick': {
      // Tapping the chip whose words are in the field clears it; the same chip with new words (2 → 3 selected) replaces them.
      if (sameSuggestion(state.filled, action.suggestion)) return { text: '', filled: null, saved: state.saved };
      const own = !state.filled && state.text.trim() ? state.text : state.saved;
      return { text: action.suggestion.instruction, filled: action.suggestion, saved: own };
    }
    case 'restore':
      return state.saved === null ? state : { text: state.saved, filled: null, saved: null };
    case 'unfill':
      return state.filled ? { text: '', filled: null, saved: state.saved } : state;
    case 'reset':
      return EMPTY_FIELD;
    default:
      return state;
  }
}

/** "Restore my text" is offered while the person's own words were replaced and are not back in the field. */
export function canRestore(state: EditField): boolean {
  return state.saved !== null && state.saved.trim() !== '' && state.saved !== state.text;
}
