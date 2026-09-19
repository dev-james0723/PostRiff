import { TourMount } from '@/features/onboarding/tour-mount';

/**
 * A template re-mounts on every workspace navigation, so each page settles in
 * with the transitions.dev page-slide clocks (`.t-page-enter` in
 * `src/styles/transitions.css`). The wrapper keeps the page's `flex-1` slot
 * next to the info sidebar. The onboarding mount (welcome, page tips, tour
 * overlay) lives here too: it re-mounts with the page, and the running tour
 * survives in its own store, which is how a tour can walk across pages.
 */
export default function AppTemplate({ children }: { children: React.ReactNode }) {
  return (
    <div className='t-page-enter flex min-w-0 flex-1 flex-col'>
      {children}
      <TourMount />
    </div>
  );
}
