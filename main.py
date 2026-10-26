"""
Multimodal Studio Hub: project skeleton
Run with:  pip install streamlit  then  streamlit run app.py

File layout (top to bottom):
  1. Page configuration
  2. Theme and CSS
  3. Placeholder data
  4. Reusable UI components
  5. Page functions (one per sidebar section)
  6. Router and sidebar (main)
"""

import html
import io
import re
import zipfile

import streamlit as st

# ---------------------------------------------------------------------------
# 1. PAGE CONFIGURATION
# Must be the first Streamlit call in the script.
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Multimodal Studio Hub",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# 2. THEME AND CSS
# Palette: ink navy (#16213E), cool paper (#F5F7FA), rule gray (#D9E0E7).
# Each modality has its own color; cards use it as a left border so the
# medium of a resource is readable at a glance.
# ---------------------------------------------------------------------------
MODALITY_COLORS = {
    "Written": "#4B3A7A",
    "Visual": "#16807A",
    "Audio": "#B8453A",
    "Video": "#8A3B5E",
    "Interactive": "#3F7D4E",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

/* Design tokens: brand palette, 4px-based spacing scale, corner radius */
:root {
  --plum: #2D1E4F; --plum-soft: #4B3A7A; --coral: #FF6B5B; --coral-hover: #FF8274;
  --teal: #1FA39A; --lavender: #F6F3FC; --ink: #1E1533; --muted: #5A5170; --line: #E3DCF3;
  --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px; --radius: 14px;
}

/* Page, text, and headings */
.stApp { background: #FFFFFF; color: var(--ink); }
[data-testid="stHeader"] { background: transparent; }
.block-container, [data-testid="stMainBlockContainer"] { max-width: 1120px; padding: var(--s6) var(--s5) var(--s7); }
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"], [data-testid="stCaptionContainer"] { font-family: 'Plus Jakarta Sans', system-ui, sans-serif; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { color: var(--ink); line-height: 1.6; }
[data-testid="stCaptionContainer"] { color: var(--muted); }
h1, h2, h3, h4, h5 { font-family: 'Fraunces', Georgia, serif !important; color: var(--plum); letter-spacing: -0.01em; }
.stApp h1 { font-size: clamp(1.9rem, 1.4rem + 2vw, 2.6rem) !important; font-weight: 700; }
.stApp h2 { font-size: clamp(1.4rem, 1.2rem + 1vw, 1.8rem) !important; margin-top: var(--s5); }
.stApp h3.res-title { font-size: 1.25rem !important; padding: 0 !important; margin: 0 0 var(--s2); }
.lead { color: var(--muted) !important; font-size: 1.05rem; max-width: 70ch; margin-bottom: var(--s5); }

/* Sidebar: lavender, logo, and navigation links */
[data-testid="stSidebar"] { background: var(--lavender); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] .logo-row { display: flex; align-items: center; gap: var(--s3); margin: var(--s2) 0 var(--s5); }
[data-testid="stSidebar"] .logo { position: relative; width: 44px; height: 44px; flex: none; border-radius: 12px; background: var(--plum); color: #FFFFFF; display: flex; align-items: center; justify-content: center; font-family: 'Fraunces', Georgia, serif; font-weight: 700; font-size: 1.1rem; }
[data-testid="stSidebar"] .logo::after { content: ""; position: absolute; right: -4px; bottom: -4px; width: 14px; height: 14px; border-radius: 50%; background: var(--coral); border: 2px solid var(--lavender); }
[data-testid="stSidebar"] .brand { font-family: 'Fraunces', Georgia, serif; font-size: 1.2rem; font-weight: 700; color: var(--plum); line-height: 1.15; }
[data-testid="stSidebar"] .tagline { font-size: .85rem; color: var(--muted); margin-top: 2px; }
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] { gap: 4px; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { width: 100%; padding: 10px 14px; border-radius: 10px; cursor: pointer; }
[data-testid="stSidebar"] [data-testid="stRadio"] label p { font-weight: 600; color: var(--plum); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background: #EBE5F8; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) { background: var(--plum); }
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p { color: #FFFFFF; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--muted); }

/* Hero banner (Home) */
.hero { background: radial-gradient(circle at 88% 16%, rgba(255,107,91,.55), transparent 38%), radial-gradient(circle at 100% 100%, rgba(31,163,154,.45), transparent 34%), var(--plum); border-radius: 20px; padding: clamp(24px, 5vw, 56px); margin-bottom: var(--s4); }
.stApp h1.hero-title { font-size: clamp(1.8rem, 1.2rem + 2.6vw, 3rem) !important; line-height: 1.12; color: #FFFFFF !important; max-width: 20ch; margin: 0 0 var(--s3); padding: 0; }
.hero p { color: #E6DFF5 !important; font-size: 1.05rem; max-width: 56ch; margin: 0; }
.chips { display: flex; flex-wrap: wrap; gap: var(--s3); margin-top: var(--s5); }
.chip { background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.3); border-radius: 12px; padding: var(--s2) var(--s4); color: #FFFFFF; font-size: .95rem; }
.chip b { font-family: 'Fraunces', Georgia, serif; font-size: 1.5rem; margin-right: var(--s2); }

/* Cards and panels (keyed containers) */
[class*="st-key-card_"] { background: var(--lavender) !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important; padding: var(--s5) !important; gap: var(--s3) !important; box-shadow: 0 1px 2px rgba(45,30,79,.06), 0 6px 18px rgba(45,30,79,.05); transition: box-shadow .15s ease; }
[class*="st-key-card_"]:hover { box-shadow: 0 2px 4px rgba(45,30,79,.08), 0 10px 24px rgba(45,30,79,.1); }
[class*="st-key-panel_"] { background: var(--lavender) !important; border: 1px solid var(--line) !important; border-radius: var(--radius) !important; padding: var(--s5) !important; }
@media (prefers-reduced-motion: reduce) { [class*="st-key-card_"] { transition: none; } }

/* Badges, pills, thumbnails */
.badge { display: inline-block; color: #FFFFFF; border-radius: 999px; padding: 3px 12px; font-size: .85rem; font-weight: 600; }
.badge.success { background: var(--teal); color: var(--plum); }
.pill { display: inline-block; background: #FFFFFF; border: 1px solid var(--line); color: var(--plum); border-radius: 999px; padding: 2px 12px; font-size: .85rem; margin: 0 var(--s2) var(--s2) 0; }
.thumb { aspect-ratio: 16 / 9; border-radius: 10px; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #FFFFFF; text-align: center; }
.thumb b { font-family: 'Fraunces', Georgia, serif; font-size: 1.5rem; }
.thumb span { font-size: .85rem; }

/* Buttons: coral for primary actions, plum outline for secondary */
[data-testid="stBaseButton-primary"] { background: var(--coral) !important; border: 2px solid var(--coral) !important; border-radius: 999px !important; font-weight: 700; }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primary"] p { color: var(--plum) !important; }
[data-testid="stBaseButton-primary"]:hover { background: var(--coral-hover) !important; border-color: var(--coral-hover) !important; }
[data-testid="stBaseButton-secondary"], [data-testid^="stBaseLinkButton"] { background: #FFFFFF !important; border: 2px solid var(--plum) !important; border-radius: 999px !important; font-weight: 600; }
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondary"] p, [data-testid^="stBaseLinkButton"], [data-testid^="stBaseLinkButton"] p { color: var(--plum) !important; }
[data-testid="stBaseButton-secondary"]:hover, [data-testid^="stBaseLinkButton"]:hover { background: var(--plum) !important; }
[data-testid="stBaseButton-secondary"]:hover p, [data-testid^="stBaseLinkButton"]:hover p { color: #FFFFFF !important; }

/* Inputs, labels, expanders */
[data-testid="stWidgetLabel"] p { font-weight: 600; color: var(--plum); }
[data-baseweb="input"], [data-baseweb="select"] > div { background: #FFFFFF; border-radius: 10px; border-color: #CFC5E8; }
[data-testid="stExpander"] { background: #FFFFFF; border: 1px solid var(--line); border-radius: 10px; }
[data-testid="stExpander"] summary { font-weight: 600; color: var(--plum); }

/* Notices: coral for alerts and empty states, teal for success */
.notice { border-radius: 12px; padding: var(--s4) var(--s5); margin: var(--s3) 0; background: #FFF1EF; border: 1px solid #FFC9C2; border-left: 6px solid var(--coral); color: var(--ink); line-height: 1.55; }
.notice.success { background: #E8F7F5; border-color: #B5E4DF; border-left-color: var(--teal); }

/* Visible keyboard focus */
.stApp button:focus-visible, .stApp input:focus-visible, .stApp a:focus-visible, .stApp [role="combobox"]:focus-visible, .stApp summary:focus-visible, .stApp label:has(input:focus-visible) { outline: 3px solid var(--plum) !important; outline-offset: 3px; }

/* Rubric table */
.table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; }
table.rubric { border-collapse: collapse; width: 100%; font-size: .92rem; min-width: 640px; }
table.rubric th { background: var(--plum); color: #FFFFFF; text-align: left; padding: var(--s3) var(--s4); font-weight: 600; }
table.rubric td { border-top: 1px solid var(--line); padding: var(--s3) var(--s4); vertical-align: top; color: var(--ink); background: #FFFFFF; }
table.rubric th.crit { background: var(--lavender); color: var(--plum); border-top: 1px solid var(--line); }

/* Small screens: tighter page padding and smaller hero details */
@media (max-width: 640px) {
  .block-container, [data-testid="stMainBlockContainer"] { padding: var(--s4) var(--s4) var(--s6); }
  .hero { border-radius: 16px; }
  .chip b { font-size: 1.25rem; }
}
</style>
"""

# ---------------------------------------------------------------------------
# 3. PLACEHOLDER DATA
# Plain Python structures. Replace with CSV, a database, or an API later.
# ---------------------------------------------------------------------------
COURSES = ["Composition I", "Intro to Communication", "Public Speaking"]

RESOURCES = [
    {"title": "Podcast planning template", "featured": True, "genre": "Podcast", "modality": "Audio", "format": "Template", "course": "Public Speaking",
     "description": "A one-page planner for episode purpose, segment order, scripting, and sound cues.",
     "tags": ["planning", "scripting", "audio"],
     "includes": ["Episode purpose statement", "Segment-by-segment script table", "Sound cue log"],
     "classroom_use": "Hand out before recording so students plan structure before opening audio software."},
    {"title": "Recording clean audio on a phone", "genre": "Podcast", "modality": "Audio", "format": "Guide", "course": "Intro to Communication",
     "description": "Practical steps for quiet spaces, microphone distance, and basic editing with free software.",
     "tags": ["recording", "equipment", "editing"],
     "includes": ["Room and mic checklist", "Three-step edit workflow", "Export settings"],
     "classroom_use": "Use in a 20-minute lab session so every group records a test clip."},
    {"title": "Infographic design checklist", "genre": "Infographic", "modality": "Visual", "format": "Checklist", "course": "Intro to Communication",
     "description": "Covers visual hierarchy, color contrast, data labeling, and source notes.",
     "tags": ["design", "hierarchy", "contrast"],
     "includes": ["Twelve-point self-check", "Contrast and type-size reminders"],
     "classroom_use": "Students check their own draft, then swap with a peer for a second review."},
    {"title": "Choosing charts for a claim", "genre": "Infographic", "modality": "Visual", "format": "Guide", "course": "Composition I",
     "description": "Matches common claims (trend, comparison, share of a whole) to chart types and shows what to avoid.",
     "tags": ["data", "charts", "evidence"],
     "includes": ["Claim-to-chart table", "Three before-and-after examples"],
     "classroom_use": "Pair with a short dataset and ask students to defend one chart choice in writing."},
    {"title": "Storyboarding a two-minute video essay", "featured": True, "genre": "Video essay", "modality": "Video", "format": "Guide", "course": "Composition I",
     "description": "Walks through shot lists, voiceover timing, and revision checkpoints.",
     "tags": ["storyboard", "video", "revision"],
     "includes": ["Storyboard grid", "Shot list template", "Two revision checkpoints"],
     "classroom_use": "Assign the storyboard as a graded draft before any footage is collected."},
    {"title": "Voiceover and pacing practice", "genre": "Video essay", "modality": "Video", "format": "Activity", "course": "Public Speaking",
     "description": "Short drills for pacing, emphasis, and pauses when reading a script aloud over images.",
     "tags": ["voiceover", "timing", "delivery"],
     "includes": ["Three practice passages", "Self-evaluation prompts"],
     "classroom_use": "Run in pairs during class; students record once and revise once."},
    {"title": "Building a photo essay sequence", "genre": "Photo essay", "modality": "Visual", "format": "Guide", "course": "Composition I",
     "description": "Shows how to order images and write captions so each frame adds to one central claim.",
     "tags": ["sequencing", "captions", "images"],
     "includes": ["Sequencing exercise", "Caption-writing prompts"],
     "classroom_use": "Have students rearrange a shuffled set of images and explain the new order."},
    {"title": "Interactive timeline starter", "genre": "Interactive timeline", "modality": "Interactive", "format": "Tool", "course": "Intro to Communication",
     "description": "A no-code timeline students can adapt to tell a research story with images and short text.",
     "tags": ["timeline", "web", "storytelling"],
     "includes": ["Starter template", "Setup instructions"],
     "classroom_use": "Good for a final project where students trace how an issue changed over time."},
    {"title": "Writing alt text and captions", "featured": True, "genre": "Cross-genre", "modality": "Visual", "format": "Guide", "course": "All courses",
     "description": "A short practice set for describing images and video so projects are accessible.",
     "tags": ["accessibility", "alt text", "captions"],
     "includes": ["Alt text do and don't list", "Five practice images"],
     "classroom_use": "Require alt text and captions as a line item on every multimodal rubric."},
    {"title": "Citing images, audio, and AI tools", "genre": "Cross-genre", "modality": "Written", "format": "Reference", "course": "All courses",
     "description": "Sample citations and disclosure statements for multimodal work.",
     "tags": ["citation", "AI policy", "attribution"],
     "includes": ["Citation patterns for images, audio, and video", "Sample AI disclosure statement"],
     "classroom_use": "Attach to the assignment sheet so expectations are clear before work begins."},
]

# Genres for the filter menu are built from the data, so new genres appear automatically
GENRES = sorted({r["genre"] for r in RESOURCES})

# Keywords shown as one-click suggestions (each returns at least one result)
SUGGESTED_KEYWORDS = ["podcast", "storyboard", "accessibility", "data", "citation", "timeline"]

# How many past searches to remember per browser session
MAX_HISTORY = 5

# Exemplar genres and their colors (white text on each color meets contrast guidelines)
EXEMPLAR_GENRE_COLORS = {
    "Comics": "#B45309",
    "Digital Story": "#6B4E9B",
    "Infographic": "#16807A",
    "Podcast": "#B8453A",
    "Poster": "#3F7D4E",
    "Video Essay": "#8A3B5E",
    "Website": "#4B3A7A",
}
EXEMPLAR_GENRES = list(EXEMPLAR_GENRE_COLORS)
SORT_OPTIONS = ["Genre (A to Z)", "Genre (Z to A)", "Title (A to Z)"]

# Each exemplar: title, genre, modality (feeds the Home strip), course, description,
# objectives, and a link (placeholder URLs; replace with real project links)
EXEMPLARS = [
    {"title": "Neighborhood Food Pantry Guide", "genre": "Website", "modality": "Interactive", "course": "Composition I",
     "description": "A three-page site that helps first-year students find campus and community food resources.",
     "objectives": ["Organize information with clear navigation", "Write concise web copy for a specific audience", "Apply basic accessibility practices such as alt text"],
     "url": "https://example.com/exemplars/food-pantry-guide"},
    {"title": "Study Abroad Stories Portfolio", "genre": "Website", "modality": "Interactive", "course": "Intro to Communication",
     "description": "A portfolio site that combines reflective writing, photographs, and a simple map.",
     "objectives": ["Design a cohesive visual identity", "Connect text and images to support a reflection", "Credit sources and image permissions"],
     "url": "https://example.com/exemplars/study-abroad-portfolio"},
    {"title": "Sleep and Study: A Three-Part Podcast", "genre": "Podcast", "modality": "Audio", "course": "Intro to Communication",
     "description": "Interviews and narration explaining how sleep affects exam performance.",
     "objectives": ["Structure an argument across several episodes", "Use music and pauses to guide listeners", "Cite expert sources aloud"],
     "url": "https://example.com/exemplars/sleep-and-study"},
    {"title": "Voices of the Library: Interview Episode", "genre": "Podcast", "modality": "Audio", "course": "Public Speaking",
     "description": "A ten-minute interview episode with an introduction, two guests, and a closing summary.",
     "objectives": ["Plan open-ended interview questions", "Control pacing and pauses when speaking", "Edit audio for clarity"],
     "url": "https://example.com/exemplars/voices-of-the-library"},
    {"title": "My First Day Teaching: A Digital Story", "genre": "Digital Story", "modality": "Video", "course": "Composition I",
     "description": "A three-minute narrated story told with personal photographs and a music bed.",
     "objectives": ["Shape a narrative arc with a clear turning point", "Pair voice and images so each adds meaning", "Reflect on purpose and audience"],
     "url": "https://example.com/exemplars/first-day-teaching"},
    {"title": "Why Libraries Still Matter", "genre": "Video Essay", "modality": "Video", "course": "Composition I",
     "description": "A two-minute essay combining archival images, voiceover, and on-screen text.",
     "objectives": ["State a claim in the opening thirty seconds", "Synchronize voiceover with visual evidence", "Show sources on screen"],
     "url": "https://example.com/exemplars/why-libraries-matter"},
    {"title": "Transit Funding at a Glance", "genre": "Infographic", "modality": "Visual", "course": "Intro to Communication",
     "description": "A one-page infographic that pairs three annotated charts with a short call to action.",
     "objectives": ["Choose chart types that fit each claim", "Build a visual hierarchy that guides the eye", "Label data and sources clearly"],
     "url": "https://example.com/exemplars/transit-funding"},
    {"title": "Citing Sources: A Four-Page Comic", "genre": "Comics", "modality": "Visual", "course": "Composition I",
     "description": "A comic that explains paraphrase, quotation, and citation to new college students.",
     "objectives": ["Translate an abstract concept into sequential images", "Balance text and image within each panel", "Revise for clarity using peer feedback"],
     "url": "https://example.com/exemplars/citing-sources-comic"},
    {"title": "Campus Recycling Research Poster", "genre": "Poster", "modality": "Visual", "course": "Public Speaking",
     "description": "A conference-style poster that summarizes a small observation study of campus recycling bins.",
     "objectives": ["Summarize research in a clear visual hierarchy", "Choose type and color that read from a distance", "Present findings in a two-minute talk"],
     "url": "https://example.com/exemplars/recycling-poster"},
]

# Lesson plans. duration_min is a number so the Estimated time filter can group plans into ranges;
# timeline entries are (minutes, activity) and should add up to duration_min.
# Lesson plans. duration_min is a number so the Estimated time filter can group plans into ranges;
# timeline entries are (minutes, activity) and should add up to duration_min.
COURSE_LEVELS = ["100-level", "200-level", "300-level and above"]
TIME_BUCKETS = {
    "Up to 30 minutes": (0, 30),
    "31 to 60 minutes": (31, 60),
    "More than 60 minutes": (61, 10_000),
}

LESSON_PLANS = [
    {"id": "podcast-essay-to-audio", "title": "From Essay to Podcast: Translating an Argument", "genre": "Podcast",
     "level": "100-level", "duration_min": 75,
     "description": "Students compare print and audio versions of one claim, then script a 60-second segment.",
     "objectives": ["Identify what changes when an argument moves from page to audio", "Draft a 60-second script from an essay paragraph"],
     "materials": ["Sample audio clip", "Script template", "Peer feedback form"],
     "prep": "Choose a short audio argument and print the matching transcript.",
     "timeline": [(10, "Warm-up: listen to a short audio argument"), (20, "Compare print and audio versions of one claim"),
                  (30, "Script a 60-second segment in pairs"), (15, "Read aloud and give peer feedback")],
     "assessment": "Collect the scripts and check that each keeps the claim while adapting the delivery for listeners."},
    {"id": "infographic-audience-workshop", "title": "Designing for Audience: Infographic Workshop", "genre": "Infographic",
     "level": "100-level", "duration_min": 50,
     "description": "A hands-on workshop on visual hierarchy, using a design checklist to revise a first draft.",
     "objectives": ["Choose a visual hierarchy for a specific audience", "Revise a draft using a design checklist"],
     "materials": ["Infographic design checklist", "Sticky notes", "Shared slide template"],
     "prep": "Print two contrasting infographics and load the slide template.",
     "timeline": [(10, "Review two contrasting infographics"), (25, "Sketch and build a draft"), (15, "Gallery walk with the checklist")],
     "assessment": "Ask each student to name one change they made and the checklist item that prompted it."},
    {"id": "video-essay-storyboard", "title": "Storyboarding a Video Essay", "genre": "Video Essay",
     "level": "200-level", "duration_min": 90,
     "description": "Students move from a claim to a shot list and storyboard before collecting any footage.",
     "objectives": ["State a claim and plan evidence across images, voiceover, and text", "Use a revision checkpoint to improve a storyboard"],
     "materials": ["Storyboard grid", "Shot list template", "Model video essay"],
     "prep": "Pick a model essay under three minutes and cue it to the opening.",
     "timeline": [(15, "Review a model essay and name its moves"), (30, "Write the claim and a shot list"),
                  (30, "Storyboard in groups"), (15, "Peer review at the revision checkpoint")],
     "assessment": "Grade the storyboard as a draft: claim, evidence plan, and source notes."},
    {"id": "website-portfolio-build", "title": "Building a Simple Portfolio Website", "genre": "Website",
     "level": "200-level", "duration_min": 120,
     "description": "A studio session that takes students from a site map to a first working page.",
     "objectives": ["Plan navigation that serves a defined audience", "Build and test one accessible page"],
     "materials": ["Website builder accounts", "Site map template", "Accessibility checklist"],
     "prep": "Confirm every student can log in to the website builder before class.",
     "timeline": [(20, "Tour two model sites and list navigation choices"), (40, "Sketch the site map and page layouts"),
                  (40, "Build a first page in the website builder"), (20, "Test with a classmate using only a keyboard")],
     "assessment": "Review the first page against the accessibility checklist."},
    {"id": "comics-explain-a-concept", "title": "Explaining a Concept in Comic Form", "genre": "Comics",
     "level": "100-level", "duration_min": 45,
     "description": "Students thumbnail a four-panel comic that explains one idea from the course.",
     "objectives": ["Translate an abstract concept into sequential images", "Balance text and image within each panel"],
     "materials": ["Four-panel thumbnail sheet", "Model explanatory comic"],
     "prep": "Prepare a short list of course concepts that students can choose from.",
     "timeline": [(10, "Read a one-page explanatory comic"), (25, "Thumbnail a four-panel explanation"), (10, "Swap and give feedback")],
     "assessment": "Check whether a classmate can restate the concept after reading the thumbnails."},
    {"id": "digital-story-turning-point", "title": "Finding the Turning Point in a Digital Story", "genre": "Digital Story",
     "level": "100-level", "duration_min": 25,
     "description": "A short mini-lesson that helps students find the moment their story turns.",
     "objectives": ["Identify the turning point in a personal narrative", "Choose three images that support it"],
     "materials": ["One-minute sample story", "Freewriting prompt"],
     "prep": "Queue the sample story and share the freewriting prompt.",
     "timeline": [(5, "Listen to a one-minute story"), (10, "Freewrite the turning point"), (10, "Pair share and choose three images")],
     "assessment": "Collect the freewrite and the three-image list as an exit ticket."},
    {"id": "ai-disclosure-multimodal", "title": "Responsible AI Use in Multimodal Projects", "genre": "Cross-genre",
     "level": "200-level", "duration_min": 50,
     "description": "Students apply the course AI policy to sample projects and write a disclosure statement.",
     "objectives": ["Explain the course AI policy in their own words", "Write a disclosure statement for a project"],
     "materials": ["Course AI policy", "Scenario cards"],
     "prep": "Print the course AI policy and prepare four scenario cards.",
     "timeline": [(10, "Discuss scenarios: allowed, allowed with disclosure, not allowed"), (25, "Annotate a sample project"), (15, "Draft a disclosure statement")],
     "assessment": "Read the disclosure statements for accuracy and specificity."},
    {"id": "poster-research-studio", "title": "Research Poster Studio", "genre": "Poster",
     "level": "300-level and above", "duration_min": 60,
     "description": "Students plan a conference-style poster and rehearse a two-minute talk.",
     "objectives": ["Summarize research in a clear visual hierarchy", "Present findings in a two-minute talk"],
     "materials": ["Poster layout template", "Two sample posters", "Timer"],
     "prep": "Bring two printed posters, one strong and one cluttered, for comparison.",
     "timeline": [(10, "Study two posters for hierarchy"), (30, "Draft a layout with headline, figure, and takeaway"), (20, "Two-minute practice talks in pairs")],
     "assessment": "Use a short checklist during the practice talks: claim, evidence, and timing."},
]
LESSON_GENRES = sorted({p["genre"] for p in LESSON_PLANS})

# Performance levels: each level earns a share of a criterion's maximum points.
# Criterion maximums are multiples of 5 so every cell works out to a whole number.
PERFORMANCE_LEVELS = [("Exemplary", 1.0), ("Proficient", 0.8), ("Developing", 0.6), ("Beginning", 0.4)]


def level_points(max_points, share):
    """Points earned at one level of one criterion, e.g. 25 x 0.8 = 20."""
    return round(max_points * share)


def crit(name, max_points, *descriptors):
    """Build one criterion: a name, its maximum points, and one descriptor per performance level."""
    assert len(descriptors) == len(PERFORMANCE_LEVELS)
    return {"name": name, "max_points": max_points, "descriptors": list(descriptors)}


# Each rubric totals 100 points. Keep text plain ASCII so the PDF fonts render it.
RUBRICS = [
    {"id": "website-rubric", "title": "Website Rubric", "genre": "Website",
     "description": "Assesses a small multi-page website for audience focus, navigation, design, and accessibility.",
     "criteria": [
         crit("Purpose and audience", 25, "Purpose is clear and every page serves the intended audience.", "Purpose is clear; most pages serve the audience.",
              "Purpose is present but the audience is unclear.", "Purpose and audience are not evident."),
         crit("Organization and navigation", 25, "Navigation is intuitive and every page is easy to reach.", "Navigation is clear with minor inconsistencies.",
              "Navigation is confusing in places.", "Pages are hard to find or connect."),
         crit("Visual design and accessibility", 30, "Consistent design; alt text, contrast, and headings meet standards.", "Mostly consistent design; most accessibility needs are met.",
              "Design is uneven; few accessibility needs are met.", "Design is cluttered; accessibility is not addressed."),
         crit("Writing and sources", 20, "Concise web copy; all sources and images are credited.", "Clear copy; most sources are credited.",
              "Copy is wordy or uneven; some credits are missing.", "Copy is unclear; sources are not credited."),
     ]},
    {"id": "podcast-rubric", "title": "Podcast Rubric", "genre": "Podcast",
     "description": "Assesses a short audio episode for purpose, structure, sound quality, and attribution.",
     "criteria": [
         crit("Purpose and audience", 25, "Purpose is clear and shapes every segment.", "Purpose is clear in most segments.",
              "Purpose appears but shifts.", "Purpose is unclear."),
         crit("Script and structure", 25, "Opening, development, and close are polished and well paced.", "Structure is clear with minor lapses.",
              "Structure is uneven or rushed.", "Structure is hard to follow."),
         crit("Audio quality and sound design", 30, "Clean recording; music and effects add meaning.", "Clean recording; some purposeful sound choices.",
              "Noticeable noise or uneven volume.", "Audio interferes with understanding."),
         crit("Sources and attribution", 20, "All sources, music, and tools are credited.", "Most sources are credited.",
              "Some credits are missing.", "Sources are not credited."),
     ]},
    {"id": "digital-story-rubric", "title": "Digital Story Rubric", "genre": "Digital Story",
     "description": "Assesses a short narrated story for narrative arc, delivery, media choices, and reflection.",
     "criteria": [
         crit("Narrative arc", 30, "A clear turning point; the story builds and resolves.", "A clear arc with a modest turning point.",
              "Events are listed with little shaping.", "No clear narrative structure."),
         crit("Voice and delivery", 20, "Natural, expressive narration at a steady pace.", "Clear narration with minor pacing issues.",
              "Narration is flat or rushed in places.", "Narration is hard to understand."),
         crit("Image and sound choices", 30, "Images and sound deepen meaning and match the narration.", "Images and sound mostly support the narration.",
              "Images and sound are loosely connected.", "Images and sound distract or are missing."),
         crit("Reflection and revision", 20, "Thoughtful reflection explains choices and revisions.", "Reflection explains most choices.",
              "Reflection is brief or general.", "No reflection is provided."),
     ]},
    {"id": "video-essay-rubric", "title": "Video Essay Rubric", "genre": "Video Essay",
     "description": "Assesses a short video essay for its claim, use of evidence, pacing, and attribution.",
     "criteria": [
         crit("Claim and argument", 30, "A focused claim is developed across the whole essay.", "A clear claim with mostly consistent support.",
              "The claim is present but loosely supported.", "No clear claim."),
         crit("Visual and audio evidence", 30, "Images, voiceover, and text work together as evidence.", "Most visuals and audio support the claim.",
              "Visuals and audio are loosely tied to the claim.", "Visuals and audio do not support the claim."),
         crit("Pacing and editing", 20, "Cuts and timing keep the viewer oriented.", "Pacing is steady with minor rough cuts.",
              "Pacing is uneven.", "Editing makes the essay hard to follow."),
         crit("Sources and attribution", 20, "All sources and media are credited on screen or in notes.", "Most sources are credited.",
              "Some credits are missing.", "Sources are not credited."),
     ]},
    {"id": "infographic-rubric", "title": "Infographic Rubric", "genre": "Infographic",
     "description": "Assesses a single-page visual argument for its claim, hierarchy, accessibility, and sources.",
     "criteria": [
         crit("Claim and evidence", 30, "The claim is clear; evidence is accurate and relevant.", "The claim is clear; most evidence is relevant.",
              "The claim or evidence is vague.", "No clear claim."),
         crit("Visual hierarchy", 25, "The eye path is deliberate and easy to follow.", "Hierarchy is mostly clear.",
              "Hierarchy is inconsistent.", "The layout is cluttered."),
         crit("Accessibility and legibility", 25, "High contrast, readable type, and alt text.", "Most accessibility needs are met.",
              "Some accessibility needs are met.", "Accessibility is not addressed."),
         crit("Sources and attribution", 20, "All sources are credited on the page.", "Most sources are credited.",
              "Some credits are missing.", "Sources are not credited."),
     ]},
]
RUBRIC_GENRES = sorted(r["genre"] for r in RUBRICS)

# ---------------------------------------------------------------------------
# 4. REUSABLE UI COMPONENTS
# Small helpers so every page draws cards the same way.
# ---------------------------------------------------------------------------
def esc(text):
    """Escape text before placing it inside HTML."""
    return html.escape(str(text))


def slug(text):
    """Lowercase, hyphenated version of a title; used to build unique container keys."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def card(key):
    """Bordered container styled as a card (the key becomes a CSS class: st-key-card_<key>)."""
    return st.container(border=True, key=f"card_{key}")


def panel(key):
    """Bordered container styled as a filter panel (CSS class: st-key-panel_<key>)."""
    return st.container(border=True, key=f"panel_{key}")


def notice(text, kind="alert", role="status"):
    """Friendly message box. kind="alert" is coral (empty states, warnings); kind="success" is teal."""
    st.markdown(f'<div class="notice {kind}" role="{role}">{esc(text)}</div>', unsafe_allow_html=True)


def card_grid(items, render_fn, columns=2):
    """Lay items out in a grid, filling columns left to right."""
    cols = st.columns(columns)
    for i, item in enumerate(items):
        with cols[i % columns]:
            render_fn(item)


def render_exemplar(e):
    """Bordered card: thumbnail placeholder, genre badge, title, description, objectives, link button."""
    color = EXEMPLAR_GENRE_COLORS[e["genre"]]
    with card(f'ex-{slug(e["title"])}'):
        # Thumbnail placeholder (swap for st.image(...) when real screenshots exist)
        st.markdown(
            f'<div class="thumb" role="img" aria-label="Placeholder thumbnail for {esc(e["title"])}" style="background:{color}">'
            f'<b>{esc(e["genre"])}</b><span>Thumbnail placeholder</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f'<span class="badge" style="background:{color}">{esc(e["genre"])}</span>', unsafe_allow_html=True)
        st.markdown(f'<h3 class="res-title">{esc(e["title"])}</h3>', unsafe_allow_html=True)
        st.caption(e["course"])
        st.write(e["description"])
        st.markdown("**Learning objectives**")
        for obj in e["objectives"]:
            st.markdown(f"- {obj}")
        # The title in the label keeps each link distinct for screen reader users
        st.link_button(f'View {e["title"]}', e["url"], help="Opens the project in a new tab")


def search_resources(resources, query, genre):
    """
    Keyword search with a genre filter.
    1. Lowercase the query and split it into terms.
    2. Keep only resources in the chosen genre ("All genres" keeps everything).
    3. Keep resources where EVERY term appears in the title, genre, description, or tags.
    4. Rank by where terms match: title = 3 points, tags = 2, genre/description = 1.
    """
    terms = query.lower().split()
    scored = []
    for r in resources:
        if genre != "All genres" and r["genre"] != genre:
            continue
        title = r["title"].lower()
        tags = " ".join(r["tags"]).lower()
        body = f'{r["genre"]} {r["description"]}'.lower()
        searchable = f"{title} {tags} {body}"
        if not all(t in searchable for t in terms):
            continue
        score = sum(3 * (t in title) + 2 * (t in tags) + (t in body) for t in terms)
        scored.append((score, r))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["title"]))  # best score first, then A to Z
    return [r for _, r in scored]


def render_resource_card(r):
    """Bordered card: genre badge, title, description, tags, and an expander for details."""
    color = MODALITY_COLORS.get(r["modality"], "#16807A")
    with card(f'res-{slug(r["title"])}'):
        featured = ' <span class="badge success">Featured</span>' if r.get("featured") else ""
        st.markdown(f'<span class="badge" style="background:{color}">{esc(r["genre"])}</span>{featured}', unsafe_allow_html=True)
        st.markdown(f'<h3 class="res-title">{esc(r["title"])}</h3>', unsafe_allow_html=True)
        st.write(r["description"])
        st.markdown("".join(f'<span class="pill">{esc(t)}</span>' for t in r["tags"]), unsafe_allow_html=True)
        with st.expander("View details"):
            st.markdown(f'**Format:** {r["format"]}  \n**Course:** {r["course"]}  \n**Modality:** {r["modality"]}')
            st.markdown("**What's included**")
            for item in r["includes"]:
                st.markdown(f"- {item}")
            st.markdown("**Classroom use**")
            st.write(r["classroom_use"])


def page_header(title, blurb):
    """Standard page title (h1) and a one-line lead paragraph."""
    st.title(title)
    st.markdown(f'<p class="lead">{esc(blurb)}</p>', unsafe_allow_html=True)


def go_to(page):
    """Button callback: switch the sidebar selection to another page."""
    st.session_state["nav"] = page


# ---------------------------------------------------------------------------
# 5. PAGE FUNCTIONS
# ---------------------------------------------------------------------------
def page_home():
    # Hero banner with count chips (counts come from the data, so they stay accurate)
    counts = [(len(RESOURCES), "resources"), (len(EXEMPLARS), "exemplars"), (len(LESSON_PLANS), "lesson plans"), (len(RUBRICS), "rubrics")]
    chips = "".join(f'<div class="chip"><b>{n}</b>{label}</div>' for n, label in counts)
    st.markdown(
        '<div class="hero"><h1 class="hero-title">Teach and learn through writing, image, sound, and video.</h1>'
        "<p>A library of resources, student exemplars, lesson plans, and rubrics for multimodal projects in college courses.</p>"
        f'<div class="chips">{chips}</div></div>',
        unsafe_allow_html=True,
    )

    # Calls to action under the hero (one primary, one secondary)
    c1, c2, _ = st.columns([1, 1, 2])
    c1.button("Search resources", key="hero_search", type="primary", on_click=go_to, args=("Search Resources",))
    c2.button("Browse exemplars", key="hero_browse", on_click=go_to, args=("Browse Exemplars",))

    # Start-here cards: each button jumps to a section
    st.header("Start here")
    links = [
        ("Search Resources", "Find a resource", "Search guides, templates, and tools by keyword and genre."),
        ("Browse Exemplars", "See student work", "Study sample projects with instructor commentary."),
        ("Lesson Plans", "Plan a session", "Open ready-to-adapt plans with timelines and materials."),
        ("Rubrics", "Choose a rubric", "Compare criteria and performance levels, then download as PDF or Word."),
    ]
    cols = st.columns(2)
    for i, (page, heading, text) in enumerate(links):
        with cols[i % 2]:
            with card(f"go-{slug(page)}"):
                st.markdown(f'<h3 class="res-title">{esc(heading)}</h3>', unsafe_allow_html=True)
                st.write(text)
                st.button(f"Open {page}", key=f"go_{page}", on_click=go_to, args=(page,))

    # Recently added resources
    st.header("Recently added")
    card_grid(RESOURCES[:3], render_resource_card, columns=3)


# --- Search page helpers: callbacks run before the page reruns, so they can set widget values ---
def set_query(term):
    """Suggestion and history buttons: put a term in the search box."""
    st.session_state["search_query"] = term


def set_genre(genre):
    """Empty-state button: switch the genre filter."""
    st.session_state["search_genre"] = genre


def clear_search():
    """Reset the keyword box and the genre filter."""
    st.session_state["search_query"] = ""
    st.session_state["search_genre"] = "All genres"
    st.session_state["last_logged"] = ""


def clear_history():
    """Forget all recent searches."""
    st.session_state["search_history"] = []


def remember_search(query):
    """Save a search at the front of the history: no duplicates, newest first, capped at MAX_HISTORY."""
    q = query.strip()
    # Skip empty searches, and skip a search already recorded (so Clear history is not undone on the next rerun)
    if not q or q.lower() == st.session_state.get("last_logged", "").lower():
        return
    st.session_state["last_logged"] = q
    history = [h for h in st.session_state["search_history"] if h.lower() != q.lower()]
    st.session_state["search_history"] = ([q] + history)[:MAX_HISTORY]


def render_empty_state(query, genre):
    """Explain why nothing matched and offer a next step."""
    q = query.strip()
    elsewhere = search_resources(RESOURCES, query, "All genres") if genre != "All genres" else []
    if elsewhere:
        n = len(elsewhere)
        verb = "matches" if n == 1 else "match"
        notice(f'No {genre} resources match "{q}", but {n} in other genres {verb}.')
        st.button("Search all genres", key="all_genres", on_click=set_genre, args=("All genres",))
    elif q:
        notice(f'We could not find anything for "{q}". Try a shorter or more general word, check the spelling, or pick a suggested keyword above.')
    else:
        notice(f"There are no {genre} resources yet. Choose another genre or clear the search.")


def page_search():
    page_header("Search resources", "Search by keyword, then narrow the results by genre.")

    # Make sure the session values exist before any widget reads them
    st.session_state.setdefault("search_query", "")
    st.session_state.setdefault("search_genre", "All genres")
    st.session_state.setdefault("search_history", [])

    # Search box, genre filter, and Clear button (all with visible labels and help text)
    with panel("search"):
        c1, c2 = st.columns([3, 1])
        query = c1.text_input("Search resources", placeholder="Try: podcast, alt text, storyboard",
                              help="Type one or more words. A resource must match every word.", key="search_query")
        genre = c2.selectbox("Genre", ["All genres"] + GENRES, help="Show only one type of project.", key="search_genre")
        st.button("Clear search", key="clear_search", on_click=clear_search, help="Empty the search box and show all genres")

    # Save this search so it appears in "Recent searches"
    remember_search(query)

    # Suggested keywords
    st.markdown("**Suggested keywords**")
    cols = st.columns(len(SUGGESTED_KEYWORDS))
    for col, term in zip(cols, SUGGESTED_KEYWORDS):
        col.button(term, key=f"sugg_{term}", on_click=set_query, args=(term,), help=f"Search for {term}", use_container_width=True)

    # Recent searches (only shown once there is a history)
    history = st.session_state["search_history"]
    if history:
        st.markdown("**Recent searches**")
        cols = st.columns(MAX_HISTORY + 1)
        for i, term in enumerate(history):
            cols[i].button(term, key=f"hist_{i}", on_click=set_query, args=(term,), help=f"Search again for {term}", use_container_width=True)
        cols[-1].button("Clear history", key="clear_history", on_click=clear_history, help="Forget recent searches")

    # No keyword and no genre: show featured resources instead of a long list
    if not query.strip() and genre == "All genres":
        st.header("Featured resources")
        st.write(f"Start with these picks, or type a keyword or choose a genre to explore all {len(RESOURCES)} resources.")
        card_grid([r for r in RESOURCES if r.get("featured")], render_resource_card)
        return

    # Otherwise run the search; the count sits in a polite live region for screen readers
    results = search_resources(RESOURCES, query, genre)
    noun = "resource" if len(results) == 1 else "resources"
    detail = (f' for "{esc(query.strip())}"' if query.strip() else "") + (f" in {esc(genre)}" if genre != "All genres" else "")
    st.markdown(f'<div role="status" aria-live="polite"><strong>{len(results)} {noun} found</strong>{detail}</div>', unsafe_allow_html=True)

    if results:
        st.header("Results")
        card_grid(results, render_resource_card)
    else:
        render_empty_state(query, genre)


def reset_exemplar_filters():
    """Reset button callback: show all genres in the default sort order."""
    st.session_state["ex_genres"] = []
    st.session_state["ex_sort"] = SORT_OPTIONS[0]


def page_exemplars():
    page_header("Browse exemplars", "Sample multimodal projects (placeholders). Filter by genre, choose a sort order, then open a project from its card.")
    st.session_state.setdefault("ex_genres", [])
    st.session_state.setdefault("ex_sort", SORT_OPTIONS[0])

    # Filter and sort controls (leaving Genres empty means all genres)
    with panel("exemplars"):
        c1, c2 = st.columns([3, 2])
        genres = c1.multiselect("Genres", EXEMPLAR_GENRES, placeholder="All genres",
                                help="Pick one or more genres. Leave empty to see all.", key="ex_genres")
        sort_by = c2.selectbox("Sort by", SORT_OPTIONS, help="Genre options group the cards under genre headings.", key="ex_sort")
        st.button("Reset filters", key="ex_reset", on_click=reset_exemplar_filters)

    # Filter, then sort (two stable passes: title first, then genre, so titles stay A to Z inside each genre)
    shown = [e for e in EXEMPLARS if not genres or e["genre"] in genres]
    shown.sort(key=lambda e: e["title"])
    if sort_by != "Title (A to Z)":
        shown.sort(key=lambda e: e["genre"], reverse=(sort_by == "Genre (Z to A)"))

    # Result count in a polite live region for screen readers
    noun = "exemplar" if len(shown) == 1 else "exemplars"
    detail = f' in {esc(", ".join(genres))}' if genres else ""
    st.markdown(f'<div role="status" aria-live="polite"><strong>{len(shown)} {noun} found</strong>{detail}</div>', unsafe_allow_html=True)

    if not shown:
        notice("No exemplars match these filters. Choose different genres or reset the filters.")
    elif sort_by == "Title (A to Z)":
        card_grid(shown, render_exemplar)  # one flat grid
    else:
        # Group cards under a heading for each genre, in the chosen order
        for genre in dict.fromkeys(e["genre"] for e in shown):
            st.header(genre)
            card_grid([e for e in shown if e["genre"] == genre], render_exemplar)


def plan_to_text(plan):
    """Turn one lesson plan into a plain-text file instructors can print or paste into a course site."""
    lines = [plan["title"].upper(), "=" * len(plan["title"]), "",
             f'Genre: {plan["genre"]}', f'Course level: {plan["level"]}', f'Duration: {plan["duration_min"]} minutes', "",
             "DESCRIPTION", plan["description"], "", "LEARNING OBJECTIVES"]
    lines += [f"{i}. {o}" for i, o in enumerate(plan["objectives"], 1)]
    lines += ["", "MATERIALS"] + [f"- {m}" for m in plan["materials"]]
    lines += ["", "PREPARATION", plan["prep"], "", "TIMELINE"]
    start = 0
    for minutes, activity in plan["timeline"]:
        lines.append(f"{start:>3}-{start + minutes:<3} min  {activity}")
        start += minutes
    lines += ["", "ASSESSMENT", plan["assessment"], "", "-" * 40,
              "Sample plan from Multimodal Studio Hub. Adapt it freely for your course."]
    return "\n".join(lines) + "\n"


def plans_to_zip(plans):
    """Bundle several plans into one zip file (one text file per plan), held in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for plan in plans:
            archive.writestr(f'{plan["id"]}.txt', plan_to_text(plan))
    return buffer.getvalue()


def filter_plans(plans, genre, level, time_range):
    """Apply the three filters; "All ..." and "Any length" mean no filtering. Results are sorted by title."""
    low, high = TIME_BUCKETS.get(time_range, (0, 10_000))
    keep = [p for p in plans
            if (genre == "All genres" or p["genre"] == genre)
            and (level == "All levels" or p["level"] == level)
            and low <= p["duration_min"] <= high]
    return sorted(keep, key=lambda p: p["title"])


def render_plan_card(plan):
    """Preview card: badge, title, level and time, description, expandable plan preview, download button."""
    color = EXEMPLAR_GENRE_COLORS.get(plan["genre"], "#4B3A7A")
    with card(f'plan-{plan["id"]}'):
        st.markdown(f'<span class="badge" style="background:{color}">{esc(plan["genre"])}</span>', unsafe_allow_html=True)
        st.markdown(f'<h3 class="res-title">{esc(plan["title"])}</h3>', unsafe_allow_html=True)
        st.markdown(f'<span class="pill">Level: {esc(plan["level"])}</span><span class="pill">Time: {plan["duration_min"]} minutes</span>',
                    unsafe_allow_html=True)
        st.write(plan["description"])
        with st.expander("Preview plan"):
            st.markdown("**Learning objectives**")
            for obj in plan["objectives"]:
                st.markdown(f"- {obj}")
            st.markdown("**Preparation**")
            st.write(plan["prep"])
            st.markdown("**Timeline**")
            for minutes, activity in plan["timeline"]:
                st.markdown(f"- **{minutes} min:** {activity}")
            st.markdown("**Materials**")
            for item in plan["materials"]:
                st.markdown(f"- {item}")
            st.markdown("**Assessment**")
            st.write(plan["assessment"])
        st.download_button(f'Download {plan["title"]} (.txt)', data=plan_to_text(plan), file_name=f'{plan["id"]}.txt',
                           mime="text/plain", key=f'dl_{plan["id"]}', help="Saves a plain-text copy you can edit", type="primary")


def reset_plan_filters():
    """Reset button callback: clear all three filters."""
    st.session_state["lp_genre"] = "All genres"
    st.session_state["lp_level"] = "All levels"
    st.session_state["lp_time"] = "Any length"


def page_lessons():
    page_header("Lesson plans", "Preview sample plans for multimodal projects, then download them to adapt for your own course.")
    st.session_state.setdefault("lp_genre", "All genres")
    st.session_state.setdefault("lp_level", "All levels")
    st.session_state.setdefault("lp_time", "Any length")

    # Three filters in one bordered container
    with panel("lessons"):
        c1, c2, c3 = st.columns(3)
        genre = c1.selectbox("Genre", ["All genres"] + LESSON_GENRES, key="lp_genre", help="The kind of project the lesson supports.")
        level = c2.selectbox("Course level", ["All levels"] + COURSE_LEVELS, key="lp_level", help="Instructional level of the course.")
        time_range = c3.selectbox("Estimated time", ["Any length"] + list(TIME_BUCKETS), key="lp_time", help="Class time the plan needs.")
        st.button("Reset filters", key="lp_reset", on_click=reset_plan_filters)

    plans = filter_plans(LESSON_PLANS, genre, level, time_range)

    # Result count in a polite live region for screen readers
    noun = "lesson plan" if len(plans) == 1 else "lesson plans"
    st.markdown(f'<div role="status" aria-live="polite"><strong>{len(plans)} {noun} found</strong></div>', unsafe_allow_html=True)

    if plans:
        # One download for everything currently shown, then the preview cards
        st.download_button(f"Download all {len(plans)} shown (.zip)", data=plans_to_zip(plans), file_name="lesson-plans.zip",
                           mime="application/zip", key="lp_zip", help="One text file per plan, bundled in a zip", type="primary")
        card_grid(plans, render_plan_card)
    else:
        notice("No lesson plans match these filters. Try a different course level or time range, or reset the filters.")


def rubric_total(rubric):
    """Total points available across all criteria."""
    return sum(c["max_points"] for c in rubric["criteria"])


def latin(text):
    """PDF core fonts only support Latin-1; replace anything else so generation never fails."""
    return str(text).encode("latin-1", "replace").decode("latin-1")


def rubric_table_html(rubric):
    """Preview table: criteria down the side, performance levels across, points shown in every cell."""
    head = '<tr><th scope="col">Criterion</th>' + "".join(f'<th scope="col">{esc(n)}</th>' for n, _ in PERFORMANCE_LEVELS) + "</tr>"
    rows = ""
    for c in rubric["criteria"]:
        cells = "".join(
            f'<td><strong>{level_points(c["max_points"], share)} pts</strong> {esc(d)}</td>'
            for (_, share), d in zip(PERFORMANCE_LEVELS, c["descriptors"])
        )
        rows += f'<tr><th scope="row" class="crit">{esc(c["name"])} ({c["max_points"]} pts)</th>{cells}</tr>'
    return f'<div class="table-wrap"><table class="rubric" aria-label="{esc(rubric["title"])}">{head}{rows}</table></div>'


def rubric_to_pdf(rubric):
    """Landscape US Letter PDF with a blank Score column and total line, ready to print and mark."""
    from fpdf import FPDF  # imported here so the other pages still work if the package is missing
    from fpdf.fonts import FontFace

    pdf = FPDF(orientation="L", unit="mm", format="Letter")
    pdf.set_margins(12, 12, 12)
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, latin(rubric["title"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, latin(rubric["description"]), new_x="LMARGIN", new_y="NEXT")
    total = rubric_total(rubric)
    pdf.cell(0, 7, latin(f'Genre: {rubric["genre"]}      Total: {total} points      Student: ______________________________'),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    header_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=(22, 33, 62))
    with pdf.table(col_widths=(36, 48, 48, 48, 48, 27), headings_style=header_style, line_height=5.2, text_align="LEFT") as table:
        header = table.row()
        for label in ["Criterion"] + [name for name, _ in PERFORMANCE_LEVELS] + ["Score"]:
            header.cell(label)
        for c in rubric["criteria"]:
            row = table.row()
            row.cell(latin(f'{c["name"]} ({c["max_points"]} pts)'))
            for (_, share), d in zip(PERFORMANCE_LEVELS, c["descriptors"]):
                row.cell(latin(f'{level_points(c["max_points"], share)} pts: {d}'))
            row.cell(f'____ / {c["max_points"]}')
        last = table.row()
        last.cell("Total score", colspan=5, align="R")
        last.cell(f"____ / {total}")
    return bytes(pdf.output())


def rubric_to_docx(rubric):
    """Editable Word version: landscape, same table as the PDF, header row shaded."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11), Inches(8.5)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Inches(0.6))

    doc.add_heading(rubric["title"], level=1)
    doc.add_paragraph(rubric["description"])
    total = rubric_total(rubric)
    doc.add_paragraph(f'Genre: {rubric["genre"]}     Total: {total} points     Student: ______________________________')

    table = doc.add_table(rows=1, cols=len(PERFORMANCE_LEVELS) + 2)
    table.style = "Table Grid"

    def shade(cell, fill):
        """Cell background (shading type CLEAR with a fill color, as Word expects)."""
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        cell._tc.get_or_add_tcPr().append(shd)

    for cell, label in zip(table.rows[0].cells, ["Criterion"] + [n for n, _ in PERFORMANCE_LEVELS] + ["Score"]):
        shade(cell, "16213E")
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(255, 255, 255)

    for c in rubric["criteria"]:
        cells = table.add_row().cells
        shade(cells[0], "EEF2F6")
        name_run = cells[0].paragraphs[0].add_run(f'{c["name"]} ({c["max_points"]} pts)')
        name_run.bold = True
        name_run.font.size = Pt(10)
        for cell, (_, share), d in zip(cells[1:], PERFORMANCE_LEVELS, c["descriptors"]):
            pts = cell.paragraphs[0].add_run(f'{level_points(c["max_points"], share)} pts: ')
            pts.bold = True
            pts.font.size = Pt(10)
            cell.paragraphs[0].add_run(d).font.size = Pt(10)
        cells[-1].paragraphs[0].add_run(f'____ / {c["max_points"]}').font.size = Pt(10)

    last = table.add_row().cells
    merged = last[0].merge(last[-2])
    merged.paragraphs[0].add_run("Total score").bold = True
    merged.paragraphs[0].alignment = 2  # right-aligned
    last[-1].paragraphs[0].add_run(f"____ / {total}").bold = True

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def render_rubric_card(rubric):
    """Card: badge, title, point total, preview expander, and PDF / Word download buttons."""
    color = EXEMPLAR_GENRE_COLORS.get(rubric["genre"], "#4B3A7A")
    total = rubric_total(rubric)
    with card(f'rubric-{rubric["id"]}'):
        st.markdown(f'<span class="badge" style="background:{color}">{esc(rubric["genre"])}</span>', unsafe_allow_html=True)
        st.markdown(f'<h3 class="res-title">{esc(rubric["title"])}</h3>', unsafe_allow_html=True)
        st.markdown(f'<span class="pill">Total: {total} points</span><span class="pill">{len(rubric["criteria"])} criteria</span>'
                    f'<span class="pill">{len(PERFORMANCE_LEVELS)} performance levels</span>', unsafe_allow_html=True)
        st.write(rubric["description"])
        with st.expander("Preview rubric"):
            levels = ", ".join(f"{name} {round(share * 100)}%" for name, share in PERFORMANCE_LEVELS)
            st.caption(f"Each level earns a share of the criterion's points: {levels}.")
            st.markdown(rubric_table_html(rubric), unsafe_allow_html=True)
        try:
            pdf_bytes, docx_bytes = rubric_to_pdf(rubric), rubric_to_docx(rubric)
        except ImportError:
            notice("PDF and Word downloads need the fpdf2 and python-docx packages. Add both to requirements.txt.", "alert", "alert")
            return
        c1, c2 = st.columns(2)
        c1.download_button(f'Download {rubric["title"]} (PDF)', data=pdf_bytes, file_name=f'{rubric["id"]}.pdf',
                           mime="application/pdf", key=f'pdf_{rubric["id"]}', help="Print-ready, landscape", type="primary")
        c2.download_button(f'Download {rubric["title"]} (Word)', data=docx_bytes, file_name=f'{rubric["id"]}.docx',
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                           key=f'docx_{rubric["id"]}', help="Editable in Word or Google Docs", type="primary")


def page_rubrics():
    page_header("Rubrics", "Preview a rubric, then download it as a PDF or Word document to adapt for your assignment.")
    st.session_state.setdefault("rb_genre", "All genres")

    # Genre filter
    with panel("rubrics"):
        genre = st.selectbox("Genre", ["All genres"] + RUBRIC_GENRES, key="rb_genre", help="Show the rubric for one type of project.")

    shown = [r for r in RUBRICS if genre == "All genres" or r["genre"] == genre]
    noun = "rubric" if len(shown) == 1 else "rubrics"
    st.markdown(f'<div role="status" aria-live="polite"><strong>{len(shown)} {noun} found</strong></div>', unsafe_allow_html=True)

    # One full-width card per rubric (the tables are wide)
    for rubric in shown:
        render_rubric_card(rubric)


# ---------------------------------------------------------------------------
# 6. ROUTER AND SIDEBAR
# The sidebar radio stores the current page in st.session_state["nav"];
# PAGES maps each label to the function that draws it.
# ---------------------------------------------------------------------------
PAGES = {
    "Home": page_home,
    "Search Resources": page_search,
    "Browse Exemplars": page_exemplars,
    "Lesson Plans": page_lessons,
    "Rubrics": page_rubrics,
}


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    st.session_state.setdefault("nav", "Home")

    with st.sidebar:
        # Logo placeholder: swap the "MS" block for your real logo (for example st.image) when you have one
        st.markdown(
            '<div class="logo-row"><div class="logo" role="img" aria-label="Logo placeholder">MS</div>'
            '<div><div class="brand">Multimodal Studio Hub</div><div class="tagline">Teaching resources for multimodal projects</div></div></div>',
            unsafe_allow_html=True,
        )
        st.radio("Navigate", list(PAGES), key="nav", label_visibility="collapsed")
        st.caption("All content is placeholder data. Replace it in Section 3 of this file.")

    PAGES[st.session_state["nav"]]()


if __name__ == "__main__":
    main()
