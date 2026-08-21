# Writing Documentation

This site is generated **directly and automatically from Google Docs**.

Google Docs is a ubiquitous way of documenting knowledge in research and
facility laboratories — and making that documentation easily readable on the
web, on any device, matters just as much as writing it. Bridging the two
turns out to be very practical: Google Docs can export a document as
Markdown, the native language of documentation sites like this one, so the
pathway from a doc to a web page can be fully automated.

To fix a typo, update a procedure, or add a photo, **edit the Google Doc**.
Never edit the website files — changes there are overwritten by the next
sync.

## Why Google Docs works so well for this

Beyond the Markdown export, Google Docs brings features that make automated
publishing reliable:

- **A unique identifier.** Every doc has a permanent ID that never changes,
  no matter where the doc lives or moves in Drive — so the site never loses
  track of its sources.
- **Version control.** Full revision history is built in; you can name
  versions and roll back at any time.
- **Group access.** The whole team can write and review together with
  familiar sharing controls.
- **An automated API.** Google provides programmatic export in every format
  the pipeline needs — Markdown, DOCX, and PDF.
- **Metadata labels.** Docs can be labeled and categorized in Drive, which
  keeps a growing documentation library organized.

## The two rules

Only a couple of rules are needed to get the best results from the
conversion:

1. **Images must be "In line with text."** The conversion silently drops any
   image set to "Wrap text" or "Break text" — it simply won't appear on the
   site. Click the image and choose the leftmost layout option ("In line").
2. **Use real heading styles, with a single H1.** The site builds each page's
   table of contents and search index from your headings, following standard
   web practice: one top-level heading (the title), and properly nested
   sections below it. Text that merely *looks* like a heading — bold, larger
   font — never appears in the TOC or in search.

## Best practices

- **Keep documents simple.** Regular text, tables, lists, and inline images
  convert perfectly; text boxes and drawings don't.
- **Never embed text in an image.** Text inside a picture can't be searched,
  scaled, or read by assistive tools.
- **Always caption your images.**
- **Use version history and metadata labels** in Google Docs — they cost
  nothing and pay off as the library grows.

## What the automation cleans up

You don't need to restructure your doc for the website. After the Markdown
conversion, the pipeline automatically removes what belongs in the printed
doc but not on a web page:

- Letterhead logos and page numbers
- The document title line (the page supplies its own title)
- The doc's table of contents — the site generates its own live one from
  your headings
- Empty headings and blank styling leftovers
- Google's *"AI-generated content may be incorrect"* boilerplate on image
  alt text

## Publishing a new document

Give the pipeline access to the doc in one of two ways:

- Set sharing to **"Anyone with the link — Viewer"** (this site's approach —
  readers also get a read-only preview link on every page), or
- Give the codebase a **service-account JSON key** for Google's API, which
  works with fully private docs.

Then add the doc to the registry sheet, and every sync picks up your edits
automatically.

## In conclusion

Google Docs is used by an enormous number of people — hundreds of millions
at the least — and it is a dominant medium for capturing and sharing working
knowledge. Connecting it directly to the web, so that documentation is
always current, searchable, and readable on any device, is what this site is
about. We will keep documenting what we learn as we go.
