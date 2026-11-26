'use client';

import { useId, useState } from 'react';
import Link from 'next/link';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import { disconnectedByCustomer } from '@/lib/channels/state';
import type { AccountReceipt } from '@/lib/voice-import/coverage';
import { routeOffer, routeReason } from '@/lib/voice-import/guides';
import { platformName } from '@/lib/voice-import/labels';
import type { ImportRouteRow } from '@/lib/voice-import/types';
import { Band, SelectField } from '../../rafii-parts';
import type { BrainTranslate } from '../brain-types';
import { ConsentStep, consentReady, EMPTY_CONSENT } from './voice-import-consent';
import type { ConsentValue } from './voice-import-consent';
import { UploadFlow } from './voice-import-upload';
import { useInvalidateVoiceImports, useVoiceImportApi } from './use-voice-import';

/** The provider id a connected account belongs to (`LinkedIn` → `linkedin`), as the routes list names platforms. */
export function providerOf(channel: Pick<ChannelView, 'platform'>, providers: ProviderView[]): string {
  return (providers.find((provider) => provider.platform === channel.platform)?.id ?? channel.platform).toLowerCase();
}

function OfficialFlow({ provider, accounts, receipts, canManage, t, focusConnectionId, onClose }: { provider: string; accounts: ChannelView[]; receipts: AccountReceipt[]; canManage: boolean; t: BrainTranslate; focusConnectionId?: string; onClose: () => void }) {
  const { api, w } = useVoiceImportApi();
  const invalidate = useInvalidateVoiceImports();
  const name = platformName(provider);
  const [chosen, setChosen] = useState(accounts.some((account) => account.id === focusConnectionId) ? (focusConnectionId as string) : accounts.length === 1 ? accounts[0].id : '');
  const [consent, setConsent] = useState<ConsentValue>(EMPTY_CONSENT);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');
  const running = receipts.some((receipt) => receipt.active?.connectionId === chosen && chosen !== '');

  async function start() {
    if (!chosen || !consentReady(consent) || starting) return;
    setStarting(true);
    setError('');
    try {
      await api.request(w, { route: 'official_api', provider, connectionId: chosen, consent: { ownership: consent.ownership, voiceScope: consent.voiceScope, confirmed: true } });
      await invalidate();
      onClose();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '');
      void invalidate();
      setStarting(false);
    }
  }

  if (!accounts.length) {
    return (
      <div className='flex min-w-0 flex-col gap-3 text-sm'>
        <p>
          {t(`No ${name} account is connected to this workspace yet.`, `此工作區尚未連接任何 ${name} 帳戶。`, `此工作区尚未连接任何 ${name} 账户。`)}
        </p>
        <div className='flex flex-wrap gap-2'>
          <Link href={`/app/channels?connect=${encodeURIComponent(provider)}`} className='rafii-focus text-foreground inline-flex min-h-11 items-center rounded-sm underline underline-offset-4'>
            {t(`Connect ${name} on Channels`, `前往 Channels 連接 ${name}`, `前往 Channels 连接 ${name}`)}
          </Link>
          <Button variant='quiet' className='min-h-11' onClick={onClose}>
            {t('Close', '關閉', '关闭')}
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className='flex min-w-0 flex-col gap-4' data-testid={`voice-import-connect-${provider}`}>
      <p className='text-sm leading-relaxed'>
        {t(
          'Rafii reads this account’s posts page by page through the platform’s official connection. The receipt then shows what was read, what was left out and whether more remain.',
          'Rafii 會經平台的官方連接逐頁讀取此帳戶的貼文，其後收據會顯示已讀取的內容、未採用的內容，以及是否還有更多。',
          'Rafii 会经平台的官方连接逐页读取此账户的帖子，其后回执会显示已读取的内容、未采用的内容，以及是否还有更多。'
        )}
      </p>
      {accounts.length > 1 ? (
        <SelectField label={t('Account to read', '要讀取的帳戶', '要读取的账户')} value={chosen} onChange={(event) => setChosen(event.target.value)} disabled={starting}>
          <option value=''>{t('Choose an account', '選擇帳戶', '选择账户')}</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.account}
            </option>
          ))}
        </SelectField>
      ) : (
        <p className='text-sm'>
          <span className='text-muted-foreground'>{t('Account to read', '要讀取的帳戶', '要读取的账户')}: </span>
          <span className='text-foreground font-medium break-words'>{accounts[0].account}</span>
        </p>
      )}
      {running && (
        <p role='status' className='text-muted-foreground text-sm'>
          {t('An import for this account is already running. Its receipt shows the progress.', '此帳戶的匯入正在進行，收據會顯示進度。', '此账户的导入正在进行，回执会显示进度。')}
        </p>
      )}
      <ConsentStep value={consent} onChange={setConsent} disabled={!canManage || starting} t={t} />
      {!canManage && <p className='text-muted-foreground text-xs'>{t('Only a member who can manage connections can start an import.', '只有可管理連接的成員才可開始匯入。', '只有可管理连接的成员才可开始导入。')}</p>}
      {error && <StateMessage kind='error' layout='inline' title={error} />}
      <div className='flex flex-wrap gap-2'>
        <Button variant='action' className='min-h-11' data-testid={`voice-import-start-${provider}`} disabled={!canManage || !chosen || running || !consentReady(consent) || starting} onClick={() => void start()}>
          {starting ? (
            <>
              <Icons.spinner className='motion-safe:animate-spin' aria-hidden /> {t('Starting…', '正在開始…', '正在开始…')}
            </>
          ) : (
            t('Start import', '開始匯入', '开始导入')
          )}
        </Button>
        <Button variant='quiet' className='min-h-11' disabled={starting} onClick={onClose}>
          {t('Close', '關閉', '关闭')}
        </Button>
      </div>
    </div>
  );
}

/**
 * One platform: which route works today, why the other does not, and the flow for the one the person picks.
 * A route the workspace reports as unavailable is never offered as a button.
 */
export function PlatformRow({
  row,
  channels,
  providers,
  receipts,
  canManage,
  t,
  focus
}: {
  row: ImportRouteRow;
  channels: ChannelView[];
  providers: ProviderView[];
  receipts: AccountReceipt[];
  canManage: boolean;
  t: BrainTranslate;
  focus?: { connectionId?: string };
}) {
  const id = useId();
  const locale = useGenUiLocale();
  const offer = routeOffer(row);
  const name = platformName(row.provider);
  const accounts = channels.filter((channel) => providerOf(channel, providers) === row.provider && !disconnectedByCustomer(channel));
  const [mode, setMode] = useState<'official' | 'upload' | null>(focus ? (offer.official ? 'official' : offer.upload ? 'upload' : null) : null);

  return (
    <Band as='li' data-testid={`voice-import-platform-${row.provider}`}>
      <div className='flex min-w-0 flex-wrap items-center gap-3'>
        <ChannelIcon platform={row.provider} name={name} size='md' />
        <h4 id={`${id}-name`} className='text-foreground min-w-0 flex-1 text-sm font-medium'>
          {name}
        </h4>
      </div>
      <dl className='flex min-w-0 flex-col gap-2 text-sm'>
        <div>
          <dt className='text-foreground font-medium'>{t('Connected account', '已連接帳戶', '已连接账户')}</dt>
          <dd className='text-muted-foreground'>
            {offer.official
              ? t('Available: Rafii can read the posts of an account you connect.', '可用：Rafii 可讀取你所連接帳戶的貼文。', '可用：Rafii 可读取你所连接账户的帖子。')
              : `${t('Not available.', '未能提供。', '无法提供。')} ${routeReason(row.provider, 'official', row.official?.reason, locale.language)}`}
          </dd>
        </div>
        <div>
          <dt className='text-foreground font-medium'>{t('Export file', '匯出檔案', '导出文件')}</dt>
          <dd className='text-muted-foreground'>
            {offer.upload
              ? offer.official
                ? t('Available: upload the export the platform gives you.', '可用：上載平台提供的匯出檔。', '可用：上传平台提供的导出文件。')
                : t('Available, and the way to bring these posts in today: upload the export the platform gives you.', '可用，亦是現時匯入這些貼文的方法：上載平台提供的匯出檔。', '可用，也是目前导入这些帖子的方法：上传平台提供的导出文件。')
              : `${t('Not available.', '未能提供。', '无法提供。')} ${routeReason(row.provider, 'export', row.export?.reason, locale.language)}`}
          </dd>
        </div>
      </dl>
      {mode === null && (offer.official || offer.upload) && (
        <div className='flex flex-wrap gap-2'>
          {offer.official && (
            <Button variant='glass' className='min-h-11' aria-label={`${t('Connect and import', '連接並匯入', '连接并导入')}: ${name}`} onClick={() => setMode('official')}>
              <Icons.link aria-hidden /> {t('Connect and import', '連接並匯入', '连接并导入')}
            </Button>
          )}
          {offer.upload && (
            <Button variant='glass' className='min-h-11' aria-label={`${t('Upload export', '上載匯出檔', '上传导出文件')}: ${name}`} onClick={() => setMode('upload')}>
              <Icons.upload aria-hidden /> {t('Upload export', '上載匯出檔', '上传导出文件')}
            </Button>
          )}
        </div>
      )}
      {mode === 'official' && <OfficialFlow provider={row.provider} accounts={accounts} receipts={receipts} canManage={canManage} t={t} focusConnectionId={focus?.connectionId} onClose={() => setMode(null)} />}
      {mode === 'upload' && <UploadFlow provider={row.provider} receipts={receipts} canManage={canManage} t={t} onClose={() => setMode(null)} />}
    </Band>
  );
}
