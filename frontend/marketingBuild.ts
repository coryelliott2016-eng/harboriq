import type { Plugin } from "vite";

const pages = [
  { path: "/", title: "Marine service software", heading: "Meet HarborIQ. The Intelligence Behind Smarter Marine Service.", description: "Explore marine service workflows, customers, vessels, jobs, dispatch, and reporting. Visit HarborIQ’s public AI Lab to check live engine availability." },
  { path: "/ai-demo", title: "AI Lab — Experience Marine Intelligence", heading: "HarborIQ AI Lab — Experience Marine Intelligence", description: "Explore engine, electrical, marine networking, and maintenance questions without registration. Live AI is unavailable until a verified HarborIQ inference engine is connected. No imitation answers are generated." },
  { path: "/contact", title: "Contact & early access", heading: "Request HarborIQ early access", description: "Request early access or a personalized marine service platform demonstration. Lead storage is confirmed only after the backend accepts your request. Email delivery and meeting bookings are not automatically confirmed." },
  { path: "/demo-disclosure", title: "AI demo limitations", heading: "HarborIQ demo limitations", description: "Suggested questions and synthetic service workflows are illustrative. No verified AI inference engine or predictive model is present in this checkout. Public demos have no customer database or privileged tool access. Do not enter sensitive information." },
];

function escape(value: string) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!);
}

function verifiedOrigin(value?: string) {
  if (!value) return "";
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" && parsed.origin === value.replace(/\/$/, "")
      ? parsed.origin : "";
  } catch { return ""; }
}

// Publish static, crawlable route summaries alongside the interactive React app.
export function marketingBuild(siteOrigin?: string): Plugin {
  const origin = verifiedOrigin(siteOrigin);
  function htmlFor(html: string, page: typeof pages[number]) {
    const title = escape(`${page.title} | HarborIQ`);
    const description = escape(page.description);
    const metadata = `<meta name="description" content="${description}">
    <meta property="og:title" content="${title}">
    <meta property="og:description" content="${description}">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary">
    ${origin ? `<link rel="canonical" href="${escape(origin + page.path)}">` : '<meta name="robots" content="noindex, nofollow">'}`;
    const summary = `<div id="root"><header><a href="/">HarborIQ</a><nav aria-label="Main navigation"><a href="/#platform">Platform</a> · <a href="/ai-demo">AI Lab</a> · <a href="/contact">Early access</a></nav></header>
    <main><h1>${escape(page.heading)}</h1><p>${description}</p>
    <p>From complex engine diagnostics to service management, discover how AI-powered intelligence can help marine professionals work smarter.</p>
    <p>AI diagnostics and predictive maintenance are not currently live. Explore authenticated service workflows without exposing customer records.</p>
    <a href="/ai-demo">Try HarborIQ AI</a> · <a href="/contact">Get Early Access</a> · <a href="/demo-disclosure">Demo limitations</a>
    <noscript>Enable JavaScript to check engine availability, use guided questions, or submit a contact request.</noscript></main></div>`;
    return html.replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`)
      .replace(/<meta name="description"[^>]*>/g, "")
      .replace("</head>", `${metadata}</head>`)
      .replace(/<div id="root"><\/div>/, summary);
  }
  return {
    name: "harboriq-marketing-pages",
    enforce: "post",
    generateBundle(_options, bundle) {
      const index = bundle["index.html"];
      if (!index || index.type !== "asset" || typeof index.source !== "string") {
        throw new Error("Marketing build requires an index.html entry.");
      }
      const original = index.source;
      index.source = htmlFor(original, pages[0]);
      for (const page of pages.slice(1)) {
        this.emitFile({ type: "asset", fileName: `${page.path.slice(1)}/index.html`, source: htmlFor(original, page) });
      }
      this.emitFile({ type: "asset", fileName: "robots.txt", source: origin
        ? `User-agent: *\nAllow: /\nSitemap: ${origin}/sitemap.xml\n`
        : "User-agent: *\nDisallow: /\n" });
      if (origin) this.emitFile({ type: "asset", fileName: "sitemap.xml", source:
        `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${pages.map((page) => `<url><loc>${escape(origin + page.path)}</loc></url>`).join("")}</urlset>\n` });
    },
  };
}
