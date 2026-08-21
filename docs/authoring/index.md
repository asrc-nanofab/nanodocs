# Writing SOPs for This Site

This site is generated directly from Google Docs. **You write and edit in
Google Docs — the site takes care of the rest.** Every SOP page here is an
automatic conversion of its source doc, refreshed whenever a sync runs.

That means: to fix a typo, update a procedure, or add a photo, **edit the
Google Doc**. Never edit the website files — changes there get overwritten by
the next sync.

## The two rules that matter

### 1. Images must be "In line with text"

This is the one that bites people. Google's conversion **silently drops any
image set to "Wrap text" or "Break text"** — the image simply won't appear on
the site, leaving an orphaned caption.

Click any image in your doc and choose the **leftmost layout option ("In
line")** in the toolbar that appears:

- ✅ In line — appears on the site
- ❌ Wrap text — dropped
- ❌ Break text — dropped

If you're unsure about an existing doc, the sync prints a warning for every
figure caption that has no image above it, so ask whoever runs the sync.

### 2. Use real heading styles

Pick **Heading 1, 2, 3…** from the styles dropdown for your section titles.
The site builds each page's table of contents from these headings — text that
merely *looks* like a heading (bold, larger font) will render fine but never
appear in the TOC or in site search.

Details that don't matter (the site fixes them):

- **Which level you start at.** Sections styled Heading 1 are shifted down
  automatically so the page title stays the only top-level heading.
- **Headings indented inside numbered lists** are recovered, though major
  sections read best at the left margin.

What does matter is the *nesting*: subsections styled one level below their
section (e.g. Heading 3 under Heading 2) show up indented in the TOC, so
readers can see the structure at a glance.

## What converts well

Use these freely — they all come through cleanly:

- **Tables** (including images inside table cells, e.g. hazard symbols)
- **Bold, italics, numbered and bulleted lists, footnotes**
- **Images** (inline!) — the site automatically recovers them at full
  resolution. The size you set in the doc carries over: small images
  (QR codes, icons) stay small, and images sized to the full page width
  render full width on the site.
- **Docs that started life as PDFs** — if your doc was converted from a
  paginated PDF, the repeating page headers and footers ("Page 2 of 9",
  the logo on every page) are removed automatically.

## What the site cleans up for you

You don't need to restructure your doc for the website. On every sync the
site automatically strips things that belong in the printed doc but not on
a web page:

- The **letterhead logo** and the **document title line** (the page supplies
  its own title)
- Your doc's **table of contents** — the site generates its own live one
  from your headings, so keep the doc's TOC for print/PDF use
- **"Page N of M"** markers and repeated page headers/footers from
  PDF-converted docs
- Empty heading lines and other invisible styling leftovers
- Google's *"AI-generated content may be incorrect"* boilerplate on image
  alt text

## What to avoid

- Wrapped/floating images (rule 1)
- Manual "fake headings" — bold text instead of a heading style (rule 2)
- Text drawn in Google Drawings or text boxes — treat anything that isn't
  regular text, a table, or an inline image as unlikely to convert

## Publishing a new SOP

1. Write the doc in Google Docs.
2. Set sharing to **"Anyone with the link — Viewer."** (The site links readers
   to a read-only preview; they never get edit access.)
3. Ask the site maintainer to add it to the registry sheet — after that, every
   sync picks up your edits automatically.

## Checking your work

After a sync, open your SOP's page on the site and skim it top to bottom:
every figure present, tables intact, headings showing in the table of
contents. If something looks wrong on the site but right in the doc, it's
almost always one of the two rules above.
