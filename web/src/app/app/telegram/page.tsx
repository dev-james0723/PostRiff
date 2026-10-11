import type { Metadata } from 'next';
import { TelegramWorkspace } from '@/features/telegram/workspace';
export const metadata: Metadata = { title: 'Telegram' };
export default function TelegramPage() { return <TelegramWorkspace />; }
