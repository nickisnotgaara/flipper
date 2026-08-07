/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,

  // === Static export (Flipper-deploy, 2026-08) ===
  // Фронт собирается в ./out/ — чистая статика без Node.js-сервера.
  // Деплоится на Vercel / Netlify / Cloudflare Pages / nginx / S3+CDN.
  // При правке фронта пересобирается только ./out/, Docker не трогаем.
  output: 'export',
  // trailingSlash нужен shared-хостингам и чтобы статика и API
  // не конфликтовали на одном домене (/api/* → бэк, остальное → статика).
  trailingSlash: true,
  // У Next Image отключаем оптимизатор (его некуда ставить без сервера).
  images: { unoptimized: true },
  // distDir оставляем дефолтный .next — `next export` сам кладёт готовую
  // статику в ./out, а .next используется только на этапе сборки.

  // Rewrites убраны: фронт ходит на бэк напрямую через
  // NEXT_PUBLIC_API_BASE (см. .env.example). Раньше это был dev-костыль,
  // чтобы обойти CORS при `docker compose --profile dev up`.
};

export default nextConfig;
