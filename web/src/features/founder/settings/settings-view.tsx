'use client';

import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useFounderPageContext } from '@/lib/founder/page-context';
import { useFounderScope } from '../customers/kit/api';
import { useAsk } from '../customers/kit/ask';
import { FounderPage, Panel } from '../customers/kit/page-frame';
import { useTabState } from '../customers/kit/tabs';
import { ContactPolicyForm } from './contact-policy-form';
import { NotificationsTab } from './notifications-tab';
import { OpsWorkspacePanel } from './ops-workspace-panel';
import { ReportsTab } from './reports-tab';

/**
 * Settings (PRD §5.1, CONTRACTS §8.E): Contact & calls (policy and the founder workspace) · Reports (briefing versions
 * with their receipts, and schedules) · Notifications (channel readiness, preferences, notices) · Budgets · Security.
 * The tab lives in the address and its ids are the nav's (`FOUNDER_SECTIONS.settings.tabs`). Budgets and Security have
 * no settings to change yet, so they say what they will hold and offer no control.
 */

function BudgetsTab() {
  return (
    <Panel title='Budgets' description='Spending limits for what Rafii does on your behalf.'>
      <StateMessage
        kind='unsupported'
        layout='inline'
        title='Budgets are not editable here yet'
        description='This tab will hold the founder workspace’s AI and voice spending limits and their alert thresholds. Today the daily contact budget is set in Contact & calls, and request rates for Founder Rafii and voice are fixed by Control.'
      />
    </Panel>
  );
}

function SecurityTab() {
  const { capabilities } = useFounderScope();
  return (
    <Panel title='Security' description='Who may use Founder Admin, and what each operator may do.'>
      <div className='flex flex-col gap-3'>
        <StateMessage
          kind='unsupported'
          layout='inline'
          title='Operator security is not editable here yet'
          description='This tab will hold operators, their capabilities and second-factor status. Today operators are managed outside this page, and every settings change already needs a second factor from the last five minutes.'
        />
        {capabilities.length > 0 && (
          <div className='flex flex-col gap-1.5'>
            <span className='text-foreground text-sm font-medium'>Capabilities in this session</span>
            <ul className='flex flex-wrap gap-1.5' aria-label='Capabilities in this session'>
              {capabilities.map((capability) => (
                <li key={capability} className='rafii-quiet rounded-full px-2.5 py-1 font-mono text-xs'>
                  {capability}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}

export function SettingsView() {
  const ask = useAsk();
  const [tab, setTab] = useTabState('settings', 'contact');
  useFounderPageContext({ section: 'settings', filters: { tab } });
  return (
    <FounderPage
      eyebrow='Settings'
      title='Settings'
      description='How and when Rafii may contact you, which briefings it writes, which notices reach you, and where Founder Rafii runs. Calls, email and push stay off until Contact & calls and the server flags allow them.'
      actions={
        <Button variant='glass' size='control' onClick={() => ask({ prompt: 'Explain my contact policy, notification channels and briefing schedules, and what would have to change before a real call, email or push could go out.' })}>
          <Icons.sparkles /> Ask Rafii
        </Button>
      }
    >
      <Tabs value={tab} onValueChange={(value) => setTab(value)}>
        <div className='scrollbar-hide -mx-1 overflow-x-auto px-1'>
          <TabsList variant='line' className='w-max'>
            <TabsTrigger value='contact'>Contact & calls</TabsTrigger>
            <TabsTrigger value='reports'>Reports</TabsTrigger>
            <TabsTrigger value='notifications'>Notifications</TabsTrigger>
            <TabsTrigger value='budgets'>Budgets</TabsTrigger>
            <TabsTrigger value='security'>Security</TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value='contact' className='flex flex-col gap-4 pt-4'>
          <Panel title='Contact & calls' description='Policy for proactive calls and briefings: quiet hours, caps, allowed events and a daily budget.'>
            <ContactPolicyForm />
          </Panel>
          <OpsWorkspacePanel />
        </TabsContent>
        <TabsContent value='reports' className='pt-4'>
          <ReportsTab />
        </TabsContent>
        <TabsContent value='notifications' className='pt-4'>
          <NotificationsTab />
        </TabsContent>
        <TabsContent value='budgets' className='pt-4'>
          <BudgetsTab />
        </TabsContent>
        <TabsContent value='security' className='pt-4'>
          <SecurityTab />
        </TabsContent>
      </Tabs>
    </FounderPage>
  );
}
