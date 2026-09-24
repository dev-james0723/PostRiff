'use client';

import { useEffect } from 'react';

// global-error replaces the root layout when it errors, so globals.css is not
// loaded here — styles must be inline and self-contained. The sheet below carries
// the Rafii tokens the error needs (DNA §20.4: an error keeps the design language):
// monochrome canvas, one glass surface, the inverted action, both colour schemes.
const SHEET = `
:root{color-scheme:light dark;--bg:#fcfcfc;--fg:#000;--muted:#626262;--quiet:rgb(0 0 0 / .05);
--glass:linear-gradient(135deg,#fff9,#ffffff45 50%,#eeeeee55);--shadow:0 12px 28px -19px #0005,inset 0 9px 22px -19px #fff;
--action:linear-gradient(130deg,#343434,#000 65%,#303030);--action-fg:#fff;--action-shadow:0 12px 25px -17px #0009}
@media (prefers-color-scheme:dark){:root{--bg:#000;--fg:#fff;--muted:#a1a1a1;--quiet:rgb(255 255 255 / .07);
--glass:linear-gradient(135deg,rgb(255 255 255 / .13),rgb(255 255 255 / .055) 40%,rgb(255 255 255 / .04) 65%,rgb(255 255 255 / .08));
--shadow:0 15px 40px -22px #000c,inset 0 5px 17px -13px #ffffffa0,inset 0 -5px 18px -14px #fff4;
--action:linear-gradient(125deg,#fff,#dedede 58%,#f5f5f5);--action-fg:#080808;--action-shadow:0 7px 28px -14px #ffffff50,inset 0 8px 15px -10px #fff}}
body{margin:0;background:var(--bg);color:var(--fg);font-family:Geist,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans CJK TC",Arial,sans-serif;-webkit-font-smoothing:antialiased}
.stage{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1.5rem 1rem}
.surface{width:100%;max-width:28rem;box-sizing:border-box;padding:1.75rem 1.5rem;border-radius:1.75rem;background:var(--glass);box-shadow:var(--shadow);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);text-align:center}
.well{display:inline-flex;width:44px;height:44px;border-radius:999px;align-items:center;justify-content:center;background:var(--quiet);margin-bottom:1rem}
h1{font-size:1.625rem;line-height:1.15;font-weight:500;letter-spacing:-.02em;margin:0 0 .5rem}
p{color:var(--muted);font-size:.9375rem;line-height:1.55;margin:0 0 1.25rem;text-wrap:pretty}
.actions{display:flex;flex-wrap:wrap;justify-content:center;gap:.5rem}
.action,.quiet{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:0 1.25rem;border:0;border-radius:.75rem;font:inherit;font-size:.875rem;font-weight:500;cursor:pointer;text-decoration:none}
.action{background:var(--action);color:var(--action-fg);box-shadow:var(--action-shadow)}
.quiet{background:transparent;color:var(--muted)}
.quiet:hover{background:var(--quiet);color:var(--fg)}
.action:focus-visible,.quiet:focus-visible{outline:2px solid var(--fg);outline-offset:3px}
`;

export default function GlobalError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (!process.env.NEXT_PUBLIC_SENTRY_DISABLED && process.env.NEXT_PUBLIC_SENTRY_DSN) {
      void import('@sentry/nextjs').then((Sentry) => Sentry.captureException(error)).catch(() => {});
    }
  }, [error]);

  return (
    <html lang='en'>
      <body>
        <style>{SHEET}</style>
        <main className='stage'>
          <div className='surface' role='alert'>
            <span className='well' aria-hidden>
              <svg width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='2' strokeLinecap='round' strokeLinejoin='round'>
                <path d='M12 9v4' />
                <path d='M10.363 3.591 2.257 17.125a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87L13.637 3.59a1.914 1.914 0 0 0 -3.274 0z' />
                <path d='M12 16h.01' />
              </svg>
            </span>
            <h1>Something went wrong</h1>
            <p>Rafii hit an unexpected error. Check your activity before retrying any publication.</p>
            <div className='actions'>
              <button type='button' className='action' onClick={() => reset()}>
                Try again
              </button>
              {/* A full navigation, not a Link: the app tree that would render one has just failed. */}
              <button type='button' className='quiet' onClick={() => window.location.assign('/')}>
                Back to home
              </button>
            </div>
          </div>
        </main>
      </body>
    </html>
  );
}
