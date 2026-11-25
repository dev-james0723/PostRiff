import type { AttentionItem } from '@/lib/attention';
import type { BillingMode } from '@/lib/api/types';

/** Shared legacy attention remains untouched; v2 work surfaces cannot present it as a credit blocker. */
export function workAttention(items: AttentionItem[], mode: BillingMode | undefined) {
  return mode === 'legacy_allowances' ? items : items.filter(item => item.id !== 'writing-allowance');
}
