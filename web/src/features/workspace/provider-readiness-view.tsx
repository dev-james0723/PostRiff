'use client';

import PageContainer from '@/components/layout/page-container';
import { StateMessage, Surface } from '@/components/rafii';
import { useChannels } from '@/lib/api/hooks';
import type { ProviderView } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';

const labels: Record<string, string> = {
  clientIdConfigured: 'Client ID configured',
  clientSecretConfigured: 'Confidential client credential configured',
  redirectUriConfigured: 'Redirect URI configured',
  providerAppCreated: 'Provider app created',
  oauthLiveTest: 'OAuth live test',
  tokenRefreshLiveTest: 'Token refresh live test',
  webhookVerified: 'Webhook verified',
  publishingPermission: 'Publishing permission',
  analyticsPermission: 'Analytics permission',
  commentsPermission: 'Comments permission',
  productionEnabled: 'Production enabled'
};

function Check({ label, value }: { label: string; value: boolean }) {
  return (
    <li className='flex items-center justify-between gap-3 border-b border-border/50 py-2 last:border-0'>
      <span className='text-sm'>{label}</span>
      <span
        className={value ? 'text-foreground text-xs font-medium' : 'text-muted-foreground text-xs'}
      >
        {value ? 'Verified' : 'Not verified'}
      </span>
    </li>
  );
}

function ProviderPanel({ provider }: { provider: ProviderView }) {
  const readiness = provider.readinessChecklist;
  if (!readiness) return null;
  const checks = Object.entries(labels).map(
    ([key, label]) => [label, Boolean(readiness[key as keyof typeof readiness])] as const
  );
  return (
    <Surface material='glass' radius='card' padding='md' className='flex flex-col gap-4'>
      <header className='flex flex-wrap items-start justify-between gap-3'>
        <div>
          <h2 className='text-lg font-medium'>{provider.platform}</h2>
          <p className='text-muted-foreground text-xs'>
            Wave {provider.wave} · {provider.readinessState?.replaceAll('_', ' ')}
          </p>
        </div>
        <span className='rafii-field rounded-full px-2.5 py-1 text-xs'>
          {readiness.productionEnabled ? 'Production enabled' : 'Not production enabled'}
        </span>
      </header>
      <ul>
        {checks.map(([label, value]) => (
          <Check key={label} label={label} value={value} />
        ))}
      </ul>
      <div className='grid gap-3 text-xs md:grid-cols-2'>
        <div>
          <p className='text-muted-foreground mb-1'>Provider verification</p>
          <p>{readiness.providerVerificationStatus === 'verified' ? 'Verified' : 'Not verified'}</p>
        </div>
        <div>
          <p className='text-muted-foreground mb-1'>Redirect URI</p>
          <p className='break-all'>{provider.callbackUri ?? 'Not configured'}</p>
        </div>
        <div>
          <p className='text-muted-foreground mb-1'>Requested scopes</p>
          <p className='break-words font-mono'>{readiness.requestedScopes.join(', ') || 'None'}</p>
        </div>
        <div>
          <p className='text-muted-foreground mb-1'>Approved scopes</p>
          <p className='break-words font-mono'>
            {readiness.approvedScopes.join(', ') || 'None verified'}
          </p>
        </div>
      </div>
      <p className='text-muted-foreground text-xs'>
        Credential values are never returned to this page. A configured credential is not a live OAuth
        or publishing verification.
      </p>
    </Surface>
  );
}

export function ProviderReadinessView() {
  const access = useWorkspaceAccess();
  const channels = useChannels();
  const allowed = checkAccess(access, { role: 'admin' });
  const providers = (channels.data?.providers ?? []).filter((provider) => provider.wave === '4A');
  return (
    <PageContainer
      pageTitle='Provider readiness'
      pageDescription='Internal evidence for Wave 4 provider setup. Each gate is independent; no green aggregate hides a missing permission.'
    >
      {!allowed ? (
        <StateMessage kind='error' title='Admin access is required.' />
      ) : channels.isLoading ? (
        <StateMessage kind='loading' title='Loading provider readiness…' />
      ) : channels.isError ? (
        <StateMessage kind='error' title='Provider readiness could not be loaded.' />
      ) : (
        <div className='grid gap-4 xl:grid-cols-2'>
          {providers.map((provider) => (
            <ProviderPanel key={provider.id} provider={provider} />
          ))}
        </div>
      )}
    </PageContainer>
  );
}
