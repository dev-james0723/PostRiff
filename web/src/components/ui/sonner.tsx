'use client';

import { useTheme } from 'next-themes';
import { Toaster as Sonner, ToasterProps } from 'sonner';

/**
 * Toasts on elevated glass (Design DNA §5.2, §23.6): Sonner's own variables carry the solid
 * fallback colour, radius and (no) border; the glass gradient, blur and separation shadow come
 * from the class recipe. `--normal-bg` stays a plain colour so Sonner's action button, which
 * inverts it, keeps a valid colour.
 */
const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = 'system' } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps['theme']}
      className='toaster group'
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--foreground)',
          '--normal-border': 'transparent',
          '--border-radius': '1.25rem'
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: 'bg-[image:var(--rafii-surface-elevated)]! text-foreground shadow-[var(--rafii-shadow-dialog)]! backdrop-blur-[40px] gap-3 p-4',
          title: 'text-sm font-medium',
          description: 'text-muted-foreground! text-sm',
          actionButton: 'rafii-action! text-[var(--rafii-action-fg)]! rounded-[0.625rem]! font-medium',
          cancelButton: 'rafii-quiet! text-foreground! rounded-[0.625rem]!'
        }
      }}
      position='top-center'
      {...props}
    />
  );
};

export { Toaster };
