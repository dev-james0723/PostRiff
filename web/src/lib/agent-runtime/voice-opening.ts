/** One opening per fresh call, after both the authenticated profile and Live are ready. */
export function voiceOpening(send: (event: Record<string, unknown>) => void, resuming = false) {
  let ready = false;
  let content: string | null = null;
  let finished = resuming;
  function attempt() {
    if (!ready || !content || finished) return;
    finished = true;
    send({ type: 'session.instructions.append', delegation_id: null, content });
  }
  return {
    prepared(instructions?: string) {
      content = instructions || 'Greet the person now in English. Introduce yourself as Rafii, their AI assistant, ask how you can help today, then pause and listen. Do not invent a name.';
      attempt();
    },
    started() { ready = true; attempt(); },
    cancel() { finished = true; }
  };
}
