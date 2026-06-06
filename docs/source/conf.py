import os
import sys

sys.path.insert(0, os.path.abspath("../.."))

# ReadTheDocs configuration
on_rtd = os.environ.get("READTHEDOCS") == "True"

project = "Runic"
copyright = "2026, Jens Rehpöhler"
author = "Jens Rehpöhler"
release = "0.2.2"
version = "0.2.2"

# ReadTheDocs version handling
if on_rtd:
    # On RTD, use the git tag or branch name
    rtd_version = os.environ.get("READTHEDOCS_VERSION", "latest")
    # Strip 'v' prefix from tags if present
    if rtd_version.startswith("v"):
        rtd_version = rtd_version[1:]
    if rtd_version not in ("latest", "stable"):
        version = rtd_version
        release = rtd_version

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_design",
]

templates_path = ["_templates"]
exclude_patterns: list[str] = []

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_logo = "_static/runic.svg"
html_favicon = "_static/runic.svg"
html_title = "Runic"

# Brand palette derived from logo (#354853, #254855, #254754)
_BRAND_LIGHT = "#0e7d92"      # vibrant teal — logo hue, lifted for legibility
_BRAND_CONTENT = "#0a6678"    # slightly deeper for body links
_BRAND_DARK = "#45c1d5"       # bright teal for dark-mode contrast
_BRAND_CONTENT_DARK = "#6bd4e5"

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "light_css_variables": {
        # Core brand
        "color-brand-primary": _BRAND_LIGHT,
        "color-brand-content": _BRAND_CONTENT,
        # Sidebar
        "color-sidebar-background": "#f0f7f8",
        "color-sidebar-background--top": "#e4f2f4",
        "color-sidebar-background--border": "#4d7580",
        "color-sidebar-brand-text": "#1a3540",
        "color-sidebar-caption-text": "#4d7580",
        "color-sidebar-link-text": "#1a3540",
        "color-sidebar-link-text--top-level": "#0e3d4a",
        "color-sidebar-item-background--hover": "#d9eef1",
        "color-sidebar-item-background--current": "#c5e6eb",
        "color-sidebar-item-expander-background--hover": "#d9eef1",
        # Search
        "color-sidebar-search-text": "#1a3540",
        "color-sidebar-search-background": "#ffffff",
        "color-sidebar-search-background--focus": "#ffffff",
        "color-sidebar-search-border": "#4d7580",
        "color-sidebar-search-icon": "#4d7580",
        # Admonitions
        "color-admonition-background": "transparent",
        # Highlighted code
        "color-highlight-on-target": "#e4f2f4",
        # Font
        "font-stack": "'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "font-stack--monospace": "'Geist Mono', 'Fira Code', 'Cascadia Code', monospace",
    },
    "dark_css_variables": {
        "color-brand-primary": _BRAND_DARK,
        "color-brand-content": _BRAND_CONTENT_DARK,
        # Sidebar
        "color-sidebar-background": "#0d1e24",
        "color-sidebar-background--top": "#0a1920",
        "color-sidebar-background--border": "#1a3540",
        "color-sidebar-brand-text": "#c8e8ed",
        "color-sidebar-caption-text": "#6daab5",
        "color-sidebar-link-text": "#b0d8e0",
        "color-sidebar-link-text--top-level": "#c8e8ed",
        "color-sidebar-item-background--hover": "#172d35",
        "color-sidebar-item-background--current": "#1f3d48",
        "color-sidebar-item-expander-background--hover": "#172d35",
        # Search
        "color-sidebar-search-text": "#c8e8ed",
        "color-sidebar-search-background": "#0e2028",
        "color-sidebar-search-background--focus": "#0e2028",
        "color-sidebar-search-border": "#2a5060",
        "color-sidebar-search-icon": "#6daab5",
        # Font
        "font-stack": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        "font-stack--monospace": "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
    },
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/jenreh/runic",
            "html": '<svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 16 16"><path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path></svg>',
        }
    ],
    "top_of_page_buttons": ["view"],
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

autodoc_member_order = "bysource"
autodoc_typehints = "description"
napoleon_google_docstring = True

copybutton_prompt_text = r"^\$ |>>> |\.\.\. "
copybutton_prompt_is_regexp = True

pygments_style = "friendly"
pygments_dark_style = "one-dark"
