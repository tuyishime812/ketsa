import type { MetadataRoute } from 'next';

/**
 * Robots rules. Allow all crawling of the public marketing site.
 * Set `KETSA_SITE_URL` (e.g. https://ketsa.example.com) to include the
 * sitemap URL and a proper host; defaults to a safe localhost placeholder.
 */
const site = process.env.KETSA_SITE_URL || 'http://localhost:3000';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
    },
    sitemap: `${site}/sitemap.xml`,
    host: site,
  };
}
