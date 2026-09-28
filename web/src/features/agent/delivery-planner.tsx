'use client';

import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { IconPlus } from '@tabler/icons-react';
import { ChannelIcon } from '@/components/channel-icon';
import { RafiiDialog, RafiiDialogContent, RafiiDialogHeader } from '@/components/rafii';
import type { LocaleTag } from '@/lib/api/types';
import {
  LanguageStage,
  useOpenGeneration,
  type LanguageDialogApi,
  type LanguageOp,
  type LanguageSelectionItem
} from './language-dialog';
import { runLanguageOp, stateKey } from './language-dialog-ops';
import {
  addDeliveryTarget,
  deliveryTargetKey,
  deliveryTargets,
  deliveryTargetSignature,
  removeDeliveryTarget
} from './delivery-planner-ops';

export interface DeliveryTargetOption<P extends string = string> {
  key: string;
  platform: P;
  channelId?: string;
  account?: string;
  state?: string;
  /** A destination without a connected account; it still produces a draft. */
  platformOnly?: boolean;
}

export interface DeliveryPlannerApi<P extends string = string> extends LanguageDialogApi<P> {
  setTargets(targets: { platform: P; channelId?: string }[]): void;
}

export interface DeliveryPlannerProps<P extends string = string> {
  id: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selection: readonly LanguageSelectionItem<P>[];
  languages: DeliveryPlannerApi<P>;
  options: readonly DeliveryTargetOption<P>[];
  /** Effective message-language values, keyed by the destination's selection key. */
  messageLanguages?: Readonly<Record<string, readonly LocaleTag[]>>;
}

type PendingCommit<P extends string> = {
  phase: 'targets' | 'waiting' | 'languages';
  targets: { platform: P; channelId?: string }[];
  operations: LanguageOp<P>[];
};

/**
 * The conversation's responsive Channel × Language editor. Destination changes stay staged in
 * this dialog; Apply first commits the target keys through the existing hook, then drains the
 * existing language operations one render at a time. Cancel, backdrop close and Escape commit none.
 */
export function DeliveryPlanner<P extends string = string>({
  id,
  open,
  onOpenChange,
  selection,
  languages,
  options,
  messageLanguages = {}
}: DeliveryPlannerProps<P>) {
  const languageEscapeRef = useRef<(() => boolean) | null>(null);
  const plannerEscapeRef = useRef<(() => boolean) | null>(null);
  const [pending, setPending] = useState<PendingCommit<P> | null>(null);
  const applying = pending !== null;
  const generation = useOpenGeneration(open);
  const appliedSignature = deliveryTargetSignature(selection);

  useEffect(() => {
    if (!pending) return;
    if (pending.phase === 'targets') {
      languages.setTargets(pending.targets);
      setPending({ ...pending, phase: 'waiting' });
      return;
    }
    if (pending.phase === 'waiting') {
      if (deliveryTargetSignature(pending.targets) !== appliedSignature) return;
      setPending({ ...pending, phase: 'languages' });
      return;
    }
    const [operation, ...rest] = pending.operations;
    if (operation) {
      runLanguageOp(languages, operation);
      setPending({ ...pending, operations: rest });
      return;
    }
    setPending(null);
    onOpenChange(false);
  }, [appliedSignature, languages, onOpenChange, pending]);

  return (
    <RafiiDialog
      open={open}
      onOpenChange={(next, details) => {
        if (next) {
          onOpenChange(true);
          return;
        }
        if (
          details.reason === 'escape-key' &&
          (languageEscapeRef.current?.() || plannerEscapeRef.current?.())
        ) {
          details.cancel();
          return;
        }
        if (applying) {
          details.cancel();
          return;
        }
        onOpenChange(false);
      }}
    >
      <RafiiDialogContent
        size='md'
        id={id}
        finalFocus={() => document.getElementById(`${id}-trigger`)}
        className='z-[80] md:max-h-[min(52rem,92dvh)]'
      >
        <RafiiDialogHeader
          eyebrow='Delivery planner'
          title='Publish to'
          intro='Choose channels and output language.'
          closeLabel='Close delivery planner'
        />
        <DeliveryPlannerStage
          key={generation}
          selection={selection}
          languages={languages}
          options={options}
          messageLanguages={messageLanguages}
          applying={applying}
          languageEscapeRef={languageEscapeRef}
          plannerEscapeRef={plannerEscapeRef}
          onCancel={() => onOpenChange(false)}
          onApply={(items, operations) => {
            setPending({ phase: 'targets', targets: deliveryTargets(items), operations });
          }}
        />
      </RafiiDialogContent>
    </RafiiDialog>
  );
}

function DeliveryPlannerStage<P extends string>({
  selection,
  languages,
  options,
  messageLanguages,
  applying,
  languageEscapeRef,
  plannerEscapeRef,
  onApply,
  onCancel
}: {
  selection: readonly LanguageSelectionItem<P>[];
  languages: DeliveryPlannerApi<P>;
  options: readonly DeliveryTargetOption<P>[];
  messageLanguages: Readonly<Record<string, readonly LocaleTag[]>>;
  applying: boolean;
  languageEscapeRef: MutableRefObject<(() => boolean) | null>;
  plannerEscapeRef: MutableRefObject<(() => boolean) | null>;
  onApply: (items: LanguageSelectionItem<P>[], operations: LanguageOp<P>[]) => void;
  onCancel: () => void;
}) {
  const [items, setItems] = useState<LanguageSelectionItem<P>[]>(() =>
    selection.map((item) => ({ ...item, languages: item.languages ? [...item.languages] : null }))
  );
  const [adding, setAdding] = useState(false);
  const selected = useMemo(() => new Set(items.map(deliveryTargetKey)), [items]);
  const available = options.filter((option) => !selected.has(option.key));
  const optionByKey = useMemo(
    () => new Map(options.map((option) => [option.key, option])),
    [options]
  );

  useEffect(() => {
    plannerEscapeRef.current = adding
      ? () => {
          setAdding(false);
          return true;
        }
      : null;
    return () => {
      plannerEscapeRef.current = null;
    };
  }, [adding, plannerEscapeRef]);

  const label = (item: LanguageSelectionItem<P>) => {
    const option = optionByKey.get(deliveryTargetKey(item));
    if (item.channelId) return `${item.platform} · ${option?.account ?? 'account'}`;
    return item.platform;
  };

  const addControl = (
    <div className='mt-2'>
      <button
        type='button'
        aria-expanded={adding}
        aria-controls='delivery-channel-options'
        disabled={applying || available.length === 0}
        onClick={() => setAdding((current) => !current)}
        className='rafii-focus rafii-glass hover:rafii-glass-selected text-foreground flex min-h-11 w-full items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 text-sm font-medium disabled:opacity-55'
      >
        <IconPlus aria-hidden className='size-4' />
        {available.length ? 'Add channel' : 'All available channels added'}
      </button>
      {adding && available.length > 0 && (
        <div
          id='delivery-channel-options'
          role='region'
          aria-label='Available channels'
          className='rafii-quiet mt-2 grid gap-1.5 rounded-[var(--rafii-radius-card)] p-2 sm:grid-cols-2'
        >
          {available.map((option) => (
            <button
              key={option.key}
              type='button'
              onClick={() => {
                setItems((current) =>
                  addDeliveryTarget(current, {
                    key: option.key,
                    platform: option.platform,
                    channelId: option.channelId,
                    languages: null
                  })
                );
                setAdding(false);
              }}
              className='rafii-focus hover:rafii-glass-selected flex min-h-11 min-w-0 items-center gap-2 rounded-[var(--rafii-radius-control)] px-2.5 py-2 text-left'
            >
              <ChannelIcon platform={option.platform} size='sm' />
              <span className='flex min-w-0 flex-1 flex-col'>
                <span className='text-foreground truncate text-sm font-medium'>
                  {option.platform}
                  {option.account ? ` · ${option.account}` : ''}
                </span>
                <span className='text-muted-foreground truncate text-xs'>
                  {option.platformOnly ? 'Draft only' : (option.state ?? 'Connected account')}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <LanguageStage
      selection={items}
      languages={languages}
      accountLabel={label}
      applying={applying}
      escapeRef={languageEscapeRef}
      applyLabel='Apply delivery'
      messageLanguages={(item) => messageLanguages[stateKey(item)] ?? []}
      onRemoveItem={(item) =>
        setItems((current) => removeDeliveryTarget(current, deliveryTargetKey(item)))
      }
      removeDisabled={items.length <= 1 || applying}
      afterItems={addControl}
      showDeliveryCount
      onCancel={onCancel}
      onApply={(operations) => onApply(items, operations)}
    />
  );
}
