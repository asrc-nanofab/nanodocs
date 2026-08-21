# Nest child documents under parent tool pages via a registry "Parent Tool" column

**Date:** 2026-08-20
**Status:** Draft

## Description

Today every tools-sheet row maps to one flat page: `tool_sops/<category>/<slug>.md`.
Some tools have several documents (e.g. a sputter tool with a main SOP plus
target-swap / recipe docs), and we want the main SOP to be the section index
with the other docs nested under it behind a caret.

The site already renders this shape in the chem section
(`chemicals/caustics_hood/index.md` + child etch SOPs), powered by
`navigation.indexes` (enabled in `mkdocs.yml`) and awesome-nav. This plan
generalizes it for tools, driven by the registry sheet instead of a
hand-written map:

- **New sheet column** on the tools registry: `Parent Tool`.
  - Blank → top-level page, exactly today's behavior.
  - Set to another row's Tool Name → this doc becomes a child page of that tool.
- **The parent row itself is the index.** No "is index" flag needed: any tool
  referenced in some row's `Parent Tool` column gets its page written to
  `tool_sops/<category>/<slug>/index.md`; children go to
  `tool_sops/<category>/<parent_slug>/<child_slug>.md`.

Key findings / constraints:

| Area | Finding |
| --- | --- |
| `resolve_page_path` | Currently resolves each row independently. Parenthood is only knowable from the whole sheet, so `sync_section` must compute the set of parent names first and pass it down (script must also tolerate the column not existing yet). |
| Category on child rows | Children inherit the parent's `Type (Category)`; a conflicting non-blank category on a child is a warning, parent wins. Child referencing an unknown parent → skip with a log line, like unmapped chem docs today. |
| `TOOL_PAGE_OVERRIDES` | Overrides map name → filename. For a parent, the directory name is the override's stem (e.g. `elionix.md` → `elionix/`). |
| Page move is one-time-destructive | The sync never deletes files, so promoting a tool to a parent leaves the old flat page behind; it must be removed by hand or `mkdocs build --strict` / nav will complain. A hand-edited H1 on the old page must be re-applied once on the new `index.md` (H1 preservation reads the target path). |
| `img/` dirs | Images are per-directory (`page_dir/img`). The new tool directory gets its own `img/`; content-hash naming means the re-sync regenerates everything, and stale files in the old category-level `img/` can be deleted if unreferenced. |
| Hosted PDFs | `pdf_asset_path` keys on document name only — no collision from nesting. Children get the same `_SOP` suffix as tools; acceptable. |
| Nav | Hand-maintained per convention: the category `.nav.yml` entry changes from `Name: slug.md` to `Name: slug` (directory), and the tool directory gets its own `.nav.yml` when child order matters (awesome-nav auto-orders alphabetically otherwise, index first). |
| Caret rendering | Nested levels below the top always render collapsible with a caret; `navigation.sections` only affects the top level, so no `mkdocs.yml` change is needed for this. |

## Steps

### Phase A — sheet + sync script

- [ ] **User:** add a `Parent Tool` column to the tools registry sheet and fill
      it in for one pilot tool's child docs (suggest AJA Sputter).
- [ ] `sync_section`: after reading rows, build `parents: set[str]` from
      non-blank `Parent Tool` values; thread it into `sync_row` /
      `resolve_page_path`. Missing column ⇒ empty set (no behavior change).
- [ ] `resolve_page_path` (tools only):
  - name in `parents` → `tool_sops/<category>/<dirname>/index.md`
  - `Parent Tool` set → resolve the parent row's category and dirname; page is
    `tool_sops/<category>/<parent_dir>/<slugify(child)>.md`; unknown parent ⇒
    skip with log line.
- [ ] `uv run ruff check .` and `uv run ruff format .` pass.
- [ ] Dry confidence check: `uv run python scripts/sync_gdocs.py tools --only
      "<pilot child doc>"` writes to the nested path; a tool with no children
      still writes to its current flat path (sync reports `unchanged`).

### Phase A review gate — STOP for sign-off

- [ ] Pilot child page landed at `tool_sops/<cat>/<tool>/<child>.md`
- [ ] Pilot parent page landed at `tool_sops/<cat>/<tool>/index.md`
- [ ] No other page paths moved
- [ ] Decision: proceed / adjust / abandon

### Phase B — pilot migration + nav

- [ ] Update the category `.nav.yml`: point the pilot tool entry at its
      directory; add a `.nav.yml` inside the tool directory if child order
      matters (index.md first).
- [ ] Re-apply the old page's H1 to the new `index.md` if it had been
      hand-renamed.
- [ ] Delete the pilot tool's old flat page (and any now-unreferenced images
      in the old `img/` dir).
- [ ] `uv run mkdocs build --strict` passes.
- [ ] Visual check on `mkdocs serve`: parent entry shows a caret, clicking the
      tool name opens the main SOP, children sit nested beneath it.

### Phase B review gate — STOP for sign-off

- [ ] Sidebar nesting looks right (caret, index behavior)
- [ ] Old flat URL gone / no broken links reported by strict build
- [ ] Decision: roll out to further tools as their child docs are added
      (each is just sheet rows + nav entries; no more script work)

## Known limits / notes

- One nesting level only (tool → children). Deeper trees are out of scope
  until a real doc needs them.
- Chem/policy keep their explicit page maps — they already express nesting.
- The registry sheet stays the single publish gate; no Drive API / service
  account credentials are needed for any of this.
- Optional follow-up (not in scope): hide the left sidebar on document pages
  via Material's per-page front matter (`hide: [navigation]`) emitted by
  `build_page`. Note `toc.integrate` puts the page TOC inside that same
  sidebar, so hiding navigation hides the TOC too unless `toc.integrate` is
  turned off (TOC then moves to the right side).
