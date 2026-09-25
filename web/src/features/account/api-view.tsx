'use client';

import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { StateMessage } from '@/components/rafii';
import { buttonVariants } from '@/components/ui/button';
import { useChannels } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { TokensCard } from './api/tokens-card';
import { AccountsCard } from './api/accounts-card';
import { NotYetCard } from './api/not-yet-card';
import { StatusStrip } from './api/status-strip';
import { useToolRegistry } from './api/tool-registry';
import { ToolsCard } from './api/tools-card';

const infoContent = {
  title: 'API & integrations',
  sections: [
    {
      title: 'Tokens',
      description: 'Let your own scripts read, draft and propose schedules. Approving, publishing and connecting accounts stay in the app.'
    },
    {
      title: 'Coming later',
      description: 'Webhooks and an MCP server for AI agents.'
    },
    {
      title: 'Where to look',
      description: 'Channels manages accounts. Models picks who writes drafts.',
      links: [
        { title: 'Channels', url: '/app/channels' },
        { title: 'Models', url: '/app/account/models' }
      ]
    }
  ]
};

function AccessFallback() {
  return (
    <StateMessage
      kind='permission'
      title='Only people who manage connections can see this'
      description='Ask an owner or admin.'
      action={
        <Link href='/app/channels' className={buttonVariants({ variant: 'glass', size: 'control' })}>
          Open Channels
        </Link>
      }
      className='w-full max-w-md'
    />
  );
}

/** Mounted only behind the access gate, so people without the permission never send these requests. */
function ApiContent() {
  const channels = useChannels();
  const tools = useToolRegistry();
  return (
    <div className='@container'>
      <div className='grid grid-cols-1 gap-8 @4xl:grid-cols-3'>
        <div className='flex min-w-0 flex-col gap-4 @4xl:col-span-3'>
          <StatusStrip channels={channels} tools={tools} />
          <TokensCard />
        </div>
        <div className='min-w-0 @4xl:col-span-2'>
          <AccountsCard channels={channels} />
        </div>
        <div className='min-w-0'>
          <ToolsCard tools={tools} />
        </div>
        <div className='min-w-0 @4xl:col-span-3'>
          <NotYetCard />
        </div>
      </div>
    </div>
  );
}

export function ApiView() {
  const canManage = checkAccess(useWorkspaceAccess(), { permission: 'manage_connections' });
  return (
    <PageContainer
      pageTitle='API & integrations'
      infoContent={infoContent}
      access={canManage}
      accessFallback={<AccessFallback />}
    >
      <ApiContent />
    </PageContainer>
  );
}
