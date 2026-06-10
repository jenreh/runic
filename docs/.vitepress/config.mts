import { defineConfig } from 'vitepress'

// ReadTheDocs serves docs at /en/latest/ (or /en/<version>/); derive base from
// the canonical URL it injects so asset paths resolve correctly.
const rtdCanonical = process.env.READTHEDOCS_CANONICAL_URL;
const base = rtdCanonical ? new URL(rtdCanonical).pathname : "/";

export default defineConfig({
  title: "runic",
  description: "Graph schema migrations and OGM for Cypher-based graph databases.",
  base,
  ignoreDeadLinks: true,

  markdown: {
    lineNumbers: true,
  },

  themeConfig: {
    logo: '/runic.svg',

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
      message: "pantau-alexa — self-hosted Alexa Smart Home backend",
      copyright: "Copyright © 2026",
    },

    search: {
      provider: 'local',
    },

  },
})
