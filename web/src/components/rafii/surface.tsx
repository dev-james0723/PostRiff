import type { ComponentPropsWithoutRef, ElementType } from 'react';
import { cn } from '@/lib/utils';

export type SurfaceMaterial = 'glass' | 'selected' | 'elevated' | 'quiet' | 'composer' | 'paper' | 'canvas';
export type SurfaceRadius = 'control' | 'card' | 'composer' | 'dialog' | 'none';

const MATERIAL: Record<SurfaceMaterial, string> = {
  glass: 'rafii-glass',
  selected: 'rafii-glass-selected',
  elevated: 'rafii-elevated',
  quiet: 'rafii-quiet',
  composer: 'rafii-composer',
  paper: 'rafii-paper',
  canvas: ''
};

const RADIUS: Record<SurfaceRadius, string> = {
  control: 'rounded-[var(--rafii-radius-control)]',
  card: 'rounded-[var(--rafii-radius-card)]',
  composer: 'rounded-[var(--rafii-radius-composer)]',
  dialog: 'rounded-[var(--rafii-radius-dialog)]',
  none: ''
};

const PADDING = {
  none: '',
  sm: 'p-3',
  md: 'p-5',
  lg: 'p-6 md:p-7'
} as const;

type SurfaceProps<T extends ElementType> = {
  as?: T;
  material?: SurfaceMaterial;
  radius?: SurfaceRadius;
  padding?: keyof typeof PADDING;
  className?: string;
} & Omit<ComponentPropsWithoutRef<T>, 'as' | 'className'>;

/**
 * One material role per surface (DNA §5.2, §5.5): a canvas, one work surface and its
 * controls. Glass explains grouping and depth; quiet panels carry dense reading content.
 */
export function Surface<T extends ElementType = 'div'>({ as, material = 'glass', radius = 'card', padding = 'md', className, ...props }: SurfaceProps<T>) {
  const Component = (as ?? 'div') as ElementType;
  return <Component data-material={material} className={cn(MATERIAL[material], RADIUS[radius], PADDING[padding], 'min-w-0', className)} {...props} />;
}
