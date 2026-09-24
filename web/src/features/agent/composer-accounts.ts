interface Target { platform: string; channelId?: string }

export function selectionFor<T extends Target>(items: readonly T[], target: Target): T | undefined {
  return items.find(item => item.platform === target.platform && (item.channelId ?? null) === (target.channelId ?? null));
}

export function previewAccount<T extends { id: string; platform: string }>(accounts: readonly T[], target: Target): T | undefined {
  if (!target.channelId) return undefined;
  return accounts.find(account => account.id === target.channelId && account.platform === target.platform);
}
