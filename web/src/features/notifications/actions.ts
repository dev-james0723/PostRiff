export type ConfirmedNotificationResult = { verified: boolean; status?: string | null };

/** Confirmation is the server's verified state, never the click or HTTP success alone. */
export async function requireConfirmedAction(
  request: () => Promise<ConfirmedNotificationResult>,
  expectedStatus: 'read' | 'dismissed'
) {
  const result = await request();
  if (!result.verified || (result.status !== undefined && result.status !== expectedStatus))
    throw new Error('The change could not be confirmed. Try again.');
  return result;
}
