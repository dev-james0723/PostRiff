'use client';

import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
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
  title: 'Outside the browser',
  sections: [
    {
      title: 'What this page shows today',
      description:
        'The accounts connected to this workspace with their verified level for each capability, the providers this deployment offers and their review status, and the tool registry. Personal tokens let your own scripts read, draft and propose within your current permissions.'
    },
    {
      title: 'What is planned',
      description:
        'Personal access tokens, signed webhooks and an MCP server for AI agents. They will read, draft and propose schedules. Approving, publishing, replying and connecting accounts will always stay in the app, with a person.'
    },
    {
      title: 'Where to look',
      description: 'Channels connects, reconnects and disconnects accounts. Models & providers decides where drafts are written.',
      links: [
        { title: 'Channels', url: '/app/channels' },
        { title: 'Models & providers', url: '/app/account/models' }
      ]
    }
  ]
};

function AccessFallback() {
  return (
    <div className='flex max-w-md flex-col items-center gap-3 text-center'>
      <p className='text-muted-foreground text-sm'>
        This page is for people who manage connections in this workspace: owners, admins and members given that permission. Ask one of them, or open Channels to see what is connected.
      </p>
      <Link href='/app/channels' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        Open Channels
      </Link>
    </div>
  );
}

/** Mounted only behind the access gate, so people without the permission never send these requests. */
function ApiContent() {
  const channels = useChannels();
  const tools = useToolRegistry();
  return (
    <div className='@container'>
      <div className='grid grid-cols-1 gap-4 @4xl:grid-cols-3'>
        <div className='min-w-0 @4xl:col-span-3'>
          <StatusStrip channels={channels} tools={tools} />
        </div>
        <div className='min-w-0 @4xl:col-span-3'><TokensCard /></div>
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
      pageDescription='What each connected account allows, the tool registry, and expiring tokens for your own scripts and agents.'
      infoContent={infoContent}
      access={canManage}
      accessFallback={<AccessFallback />}
    >
      <ApiContent />
    </PageContainer>
  );
}
