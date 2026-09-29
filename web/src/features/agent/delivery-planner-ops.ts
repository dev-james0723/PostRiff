export interface DeliveryTargetValue<P extends string = string> {
  key?: string;
  platform: P;
  channelId?: string | null;
  languages?: string[] | null;
}

/** The same identity rule as useChannelLanguages: account id, otherwise platform. */
export function deliveryTargetKey(target: DeliveryTargetValue): string {
  return target.key ?? target.channelId ?? target.platform;
}

export function addDeliveryTarget<P extends string, T extends DeliveryTargetValue<P>>(
  current: readonly T[],
  target: T
): T[] {
  const key = deliveryTargetKey(target);
  return current.some((item) => deliveryTargetKey(item) === key)
    ? [...current]
    : [...current, target];
}

/** A delivery plan must always retain at least one destination. */
export function removeDeliveryTarget<P extends string, T extends DeliveryTargetValue<P>>(
  current: readonly T[],
  key: string
): T[] {
  if (current.length <= 1) return [...current];
  return current.filter((item) => deliveryTargetKey(item) !== key);
}

/** The exact target list committed back through useChannelLanguages.setTargets. */
export function deliveryTargets<P extends string>(
  items: readonly DeliveryTargetValue<P>[]
): { platform: P; channelId?: string }[] {
  return items.map((item) =>
    item.channelId
      ? { platform: item.platform, channelId: item.channelId }
      : { platform: item.platform }
  );
}

export function deliveryTargetSignature(items: readonly DeliveryTargetValue[]): string {
  return items.map(deliveryTargetKey).join('\u001f');
}
