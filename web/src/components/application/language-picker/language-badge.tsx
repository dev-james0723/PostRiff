import { FLAG_FONT, glyphFontFamily, locales } from '@/lib/locales';
import { cn } from '@/lib/utils';

/** A language as people recognise it: flag, then its own name in its own script. Old values (English, 繁體中文) read the same. */
export function LanguageName({ language, className, flagClassName }: { language: string | null | undefined; className?: string; flagClassName?: string }) {
  const entry = locales.entry(language);
  if (!entry) return <span className={className}>{language}</span>;
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1', className)} title={entry.english}>
      <span aria-hidden className={cn('shrink-0 leading-none', flagClassName)} style={{ fontFamily: FLAG_FONT }}>
        {entry.flag}
      </span>
      <span lang={entry.tag} dir={entry.dir} className='truncate' style={{ fontFamily: glyphFontFamily(entry.glyphs) }}>
        {entry.native}
      </span>
    </span>
  );
}

/** A compact pill for tabs, rows and cards. */
export function LanguageBadge({ language, className }: { language: string | null | undefined; className?: string }) {
  return (
    <span className={cn('bg-muted text-foreground inline-flex h-5 max-w-full items-center rounded-md px-1.5 text-[11.5px] font-medium', className)}>
      <LanguageName language={language} />
    </span>
  );
}
