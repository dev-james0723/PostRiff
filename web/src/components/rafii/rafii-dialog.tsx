'use client';

import { Dialog as DialogPrimitive } from '@base-ui/react/dialog';
import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';

const SIZE = {
  sm: 'md:w-[34rem]',
  md: 'md:w-[43rem]',
  lg: 'md:w-[54rem]',
  xl: 'md:w-[57rem]'
} as const;

export const RafiiDialog = DialogPrimitive.Root;
export const RafiiDialogTrigger = DialogPrimitive.Trigger;
export const RafiiDialogClose = DialogPrimitive.Close;

export interface RafiiDialogContentProps extends DialogPrimitive.Popup.Props {
  size?: keyof typeof SIZE;
  /** Fills the viewport height on phones (bottom sheet); centred elevated glass on wider screens. */
  className?: string;
  children: ReactNode;
}

/**
 * Elevated glass dialog (DNA §12.2): a flex column with a stable header, a scrolling body and a
 * stable footer. On phones it becomes a near-full-height bottom sheet with a handle. Focus is
 * contained and restored by Base UI; the `t-modal` clocks come from transitions.css.
 */
export function RafiiDialogContent({ size = 'md', className, children, ...props }: RafiiDialogContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Backdrop className='t-modal-backdrop rafii-scrim fixed inset-0 isolate z-50' />
      <DialogPrimitive.Popup
        data-slot='rafii-dialog'
        className={cn(
          't-modal rafii-elevated fixed z-50 flex max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] flex-col overflow-hidden text-sm outline-none',
          'inset-x-2 bottom-2 rounded-[var(--rafii-radius-mobile-dialog)]',
          'md:inset-auto md:top-1/2 md:left-1/2 md:max-h-[min(58rem,94dvh)] md:max-w-[calc(100vw-3rem)] md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-[var(--rafii-radius-dialog)]',
          SIZE[size],
          className
        )}
        {...props}
      >
        <span aria-hidden className='bg-foreground/35 mx-auto mt-2.5 h-1 w-8 shrink-0 rounded-full md:hidden' />
        {children}
      </DialogPrimitive.Popup>
    </DialogPrimitive.Portal>
  );
}

export function RafiiDialogHeader({ eyebrow, title, accent, intro, back, closeLabel = 'Close', children, className }: { eyebrow?: ReactNode; title: ReactNode; accent?: ReactNode; intro?: ReactNode; back?: ReactNode; closeLabel?: string; children?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex shrink-0 flex-col gap-3 px-5 pt-4 pb-3 md:px-7 md:pt-6', className)}>
      <div className='flex items-start gap-3'>
        {back}
        <div className='flex min-w-0 flex-1 flex-col gap-1.5'>
          {eyebrow && <span className='rafii-eyebrow'>{eyebrow}</span>}
          <DialogPrimitive.Title className='text-foreground text-[1.75rem] leading-[1.12] font-medium tracking-[-0.02em] text-balance md:text-[2rem]'>
            {title}
            {accent && (
              <>
                {' '}
                <em className='rafii-serif'>{accent}</em>
              </>
            )}
          </DialogPrimitive.Title>
          {intro && <DialogPrimitive.Description className='text-muted-foreground text-sm leading-relaxed'>{intro}</DialogPrimitive.Description>}
        </div>
        <DialogPrimitive.Close aria-label={closeLabel} className='rafii-glass rafii-focus hover:rafii-glass-selected flex size-11 shrink-0 items-center justify-center rounded-full'>
          <Icons.close className='size-4' />
        </DialogPrimitive.Close>
      </div>
      {children}
    </div>
  );
}

export function RafiiDialogBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-4 md:px-7', className)}>{children}</div>;
}

export function RafiiDialogFooter({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rafii-panel z-[1] flex shrink-0 flex-col gap-2 px-5 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))] md:px-7 md:pb-5', className)}>{children}</div>;
}
