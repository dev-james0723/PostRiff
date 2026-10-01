'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { SettingsView } from './settings-view';

/** `/founder/settings` — Contact & calls policy, briefing schedules and the notifications readiness note. */
export default function SettingsSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='settings' onAsk={onAsk}>
      <SettingsView />
    </FounderAskProvider>
  );
}
