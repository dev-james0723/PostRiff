export interface DeliverySummaryLanguage {
  tag: string;
  label: string;
  fromMessage?: boolean;
}

export interface DeliverySummaryRow {
  key: string;
  platform: string;
  account?: string;
  languages: readonly DeliverySummaryLanguage[];
}

export interface DeliverySummaryValue {
  destinationCount: number;
  languageCount: number;
  iconPlatforms: string[];
  hiddenIconCount: number;
  primary: string;
  secondary: string;
  secondaryLabel: string;
  secondaryExtraCount: number;
  accessible: string;
}

const plural = (count: number, one: string, many = `${one}s`) =>
  `${count} ${count === 1 ? one : many}`;

/**
 * Reduces the effective delivery rows to the compact, non-scrolling summary shown in Composer.
 * Rows are destination/account keyed, so two accounts on one platform remain two destinations.
 */
export function deriveDeliverySummary(rows: readonly DeliverySummaryRow[]): DeliverySummaryValue {
  const languages = Array.from(
    new Set(rows.flatMap((row) => row.languages.map((language) => language.tag)))
  );
  const iconPlatforms = rows.slice(0, 3).map((row) => row.platform);
  const hiddenIconCount = Math.max(0, rows.length - iconPlatforms.length);

  let primary = 'Choose channels';
  let secondary = 'No delivery selected';
  let secondaryLabel = secondary;
  let secondaryExtraCount = 0;
  if (rows.length === 1) {
    primary = rows[0].platform;
    const first = rows[0].languages[0]?.label ?? 'Choose a language';
    secondaryExtraCount = Math.max(0, rows[0].languages.length - 1);
    secondaryLabel = first;
    secondary = secondaryExtraCount ? `${first} +${secondaryExtraCount}` : first;
  } else if (rows.length > 1) {
    primary = plural(rows.length, 'channel');
    secondary = plural(languages.length, 'language');
    secondaryLabel = secondary;
  }

  const destinations = rows.map((row) => {
    const identity = row.account ? `${row.platform}, ${row.account}` : row.platform;
    const output = row.languages.length
      ? row.languages.map((language) => language.label).join(', ')
      : 'no language selected';
    const fromMessage = row.languages.some((language) => language.fromMessage)
      ? ', from the message'
      : '';
    return `${identity}: ${output}${fromMessage}`;
  });
  const counts = `${plural(rows.length, 'destination')}; ${plural(languages.length, 'language')}`;

  return {
    destinationCount: rows.length,
    languageCount: languages.length,
    iconPlatforms,
    hiddenIconCount,
    primary,
    secondary,
    secondaryLabel,
    secondaryExtraCount,
    accessible: rows.length
      ? `Delivery. ${destinations.join('; ')}. ${counts}.`
      : 'Delivery. No destinations selected.'
  };
}
