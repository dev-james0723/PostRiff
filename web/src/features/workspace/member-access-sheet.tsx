'use client';

import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { StatefulButton, type ButtonState } from '@/components/motion/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { Member, Membership } from '@/lib/api/types';
import { permissionsFor, ROLE_DESCRIPTIONS, ROLE_LABELS } from '@/lib/auth/permissions';
import { EASE_OUT } from '@/lib/ease';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { WorkspaceRole } from '@/types';
import {
  APPROVAL_HOLD_NOTE,
  ASSIGNABLE_ROLES,
  canAssignRole,
  FLAGS,
  flagsOf,
  grantRules,
  losesApprove,
  NO_FLAGS,
  PERMISSION_LABELS,
  shortId,
  type Flags
} from './access-model';
import { useChangeError } from './use-change-error';

/** How long "Saved" stays on the button before the sheet closes. */
const SUCCESS_HOLD_MS = 1200;

function DiffChips({ before, after }: { before: Membership; after: Membership }) {
  const reduce = useReducedMotion();
  const was = permissionsFor(before);
  const will = permissionsFor(after);
  const changes = [
    ...will.filter((p) => !was.includes(p)).map((p) => ({ permission: p, added: true })),
    ...was.filter((p) => !will.includes(p)).map((p) => ({ permission: p, added: false }))
  ];
  if (changes.length === 0) {
    return <p className='text-muted-foreground text-sm'>No change to what they can do.</p>;
  }
  // Stagger stays within the motion budget: 40ms apart, 300ms in total.
  const stagger = Math.min(0.04, 0.3 / changes.length);
  return (
    <ul className='flex flex-wrap gap-1.5' aria-label='Permission changes'>
      {changes.map((change, index) => (
        <motion.li
          key={`${change.added ? 'add' : 'remove'}-${change.permission}`}
          initial={{ opacity: 0, y: reduce ? 0 : 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, ease: EASE_OUT, delay: reduce ? 0 : index * stagger }}
        >
          <AnimatedBadge size='sm' status={change.added ? 'success' : 'danger'} showIcon={false}>
            <span className='sr-only'>{change.added ? 'Gains' : 'Loses'}</span>
            <span aria-hidden>{change.added ? '+ ' : '− '}</span>
            {PERMISSION_LABELS[change.permission].short}
          </AnimatedBadge>
        </motion.li>
      ))}
    </ul>
  );
}

function AccessForm({
  member,
  actor,
  onDone,
  onSaved
}: {
  member: Member;
  actor: Membership | null;
  onDone: () => void;
  onSaved?: (userId: string) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const reportError = useChangeError();
  const [role, setRole] = useState<WorkspaceRole>(member.role);
  const [flags, setFlags] = useState<Flags>(() => flagsOf(member));
  const [state, setState] = useState<ButtonState>('idle');
  const [confirming, setConfirming] = useState(false);
  const closeTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
    },
    []
  );

  const viewer = role === 'viewer';
  // A viewer's grants never apply (`Membership.allows`), so saving a viewer clears them.
  const payload: Flags = viewer ? NO_FLAGS : flags;
  const rules = grantRules(actor, payload);
  const blocked = FLAGS.filter((flag) => rules[flag.key].mustRemove);
  const unheld = !viewer && FLAGS.some((flag) => rules[flag.key].cannotAdd && !payload[flag.key]);
  const before = flagsOf(member);
  const changed = role !== member.role || FLAGS.some((flag) => payload[flag.key] !== before[flag.key]);
  const added = FLAGS.filter((flag) => payload[flag.key] && !before[flag.key]);
  const removed = FLAGS.filter((flag) => !payload[flag.key] && before[flag.key]);
  // Losing approve holds anything they already approved (hosted_worker.py re-checks at claim time).
  const holdsApprovals = losesApprove(member, { role, ...payload });
  const settled = state === 'loading' || state === 'success';

  function edit(update: () => void) {
    update();
    if (state === 'error') setState('idle');
  }

  async function save() {
    setConfirming(false);
    setState('loading');
    try {
      await api.updateMember(workspaceId, member.userId, role, payload);
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.members(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.audit(workspaceId) })
      ]);
      setState('success');
      onSaved?.(member.userId);
      toast.success(`Access changed for ${shortId(member.userId)}`, holdsApprovals ? { description: APPROVAL_HOLD_NOTE } : undefined);
      closeTimer.current = window.setTimeout(onDone, SUCCESS_HOLD_MS);
    } catch (err) {
      setState('error');
      // 404 / 409: someone changed this member elsewhere; show the list as the API has it now.
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
        void client.invalidateQueries({ queryKey: keys.members(workspaceId) });
      }
      reportError(err, 'The change could not be confirmed. Check the member list before trying again.');
    }
  }

  return (
    <>
      <div className='flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4'>
        <div className='flex flex-col gap-1.5'>
          <Label htmlFor='access-role'>Role</Label>
          <Select value={role} onValueChange={(value) => edit(() => setRole(value as WorkspaceRole))}>
            <SelectTrigger id='access-role' className='w-full' disabled={settled}>
              <SelectValue>{ROLE_LABELS[role]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {ASSIGNABLE_ROLES.filter((r) => r === member.role || canAssignRole(actor, r)).map((r) => (
                <SelectItem key={r} value={r}>
                  {ROLE_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className='text-muted-foreground text-xs'>{ROLE_DESCRIPTIONS[role]}</p>
        </div>

        <fieldset className='flex flex-col gap-2.5'>
          <legend className='mb-1 text-sm font-medium'>Extra grants</legend>
          {viewer ? (
            <p className='text-muted-foreground text-xs'>Viewers cannot carry grants. Saving as a viewer clears them.</p>
          ) : (
            unheld && <p className='text-muted-foreground text-xs'>Greyed-out grants are ones you do not hold, so you cannot hand them out.</p>
          )}
          {FLAGS.map((flag) => {
            const rule = rules[flag.key];
            const checked = payload[flag.key];
            // Turning a grant off is always allowed; turning it on needs the actor to hold it.
            const disabled = settled || viewer || (rule.cannotAdd && !checked);
            return (
              <div key={flag.key} className='flex flex-col gap-0.5'>
                <Label className='flex items-start gap-2 text-sm font-normal'>
                  <Checkbox
                    className='mt-0.5'
                    checked={checked}
                    disabled={disabled}
                    onCheckedChange={(value) => edit(() => setFlags({ ...flags, [flag.key]: value === true }))}
                  />
                  <span className='flex flex-col gap-0.5'>
                    <span className={disabled ? 'text-muted-foreground' : undefined}>{flag.label}</span>
                    <span className='text-muted-foreground text-xs leading-snug'>{flag.explains}</span>
                  </span>
                </Label>
                {rule.mustRemove && (
                  <p className='pl-6 text-xs text-amber-700 dark:text-amber-300'>
                    You do not hold this grant, so you cannot keep it on. Turn it off to save, or ask the owner to make this change.
                  </p>
                )}
              </div>
            );
          })}
        </fieldset>

        <section className='flex flex-col gap-2' aria-labelledby='access-diff'>
          <h3 id='access-diff' className='text-sm font-medium'>
            What changes for them
          </h3>
          <DiffChips before={member} after={{ role, ...payload }} />
          {holdsApprovals && <p className='text-muted-foreground text-xs'>{APPROVAL_HOLD_NOTE}</p>}
        </section>
      </div>

      <SheetFooter className='border-t'>
        <p className='text-muted-foreground text-xs'>
          Changing access needs a recent sign-in. The change is recorded in the audit log.
        </p>
        <div className='flex flex-wrap justify-end gap-2'>
          <Button variant='outline' onClick={onDone} disabled={state === 'loading'}>
            {state === 'success' ? 'Close' : 'Cancel'}
          </Button>
          <StatefulButton
            state={state}
            loadingText='Saving…'
            successText='Saved'
            errorText='Try again'
            disabled={!changed || blocked.length > 0}
            aria-disabled={state === 'success' || undefined}
            onClick={() => {
              if (state === 'success' || state === 'loading') return;
              setConfirming(true);
            }}
          >
            Save access…
          </StatefulButton>
        </div>
      </SheetFooter>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Change access for {shortId(member.userId)}?</AlertDialogTitle>
            <AlertDialogDescription>It applies right away to everything they do in this workspace.</AlertDialogDescription>
          </AlertDialogHeader>
          <ul className='flex flex-col gap-1 text-sm'>
            {role !== member.role && (
              <li>
                Role: {ROLE_LABELS[member.role]} → <span className='font-medium'>{ROLE_LABELS[role]}</span>
              </li>
            )}
            {added.length > 0 && <li>Grants added: {added.map((flag) => flag.label).join(', ')}</li>}
            {removed.length > 0 && <li>Grants removed: {removed.map((flag) => flag.label).join(', ')}</li>}
          </ul>
          {holdsApprovals && (
            <p className='text-sm text-amber-700 dark:text-amber-300' data-testid='access-approval-hold'>
              They can no longer approve. {APPROVAL_HOLD_NOTE}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Keep as is</AlertDialogCancel>
            <AlertDialogAction onClick={() => void save()}>Change access</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

/**
 * Change one member's role and extra grants. Shared by the Roles and Members pages.
 * The disabled rules mirror `permissions.py` `validate_grant`; the API decides.
 */
export function MemberAccessSheet({
  member,
  actor,
  open,
  onOpenChange,
  onSaved
}: {
  member: Member | null;
  actor: Membership | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved?: (userId: string) => void;
}) {
  return (
    <Sheet open={open && member !== null} onOpenChange={onOpenChange}>
      <SheetContent side='right' className='gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-md'>
        {member && (
          <>
            <SheetHeader className='pr-12'>
              <SheetTitle className='flex flex-wrap items-center gap-2'>
                <Icons.user className='size-4' aria-hidden />
                Change access
              </SheetTitle>
              <SheetDescription className='flex flex-wrap items-center gap-1.5'>
                <span className='font-mono text-xs'>{shortId(member.userId)}</span>
                <Badge variant='outline'>{ROLE_LABELS[member.role]}</Badge>
              </SheetDescription>
            </SheetHeader>
            <AccessForm key={member.userId} member={member} actor={actor} onDone={() => onOpenChange(false)} onSaved={onSaved} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
