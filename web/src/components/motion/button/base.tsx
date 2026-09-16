'use client';

import { AnimatePresence, type HTMLMotionProps, motion, useReducedMotion } from 'motion/react';
import {
  forwardRef,
  type PointerEvent,
  type ReactNode,
  useCallback,
  useRef,
  useState
} from 'react';
import { EASE_OUT, SPRING_PRESS } from '@/lib/ease';
import { buttonVariants } from '@/components/ui/button';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { cn } from '@/lib/utils';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'outline' | 'destructive';
export type ButtonSize = 'xs' | 'sm' | 'md' | 'lg' | 'icon';

export interface ButtonProps extends Omit<HTMLMotionProps<'button'>, 'children'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  pressScale?: number;
  /** Spawn a Material-style ripple from the press point. Off by default. */
  ripple?: boolean;
  children?: ReactNode;
}

export interface ButtonLinkProps extends Omit<HTMLMotionProps<'a'>, 'children'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  pressScale?: number;
  children?: ReactNode;
}

type Ripple = { id: number; x: number; y: number; size: number };

// PostRiff: the motion buttons render through the app's own `buttonVariants`,
// so press physics come from beUI while shape, color and radius follow the
// active theme. `transition-colors` replaces the variants' `transition-all`,
// which would otherwise also tween the transform Motion drives every frame.
const VARIANT_MAP: Record<
  ButtonVariant,
  'default' | 'secondary' | 'ghost' | 'outline' | 'destructive'
> = {
  primary: 'default',
  secondary: 'secondary',
  ghost: 'ghost',
  outline: 'outline',
  destructive: 'destructive'
};

const SIZE_MAP: Record<ButtonSize, 'sm' | 'default' | 'lg' | 'icon' | 'xs'> = {
  xs: 'xs',
  sm: 'sm',
  md: 'default',
  lg: 'lg',
  icon: 'icon'
};

function motionButtonClass(variant: ButtonVariant, size: ButtonSize) {
  return cn(
    buttonVariants({ variant: VARIANT_MAP[variant], size: SIZE_MAP[size] }),
    'transition-colors'
  );
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    size = 'md',
    pressScale = 0.93,
    ripple = false,
    className,
    children,
    onPointerDown,
    ...rest
  },
  ref
) {
  const reduce = useReducedMotion();
  const canHover = useHoverCapable();
  const [ripples, setRipples] = useState<Ripple[]>([]);
  const nextId = useRef(0);

  const handlePointerDown = useCallback(
    (event: PointerEvent<HTMLButtonElement>) => {
      if (ripple && !reduce) {
        const rect = event.currentTarget.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height) * 2;
        const id = nextId.current++;
        setRipples((prev) => [
          ...prev,
          {
            id,
            x: event.clientX - rect.left,
            y: event.clientY - rect.top,
            size
          }
        ]);
      }
      onPointerDown?.(event);
    },
    [ripple, reduce, onPointerDown]
  );

  return (
    <motion.button
      ref={ref}
      type='button'
      whileTap={reduce ? undefined : { scale: pressScale }}
      whileHover={reduce || !canHover ? undefined : { scale: 1.02 }}
      transition={SPRING_PRESS}
      onPointerDown={handlePointerDown}
      className={cn(
        motionButtonClass(variant, size),
        ripple && 'relative overflow-hidden',
        className
      )}
      {...rest}
    >
      {ripple && !reduce ? (
        <span className='pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]'>
          <AnimatePresence>
            {ripples.map((r) => (
              <motion.span
                key={r.id}
                className='absolute rounded-full bg-current'
                style={{
                  left: r.x,
                  top: r.y,
                  width: r.size,
                  height: r.size,
                  x: '-50%',
                  y: '-50%'
                }}
                initial={{ scale: 0.05, opacity: 0.3 }}
                animate={{ scale: 1, opacity: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 1.6, ease: EASE_OUT }}
                onAnimationComplete={() => setRipples((prev) => prev.filter((x) => x.id !== r.id))}
              />
            ))}
          </AnimatePresence>
        </span>
      ) : null}
      {children}
    </motion.button>
  );
});

export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink(
  { variant = 'primary', size = 'md', pressScale = 0.93, className, children, ...rest },
  ref
) {
  const reduce = useReducedMotion();
  const canHover = useHoverCapable();

  return (
    <motion.a
      ref={ref}
      whileTap={reduce ? undefined : { scale: pressScale }}
      whileHover={reduce || !canHover ? undefined : { scale: 1.02 }}
      transition={SPRING_PRESS}
      className={cn(motionButtonClass(variant, size), className)}
      {...rest}
    >
      {children}
    </motion.a>
  );
});
