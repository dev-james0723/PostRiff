export const INBOUND_CODE_COOLDOWN_SECONDS = 30;

export function inboundCodeCooldownUntil(nowSeconds: number) {
  return nowSeconds + INBOUND_CODE_COOLDOWN_SECONDS;
}

export function inboundCodeCooldownSeconds(nowSeconds: number, cooldownUntil: number) {
  return Math.max(0, Math.ceil(cooldownUntil - nowSeconds));
}
