/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: process.env.BACKEND_URL || 'http://localhost:8518/:path*',
      },
    ];
  },
  typescript: {
    ignoreBuildErrors: false,
  },
};

module.exports = nextConfig;
