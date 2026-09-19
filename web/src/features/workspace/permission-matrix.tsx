'use client';

import { useEffect, useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Badge, badgeVariants } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ALL_PERMISSIONS } from '@/lib/auth/access';
import { allows, ROLE_LABELS } from '@/lib/auth/permissions';
import { cn } from '@/lib/utils';
import type { WorkspacePermission, WorkspaceRole } from '@/types';
import {
  ASSIGNABLE_ROLES,
  FLAGS,
  flagShort,
  grantsFor,
  NO_FLAGS,
  PERMISSION_LABELS,
  ROLES,
  unlockedBy,
  type FlagKey
} from './access-model';

type Cell = { kind: 'yes' } | { kind: 'grant'; flags: FlagKey[] } | { kind: 'no' };

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
      <TooltipTrigger className={cn(badgeVariants({ variant: 'outline' }), 'cursor-help')}>with grant</TooltipTrigger>
      <TooltipContent className='max-w-64 text-left'>
        {ROLE_LABELS[role]} role: only with the {grantNames(flags)} grant. The owner, or an admin who holds that grant, can add it
        without changing the role.
      </TooltipContent>
    </Tooltip>
  );
}

function RoleTable({ yourRole, highlight }: { yourRole: WorkspaceRole | null; highlight: WorkspacePermission | null }) {
  return (
    <div className='hidden overflow-x-auto rounded-lg border md:block'>
      <Table>
        <TableHeader>
          <TableRow className='hover:bg-transparent'>
            <TableHead className='bg-background sticky left-0 z-10'>Permission</TableHead>
            {ROLES.map((role) => (
              <TableHead key={role} className={cn('text-center', role === yourRole && 'bg-muted/40')}>
                <span className='inline-flex items-center gap-1.5'>
                  {ROLE_LABELS[role]}
                  {role === yourRole && (
                    <Badge variant='secondary' className='h-4 px-1.5 text-[10px]'>
                      you
                    </Badge>
                  )}
                </span>
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {ALL_PERMISSIONS.map((permission) => (
            <TableRow
              key={permission}
              id={anchorId(permission)}
              className={cn('scroll-mt-24 duration-150', highlight === permission && 'bg-primary/10')}
            >
              <TableCell className='bg-background sticky left-0 z-10 min-w-40 whitespace-normal'>{PERMISSION_LABELS[permission].label}</TableCell>
              {ROLES.map((role) => {
                const cell = cellFor(role, permission);
                return (
                  <TableCell key={role} className={cn('text-center', role === yourRole && 'bg-muted/40')}>
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
    </div>
  );
}

/** Below 768px the same facts as a list: one row per permission, roles as chips. */
function RoleList({ yourRole, highlight }: { yourRole: WorkspaceRole | null; highlight: WorkspacePermission | null }) {
  return (
    <ul className='divide-y rounded-lg border md:hidden'>
      {ALL_PERMISSIONS.map((permission) => {
        const cells = ROLES.map((role) => ({ role, cell: cellFor(role, permission) }));
        const not = cells.filter((item) => item.cell.kind === 'no').map((item) => item.role);
        return (
          <li
            key={permission}
            id={anchorId(permission, true)}
            className={cn('flex scroll-mt-24 flex-col gap-2 p-3 transition-colors duration-150', highlight === permission && 'bg-primary/10')}
          >
            <span className='text-sm font-medium'>{PERMISSION_LABELS[permission].label}</span>
            <span className='flex flex-wrap gap-1.5'>
              {cells.map(({ role, cell }) =>
                cell.kind === 'no' ? null : (
                  <Badge
                    key={role}
                    variant='outline'
                    className={cn(
                      'font-normal',
                      cell.kind === 'grant' && 'text-muted-foreground border-dashed',
                      role === yourRole && 'ring-primary ring-1'
                    )}
                  >
                    {cell.kind === 'yes' ? `✓ ${ROLE_LABELS[role]}` : `${ROLE_LABELS[role]} with the ${grantNames(cell.flags)} grant`}
                    {role === yourRole && <span className='text-muted-foreground'>· you</span>}
                  </Badge>
                )
              )}
            </span>
            {not.length > 0 && (
              <span className='text-muted-foreground text-xs'>
                Not for: {not.map((role) => `${ROLE_LABELS[role]}${role === yourRole ? ' (you)' : ''}`).join(', ')}
              </span>
            )}
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
          <li key={flag.key} className='flex min-w-0 flex-col gap-2 rounded-lg border p-3'>
            <div className='flex flex-col gap-0.5'>
              <span className='font-medium'>{flag.label}</span>
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
          </li>
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
  const [view, setView] = useState('role');
  const [highlight, setHighlight] = useState<WorkspacePermission | null>(null);

  useEffect(() => {
    const key = decodeURIComponent(window.location.hash.replace(/^#permission-/, '')) as WorkspacePermission;
    if (!window.location.hash.startsWith('#permission-') || !ALL_PERMISSIONS.includes(key)) return;
    const target = [anchorId(key), anchorId(key, true)]
      .map((id) => document.getElementById(id))
      .find((element) => element !== null && element.getClientRects().length > 0);
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
      <div className='flex flex-col gap-1'>
        <h3 id='roles-matrix-heading' className='text-lg font-semibold'>
          Permission matrix
        </h3>
        <p className='text-muted-foreground text-sm'>
          ✓ the role includes it · <span className='text-foreground font-medium'>with grant</span> an owner or admin can add that one right
          without changing the role (never for viewers) · — not available
        </p>
      </div>
      <Tabs value={view} onValueChange={setView} variant='segment'>
        <TabsList aria-label='Matrix view' className='border'>
          <TabsTrigger value='role'>By role</TabsTrigger>
          <TabsTrigger value='grant'>By grant</TabsTrigger>
        </TabsList>
        <TabsContent value='role'>
          <RoleTable yourRole={yourRole} highlight={highlight} />
          <RoleList yourRole={yourRole} highlight={highlight} />
        </TabsContent>
        <TabsContent value='grant'>
          <ByGrant />
        </TabsContent>
      </Tabs>
    </section>
  );
}
