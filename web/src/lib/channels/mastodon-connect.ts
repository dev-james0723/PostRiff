/** A reconnect hint only. The server remains responsible for URL validation and SSRF protection. */
export function mastodonReconnectServer(account?: string): string {
  if (!account) return '';
  const separator = account.lastIndexOf('@');
  return separator > 0 ? account.slice(separator + 1) : '';
}
