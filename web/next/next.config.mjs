/** @type {import('next').NextConfig} */
const isProd = process.env.NODE_ENV === 'production';

const nextConfig = {
  reactStrictMode: false,

  // === Static export (Flipper-deploy, 2026-08) ===
  // Фронт собирается в ./out/ — чистая статика без Node.js-сервера.
  // Деплоится на Vercel / Netlify / Cloudflare Pages / nginx / S3+CDN.
  // При правке фронта пересобирается только ./out/, Docker не трогаем.
  // В dev-режиме output НЕ export — чтобы работал SSR для force-dynamic
  // страниц с server-side fetch.
  ...(isProd ? { output: 'export' } : {}),
  // trailingSlash: true в production-билде (next build → out/foo/index.html
  // для shared-хостингов), но в dev-режиме (next dev) вызывает бесконечный
  // редирект 308 → / 308 → /, и страница не грузится. Поэтому только в prod.
  trailingSlash: isProd,
  // У Next Image отключаем оптимизатор (его некуда ставить без сервера).
  images: { unoptimized: true },
  // distDir оставляем дефолтный .next — `next export` сам кладёт готовую
  // статику в ./out, а .next используется только на этапе сборки.
};

export default nextConfig;
