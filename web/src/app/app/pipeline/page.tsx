import { redirect } from 'next/navigation';

/** The Pipeline board folded into Queue (Rafii v9): its drafts live under Queue → Drafts. */
export default function Page() {
  redirect('/app/queue?view=drafts');
}
