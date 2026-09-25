/** The server revision check is still required; this also detects edits made since the user began typing. */
export function checkEditBase(baseText: string, serverText: string, desiredText: string): void {
  if (serverText !== baseText && serverText !== desiredText) {
    throw new Error('This draft changed elsewhere. Your edit is kept here; compare it with the saved draft before saving.');
  }
}
