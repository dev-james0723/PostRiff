/**
 * Launch switch for the children's play area: every /play/* route is a 404 unless RAFII_PLAY_ENABLED=1 on the server
 * (off by default). It stays off until James and counsel approve the children's privacy notice
 * (docs/music-game/PRIVACY-NOTICE-DRAFT.md), since the current policy says the site is not directed at under-18s.
 * Server-only, read when the page is built or rendered. Pure (no imports) so node's test runner can load it directly.
 */
export function isPlayEnabled(env: Record<string, string | undefined> = process.env): boolean {
  return env.RAFII_PLAY_ENABLED === '1';
}
