'use client';

import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useAsk } from '../customers/kit/ask';
import { FounderPage, Panel } from '../customers/kit/page-frame';
import { useTabState } from '../customers/kit/tabs';
import { BriefingSchedules } from './briefing-schedules';
import { ContactPolicyForm } from './contact-policy-form';

/**
 * Settings (PRD §5.1): Contact & calls · Reports (briefing schedules) · Notifications. The tab lives in the
 * address and its ids are the nav's (`FOUNDER_SECTIONS.settings.tabs`). Notification preferences for the founder
 * have no endpoint in P0, so that tab says so.
 */

export function SettingsView() {
  const ask = useAsk();
  const [tab, setTab] = useTabState('settings', 'contact');
  useFounderPageContext({ section: 'settings', filters: { tab } });
  return (
    <FounderPage
      eyebrow='Settings'
      title='Settings'
      description='How and when Rafii may contact you, which briefings it writes, and what stays off. Real calls, email and push are disabled in this release.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Explain my contact policy and briefing schedules, and what would have to change before a real call could be placed.' })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <Tabs value={tab} onValueChange={(value) => setTab(value)}>
        <TabsList variant='line' className='w-max'>
          <TabsTrigger value='contact'>Contact & calls</TabsTrigger>
          <TabsTrigger value='reports'>Reports</TabsTrigger>
          <TabsTrigger value='notifications'>Notifications</TabsTrigger>
        </TabsList>
        <TabsContent value='contact' className='pt-4'>
          <Panel title='Contact & calls' description='Policy for proactive calls and briefings: quiet hours, caps, allowed events and a daily budget.'>
            <ContactPolicyForm />
          </Panel>
        </TabsContent>
        <TabsContent value='reports' className='pt-4'>
          <Panel title='Briefing schedules' description='Daily or weekly briefings composed from the day’s receipts. Reports are readable on Overview even while delivery is off.'>
            <BriefingSchedules />
          </Panel>
        </TabsContent>
        <TabsContent value='notifications' className='pt-4'>
          <Panel title='Notifications' description='Which founder events notify you, on which channel.'>
            <StateMessage kind='unsupported' title='Founder notification preferences are not available yet' description='No notification-preferences endpoint exists for the founder in P0 (CONTRACTS §3). Incident and briefing contact follows the Contact & calls policy; product notifications keep their workspace settings.' />
          </Panel>
        </TabsContent>
      </Tabs>
    </FounderPage>
  );
}
