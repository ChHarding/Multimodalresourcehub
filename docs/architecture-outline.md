The app is a single-file Streamlit app with four layers:
Configuration and styling. Page config, then one injected CSS block that defines the academic theme (a deep navy and warm gold palette, serif headings, card styles).
Placeholder data layer. Python lists and dicts for resources, exemplars, lesson plans, and rubrics. Each is a plain structure that you can later swap for a CSV, a database, or an API call.
Reusable UI components. Small functions such as render_card(), render_tags(), and section_header(), so every page draws cards the same way.
Page functions and router. One function per section (page_home, page_search, and so on). A sidebar radio menu stores the selection, and a dictionary maps each name to its page function.

