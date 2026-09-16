'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import type { ModelOption } from '@/lib/api/types';
import { cn } from '@/lib/utils';
import { shortLabel } from './use-model';

/** The composer's model pill: PostRiff routes first, then each local CLI, like a settings picker in miniature. */
export function ModelPicker({ options, model, onChoose, disabled }: { options: ModelOption[]; model: string; onChoose: (id: string) => void; disabled?: boolean }) {
  const current = options.find((m) => m.id === model);
  const ready = current?.qualified ?? model === 'deterministic-preview';
  const groups: { title: string; items: ModelOption[] }[] = [
    { title: 'PostRiff', items: options.filter((m) => !m.route || m.route === 'fixture' || m.route === 'managed') },
    { title: 'Local CLI · Claude Code', items: options.filter((m) => m.route === 'claude-code') }
  ].filter((group) => group.items.length > 0);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        disabled={disabled}
        render={<Button variant='outline' size='sm' className='h-7 gap-1.5 px-2.5 font-normal' title={current?.detail} aria-label='Model' />}
      >
        <span aria-hidden className={cn('size-1.5 rounded-full', ready ? 'bg-emerald-500' : 'bg-amber-500')} />
        <span className='font-mono text-[11.5px]'>{shortLabel(current, model)}</span>
        <Icons.chevronDown className='size-3' />
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='w-80'>
        {groups.map((group, index) => (
          <DropdownMenuGroup key={group.title}>
            {index > 0 && <DropdownMenuSeparator />}
            <DropdownMenuLabel className='text-muted-foreground text-xs'>{group.title}</DropdownMenuLabel>
            {group.items.map((item) => (
              <DropdownMenuItem key={item.id} disabled={!item.qualified} onClick={() => onChoose(item.id)} className='flex flex-col items-start gap-0.5'>
                <span className='flex w-full items-center gap-2 text-sm'>
                  <span className={cn('size-1.5 shrink-0 rounded-full', item.qualified ? 'bg-emerald-500' : 'bg-muted-foreground/40')} />
                  <span className='flex-1 truncate'>{item.label}</span>
                  {item.id === model && <Icons.check className='size-3.5' />}
                </span>
                <span className='text-muted-foreground line-clamp-2 pl-3.5 text-xs'>{item.detail}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href='/app/account/models' aria-label='Models and providers' />}>
          <Icons.adjustments className='mr-2 size-4' />
          Models &amp; providers
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
