'use client';

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { useFlash } from '@/hooks/use-flash';
import { useMembers } from '@/lib/api/hooks';
import type { Member, Membership } from '@/lib/api/types';
import { ALL_PERMISSIONS, checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { useAuth } from '@/lib/auth/session';
import { cn } from '@/lib/utils';
import { useWorkspace } from '@/lib/workspace/provider';
import {
  ASSIGNABLE_ROLES,
  canAssignRole,
  FLAGS,
  flagsOf,
  howToGetMore,
  PERMISSION_LABELS,
  STEP_UP_ACTIONS
} from './access-model';
import { MemberAccessSheet } from './member-access-sheet';
import { PermissionMatrix } from './permission-matrix';
import { RecentAccessChanges } from './recent-access-changes';
import { RoleCards } from './role-cards';

const infoContent = {
  title: 'Roles and grants',
  sections: [
    {
      title: 'Five roles and four grants',
      description:
        'Owner, admin, editor, approver and viewer. A grant adds one right (approve, reply, moderate, manage connections) to a member without changing their role.',
      links: [{ title: 'Members', url: '/app/workspace/members' }]
    },
    {
      title: 'Grants never lift a viewer',
      description:
        'A viewer stays read-only whatever grants they carry. Only the owner or an admin can change access, nobody can change their own, and a grant can only be handed out by someone who holds it.'
    },
    {
      title: 'Some changes need a recent sign-in',
      description:
        'Changing someone’s role or grants, removing a member and inviting only work shortly after a fresh sign-in. If yours is too old, nothing is saved: sign out, sign in again and retry. Every change is recorded in the audit log.',
      links: [{ title: 'Audit log', url: '/app/workspace/audit' }]
    }
  ]
};

function sameMembership(a: Membership, b: Membership) {
  const fa = flagsOf(a);
  const fb = flagsOf(b);
  return a.role === b.role && FLAGS.every((flag) => fa[flag.key] === fb[flag.key]);
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <span className='text-muted-foreground text-xs font-medium'>{children}</span>;
}

/** Where the signed-in member stands, from the workspace membership the menus and page gates use. */
function YourAccess({ membership, fresh, canManage }: { membership: Membership; fresh: Membership | null; canManage: boolean }) {
  const access = useWorkspaceAccess();
  const workspace = useWorkspace();
  const role = membership.role;
  const owner = role === 'owner';
  const flags = flagsOf(membership);
  const held = FLAGS.filter((flag) => flags[flag.key]);
  const permissions = ALL_PERMISSIONS.filter((permission) => access.permissions.includes(permission));
  const more = howToGetMore(membership);
  // The members endpoint reports the caller's membership as the API sees it now; the provider loaded earlier.
  const drifted = fresh !== null && !sameMembership(membership, fresh);
  const roles = ASSIGNABLE_ROLES.filter((r) => canAssignRole(membership, r));

  return (
    <section aria-labelledby='roles-you-heading'>
      <Card data-tour='roles-you'>
        <CardContent className='flex flex-col gap-5'>
          <h3 id='roles-you-heading' className='sr-only'>
            Your access
          </h3>
          <div className='grid gap-4 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_minmax(0,14rem)]'>
            <div className='flex flex-col gap-1.5'>
              <FieldLabel>Your role</FieldLabel>
              <AnimatedBadge status='info' className='w-fit' contentKey={role}>
                {ROLE_LABELS[role]}
              </AnimatedBadge>
              <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
            </div>
            <div className='flex flex-col gap-1.5'>
              <FieldLabel>What you can do</FieldLabel>
              {permissions.length === 0 ? (
                <p className='text-muted-foreground text-sm'>Nothing in this workspace.</p>
              ) : (
                <ul className='flex flex-wrap gap-1.5'>
                  {permissions.map((permission) => (
                    <li key={permission}>
                      <Badge variant='outline' title={PERMISSION_LABELS[permission].label}>
                        {PERMISSION_LABELS[permission].short}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className='flex flex-col gap-1.5'>
              <FieldLabel>Your extra grants</FieldLabel>
              {owner ? (
                <p className='text-muted-foreground text-sm'>Not needed: an owner holds every right.</p>
              ) : held.length === 0 ? (
                <p className='text-muted-foreground text-sm'>None</p>
              ) : (
                <>
                  <ul className='flex flex-wrap gap-1.5'>
                    {held.map((flag) => (
                      <li key={flag.key}>
                        <Badge variant='secondary' className={role === 'viewer' ? 'line-through' : undefined} title={flag.label}>
                          {flag.short}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                  {role === 'viewer' && (
                    <p className='text-muted-foreground text-xs'>Recorded, but inactive: grants never apply to a viewer.</p>
                  )}
                </>
              )}
            </div>
          </div>

          <div className={cn('grid gap-4 border-t pt-4', canManage && 'md:grid-cols-2')}>
            <div className='flex flex-col gap-1.5'>
              <FieldLabel>{owner ? 'As the owner' : 'To do more'}</FieldLabel>
              {owner ? (
                <p className='text-sm'>You own this workspace: every permission, billing and deletion.</p>
              ) : (
                <ul className='flex flex-col gap-1 text-sm'>
                  {more.map((line) => (
                    <li key={line} className='flex gap-2'>
                      <Icons.chevronRight className='text-muted-foreground mt-0.5 size-3.5 shrink-0' aria-hidden />
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {canManage && (
              <div className='flex flex-col gap-2' data-tour='roles-grants'>
                <FieldLabel>What you can hand out</FieldLabel>
                <div className='flex flex-wrap items-center gap-1.5'>
                  <span className='text-muted-foreground text-xs'>Roles</span>
                  {roles.map((r) => (
                    <Badge key={r} variant='outline'>
                      {ROLE_LABELS[r]}
                    </Badge>
                  ))}
                </div>
                <div className='flex flex-wrap items-center gap-1.5'>
                  <span className='text-muted-foreground text-xs'>Grants</span>
                  {FLAGS.map((flag) => {
                    const yours = owner || flags[flag.key];
                    return (
                      <Badge
                        key={flag.key}
                        variant='outline'
                        className={cn(!yours && 'text-muted-foreground line-through')}
                        title={yours ? flag.label : `${flag.label}: you do not hold it`}
                      >
                        {flag.short}
                        {!yours && <span className='sr-only'> (you do not hold it)</span>}
                      </Badge>
                    );
                  })}
                </div>
                <p className='text-muted-foreground text-xs'>
                  You can only hand out grants you hold yourself. Nobody can change their own access, and the owner’s access is not
                  changed from here.
                </p>
              </div>
            )}
          </div>

          {drifted && (
            <div
              role='status'
              className='flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm'
            >
              <span>Your access changed since this page loaded. Menus still follow the earlier access.</span>
              <Button size='sm' variant='outline' onClick={() => void workspace.refresh()}>
                Reload access
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

/** Actions the API only accepts shortly after a fresh sign-in (`assert_fresh`), whatever the role. */
function SensitiveChanges() {
  return (
    <section className='flex flex-col gap-3' aria-labelledby='roles-stepup-heading' data-tour='roles-stepup'>
      <div className='flex flex-col gap-1'>
        <h3 id='roles-stepup-heading' className='text-lg font-semibold'>
          Sensitive changes
        </h3>
        <p className='text-muted-foreground text-sm'>
          These only work shortly after a fresh sign-in, on top of the right permission. If yours is too old, nothing is saved: sign out,
          sign in again and retry. Revoking an invitation does not need it.
        </p>
      </div>
      <ul className='flex flex-wrap gap-1.5'>
        {STEP_UP_ACTIONS.map((action) => (
          <li key={action}>
            <Badge variant='outline' className='font-normal'>
              <Icons.lock aria-hidden />
              {action}
            </Badge>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function RolesView() {
  const access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission: 'manage_members' });
  const workspace = useWorkspace();
  const auth = useAuth();
  const members = useMembers();
  const [target, setTarget] = useState<Member | null>(null);
  const [open, setOpen] = useState(false);
  const [justSaved, flashSaved] = useFlash<string>();

  // `isPending`, not `isLoading`: a query whose retries are paused (offline, hidden tab) has no data yet and must not read as empty.
  const list = members.data?.members;
  const you = list?.find((member) => member.you)?.userId ?? auth.user?.id ?? null;
  // The members endpoint returns the caller's membership as the API sees it now.
  const actor = members.data?.membership ?? workspace.membership;

  return (
    <PageContainer
      pageTitle='Roles'
      pageDescription='What each role can do in this workspace, who holds it, and where you stand.'
      infoContent={infoContent}
      access={access.hasWorkspace}
      accessFallback={<p className='text-muted-foreground text-sm'>Join or create a workspace first.</p>}
      pageHeaderAction={
        canManage ? (
          <Link href='/app/workspace/members' className={cn('t-learn', buttonVariants({ variant: 'outline' }))}>
            Manage members <LearnMoreChevron />
          </Link>
        ) : undefined
      }
    >
      <div className='flex min-w-0 flex-col gap-6'>
        {workspace.membership && (
          <YourAccess membership={workspace.membership} fresh={members.data?.membership ?? null} canManage={canManage} />
        )}
        <RoleCards
          state={{ members: list, isLoading: members.isPending, error: members.error, refetch: () => void members.refetch() }}
          canManage={canManage}
          justSaved={justSaved}
          onEdit={(member) => {
            setTarget(member);
            setOpen(true);
          }}
        />
        <PermissionMatrix yourRole={workspace.membership?.role ?? null} />
        <SensitiveChanges />
        {/* Any member may read the audit API, but who sees access history here is a product decision; managers only for now. */}
        {canManage && <RecentAccessChanges key={workspace.workspaceId ?? 'none'} you={you} />}
      </div>
      {canManage && <MemberAccessSheet member={target} actor={actor} open={open} onOpenChange={setOpen} onSaved={flashSaved} />}
    </PageContainer>
  );
}
