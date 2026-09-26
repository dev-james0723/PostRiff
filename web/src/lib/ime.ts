/**
 * IME (Chinese, Japanese, Korean input) rules shared by every composer key handler (chat-context SPEC §4.9).
 *
 * A key press that belongs to a composition is never a send, menu or chip key. Browsers disagree on the order:
 * Chrome and Firefox send keydown with `isComposing` before `compositionend`; Safari sends `compositionend` first and
 * then the committing keydown with keyCode 229; Android keyboards send keyCode 229 throughout. The guard therefore
 * keeps "composing" true until one task after `compositionend`, so Safari's late Enter is still ignored.
 */

export interface KeyLike {
  isComposing?: boolean;
  keyCode?: number;
  nativeEvent?: { isComposing?: boolean; keyCode?: number };
}

/** A key press that belongs to an IME composition: never a send, menu or chip key. */
export function isImeEvent(event: KeyLike): boolean {
  return Boolean(
    event.isComposing ||
    event.nativeEvent?.isComposing ||
    event.keyCode === 229 ||
    event.nativeEvent?.keyCode === 229
  );
}

export interface ImeGuard {
  onCompositionStart(): void;
  onCompositionEnd(): void;
  /** True while composing, until one task after `compositionend`, or when the event itself says IME. */
  composing(event?: KeyLike): boolean;
}

export function createImeGuard(
  schedule: (run: () => void) => unknown = (run) => setTimeout(run, 0)
): ImeGuard {
  let active = false;
  let settling = 0;
  return {
    onCompositionStart() {
      active = true;
    },
    onCompositionEnd() {
      active = false;
      settling += 1;
      schedule(() => {
        settling = Math.max(0, settling - 1);
      });
    },
    composing(event) {
      return active || settling > 0 || Boolean(event && isImeEvent(event));
    }
  };
}
