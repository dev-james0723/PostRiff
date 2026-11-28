'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { AiIntelligenceControl } from '@/components/rafii/ai-intelligence-control';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import type { CreativeAspect, CreativeModel, CreativeQuote, CreativeQuoteReply, CreativeSettings } from '@/lib/api/creative-video';
import { GenerationSettings } from './generation-settings';
import { FirstFramePicker, firstFrameModel } from './first-frame';
import { canAuthorizeQuote, formatCredits, initialSettings, parseCreditLimit, videoLevels } from './intelligence';
import { formatUsd } from './scene-edit';

export function RunwayAttribution() {
  return <a href='https://runwayml.com/' target='_blank' rel='noopener noreferrer'
    className='rafii-focus w-fit rounded-sm text-xs underline underline-offset-4'>Powered by Runway</a>;
}

function QuoteDetails({ quote, durationMs, aspect }: { quote: CreativeQuote; durationMs: number; aspect: CreativeAspect }) {
  const { outputProfile: output } = quote;
  const wallet = quote.availableMilliCredits;
  const rows = [
    ['Available balance', wallet == null ? 'No credit balance reported' : `${formatCredits(wallet)} credits`],
    ['Maximum for this take', quote.maximumMilliCredits == null ? 'Unavailable' : `${formatCredits(quote.maximumMilliCredits)} credits`],
    ['Estimated balance after', quote.remainingMilliCredits == null ? 'Unavailable' : quote.remainingMilliCredits < 0 ?
      `Short by ${formatCredits(-quote.remainingMilliCredits)} credits` : `${formatCredits(quote.remainingMilliCredits)} credits`],
    ['Scene output', `${durationMs / 1000} s · ${aspect}${output ? ` · ${output.width} × ${output.height}` : ''}`],
    ['Audio', quote.audio === 'generated' ? 'Generated with the clip' : quote.audio === 'silent' ? 'Silent clip' : 'Unspecified'],
    ['Typical wait for verified footage', quote.expectedGenerationSeconds == null ? 'Unmeasured' : `${Math.ceil(quote.expectedGenerationSeconds)} s`]
  ];
  return <div className='rafii-quiet grid gap-3 rounded-xl p-4'>
    <div className='grid gap-1'>
      <h4 className='text-sm font-medium'>Estimated AI Credits</h4>
      <p className='text-2xl font-semibold tabular-nums'>{quote.estimatedMilliCredits == null ? 'Unavailable' : formatCredits(quote.estimatedMilliCredits)}</p>
      {quote.label && <p className='text-sm'>{quote.label}</p>}
      {quote.recommendation && <p className='text-sm text-muted-foreground'>{quote.recommendation}</p>}
      {quote.provider === 'runway' && <RunwayAttribution />}
    </div>
    <dl className='grid grid-cols-2 gap-x-4 gap-y-2 border-t pt-3 text-sm'>
      {rows.map(([label, value]) => <div key={label} className='min-w-0'>
        <dt className='text-xs text-muted-foreground'>{label}</dt><dd className='mt-0.5 tabular-nums'>{value}</dd>
      </div>)}
    </dl>
    {quote.estimatedUsdMicro != null && <p className='text-xs text-muted-foreground'>
      Estimated provider cost {formatUsd(quote.estimatedUsdMicro)}{quote.billedSeconds ? ` for ${quote.billedSeconds} s` : ''}.
      {' '}Final usage settles after reconciliation.
    </p>}
    {Boolean(quote.limitations?.length) && <ul className='grid list-disc gap-1 pl-4 text-xs text-muted-foreground'>
      {quote.limitations?.map(note => <li key={note}>{note}</li>)}
    </ul>}
  </div>;
}

type QuoteRead = { key: string; reply?: CreativeQuoteReply; error?: string; code?: string };

export function SceneQuote({ models, durationMs, aspect, hasReference, disabled, localOnly = false, cloudAllowed = true, savedSettings, onSettings, onQuote, onGenerate }: {
  models: CreativeModel[]; durationMs: number; aspect: CreativeAspect; hasReference: boolean; disabled: boolean;
  localOnly?: boolean; cloudAllowed?: boolean; savedSettings?: CreativeSettings; onSettings?: (settings: CreativeSettings) => void;
  onQuote: (settings: CreativeSettings) => Promise<CreativeQuoteReply>; onGenerate: (quoteId: string) => void;
}) {
  const [settings, setSettings] = useState<CreativeSettings>(() => {
    if (localOnly) return { level: 'draft', mode: 'manual', model: 'storyboard-v1' };
    if (!savedSettings) return initialSettings;
    const { maxMilliCredits: _savedCap, ...rest } = savedSettings;
    return rest.firstFrameAssetId ? { ...rest, firstFrameConsent: false } : rest;
  });
  const [limit, setLimit] = useState(!localOnly && savedSettings?.maxMilliCredits != null ? String(savedSettings.maxMilliCredits / 1000) : '');
  const [nonce, setNonce] = useState(0);
  const [read, setRead] = useState<QuoteRead | null>(null);
  const [approved, setApproved] = useState('');
  const [expired, setExpired] = useState('');
  const spent = useRef('');
  const cap = limit.trim() ? parseCreditLimit(limit) : null;
  const issue = limit.trim() && cap == null ? 'Use a credit amount with up to three decimal places.'
    : settings.mode === 'budget' && cap == null ? 'Enter your maximum AI Credits in Advanced settings.'
    : settings.mode === 'manual' && !settings.model ? 'Choose a model in Advanced settings.'
    : settings.firstFrameAssetId && !settings.firstFrameConsent ? 'Confirm permission for the selected first frame to see its quote.' : '';
  const request = useMemo(() => cap === null ? settings : { ...settings, maxMilliCredits: cap }, [settings, cap]);
  const key = JSON.stringify([request, nonce]);
  useEffect(() => {
    if (disabled || issue) return;
    let active = true;
    const timer = setTimeout(() => {
      onQuote(request).then(reply => { if (active) setRead({ key, reply }); }, error => {
        if (active) setRead({ key, error: error instanceof Error ? error.message : 'The workspace could not price this scene.',
          code: typeof error?.code === 'string' ? error.code : undefined });
      });
    }, 220);
    return () => { active = false; clearTimeout(timer); };
  }, [request, key, issue, disabled, onQuote]);
  const current = read?.key === key && !disabled && !issue ? read : null;
  const quote = current?.reply?.quote;
  const catalog = current?.reply?.models ?? models;
  useEffect(() => {
    if (!quote?.id || !quote.expiresAt) return;
    const id = quote.id;
    const timer = setTimeout(() => { setExpired(id); setApproved(''); }, Math.max(0, quote.expiresAt * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [quote]);
  const local = localOnly || quote?.mediaKind === 'composed';
  const permitted = !localOnly || quote?.mediaKind === 'composed' && quote.estimatedMilliCredits === 0 &&
    quote.estimatedUsdMicro === 0 && quote.maximumMilliCredits === 0;
  const valid = canAuthorizeQuote(quote, Date.now()) && permitted && quote.id !== expired && spent.current !== quote.id;
  const canSubmit = valid && approved === quote.id;
  const fallback = catalog.find(item => item.id === 'storyboard-v1' && item.available);
  const offerDraft = !localOnly && fallback && (quote?.eligible === false || current?.code === 'creative_video_no_model');
  function choose(next: CreativeSettings) {
    setApproved(''); setSettings(next);
    if (!localOnly) onSettings?.(cap == null ? next : { ...next, maxMilliCredits: cap });
  }
  function refresh() { setApproved(''); setNonce(value => value + 1); }
  return <div className='grid gap-4'>
    <AiIntelligenceControl options={videoLevels} value={settings.level} disabled={disabled || localOnly}
      onChange={level => choose({ ...settings, level })} />
    {!localOnly && <FirstFramePicker enabled={cloudAllowed && models.some(m => m.id === firstFrameModel && m.available)}
      disabled={disabled} settings={settings} onChange={choose} />}
    {localOnly ? <p className='text-sm text-muted-foreground'>Editors can compose a free storyboard. A workspace approver can authorize cloud footage.</p> :
      <GenerationSettings settings={settings} onChange={choose} limit={limit} onLimit={value => {
        setApproved(''); setLimit(value);
        const max = parseCreditLimit(value);
        if (max != null || !value.trim()) onSettings?.(max == null ? settings : { ...settings, maxMilliCredits: max });
      }}
        models={catalog} hasReference={hasReference} disabled={disabled} />}
    <div className='grid min-w-0 gap-2' aria-live='polite' aria-atomic='true'>
      {disabled ? <p className='text-sm text-muted-foreground'>Save your changes and finish the current action to review a quote.</p> :
        issue ? <p className='text-sm'>{issue}</p> : current?.error ? <p className='text-sm text-destructive'>{current.error}</p> :
        !quote ? <p className='text-sm text-muted-foreground'>Getting a scene quote…</p> : <>
          {(quote.eligible || quote.estimatedMilliCredits != null) && <QuoteDetails quote={quote} durationMs={durationMs} aspect={aspect} />}
          {!quote.eligible && <div className='grid gap-1 text-sm'>
            <p>{quote.reason || 'No available model meets these settings.'}</p>
            <p className='text-muted-foreground'>Try a shorter scene, choose another model or use original footage from your Library.</p>
          </div>}
          {quote.id && !valid && quote.eligible && <p className='text-sm'>Refresh the estimate before authorizing this take.</p>}
        </>}
    </div>
    {!disabled && !issue && (current?.error || quote && !valid) && <div className='flex flex-wrap gap-2'>
      {offerDraft && <Button variant='glass' size='lg' onClick={() =>
        choose({ mode: 'manual', model: fallback.id, level: 'draft', audio: 'silent', resolution: '720p' })}>Use a draft storyboard</Button>}
      <Button variant='quiet' size='lg' onClick={refresh}>Refresh quote</Button>
      {offerDraft && <p className='basis-full text-xs text-muted-foreground'>The storyboard uses a silent 720p motion card with standard creative settings. Your credit limit still applies.</p>}
    </div>}
    <div className='flex items-start gap-3'>
      <Checkbox id='generation-consent' checked={Boolean(valid && approved === quote.id)} disabled={!valid}
        onCheckedChange={value => setApproved(value === true && valid ? quote.id : '')} />
      <Label htmlFor='generation-consent' className='min-h-8 leading-snug'>
        {local ? 'I approve composing this storyboard scene at the quoted limit.' : settings.firstFrameAssetId ?
          'I approve sending the selected Library photo, scene direction and authorized brand context to Google Cloud Veo for one take within the displayed limit.' :
          'I approve sending this scene’s direction and authorized brand context to the quoted provider for one take within the displayed limit.'}
      </Label>
    </div>
    <Button variant='action' size='control' className='w-fit' disabled={!canSubmit} onClick={() => {
      if (canSubmit && canAuthorizeQuote(quote, Date.now()) && spent.current !== quote.id) {
        spent.current = quote.id; setApproved(''); onGenerate(quote.id);
      }
    }}>{local ? 'Compose this scene' : 'Generate this scene'}</Button>
  </div>;
}
