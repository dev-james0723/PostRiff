/**
 * What an answer asks the panel to do by itself (docs/design/rafii-live-agent/CONTRACTS.md, Contract 2), and the
 * ledger that makes it happen once. The panel runs these for the latest answer only, once per message id, in text
 * and voice alike, and never for an answer read back from history or drawn again: only a turn response in this
 * session is ever claimed. No imports, so `web/tests/rafii-guide.test.cjs` can load it directly.
 */

export type AutoAction =
  | { kind: 'guide'; guideId: string }
  | { kind: 'navigate'; href: string }
  | { kind: 'style'; style: Record<string, unknown> };

type Loose = Record<string, unknown>;

const isObject = (value: unknown): value is Loose => typeof value === 'object' && value !== null && !Array.isArray(value);
const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;

/**
 * The actions in an answer's blocks. A guide opens its own page, so it wins over an automatic link. A `style` voice
 * command applies in text mode only: in a call, the voice session carries out every voice command itself.
 */
export function autoActionsOf(blocks: readonly unknown[] | null | undefined, modality: 'text' | 'voice'): AutoAction[] {
  const list = Array.isArray(blocks) ? blocks.filter(isObject) : [];
  const actions: AutoAction[] = [];
  const guide = list.find((block) => block.type === 'guide_card' && block.auto === true && nonEmpty(block.guideId));
  const link = list.find((block) => block.type === 'navigation_card' && block.auto === true && nonEmpty(block.href));
  if (guide) actions.push({ kind: 'guide', guideId: String(guide.guideId) });
  else if (link) actions.push({ kind: 'navigate', href: String(link.href) });
  if (modality === 'text') {
    const style = list.find((block) => block.type === 'voice_command' && block.command === 'style' && isObject(block.style));
    if (style) actions.push({ kind: 'style', style: style.style as Loose });
  }
  return actions;
}

export interface AutoLedger {
  /** A number for a request as it starts (or, for a voice answer, as it arrives); later requests get larger ones. */
  begin(): number;
  /**
   * True exactly once for an answer: never twice for one message id, and never for an answer whose request is older
   * than one whose answer already ran (it would undo a newer request).
   */
  claim(messageId: string | null | undefined, ticket: number): boolean;
}

export function createAutoLedger(limit = 200): AutoLedger {
  let tickets = 0;
  let newest = 0;
  const done = new Set<string>();
  const remember = (id: string) => {
    done.add(id);
    if (done.size > limit) {
      const oldest = done.values().next().value;
      if (oldest !== undefined) done.delete(oldest);
    }
  };
  return {
    begin() {
      tickets += 1;
      return tickets;
    },
    claim(messageId, ticket) {
      if (!nonEmpty(messageId) || done.has(messageId)) return false;
      remember(messageId);
      if (ticket < newest) return false;
      newest = ticket;
      return true;
    }
  };
}
