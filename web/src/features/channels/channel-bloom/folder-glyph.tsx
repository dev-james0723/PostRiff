'use client';

import type { CSSProperties } from 'react';
import { IconBriefcase, IconFolder, IconHeart, IconMusic, IconSparkles, IconWorld, type Icon } from '@tabler/icons-react';
import { ChannelIcon } from '@/components/channel-icon';
import type { ChannelFolder } from '@/lib/api/types';
import type { FolderAccount, FolderSymbol } from '@/lib/channels/folders';
import { cn } from '@/lib/utils';
import { peekAccounts } from './helpers';

export const SYMBOL_ICONS: Record<FolderSymbol, Icon> = {
  folder: IconFolder,
  spark: IconSparkles,
  music: IconMusic,
  briefcase: IconBriefcase,
  heart: IconHeart,
  globe: IconWorld
};

export function symbolIcon(symbol: string | undefined): Icon {
  return (SYMBOL_ICONS as Record<string, Icon>)[symbol ?? ''] ?? IconFolder;
}

const EASE = 'ease-[var(--rafii-ease-soft)]';

/* The three peeking marks lean out a little on hover and fully when the folder is inspected
   (prototype `folders-v9.css`); `--i` is the mark's index. */
const PEEK =
  'rafii-spatial-motion block transition-transform duration-500 [filter:drop-shadow(0_3px_2px_#0004)] ' +
  '[transform:translateY(calc(var(--i)*2px))_rotate(calc((var(--i)_-_1)*10deg))] ' +
  'group-hover/card:[transform:translateY(calc(-3px_+_var(--i)*1px))_rotate(calc((var(--i)_-_1)*13deg))] ' +
  'group-data-[inspected=true]/glyph:[transform:translateY(calc(-8px_+_var(--i)*2px))_rotate(calc((var(--i)_-_1)*13deg))]';

const FRONT =
  'rafii-spatial-motion absolute top-[39px] right-[5px] left-[5px] flex h-[35px] origin-bottom items-center rounded-[7px_7px_10px_10px] ' +
  'bg-[linear-gradient(135deg,#fefefe77,#9999,#eeeeee55)] shadow-[inset_0_6px_12px_-10px_#fff,0_9px_12px_-10px_#000b] backdrop-blur-[10px] ' +
  'transition-transform duration-500 dark:bg-[linear-gradient(135deg,#b9b9b94d,#65656580_52%,#bbbbbb36)] ' +
  'group-hover/card:[transform:rotateX(-12deg)] group-data-[inspected=true]/glyph:[transform:rotateX(-23deg)_translateY(2px)]';

/**
 * The folder object (v9 addendum §2): a backplate, up to three member marks peeking out behind a
 * translucent front that carries the folder's symbol. Decorative: the card next to it says
 * everything in words. Brand marks keep their colour (contracts rule 1); the folder itself is
 * Rafii grey.
 */
export function FolderGlyph({ folder, accounts, inspected = false, className }: { folder: Pick<ChannelFolder, 'symbol' | 'accountIds'>; accounts: readonly FolderAccount[]; inspected?: boolean; className?: string }) {
  const { shown, more } = peekAccounts(folder, accounts);
  const Symbol = symbolIcon(folder.symbol);
  return (
    <span aria-hidden data-glyph='' data-inspected={inspected ? 'true' : 'false'} className={cn('group/glyph rafii-spatial-motion pointer-events-none relative block h-[78px] w-[100px] shrink-0 transition-transform duration-300 [perspective:260px]', className)}>
      <span className='absolute top-[17px] left-2 block h-[51px] w-[84px] rounded-[7px_10px_9px_9px] bg-[linear-gradient(155deg,#9c9c9c,#535353)] shadow-[0_12px_15px_-8px_#0008] [clip-path:polygon(0_0,36%_0,46%_14%,100%_14%,100%_100%,0_100%)]' />
      <span className='absolute top-3 left-3.5 z-0 flex items-center [transform-style:preserve-3d]'>
        {shown.map((account, i) => (
          <span key={account.id} style={{ ['--i' as string]: i } as CSSProperties} className={cn(PEEK, EASE, i > 0 && '-ml-0.5')}>
            <ChannelIcon platform={account.platform} name={account.platform} size='md' className='h-[30px] w-[27px] rounded-lg shadow-[inset_0_7px_9px_-12px_#fff]' />
          </span>
        ))}
      </span>
      <span className={cn(FRONT, EASE)}>
        <span className='ml-3 grid place-items-center text-[#1119] dark:text-[#f7f7f7a8]'>
          <Symbol className='size-[15px]' stroke={1.75} />
        </span>
        <i className='mr-[13px] ml-auto h-[3px] w-[19px] rounded-sm bg-[#1112] dark:bg-[#ffffff27]' />
        {more > 0 && <b className='mr-1.5 text-[10px] leading-none font-semibold text-[#111c] dark:text-white'>+{more}</b>}
      </span>
    </span>
  );
}
