'use client';

import { useEffect, useId, useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { SegmentedControl, Surface } from '@/components/rafii';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ALL_PERMISSIONS } from '@/lib/auth/access';
import { allows, ROLE_LABELS } from '@/lib/auth/permissions';
import { cn } from '@/lib/utils';
import type { WorkspacePermission, WorkspaceRole } from '@/types';
import { ASSIGNABLE_ROLES, FLAGS, flagShort, grantsFor, NO_FLAGS, PERMISSION_LABELS, ROLES, unlockedBy, type FlagKey } from './access-model';
import { SectionHeading, StatusChip } from './rafii-parts';

type Cell = { kind: 'yes' } | { kind: 'grant'; flags: FlagKey[] } | { kind: 'no' };

/** Pinned cells need an opaque-enough fill that matches the quiet surface they sit in. */
const PINNED_FILL = 'color-mix(in oklch, var(--foreground) 4%, var(--background))';

function cellFor(role: WorkspaceRole, permission: WorkspacePermission): Cell {
  if (allows({ role, ...NO_FLAGS }, permission)) return { kind: 'yes' };
  const flags = grantsFor(role, permission);
  return flags.length > 0 ? { kind: 'grant', flags } : { kind: 'no' };
}

function grantNames(flags: FlagKey[]) {
  return flags.map(flagShort).join(' or ');
}

/** Anchor for deep links such as `/app/workspace/roles#permission-approve`. */
function anchorId(permission: WorkspacePermission, compact = false) {
  return `permission-${permission}${compact ? '-compact' : ''}`;
}

function GrantCell({ role, flags }: { role: WorkspaceRole; flags: FlagKey[] }) {
  return (
    <Tooltip>
      <TooltipTrigger className='rafii-focus rounded-full'>
        <StatusChip icon='key' className='cursor-help'>
          with grant
        </StatusChip>
      </TooltipTrigger>
      <TooltipContent className='rafii-elevated max-w-64 rounded-2xl px-3.5 py-3 text-left'>
        {ROLE_LABELS[role]} role: only with the {grantNames(flags)} grant. The owner, or an admin who holds that grant, can add it without changing the role.
      </TooltipContent>
    </Tooltip>
  );
}

function RoleTable({ yourRole, highlight }: { yourRole: WorkspaceRole | null; highlight: WorkspacePermission | null }) {
  return (
    <Surface material='quiet' padding='none' className='relative hidden overflow-x-auto md:block'>
      <Table className='text-sm'>
        <TableHeader className='[&_tr]:border-0'>
          <TableRow className='border-0 hover:bg-transparent'>
            <TableHead className='text-muted-foreground sticky left-0 z-10 h-11 pl-4 text-xs font-medium' style={{ background: PINNED_FILL }}>
              Permission
            </TableHead>
            {ROLES.map((role) => (
              <TableHead key={role} className={cn('text-muted-foreground h-11 px-3 text-center text-xs font-medium', role === yourRole && 'bg-foreground/[0.04]')}>
                <span className='inline-flex items-center gap-1.5'>
                  {ROLE_LABELS[role]}
                  {role === yourRole && (
                    <StatusChip icon={null} className='h-5 px-1.5 text-[11px]'>
                      you
                    </StatusChip>
                  )}
                </span>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {ALL_PERMISSIONS.map((permission) => (
            <TableRow key={permission} id={anchorId(permission)} className={cn('border-0 scroll-mt-24 transition-colors duration-150 hover:bg-transparent', highlight === permission && 'bg-foreground/10')}>
              <TableCell className='text-foreground sticky left-0 z-10 min-w-40 py-3 pl-4 whitespace-normal' style={{ background: PINNED_FILL }}>
                {PERMISSION_LABELS[permission].label}
              </TableCell>
              {ROLES.map((role) => {
                const cell = cellFor(role, permission);
                return (
                  <TableCell key={role} className={cn('px-3 py-3 text-center', role === yourRole && 'bg-foreground/[0.04]')}>
                    {cell.kind === 'yes' ? (
                      <span aria-label='Yes'>✓</span>
                    ) : cell.kind === 'grant' ? (
                      <GrantCell role={role} flags={cell.flags} />
                    ) : (
                      <span className='text-muted-foreground' aria-label='No'>
                        —
                      </span>
                    )}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Surface>
  );
}

/** Below 768px the same facts as a list: one row per permission, roles as chips. */
function RoleList({ yourRole, highlight }: { yourRole: WorkspaceRole | null; highlight: WorkspacePermission | null }) {
  return (
    <ul className='flex flex-col gap-2 md:hidden'>
      {ALL_PERMISSIONS.map((permission) => {
        const cells = ROLES.map((role) => ({ role, cell: cellFor(role, permission) }));
        const not = cells.filter((item) => item.cell.kind === 'no').map((item) => item.role);
        return (
          <li key={permission} id={anchorId(permission, true)} className={cn('rafii-quiet flex scroll-mt-24 flex-col gap-2 rounded-[var(--rafii-radius-control)] p-4 transition-colors duration-150', highlight === permission && 'rafii-glass-selected')}>
            <span className='text-foreground text-sm font-medium'>{PERMISSION_LABELS[permission].label}</span>
            <span className='flex flex-wrap gap-1.5'>
              {cells.map(({ role, cell }) =>
                cell.kind === 'no' ? null : (
                  <StatusChip key={role} icon={cell.kind === 'yes' ? 'check' : 'key'} className={cn('h-auto min-h-7 py-1 font-normal whitespace-normal', cell.kind === 'grant' && 'text-muted-foreground', role === yourRole && 'rafii-glass')}>
                    {cell.kind === 'yes' ? ROLE_LABELS[role] : `${ROLE_LABELS[role]} with the ${grantNames(cell.flags)} grant`}
                    {role === yourRole && <span className='text-muted-foreground'> · you</span>}
                  </StatusChip>
                )
              )}
            </span>
            {not.length > 0 && <span className='text-muted-foreground text-xs'>Not for: {not.map((role) => `${ROLE_LABELS[role]}${role === yourRole ? ' (you)' : ''}`).join(', ')}</span>}
          </li>
        );
      })}
    </ul>
  );
}

function ByGrant() {
  return (
    <ul className='grid gap-3 md:grid-cols-2'>
      {FLAGS.map((flag) => {
        const unlocks = unlockedBy(flag.key);
        const included = ROLES.filter((role) => unlocks.every((permission) => allows({ role, ...NO_FLAGS }, permission)));
        const lifted = ASSIGNABLE_ROLES.filter((role) => unlocks.some((permission) => grantsFor(role, permission).includes(flag.key)));
        return (
          <Surface key={flag.key} as='li' material='quiet' padding='sm' className='flex flex-col gap-2 p-4'>
            <div className='flex flex-col gap-0.5'>
              <span className='text-foreground font-medium'>{flag.label}</span>
              <span className='text-muted-foreground text-xs'>{flag.explains}</span>
            </div>
            <dl className='grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm'>
              <dt className='text-muted-foreground'>Adds</dt>
              <dd>{unlocks.map((permission) => PERMISSION_LABELS[permission].label).join(', ')}</dd>
              <dt className='text-muted-foreground'>Changes things for</dt>
              <dd>{lifted.map((role) => ROLE_LABELS[role]).join(', ')}</dd>
              <dt className='text-muted-foreground'>Already included for</dt>
              <dd>{included.map((role) => ROLE_LABELS[role]).join(', ')}</dd>
            </dl>
          </Surface>
        );
      })}
    </ul>
  );
}

/**
 * The access model from the client mirror of `permissions.py` (static, so no loading state).
 * A link to `#permission-<key>` scrolls that row into view and tints it briefly.
 */
export function PermissionMatrix({ yourRole }: { yourRole: WorkspaceRole | null }) {
  const reduce = useReducedMotion();
  const [view, setView] = useState<'role' | 'grant'>('role');
  const [highlight, setHighlight] = useState<WorkspacePermission | null>(null);
  const base = useId();
  const panelIds = [`${base}-role`, `${base}-grant`];

  useEffect(() => {
    const key = decodeURIComponent(window.location.hash.replace(/^#permission-/, '')) as WorkspacePermission;
    if (!window.location.hash.startsWith('#permission-') || !ALL_PERMISSIONS.includes(key)) return;
    const target = [anchorId(key), anchorId(key, true)].map((id) => document.getElementById(id)).find((element) => element !== null && element.getClientRects().length > 0);
    if (!target) return;
    target.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    const start = window.setTimeout(() => setHighlight(key), 0);
    const end = window.setTimeout(() => setHighlight(null), 1600);
    return () => {
      window.clearTimeout(start);
      window.clearTimeout(end);
    };
  }, [reduce]);

  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-matrix-heading' data-tour='roles-matrix'>
      <SectionHeading
        id='roles-matrix-heading'
        title='Permission matrix'
        description={
          <>
            ✓ the role includes it · <span className='text-foreground font-medium'>with grant</span> an owner or admin can add that one right without changing the role (never for viewers) · — not available
          </>
        }
      />
      <SegmentedControl
        pattern='tabs'
        label='Matrix view'
        size='md'
        value={view}
        onChange={setView}
        panelIds={panelIds}
        className='w-full sm:w-fit'
        options={[
          { value: 'role', label: 'By role' },
          { value: 'grant', label: 'By grant' }
        ]}
      />
      {view === 'role' ? (
        <div role='tabpanel' id={panelIds[0]} tabIndex={0} className='rafii-focus flex flex-col gap-2 rounded-[var(--rafii-radius-card)]'>
          <RoleTable yourRole={yourRole} highlight={highlight} />
          <RoleList yourRole={yourRole} highlight={highlight} />
        </div>
      ) : (
        <div role='tabpanel' id={panelIds[1]} tabIndex={0} className='rafii-focus rounded-[var(--rafii-radius-card)]'>
          <ByGrant />
        </div>
      )}
    </section>
  );
}
