// Canonical URL derivation, shared by the VitePress config (which emits the
// tags) and by `check-canonical.mjs` (which verifies the built HTML).
//
// Read the Docs serves every version behind its own prefix — /en/latest/,
// /en/v0.6.0/, /en/stable/ — and `base` follows that prefix so assets resolve.
// The canonical URL deliberately does NOT follow it: every version of a page
// points at the same DOCS_ROOT + pagename URL, so crawlers only ever index one
// copy and link equity never splits across versions.

/** Production origin. Absolute even in local builds, so crawlers never see localhost. */
export const SITE_URL = "https://runic.rehpoehler.de";

/** Version-independent root that every canonical URL is built from. */
export const DOCS_ROOT = `${SITE_URL}/en/latest/`;

/**
 * The page name for a VitePress `relativePath`, e.g. `ogm/api.md` -> `ogm/api.html`,
 * `rag/index.md` -> `rag/`, `index.md` -> `` (empty, i.e. DOCS_ROOT itself).
 *
 * The `index` match is anchored to a path segment so a page called
 * `myindex.md` is not mangled into `my`.
 *
 * @param {string} relativePath VitePress page `relativePath`.
 * @returns {string}
 */
export function pageNameFor(relativePath) {
  return relativePath
    .replace(/(^|\/)index\.md$/, "$1")
    .replace(/\.md$/, ".html");
}

/**
 * Canonical URL for a VitePress `relativePath` — always DOCS_ROOT + pagename,
 * independent of the version this build is served under.
 *
 * @param {string} relativePath VitePress page `relativePath`.
 * @returns {string}
 */
export function canonicalFor(relativePath) {
  return `${DOCS_ROOT}${pageNameFor(relativePath)}`;
}

/**
 * Canonical URL for an emitted HTML file, e.g. `ogm/api.html` or `rag/index.html`.
 * The inverse view of {@link canonicalFor}, used to audit a finished build.
 *
 * @param {string} htmlPath Path of the HTML file relative to the output root.
 * @returns {string}
 */
export function canonicalForHtml(htmlPath) {
  return `${DOCS_ROOT}${htmlPath.replace(/(^|\/)index\.html$/, "$1")}`;
}
