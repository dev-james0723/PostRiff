'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { siteConfig } from '@/config/site';

const TOPICS: { id: string; label: string }[] = [
  { id: 'support', label: 'Support' },
  { id: 'billing', label: 'Billing' },
  { id: 'design-partner', label: 'Design partner programme' },
  { id: 'api', label: 'API early access' },
  { id: 'press', label: 'Press' },
  { id: 'security', label: 'Security' }
];

/** Borderless field fill at the standard 48px control height, 16px text on phones (DNA §11.1, §23.1). */
const FIELD = 'rafii-field border-0 bg-(--rafii-surface-field) dark:bg-(--rafii-surface-field) dark:hover:bg-(--rafii-surface-field) h-12 rounded-[var(--rafii-radius-control)] px-3.5 text-base md:text-sm';

/**
 * The one work surface of the page: label → control → action, staged locally and handed to the
 * visitor's own mail app on submit (no server, no stored message). `?topic=` preselects a topic.
 */
export function ContactForm() {
  const params = useSearchParams();
  const [topic, setTopic] = useState('support');
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const requested = params.get('topic');
    if (requested && TOPICS.some((t) => t.id === requested)) setTopic(requested);
  }, [params]);

  const subject = `[${TOPICS.find((t) => t.id === topic)?.label ?? 'Contact'}] ${name || 'Rafii enquiry'}`;
  const href = `mailto:${siteConfig.supportEmail}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(message)}`;

  return (
    <Surface
      as='form'
      material='glass'
      radius='composer'
      padding='lg'
      className='flex max-w-xl flex-col gap-5'
      onSubmit={(event) => {
        event.preventDefault();
        window.location.href = href;
      }}
    >
      <div className='flex flex-col gap-2'>
        <Label htmlFor='topic'>Topic</Label>
        <Select value={topic} onValueChange={(value) => setTopic(String(value))}>
          <SelectTrigger id='topic' className={`${FIELD} w-full data-[size=default]:h-12`}>
            <SelectValue>{TOPICS.find((t) => t.id === topic)?.label}</SelectValue>
          </SelectTrigger>
          <SelectContent className='rafii-elevated rounded-[var(--rafii-radius-control)] shadow-2xl ring-0'>
            {TOPICS.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='name'>Your name</Label>
        <Input id='name' className={FIELD} value={name} onChange={(event) => setName(event.target.value)} autoComplete='name' />
      </div>
      <div className='flex flex-col gap-2'>
        <Label htmlFor='message'>Message</Label>
        <Textarea id='message' className={`${FIELD} h-auto min-h-40 py-3`} rows={6} value={message} onChange={(event) => setMessage(event.target.value)} required />
      </div>
      <div className='flex flex-wrap items-center gap-3'>
        <Button type='submit' variant='action' size='control'>
          Open in your email app
        </Button>
        <span className='text-muted-foreground text-sm'>
          Or write directly to{' '}
          <a href={`mailto:${siteConfig.supportEmail}`} className='rafii-focus text-foreground rounded-sm underline underline-offset-2'>
            {siteConfig.supportEmail}
          </a>
          .
        </span>
      </div>
    </Surface>
  );
}
