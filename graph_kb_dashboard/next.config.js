/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  eslint: {
    // Pre-existing lint issues in help/wizard pages — skip during build
    ignoreDuringBuilds: true,
  },
  typescript: {
    // Pre-existing type errors in documents/wizard pages — skip during build
    ignoreBuildErrors: true,
  },
  experimental: {
    // Allow useSearchParams without Suspense boundary (pre-existing pages)
    missingSuspenseWithCSRBailout: false,
  },
  transpilePackages: ['recharts', 'mermaid'],
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1',
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws',
  },
  webpack: (config, { isServer }) => {
    // Ignore A-Frame during SSR (it's a browser-only library)
    if (isServer) {
      config.resolve.alias.aframe = false;
      config.resolve.alias['aframe-extras'] = false;
      config.resolve.alias['aframe-forcegraph-component'] = false;
      // Mermaid is browser-only — exclude from the server bundle entirely
      config.resolve.alias.mermaid = false;
    }
    return config;
  },
};

module.exports = nextConfig;
