'use client';

import { useEffect, useId, useRef, type CSSProperties } from 'react';
import { ChannelIcon } from '@/components/channel-icon';
import type { FolderAccount, FolderSymbol } from '@/lib/channels/folders';
import { useMotionPreference } from '@/lib/rafii/motion';
import { symbolIcon } from './folder-glyph';
import styles from './folder-preview.module.css';

// The reference opens the two leaves, receives the object behind the front leaf,
// lights the pocket, then settles. All moving layers share this coordinate space.
/** Decorative live preview. Membership stays controlled by FolderEditor. */
export function FolderPreview({
  symbol,
  accountIds,
  accounts
}: {
  symbol: FolderSymbol;
  accountIds: readonly string[];
  accounts: readonly FolderAccount[];
}) {
  const uid = useId().replace(/:/g, '');
  const root = useRef<HTMLSpanElement>(null);
  const initialMembers = useRef(new Set(accountIds));
  const previousMembers = useRef(new Set(accountIds));
  const { reduced } = useMotionPreference();
  const members = accountIds.flatMap((id) => {
    const account = accounts.find((item) => item.id === id);
    return account ? [account] : [];
  });
  const membershipKey = JSON.stringify(accountIds);
  const Symbol = symbolIcon(symbol);

  useEffect(() => {
    const ids: string[] = JSON.parse(membershipKey);
    const added = ids.some((id) => !previousMembers.current.has(id));
    for (const id of initialMembers.current) {
      if (!ids.includes(id)) initialMembers.current.delete(id);
    }
    previousMembers.current = new Set(ids);
    if (!added || reduced || !root.current) return;

    // A new click can interrupt the receiving motion. The individual keyed logo
    // flights remain independent, so rapid additions never overwrite one another.
    const animations: Animation[] = [];
    const play = (part: string, frames: Keyframe[], duration = 1400) => {
      const node = root.current?.querySelector<HTMLElement>(`[data-folder-part="${part}"]`);
      if (node)
        animations.push(node.animate(frames, { duration, easing: 'cubic-bezier(.22,.68,.2,1)' }));
    };
    play('front', [
      { transform: 'perspective(500px) rotateX(-10deg)' },
      { transform: 'perspective(500px) rotateX(-34deg) translateY(3px)', offset: 0.26 },
      { transform: 'perspective(500px) rotateX(-28deg) translateY(3px)', offset: 0.57 },
      { transform: 'perspective(500px) rotateX(-7deg)', offset: 0.84 },
      { transform: 'perspective(500px) rotateX(-10deg)' }
    ]);
    play('back', [
      { transform: 'translateY(-3px) rotate(-2deg)' },
      { transform: 'translateY(-12px) rotate(-5deg)', offset: 0.28 },
      { transform: 'translateY(-11px) rotate(-4deg)', offset: 0.6 },
      { transform: 'translateY(-3px) rotate(-2deg)' }
    ]);
    play('rig', [
      { transform: 'translateY(0)' },
      { transform: 'translateY(-2px)', offset: 0.25 },
      { transform: 'translateY(3px)', offset: 0.5 },
      { transform: 'translateY(-1px)', offset: 0.72 },
      { transform: 'translateY(0)' }
    ]);
    play('glow', [
      { opacity: 0, transform: 'scale(.6)' },
      { opacity: 0, transform: 'scale(.65)', offset: 0.36 },
      { opacity: 1, transform: 'scale(1.12)', offset: 0.58 },
      { opacity: 0.65, transform: 'scale(1)', offset: 0.72 },
      { opacity: 0, transform: 'scale(.8)' }
    ]);
    return () => animations.forEach((animation) => animation.cancel());
  }, [membershipKey, reduced]);

  return (
    <span
      ref={root}
      aria-hidden='true'
      data-folder-preview=''
      data-reduced-motion={reduced}
      className={styles.preview}
    >
      <span className={styles.scene}>
        <span className={styles.shadow} />
        <span data-folder-part='rig' className={styles.rig}>
          <svg data-folder-part='back' className={styles.back} viewBox='0 0 200 176' fill='none'>
            <defs>
              <linearGradient
                id={`${uid}-back`}
                x1='52'
                y1='57'
                x2='122'
                y2='147'
                gradientUnits='userSpaceOnUse'
              >
                <stop className={styles.backTop} />
                <stop offset='1' className={styles.backBottom} />
              </linearGradient>
            </defs>
            <path
              d='M40 61Q39 55 46 55H78Q81 55 84 58L96 69H160Q168 69 167 77L157 142Q156 148 148 148H57Q51 148 50 142Z'
              fill={`url(#${uid}-back)`}
              stroke='currentColor'
              strokeWidth='.8'
            />
          </svg>

          <span className={styles.contents}>
            {members.map((account, i) => (
              <span
                key={account.id}
                data-folder-logo={account.id}
                className={styles.member}
                style={
                  {
                    '--slot': Math.min(i, 2),
                    '--lean': `${(Math.min(i, 2) - 1) * 12}deg`
                  } as CSSProperties
                }
              >
                {/* Initial edit/selection members are already filed. New members get a
                    separate flight even when the three visible peek slots are full. */}
                {!initialMembers.current.has(account.id) && (
                  <span className={styles.flight} data-folder-flight={account.id}>
                    <ChannelIcon
                      platform={account.platform}
                      name={account.platform}
                      size='md'
                      className={styles.brand}
                    />
                  </span>
                )}
                {i < 3 && (
                  <span
                    className={`${styles.peek} ${initialMembers.current.has(account.id) ? '' : styles.newPeek}`}
                  >
                    <ChannelIcon
                      platform={account.platform}
                      name={account.platform}
                      size='md'
                      className={styles.brand}
                    />
                  </span>
                )}
              </span>
            ))}
          </span>
          <span data-folder-part='glow' className={styles.glow} />

          <span data-folder-part='front' className={styles.front}>
            <svg className={styles.face} viewBox='0 0 200 176' fill='none'>
              <defs>
                <linearGradient
                  id={`${uid}-face`}
                  x1='68'
                  y1='78'
                  x2='111'
                  y2='161'
                  gradientUnits='userSpaceOnUse'
                >
                  <stop className={styles.faceTop} />
                  <stop offset='.48' className={styles.faceMiddle} />
                  <stop offset='1' className={styles.faceBottom} />
                </linearGradient>
                <linearGradient
                  id={`${uid}-edge`}
                  x1='95'
                  y1='80'
                  x2='100'
                  y2='157'
                  gradientUnits='userSpaceOnUse'
                >
                  <stop stopColor='white' stopOpacity='.62' />
                  <stop offset='.4' stopColor='white' stopOpacity='.15' />
                  <stop offset='1' stopColor='white' stopOpacity='0' />
                </linearGradient>
              </defs>
              <path
                d='M23 82H62Q66 82 69 85L79 95Q82 98 87 98H179Q187 98 185 106L176 150Q175 157 167 157H38Q31 157 30 150L16 91Q14 82 23 82Z'
                fill={`url(#${uid}-face)`}
                stroke={`url(#${uid}-edge)`}
                strokeWidth='1.2'
              />
              <path
                d='M24 84H61Q65 84 68 87L79 98Q82 101 87 101H178'
                stroke='white'
                strokeOpacity='.08'
                strokeWidth='1'
              />
            </svg>
            <Symbol className={styles.symbol} stroke={1.45} />
            <span className={styles.handle} />
            {members.length > 3 && <span className={styles.more}>+{members.length - 3}</span>}
          </span>
        </span>
      </span>
    </span>
  );
}
