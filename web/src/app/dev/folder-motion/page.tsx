import { notFound } from 'next/navigation';
import { FolderMotionDemo } from './preview';

export const metadata = { title: 'Folder motion preview', robots: { index: false } };

export default function Page() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <FolderMotionDemo />;
}
