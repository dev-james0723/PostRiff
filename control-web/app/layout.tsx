import type { Metadata } from 'next';
import './globals.css';
export const dynamic='force-dynamic';
export const metadata: Metadata = {title:'Rafii Control',robots:{index:false,follow:false},description:'Private founder operations'};
export default function Layout({children}:{children:React.ReactNode}) {
  return <html lang="en" data-theme="rafii"><body><a href="#main" className="skip">Skip to content</a>{children}</body></html>;
}
