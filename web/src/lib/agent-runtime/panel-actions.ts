/**
 * What the Rafii panel can do on the person's behalf, registered by the components that own each ability and called
 * by whoever decides to use it (a voice request, an agent answer, a typed command). Nothing here performs an action
 * itself; a missing handler means the ability isn't available on this screen and the caller says so.
 */
import type { AgentStylePatch } from './style';

export interface PanelActions {
  /** Open an allowlisted Rafii page (an internal href from the route manifest). */
  navigate?: (href: string) => void;
  /** Run a guided walkthrough from the guide manifest; resolves false when it couldn't start here. */
  startGuide?: (guideId: string) => Promise<boolean> | boolean;
  stopGuide?: () => void;
  /** Change how Rafii talks (persisted to the person's profile). */
  setStyle?: (patch: AgentStylePatch) => Promise<void> | void;
  /** Open the style picker (the `/style` command without a preset). */
  openStyle?: () => void;
  /** Start a voice call from the panel (the `/voice` command). */
  startVoice?: () => void;
  /** Start a new conversation in the panel (the `/new` command). */
  newConversation?: () => void;
}

const handlers: PanelActions = {};
const listeners = new Set<() => void>();

/** Register handlers; returns a function that removes exactly these (a newer registration is kept). */
export function registerPanelActions(next: PanelActions): () => void {
  const added = Object.entries(next).filter(([, fn]) => typeof fn === 'function') as [keyof PanelActions, never][];
  for (const [key, fn] of added) handlers[key] = fn;
  listeners.forEach((listener) => listener());
  return () => {
    for (const [key, fn] of added) if (handlers[key] === fn) delete handlers[key];
    listeners.forEach((listener) => listener());
  };
}

export function panelActions(): Readonly<PanelActions> {
  return handlers;
}

export function onPanelActionsChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
