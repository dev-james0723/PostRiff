import type { NextConfig } from 'next';
const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{source:'/:path*',headers:[
      {key:'Cache-Control',value:'private, no-store'},
      {key:'X-Frame-Options',value:'DENY'},
      {key:'X-Content-Type-Options',value:'nosniff'},
      {key:'Referrer-Policy',value:'no-referrer'},
      {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'},
      {key:'X-Robots-Tag',value:'noindex, nofollow, noarchive'}
    ]}];
  }
};
export default nextConfig;
