import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';

export interface AvatarUser {
  name?: string;
  email?: string;
  imageUrl?: string;
}

interface UserAvatarProfileProps {
  className?: string;
  showInfo?: boolean;
  user?: AvatarUser | null;
}

function initialsFor(user?: AvatarUser | null) {
  const source = user?.name?.trim() || user?.email?.trim() || '';
  if (!source) return 'PR';
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export function UserAvatarProfile({ className, showInfo = false, user }: UserAvatarProfileProps) {
  return (
    <div className='flex items-center gap-2'>
      <Avatar className={className}>
        <AvatarImage src={user?.imageUrl || ''} alt={user?.name || ''} />
        <AvatarFallback className='rounded-lg'>{initialsFor(user)}</AvatarFallback>
      </Avatar>

      {showInfo && (
        <div className='grid flex-1 text-left text-sm leading-tight'>
          <span className='truncate font-semibold'>{user?.name || ''}</span>
          <span className='truncate text-xs'>{user?.email || ''}</span>
        </div>
      )}
    </div>
  );
}
