import { describe, expect, it } from "vitest";
import type { OutputBundle, PluginContext } from "rollup";
import { marketingBuild } from "./marketingBuild";

function generate(origin?: string) {
  const plugin = marketingBuild(origin);
  const emitted: { fileName: string; source: string }[] = [];
  const bundle = { "index.html": {
    type: "asset", source: '<html><head><title>HarborIQ</title></head><body><div id="root"></div><script src="/assets/app.js"></script></body></html>',
  } } as unknown as OutputBundle;
  const hook = plugin.generateBundle;
  if (typeof hook !== "function") throw new Error("Expected a generateBundle function");
  hook.call({ emitFile: (asset: { fileName: string; source: string }) => {
    emitted.push(asset); return asset.fileName;
  } } as unknown as PluginContext, {} as never, bundle, false);
  const index = bundle["index.html"];
  if (index.type !== "asset") throw new Error("Expected an HTML asset");
  return { emitted, html: String(index.source) };
}

describe("separate marketing build", () => {
  it("publishes crawlable summaries and excludes previews from indexing", () => {
    const { html, emitted } = generate();
    expect(html).toContain("<h1>Meet HarborIQ.");
    expect(html).toContain('name="robots" content="noindex, nofollow"');
    expect(html).toContain('src="/assets/app.js"');
    expect(emitted.find((file) => file.fileName === "robots.txt")?.source).toContain("Disallow: /");
    expect(emitted.some((file) => file.fileName === "sitemap.xml")).toBe(false);
    expect(emitted.filter((file) => file.fileName.endsWith("/index.html"))).toHaveLength(3);
    expect(emitted.find((file) => file.fileName === "ai-demo/index.html")?.source).toContain("Live AI is unavailable");
  });

  it("only enables canonical URLs and sitemap for a configured HTTPS origin", () => {
    const { html, emitted } = generate("https://marketing.example");
    expect(html).toContain('rel="canonical" href="https://marketing.example/"');
    expect(emitted.find((file) => file.fileName === "sitemap.xml")?.source).toContain("https://marketing.example/ai-demo");
    expect(emitted.find((file) => file.fileName === "robots.txt")?.source).toContain("Sitemap: https://marketing.example/sitemap.xml");
    expect(generate("******marketing.example").html).toContain("noindex");
    expect(generate('https://marketing.example/path"><script>').html).toContain("noindex");
    expect(generate("http://marketing.example").html).toContain("noindex");
  });
});
