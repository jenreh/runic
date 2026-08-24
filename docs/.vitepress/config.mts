import { readFileSync } from 'node:fs'
import { defineConfigWithTheme } from 'vitepress'
import type { DefaultTheme } from 'vitepress'

// Extend the default theme config with a `version` field consumed by the
// custom navbar slot.
interface ThemeConfig extends DefaultTheme.Config {
  version: string
}

// ReadTheDocs serves docs at /en/latest/ (or /en/<version>/); derive base from
// the canonical URL it injects so asset paths resolve correctly.
const rtdCanonical = process.env.READTHEDOCS_CANONICAL_URL;
const base = rtdCanonical ? new URL(rtdCanonical).pathname : "/";

// Absolute origin + docs root used for canonical links, `og:url`, and social
// card images. These must stay absolute and production-facing even in local
// builds (where `base` is "/"), otherwise crawlers get relative or localhost
// URLs. RTD serves the published docs under /en/<version>/.
const SITE_URL = "https://runic.rehpoehler.de";
const DOCS_ROOT = `${SITE_URL}/en/latest/`;
const SITE_DESCRIPTION =
  "Python graph OGM, Graph-RAG toolkit and Alembic-style schema migrations " +
  "for Cypher graph databases — FalkorDB, Neo4j, Memgraph, ArcadeDB and Apache AGE.";

// Read the package version from pyproject.toml at build time so the navbar
// badge always matches the released version without manual updates.
const pyproject = readFileSync(new URL("../../pyproject.toml", import.meta.url), "utf-8");
const version = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1] ?? "";

export default defineConfigWithTheme<ThemeConfig>({
  title: "runic",
  description: SITE_DESCRIPTION,
  base,
  ignoreDeadLinks: true,
  sitemap: {
    hostname: DOCS_ROOT
  },

  head: [
    // Inverted favicon: the rune knocked out of a solid tile in the logo's own
    // slate. The raster fallbacks earn their place — search-engine crawlers
    // commonly fetch /favicon.ico or a sized PNG and never look at the SVG.
    ["link", { rel: "icon", type: "image/svg+xml", href: `${base}favicon.svg` }],
    ["link", { rel: "icon", type: "image/x-icon", sizes: "any", href: `${base}favicon.ico` }],
    ["link", { rel: "icon", type: "image/png", sizes: "96x96", href: `${base}favicon-96.png` }],
    ["link", { rel: "apple-touch-icon", sizes: "180x180", href: `${base}apple-touch-icon.png` }],
    ["meta", { name: "theme-color", content: "#354853" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:site_name", content: "runic" }],
    ["meta", { property: "og:locale", content: "en_US" }],
    ["meta", { property: "og:image", content: `${DOCS_ROOT}og-runic.png` }],
    ["meta", { property: "og:image:width", content: "1200" }],
    ["meta", { property: "og:image:height", content: "630" }],
    [
      "meta",
      {
        property: "og:image:alt",
        content: "runic — Python graph OGM, migrations and Graph-RAG for Cypher graph databases",
      },
    ],
    ["meta", { name: "twitter:card", content: "summary_large_image" }],
    ["meta", { name: "twitter:image", content: `${DOCS_ROOT}og-runic.png` }],
  ],

  // Per-page canonical + social metadata. VitePress emits `<title>` and
  // `<meta name="description">` on its own; everything below is derived from
  // the same page data so the two never drift apart.
  transformPageData(pageData) {
    if (pageData.relativePath === "404.md") return;

    const canonical = `${DOCS_ROOT}${pageData.relativePath}`
      .replace(/index\.md$/, "")
      .replace(/\.md$/, ".html");

    const pageTitle = pageData.frontmatter.title ?? pageData.title ?? "runic";
    // Mirror VitePress' own `<title>` resolution: a page opting out of the
    // title template (the home page) keeps its title verbatim.
    const socialTitle =
      pageData.frontmatter.titleTemplate === false || pageTitle === "runic"
        ? pageTitle
        : `${pageTitle} | runic`;
    const description = pageData.frontmatter.description ?? SITE_DESCRIPTION;

    pageData.frontmatter.head ??= [];
    pageData.frontmatter.head.push(
      ["link", { rel: "canonical", href: canonical }],
      ["meta", { property: "og:url", content: canonical }],
      ["meta", { property: "og:title", content: socialTitle }],
      ["meta", { property: "og:description", content: description }],
      ["meta", { name: "twitter:title", content: socialTitle }],
      ["meta", { name: "twitter:description", content: description }],
    );
  },

  markdown: {
    lineNumbers: true,
    config: (md) => {
      const defaultTableOpen = md.renderer.rules.table_open ??
        ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
      const defaultTableClose = md.renderer.rules.table_close ??
        ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options))
      md.renderer.rules.table_open = (...args) =>
        '<div class="table-scroll">' + defaultTableOpen(...args)
      md.renderer.rules.table_close = (...args) =>
        defaultTableClose(...args) + '</div>'
    },
  },

  themeConfig: {
    logo: '/runic.svg',
    // Surfaced in the navbar (right of the social links) via the theme's
    // `nav-bar-content-after` slot.
    version,

    nav: [
      { text: 'Home', link: '/' },
      { text: 'Installation', link: '/installation' },
      {
        text: 'OGM',
        items: [
          { text: 'Quickstart', link: '/ogm/quickstart' },
          { text: 'Define your models', link: '/ogm/concepts' },
          { text: 'Relationships', link: '/ogm/relationships' },
          { text: 'Query Builder', link: '/ogm/query-builder' },
          { text: 'Statement Catalogues', link: '/ogm/statements' },
          { text: 'Read and write data', link: '/ogm/session' },
          { text: 'Async Guide', link: '/ogm/async' },
          { text: 'Test your OGM code', link: '/ogm/testing' },
          { text: 'Supported Drivers', link: '/ogm/drivers' },
          { text: 'API Reference', link: '/ogm/api' },
        ],
      },
      {
        text: 'Migration',
        items: [
          { text: 'Quickstart', link: '/migration/quickstart' },
          { text: 'OGM and Migrations', link: '/migration/integration' },
          { text: 'CLI Reference', link: '/migration/cli-reference' },
          { text: 'Schema Management', link: '/migration/schema' },
          { text: 'Operations Reference', link: '/migration/operations-reference' },
          { text: 'Autogenerate', link: '/migration/autogenerate' },
          { text: 'Branching & Merging', link: '/migration/branching' },
          { text: 'Testing Migrations', link: '/migration/testing' },
          { text: 'Limitations', link: '/migration/limitations' },
          { text: 'API Reference', link: '/migration/api' },
        ],
      },
      {
        text: 'Graph-RAG',
        items: [
          { text: 'What is Graph-RAG?', link: '/rag/concepts' },
          { text: 'Quickstart', link: '/rag/quickstart' },
          { text: 'Ingesting documents', link: '/rag/ingestion' },
          { text: 'Retrieval & answers', link: '/rag/retrieval' },
          { text: 'Designing & optimizing ontologies', link: '/rag/ontologies' },
          { text: 'Evaluating quality', link: '/rag/evaluation' },
          { text: 'Configuration & deployment', link: '/rag/configuration' },
          { text: 'Writing custom ports', link: '/rag/custom-ports' },
          { text: 'Document parsing with Docling', link: '/rag/docling' },
          { text: 'API Reference', link: '/rag/api' },
        ],
      },
    ],

    sidebar: {
      '/ogm/': [
        {
          text: 'OGM',
          items: [
            { text: 'Quickstart', link: '/ogm/quickstart' },
            { text: 'Define your models', link: '/ogm/concepts' },
            { text: 'Relationships', link: '/ogm/relationships' },
            { text: 'Query Builder', link: '/ogm/query-builder' },
            { text: 'Statement Catalogues', link: '/ogm/statements' },
            { text: 'Read and write data', link: '/ogm/session' },
            { text: 'Async Guide', link: '/ogm/async' },
            { text: 'Test your OGM code', link: '/ogm/testing' },
            { text: 'Supported Drivers', link: '/ogm/drivers' },
            { text: 'API Reference', link: '/ogm/api' },
          ],
        },
      ],
      '/migration/': [
        {
          text: 'Migration',
          items: [
            { text: 'Quickstart', link: '/migration/quickstart' },
            { text: 'OGM and Migrations', link: '/migration/integration' },
            { text: 'CLI Reference', link: '/migration/cli-reference' },
            { text: 'Schema Management', link: '/migration/schema' },
            { text: 'Operations Reference', link: '/migration/operations-reference' },
            { text: 'Autogenerate', link: '/migration/autogenerate' },
            { text: 'Branching & Merging', link: '/migration/branching' },
            { text: 'Testing Migrations', link: '/migration/testing' },
            { text: 'Limitations', link: '/migration/limitations' },
            { text: 'API Reference', link: '/migration/api' },
          ],
        },
      ],
      '/rag/': [
        {
          text: 'Graph-RAG',
          link: '/rag/',
          items: [
            { text: 'What is Graph-RAG?', link: '/rag/concepts' },
            { text: 'Quickstart', link: '/rag/quickstart' },
            { text: 'Ingesting documents', link: '/rag/ingestion' },
            { text: 'Retrieval & answers', link: '/rag/retrieval' },
            { text: 'Designing & optimizing ontologies', link: '/rag/ontologies' },
            { text: 'Evaluating quality', link: '/rag/evaluation' },
            { text: 'Configuration & deployment', link: '/rag/configuration' },
            { text: 'Writing custom ports', link: '/rag/custom-ports' },
            { text: 'Document parsing with Docling', link: '/rag/docling' },
            { text: 'API Reference', link: '/rag/api' },
          ],
        },
      ],
      '/': [
        {
          text: 'Getting Started',
          items: [
            { text: 'Installation', link: '/installation' },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/jenreh/runic' },
    ],

    footer: {
      message: `runic — Python graph OGM, schema migrations and Graph-RAG for Cypher graph databases. · <a href="${base}impressum">Impressum</a><img src="${base}badges/ai-generated-black.svg" alt="AI generated" class="footer-ai-badge footer-ai-badge-light"><img src="${base}badges/ai-generated-white.svg" alt="AI generated" class="footer-ai-badge footer-ai-badge-dark">`,
      copyright: "Copyright © 2026",
    },

    search: {
      provider: 'local',
    },

  },
})
