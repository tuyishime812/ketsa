import type { MetadataRoute } from 'next';

/**
 * Sitemap for the single-page Ketsa site. Anchor sections are reachable from
 * the root URL; the crawler only needs the root entry plus any explicit pages.
 */
export default function sitemap(): MetadataRoute.Sitemap {
  const site = process.env.KETSA_SITE_URL || 'http://localhost:3000';
  const lastModified = new Date();

  return [
    {
      url: site,
      lastModified,
      changeFrequency: 'hourly',
      priority: 1,
    },
  ];
}
