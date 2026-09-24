import { ImageResponse } from 'next/og';
import { siteConfig } from '@/config/site';

export const alt = 'Rafii — your ideas, on every platform, in your voice';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: 72,
          background: 'linear-gradient(135deg, #0b0b0f 0%, #17171d 100%)',
          color: '#fafafa',
          fontFamily: 'sans-serif'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 36, fontWeight: 700 }}>
          <div style={{ width: 48, height: 48, borderRadius: 12, background: '#fafafa', color: '#0b0b0f', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28 }}>P</div>
          {siteConfig.name}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <div style={{ fontSize: 64, fontWeight: 700, lineHeight: 1.1, maxWidth: 1000 }}>Your AI teammate for social media.</div>
          <div style={{ fontSize: 30, color: '#a1a1aa', maxWidth: 1000 }}>Rewritten per platform, approved by you, published with a receipt.</div>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 22, color: '#d4d4d8' }}>
          {['LinkedIn', 'Instagram', 'Threads', '小紅書', 'Bilibili', '知乎', 'YouTube', 'TikTok'].map((name) => (
            <div key={name} style={{ padding: '8px 16px', borderRadius: 999, border: '1px solid #3f3f46' }}>
              {name}
            </div>
          ))}
        </div>
      </div>
    ),
    size
  );
}
