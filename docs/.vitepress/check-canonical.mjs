// Post-build guard: every emitted page must declare exactly one canonical URL,
// and that URL must be DOCS_ROOT + pagename — never the version prefix this
// build happens to be served under (/en/latest/, /en/stable/, /en/<tag>/).
//
// Run via `npm run docs:check-canonical` after a build; `npm run docs:build`
// chains it, so a regression fails the Read the Docs build instead of quietly
// splitting one page across several indexed URLs.

import { readFile, readdir } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { DOCS_ROOT, canonicalForHtml } from "./canonical.mjs";

const DIST = fileURLToPath(new URL("./dist/", import.meta.url));

// Pages VitePress renders without page data, so `transformPageData` never runs
// and no canonical is emitted. Excluding them here keeps the check honest.
const EXEMPT = new Set(["404.html"]);

/** @param {string} dir @returns {AsyncGenerator<string>} */
async function* htmlFiles(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* htmlFiles(full);
    else if (entry.name.endsWith(".html")) yield full;
  }
}

/** @param {string} html @param {RegExp} pattern @returns {string[]} */
function matchAll(html, pattern) {
  return [...html.matchAll(pattern)].map((m) => m[1]);
}

const failures = [];
let checked = 0;

for await (const file of htmlFiles(DIST)) {
  const page = relative(DIST, file).split(sep).join("/");
  if (EXEMPT.has(page)) continue;

  const html = await readFile(file, "utf-8");
  const expected = canonicalForHtml(page);
  const canonicals = matchAll(
    html,
    /<link[^>]+rel="canonical"[^>]+href="([^"]*)"/g,
  );
  const ogUrls = matchAll(
    html,
    /<meta[^>]+property="og:url"[^>]+content="([^"]*)"/g,
  );

  if (canonicals.length !== 1) {
    failures.push(`${page}: expected 1 canonical link, found ${canonicals.length}`);
  } else if (canonicals[0] !== expected) {
    failures.push(`${page}: canonical is ${canonicals[0]}, expected ${expected}`);
  }
  if (ogUrls.length === 1 && ogUrls[0] !== expected) {
    failures.push(`${page}: og:url is ${ogUrls[0]}, expected ${expected}`);
  }
  checked += 1;
}

if (checked === 0) {
  console.error(`No HTML found under ${DIST} — run the build first.`);
  process.exit(1);
}

if (failures.length > 0) {
  console.error(`Canonical check failed (${failures.length} problem(s)):`);
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(`Canonical check passed: ${checked} page(s) all point at ${DOCS_ROOT}<pagename>.`);
