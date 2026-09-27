import type { Metadata } from 'next';
import { GrowthStudio } from '@/features/growth/growth-studio';

export const metadata: Metadata = { title: 'Growth Studio' };
export default function Page() { return <GrowthStudio />; }
