// https://vitepress.dev/guide/custom-theme
import { h } from 'vue'
import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import { inBrowser, useData } from 'vitepress'
import './style.css'

export default {
  extends: DefaultTheme,
  Layout: () => {
    const { theme } = useData()
    return h(DefaultTheme.Layout, null, {
      // https://vitepress.dev/guide/extending-default-theme#layout-slots
      // Render the package version right after the social links (GitHub icon).
      'nav-bar-content-after': () =>
        theme.value.version
          ? h(
              'span',
              { class: 'nav-version' },
              `v${theme.value.version}`,
            )
          : null,
    })
  },
  enhanceApp({ app, router, siteData }) {
    if (inBrowser) {
      // One delegated, capturing listener: scroll events don't bubble, but
      // they fire on ancestors in the capture phase. This catches every
      // `.table-scroll` (current, future, across route changes) and toggles
      // `is-scrolled-x` so the sticky first column shows a right-edge shadow
      // only while the table is scrolled horizontally.
      document.addEventListener(
        'scroll',
        (e) => {
          const el = e.target as HTMLElement
          if (el?.classList?.contains('table-scroll')) {
            el.classList.toggle('is-scrolled-x', el.scrollLeft > 0)
          }
        },
        { capture: true, passive: true },
      )
    }
  }
} satisfies Theme
