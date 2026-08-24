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

// Read the package version from pyproject.toml at build time so the navbar
// badge always matches the released version without manual updates.
const pyproject = readFileSync(new URL("../../pyproject.toml", import.meta.url), "utf-8");
const version = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1] ?? "";

export default defineConfigWithTheme<ThemeConfig>({
  title: "runic",
  description: "Graph schema migrations and OGM for Cypher-based graph databases.",
  base,
  ignoreDeadLinks: true,
  sitemap: {
    hostname: 'https://runic.rehpoehler.de/en/latest/'
  },

  head: [
    ["link", { rel: "icon", type: "image/svg+xml", href: `${base}runic.svg` }],
  ],

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
      message: `runic - Graph schema migrations and OGM for Cypher-based graph databases. · <a href="${base}impressum">Impressum</a>`,
      copyright: "Copyright © 2026",
    },

    search: {
      provider: 'local',
    },

  },
})
