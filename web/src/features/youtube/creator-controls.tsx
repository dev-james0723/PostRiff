'use client';

import { useId, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { YouTubeCapability } from '@/lib/youtube/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';

type Prepare = (
  action: string,
  inputs: Record<string, unknown>,
  summary: string,
  options?: Record<string, unknown>
) => Promise<void>;
type Read = (resource: string, query?: Record<string, unknown>) => Promise<void>;
const control = 'h-10 w-full rounded-md border bg-background px-3 text-sm';

function Field({
  label,
  value,
  change,
  multiline = false
}: {
  label: string;
  value: string;
  change: (value: string) => void;
  multiline?: boolean;
}) {
  const id = useId();
  return (
    <div className='grid gap-1.5'>
      <Label htmlFor={id}>{label}</Label>
      {multiline ? (
        <Textarea id={id} value={value} onChange={(event) => change(event.target.value)} />
      ) : (
        <Input id={id} value={value} onChange={(event) => change(event.target.value)} />
      )}
    </div>
  );
}

export function LiveCreatorControls({
  capabilities,
  broadcast,
  stream,
  chat,
  busy,
  prepare,
  read
}: {
  capabilities?: Record<string, YouTubeCapability>;
  broadcast: string;
  stream: string;
  chat: string;
  busy: boolean;
  prepare: Prepare;
  read: Read;
}) {
  const id = useId();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [question, setQuestion] = useState('');
  const [choices, setChoices] = useState('');
  const [target, setTarget] = useState('');
  const [resource, setResource] = useState('');
  const [seconds, setSeconds] = useState('300');
  const [permanent, setPermanent] = useState(false);
  const [probe, setProbe] = useState(false);
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { role: 'owner' });
  const can = (name: string) =>
    capabilities?.[name]?.canExecute === true ||
    (owner && probe && capabilities?.[name]?.state === 'BLOCKED — ACCOUNT ELIGIBILITY');
  const reviewed: Prepare = (action, inputs, summary) =>
    prepare(action, inputs, summary, { eligibilityProbe: owner && probe });
  const base = { broadcastId: broadcast, liveChatId: chat };
  const button = (label: string, ready: boolean, action: () => Promise<void>) => (
    <Button variant='outline' disabled={busy || !ready} onClick={() => void action()}>
      {label}
    </Button>
  );
  return (
    <div className='grid gap-5'>
      {owner && (
        <Label className='flex items-center gap-2'>
          <input
            aria-label='Allow one reviewed Live Chat eligibility test'
            type='checkbox'
            checked={probe}
            onChange={(event) => setProbe(event.target.checked)}
          />
          Allow one reviewed Live Chat eligibility test
        </Label>
      )}
      {can('live_broadcast') && (
        <div className='grid gap-3 rounded-md border p-4'>
          <h3 className='text-sm font-medium'>Edit or remove an existing Live resource</h3>
          <Field label='Replacement title' value={title} change={setTitle} />
          <Field
            label='Replacement description'
            value={description}
            change={setDescription}
            multiline
          />
          <div className='flex flex-wrap gap-2'>
            {button('Review broadcast metadata', Boolean(broadcast && title), () =>
              reviewed(
                'broadcast.edit',
                { id: broadcast, patch: { snippet: { title, description } } },
                `Update broadcast ${broadcast}:\n${title}\n${description}`
              )
            )}
            {button('Review broadcast deletion', Boolean(broadcast), () =>
              reviewed(
                'broadcast.delete',
                { id: broadcast },
                `Delete broadcast ${broadcast}. This requires its exact ID and a fresh sign-in.`
              )
            )}
            {can('live_stream') && (
              <>
                {button('Review stream metadata', Boolean(stream && title), () =>
                  reviewed(
                    'stream.edit',
                    { id: stream, patch: { snippet: { title, description } } },
                    `Update stream ${stream}:\n${title}\n${description}. Ingestion settings stay immutable.`
                  )
                )}
                {button('Review stream deletion', Boolean(stream), () =>
                  reviewed(
                    'stream.delete',
                    { id: stream },
                    `Delete stream ${stream}. Bound broadcasts may prevent this operation.`
                  )
                )}
              </>
            )}
          </div>
        </div>
      )}
      {can('live_chat_write') && (
        <div className='grid gap-3 rounded-md border p-4'>
          <h3 className='text-sm font-medium'>Live Chat poll</h3>
          <Field
            label='Poll question (up to 100 characters)'
            value={question}
            change={setQuestion}
          />
          <Field
            label='Two to four choices, one per line (up to 35 characters each)'
            value={choices}
            change={setChoices}
            multiline
          />
          {button('Review poll creation', Boolean(broadcast && chat && question && choices), () =>
            reviewed(
              'chat.poll',
              { ...base, poll: { question, options: choices.split('\n') } },
              `Create a poll in ${chat}:\n${question}\n${choices}`
            )
          )}
          <Field
            label='Exact poll message ID from this chat'
            value={resource}
            change={setResource}
          />
          {button('Review poll closure', Boolean(broadcast && chat && resource), () =>
            reviewed(
              'chat.close_poll',
              { ...base, id: resource },
              `Close poll ${resource} in chat ${chat}.`
            )
          )}
        </div>
      )}
      {can('live_moderation') && (
        <div className='grid gap-3 rounded-md border p-4'>
          <h3 className='text-sm font-medium'>Live moderation</h3>
          {button('Read chat moderators', Boolean(broadcast && chat), () =>
            read('chat_moderators', { ...base, eligibilityProbe: owner && probe })
          )}
          <Field label='Target viewer Channel ID' value={target} change={setTarget} />
          <Field label='Timeout duration in seconds' value={seconds} change={setSeconds} />
          <Label className='flex items-center gap-2' htmlFor={id + '-ban'}>
            <input
              aria-label='Permanently ban this viewer'
              id={id + '-ban'}
              type='checkbox'
              checked={permanent}
              onChange={(event) => setPermanent(event.target.checked)}
            />
            Permanent ban, requiring exact ID confirmation
          </Label>
          <div className='flex flex-wrap gap-2'>
            {button('Review timeout or ban', Boolean(broadcast && chat && target), () =>
              reviewed(
                'chat.ban',
                {
                  ...base,
                  channelId: target,
                  permanent,
                  ...(!permanent ? { durationSeconds: Number(seconds) } : {})
                },
                `${permanent ? 'Permanently ban' : 'Time out'} viewer ${target} in chat ${chat}${permanent ? '' : ' for ' + seconds + ' seconds'}.`
              )
            )}
            {button('Review moderator addition', Boolean(broadcast && chat && target), () =>
              reviewed(
                'chat.add_moderator',
                { ...base, channelId: target },
                `Add ${target} as a moderator for chat ${chat}.`
              )
            )}
          </div>
          <Field
            label='Recorded ban or moderator resource ID'
            value={resource}
            change={setResource}
          />
          <div className='flex flex-wrap gap-2'>
            {button('Review removal of ban', Boolean(broadcast && chat && resource), () =>
              reviewed(
                'chat.unban',
                { ...base, id: resource },
                `Remove ban ${resource} from chat ${chat}.`
              )
            )}
            {button('Review moderator removal', Boolean(broadcast && chat && resource), () =>
              reviewed(
                'chat.remove_moderator',
                { ...base, id: resource },
                `Remove moderator ${resource} from chat ${chat}.`
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function MetadataControls({
  kind,
  identifier,
  busy,
  prepare
}: {
  kind: 'video' | 'playlist';
  identifier: string;
  busy: boolean;
  prepare: Prepare;
}) {
  const id = useId();
  const [language, setLanguage] = useState('');
  const [localizations, setLocalizations] = useState('');
  const [tags, setTags] = useState('');
  const [category, setCategory] = useState('');
  const [kids, setKids] = useState('');
  const [synthetic, setSynthetic] = useState('');
  const [error, setError] = useState('');
  async function review() {
    try {
      const patch: Record<string, unknown> = {};
      if (language) patch.snippet = { defaultLanguage: language };
      if (kind === 'video') {
        if (category || tags)
          patch.snippet = {
            ...(patch.snippet as Record<string, unknown> | undefined),
            ...(category ? { categoryId: category } : {}),
            ...(tags ? { tags: tags.split(',') } : {})
          };
        const status: Record<string, boolean> = {};
        if (kids) status.selfDeclaredMadeForKids = kids === 'yes';
        if (synthetic) status.containsSyntheticMedia = synthetic === 'yes';
        if (Object.keys(status).length) patch.status = status;
      }
      if (localizations) patch.localizations = JSON.parse(localizations);
      setError('');
      await prepare(
        kind + '.edit',
        { id: identifier, patch },
        `Update ${kind} ${identifier}:\n${JSON.stringify(patch, null, 2)}`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Invalid metadata.');
    }
  }
  return (
    <details className='rounded-md border p-4'>
      <summary className='cursor-pointer text-sm font-medium'>
        Language, localized metadata and declarations
      </summary>
      <div className='mt-4 grid gap-3'>
        <Field label='Default language (BCP 47)' value={language} change={setLanguage} />
        <Field
          label='Localized titles and descriptions (JSON keyed by language)'
          value={localizations}
          change={setLocalizations}
          multiline
        />
        {kind === 'video' && (
          <>
            <Field label='Category ID' value={category} change={setCategory} />
            <Field
              label='Replacement tags, comma separated (leave empty to preserve)'
              value={tags}
              change={setTags}
            />
            {[
              ['Audience declaration', kids, setKids],
              ['Altered or synthetic media declaration', synthetic, setSynthetic]
            ].map(([label, value, setter], index) => (
              <div className='grid gap-1.5' key={index}>
                <Label htmlFor={id + index}>{String(label)}</Label>
                <select
                  id={id + index}
                  className={control}
                  value={String(value)}
                  onChange={(event) => (setter as (v: string) => void)(event.target.value)}
                >
                  <option value=''>Preserve existing declaration</option>
                  <option value='no'>No</option>
                  <option value='yes'>Yes</option>
                </select>
              </div>
            ))}
            <p className='text-xs text-muted-foreground'>
              Audience and realistic altered media are your declarations. Ordinary AI copywriting
              does not require an altered-media declaration by itself.
            </p>
          </>
        )}
        {error && (
          <p role='alert' className='text-sm text-destructive'>
            {error}
          </p>
        )}
        <Button variant='outline' disabled={busy || !identifier} onClick={() => void review()}>
          Review metadata change
        </Button>
      </div>
    </details>
  );
}
