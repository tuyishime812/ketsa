import type { MetadataRoute } from 'next';

/**
 * Sitemap for the Ketsa site. The public marketing pages are static and
 * crawlable; the live app surfaces (dashboard, portfolio, admin) are
 * deliberately excluded — they are per-wallet or private and would only add
 * noise to a crawler's budget.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const site = (process.env.KETSA_SITE_URL || 'http://localhost:3000').replace(
    /\/$/,
    '',
  );
  const lastModified = new Date();

  return [
    { url: site, lastModified, changeFrequency: 'hourly', priority: 1 },
    { url: `${site}/team`, lastModified, changeFrequency: 'daily', priority: 0.7 },
    { url: `${site}/terms`, lastModified, changeFrequency: 'yearly', priority: 0.3 },
    { url: `${site}/privacy`, lastModified, changeFrequency: 'yearly', priority: 0.3 },
  ];
}
