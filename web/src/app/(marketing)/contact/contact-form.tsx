'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
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
    <form
      className='flex max-w-xl flex-col gap-4'
      onSubmit={(event) => {
        event.preventDefault();
        window.location.href = href;
      }}
    >
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='topic'>Topic</Label>
        <Select value={topic} onValueChange={(value) => setTopic(String(value))}>
          <SelectTrigger id='topic'>
            <SelectValue>{TOPICS.find((t) => t.id === topic)?.label}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {TOPICS.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='name'>Your name</Label>
        <Input id='name' value={name} onChange={(event) => setName(event.target.value)} autoComplete='name' />
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='message'>Message</Label>
        <Textarea id='message' rows={6} value={message} onChange={(event) => setMessage(event.target.value)} required />
      </div>
      <div className='flex flex-wrap items-center gap-3'>
        <Button type='submit'>Open in your email app</Button>
        <span className='text-muted-foreground text-xs'>
          Or write directly to <a href={`mailto:${siteConfig.supportEmail}`} className='underline'>{siteConfig.supportEmail}</a>.
        </span>
      </div>
    </form>
  );
}
