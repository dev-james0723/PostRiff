/**
 * A template re-mounts on every workspace navigation, so each page settles in
 * with the transitions.dev page-slide clocks (`.t-page-enter` in
 * `src/styles/transitions.css`). The wrapper keeps the page's `flex-1` slot
 * next to the info sidebar.
 */
export default function AppTemplate({ children }: { children: React.ReactNode }) {
  return <div className='t-page-enter flex min-w-0 flex-1 flex-col'>{children}</div>;
}
