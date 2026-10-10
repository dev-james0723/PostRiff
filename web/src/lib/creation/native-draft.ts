/**
 * What a review shows beside one native draft (Content Skills A29): the exact destination, the native format, whether
 * the platform's writing instructions reached the writer, what media the format still needs, and whether Rafii can
 * publish it. Read-only: every value comes from the draft the server wrote (`rafii.native-draft.v1`); nothing here
 * checks or grants a connection, an approval or a publish.
 */
import { formatLabel } from './capabilities';

export interface NativeSkillRoute {
  qualified: boolean;
  generic?: boolean;
  missing?: string[];
  cut?: boolean;
}

export interface NativeDraft {
  schema?: string;
  platform?: string;
  formatId?: string;
  unresolved?: string[];
  missingContent?: string[];
  media?: { required?: string; state?: string; reason?: string };
  constraints?: { verified?: boolean };
  readiness?: { draft?: string; export?: string; publish?: string; publishNote?: string };
  skillRoute?: NativeSkillRoute | null;
}

export type FactTone = 'neutral' | 'attention';

export interface DraftFact {
  key: 'destination' | 'format' | 'writing' | 'media' | 'publish' | 'limits';
  label: string;
  value: string;
  tone: FactTone;
}

const BINDING_WORDS: Record<string, string> = {
  page_ref: 'Facebook Page', board_ref: 'board', subreddit: 'subreddit', chat_ref: 'chat', channel_ref: 'channel',
  group_ref: 'group', location_ref: 'location', official_account_ref: 'official account', destination_url: 'link',
  did: 'account DID', pds: 'data server'
};

function bindingWord(name: string): string {
  return BINDING_WORDS[name] ?? name.replace(/_ref$/, '').replaceAll('_', ' ');
}

const MEDIA_WORDS: Record<string, string> = {
  video: 'Needs your video · Rafii wrote the script, not a video',
  image: 'Needs an image',
  document: 'Needs a document'
};

/**
 * Facts in display order. `connected` is whether the workspace has a connection on this platform (the caller knows;
 * `undefined` when it doesn't). A draft without a native record (older or formatless) gets the destination only.
 */
export function draftFacts(variant: { platform: string; account?: string; channelId?: string; native?: NativeDraft | null }, connected?: boolean): DraftFact[] {
  const native = variant.native && typeof variant.native === 'object' ? variant.native : null;
  const facts: DraftFact[] = [];
  const unresolved = native?.unresolved ?? [];
  const account = variant.account
    ? variant.account
    : connected === false
      ? `No ${variant.platform} account connected · draft, copy and export only`
      : 'Not written for a specific account';
  facts.push({ key: 'destination', label: 'Account', value: account, tone: variant.account ? 'neutral' : 'attention' });
  if (!native) return facts;
  if (native.formatId) facts.push({ key: 'format', label: 'Format', value: formatLabel(variant.platform, native.formatId), tone: 'neutral' });
  const route = native.skillRoute;
  if (route) {
    facts.push(
      route.qualified
        ? { key: 'writing', label: 'Writing guide', value: `${variant.platform} guide applied in full`, tone: 'neutral' }
        : {
            key: 'writing',
            label: 'Writing guide',
            value: `Unverified generic draft · ${route.cut ? 'the guide was cut short' : `missing ${(route.missing ?? []).length || 'some'} required instruction${(route.missing ?? []).length === 1 ? '' : 's'}`}`,
            tone: 'attention'
          }
    );
  } else {
    facts.push({ key: 'writing', label: 'Writing guide', value: 'Not recorded for this draft', tone: 'attention' });
  }
  const media = native.media;
  if (media && media.required && media.required !== 'optional') {
    const attached = media.state === 'attached_unvalidated';
    facts.push({ key: 'media', label: 'Media', value: attached ? 'Attached · not yet checked against the format' : (MEDIA_WORDS[media.required] ?? 'Needs media'), tone: attached ? 'neutral' : 'attention' });
  }
  const publish = native.readiness?.publish;
  const missingPlace = unresolved.map(bindingWord);
  const publishValue =
    publish === 'export_only'
      ? 'Export only · Rafii can’t publish this format yet'
      : missingPlace.length
        ? `Needs ${missingPlace.slice(0, 3).join(', ')}${missingPlace.length > 3 ? ` and ${missingPlace.length - 3} more` : ''} before publishing`
        : connected === false
          ? `Connect ${variant.platform} to publish`
          : 'Not checked · publishing runs the live account and approval checks';
  facts.push({ key: 'publish', label: 'Publishing', value: publishValue, tone: publish === 'export_only' || missingPlace.length || connected === false ? 'attention' : 'neutral' });
  if (native.constraints && native.constraints.verified === false) {
    facts.push({ key: 'limits', label: 'Limits', value: 'Platform limits for this format are unverified', tone: 'neutral' });
  }
  return facts;
}
