/**
 * Public marketing site that hosts the Terms of Service and Privacy Policy.
 *
 * Configurable at build time because the primary domain (harboriq.com) is
 * not currently attached to the deployed marketing site; linking legal
 * pages to a domain that returns an error would leave signup consent
 * pointing at nothing. Set VITE_MARKETING_SITE_URL to https://harboriq.com
 * once that domain serves the Vercel deployment.
 */
export const MARKETING_SITE_URL = (
  import.meta.env.VITE_MARKETING_SITE_URL ?? "https://harboriq-gamma.vercel.app"
).replace(/\/+$/, "");

export const TERMS_URL = `${MARKETING_SITE_URL}/#/terms`;
export const PRIVACY_URL = `${MARKETING_SITE_URL}/#/privacy`;
