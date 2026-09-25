/** Immediate submission lock; React state alone does not guard same-tick events. */
export function createSubmissionGate() {
  let mounted = false;
  let pending = false;
  return {
    activate() { mounted = true; },
    dispose() { mounted = false; },
    alive() { return mounted; },
    enter() {
      if (!mounted || pending) return false;
      pending = true;
      return true;
    },
    leave() { pending = false; }
  };
}
