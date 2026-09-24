import Providers from '@/components/layout/providers';
import { Toaster } from '@/components/ui/sonner';
import { fontVariables, uiFontFamily } from '@/components/themes/font.config';
import { DEFAULT_THEME, THEME_COOKIE, THEMES } from '@/components/themes/theme.config';
import ThemeProvider from '@/components/themes/theme-provider';
import { siteConfig } from '@/config/site';
import { cn } from '@/lib/utils';
import { Analytics } from '@vercel/analytics/next';
import type { Metadata, Viewport } from 'next';
import { cookies } from 'next/headers';
import NextTopLoader from 'nextjs-toploader';
import { NuqsAdapter } from 'nuqs/adapters/next/app';
import '../styles/globals.css';

const META_THEME_COLORS = {
  light: '#ffffff',
  dark: '#000000'
};

export const metadata: Metadata = {
  metadataBase: new URL(siteConfig.url),
  title: {
    default: `${siteConfig.name} · One idea, every platform, in your voice`,
    template: `%s · ${siteConfig.name}`
  },
  description: siteConfig.description,
  applicationName: siteConfig.name,
  openGraph: {
    title: `${siteConfig.name} · One idea, every platform, in your voice`,
    description: siteConfig.description,
    siteName: siteConfig.name,
    type: 'website',
    url: siteConfig.url
  },
  twitter: {
    card: 'summary_large_image',
    title: `${siteConfig.name} · One idea, every platform, in your voice`,
    description: siteConfig.description
  }
};

export const viewport: Viewport = {
  themeColor: META_THEME_COLORS.light,
  width: 'device-width',
  initialScale: 1
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const activeThemeValue = cookieStore.get(THEME_COOKIE)?.value;
  const isValidTheme = THEMES.some((t) => t.value === activeThemeValue);
  const themeToApply = isValidTheme ? activeThemeValue! : DEFAULT_THEME;

  return (
    <html lang='en' suppressHydrationWarning data-theme={themeToApply}>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                if (localStorage.theme === 'dark' || ((!('theme' in localStorage) || localStorage.theme === 'system') && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', '${META_THEME_COLORS.dark}')
                }
              } catch (_) {}
            `
          }}
        />
        {/* The next/font Geist face for the Rafii theme (styles/rafii.css re-applies it after the theme layer resets --font-sans). */}
        <style dangerouslySetInnerHTML={{ __html: `:root{--font-rafii-ui:${uiFontFamily}}` }} />
      </head>
      <body
        className={cn(
          'bg-background overflow-x-hidden overscroll-none font-sans antialiased',
          fontVariables
        )}
      >
        <NextTopLoader color='var(--primary)' showSpinner={false} />
        <NuqsAdapter>
          <ThemeProvider
            attribute='class'
            defaultTheme='system'
            enableSystem
            disableTransitionOnChange
            enableColorScheme
          >
            <Providers activeThemeValue={themeToApply}>
              <Toaster />
              {children}
            </Providers>
          </ThemeProvider>
        </NuqsAdapter>
        <Analytics />
      </body>
    </html>
  );
}
