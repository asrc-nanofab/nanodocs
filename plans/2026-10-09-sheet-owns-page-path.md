# Derive each page path from the sheet hierarchy

**Date:** 2026-10-09
**Status:** Draft — hierarchy decisions recorded, awaiting Phase A

## Description

The registry sheets list the documents, but the site path for each row is
decided in `scripts/sync_gdocs.py`. Tools are slugified into a category
folder, with five exceptions in `TOOL_PAGE_OVERRIDES`. Chem and policy are
name → path dicts (`CHEM_PAGE_MAP`, `POLICY_PAGE_MAP`).

Each sheet also stores the same Google Doc twice. `Share Link` (chem:
`Shared Link`) is the `/edit` URL. `PDF Link` is that same doc with
`/export?format=pdf`. The sync ignores the share link and reads only
`PDF Link`.

Decisions recorded 2026-10-09:

- The path is `Class`, `Name`, and `Parent`. There is no `Page` column and no filename map in Python.
- `Name` is whatever is typed in the sheet. The file slug is `slugify(Name)`. The names get edited in the sheet to the words that should become filenames. Old filenames are not kept.
- A row is a folder when another row in the same class sets `Parent` to its `Name`. Nothing else marks folder versus document.
- A child page is its own row. Its `Parent` is the folder row's `Name`, and its own `Name` is its file.
- Public URLs move to those derived paths.
- One `Share Link`. The script parses `/document/d/{id}` and builds preview, Markdown, DOCX, and PDF export URLs from it.

| Column | What it is |
| --- | --- |
| `Name` | Words you want in the filename. `slugify(Name)` is the file. This is also the value a child puts in `Parent`. |
| `Class` | The group folder. `slugify(Class)` is that segment. |
| `Parent` | Blank, or the `Name` of another row in the same class. |
| `Share Link` | The one doc URL. |

Which sheet the row is on supplies the top segment: tools → `tool_sops/`,
chem → `chemicals/`, policy → `policy/`. A policy row with a blank `Class`
lands directly in `policy/`. `Becoming a Nanofab User` therefore leaves
`docs/signup.md` and becomes `policy/<slug of whatever that row is renamed to>.md`.

`slugify` is the one already in the script: lowercase, and every run of
non-letters becomes `_`. `Gold Etch` → `gold_etch`. `ICP-Cl` → `icp_cl`.

### How a path is built

Parent blank, and no row points at this name: a document in the class.

```text
Class deposition, Name "AJA Sputter"
  → tool_sops/deposition/aja_sputter.md
```

Some other row has `Parent` equal to this `Name`: this row is the folder
index. The child sits inside it.

```text
Class deposition, Name "PECVD"
  → tool_sops/deposition/pecvd/index.md

Class deposition, Name "Oxide Recipe", Parent "PECVD"
  → tool_sops/deposition/pecvd/oxide_recipe.md
```

Same rule for a hood. The etch page names the hood row as `Parent`, so the
hood is the folder and the etch is the file inside it. `Class` is only the
group above that.

```text
Class caustics, Name "Caustics Hood"
  → chemicals/caustics/caustics_hood/index.md

Class caustics, Name "Gold Etch", Parent "Caustics Hood"
  → chemicals/caustics/caustics_hood/gold_etch.md
```

`Type (Category)` is replaced by `Class`. `--category` matches the `Class`
cell. Chem `Type` and policy `Full Name` stay as labels the script does
not read.

Sidebar order stays in `docs/**/.nav.yml`. A folder is listed by its
directory name (`pecvd`); a document is listed by its file
(`aja_sputter.md`). The sync does not write those files.

The on-page H1 stays the heading already on the page. `Name` is the
filename, and the fallback title only when a page is brand new.

Rows with no share link stay unpublished. A `Parent` that matches no
`Name` in that class is skipped and logged. Two rows in one class with
the same `Name` are skipped and logged.

The hosted PDF name is still built from `Name` (spaces become `_`, tools
keep the `_SOP` suffix). Renaming `Name` renames that PDF and its R2 key.
Those uploads happen in Phase C, after the names are settled.

## Steps

### Phase A — Set `Class`, `Parent`, and the names

Leave `PDF Link` in place so the current sync keeps working. On the chem
sheet, rename `Shared Link` to `Share Link`. Add `Class` and `Parent`.

Edit `Name` to the words that should become the filename. `slugify` of
that cell is the file. `ICP-Cl` becomes `icp_cl`. A name left as
`Gold Etch SOP` becomes `gold_etch_sop`.

`Class` is the folder word. `deposition` stays `deposition`. `Etching`
becomes `etching`, which moves that group off today's `etch` folder.
Type the word you want the folder to be.

`Parent` is blank unless the page lives inside another row. PECVD stays a
document until some row sets `Parent` to `PECVD`. The hand-written sample
`docs/tool_sops/deposition/pecvd/pecvd_processes.md` is not a sheet row,
so it does not make PECVD a folder. Remove it, or replace it with a real
child row, before the sync runs.

### Phase A review gate — STOP for sign-off

- [ ] `Class` and `Parent` are filled the way the path rules describe
- [ ] Every `Name` you care about has been edited to the words you want slugified
- [ ] Chem's URL column is `Share Link`
- [ ] `PDF Link` is still present
- [ ] The PECVD sample page is gone, or a real child row parents PECVD
- [ ] Decision: proceed / adjust / abandon

### Phase B — Script derives the path and reads `Share Link`

- [ ] Resolve the path from `Class`, `Name`, and `Parent` by the rules above. Reject a `Parent` with no match, a duplicate `Name` in a class, and a path that escapes that section's tree.
- [ ] Parse the doc id from `Share Link`. Build `/preview`, `export?format=md`, `export?format=docx`, and `export?format=pdf`. Stop reading `PDF Link`.
- [ ] Delete `TOOL_CATEGORY_DIRS`, `TOOL_PAGE_OVERRIDES`, `CHEM_PAGE_MAP`, and `POLICY_PAGE_MAP`.
- [ ] `--category` filters on `Class`.
- [ ] Update `README.md`, `AGENTS.md`, and `docs/authoring/index.md`: one link column, path comes from class / name / parent.
- [ ] `uv run ruff check .` and `uv run ruff format .`
- [ ] One sync of `tools chem policy`. New files appear at the derived paths. The old files stay on disk until Phase C.

### Phase B review gate — STOP for sign-off

- [ ] Each published row is at `slug(Class)/slug(Name).md`, or at `slug(Name)/index.md` when another row parents it
- [ ] A child row is inside its parent's folder, under its own slug
- [ ] `uv run zensical build --strict` passes
- [ ] Decision: proceed / adjust / abandon

### Phase C — Drop the old files and `PDF Link`

- [ ] Delete the markdown files the sync replaced, and update `.nav.yml` lines to the new file or to the directory when the row is a folder
- [ ] Update hand-written links (section index pages) that still point at the old filenames
- [ ] Delete the `PDF Link` column on all three sheets
- [ ] Re-run the sync and confirm every published row resolves from `Share Link`, `Class`, `Name`, and `Parent`
- [ ] Upload renamed PDF keys to R2 and drop the old keys

## Known limits / notes

- `.nav.yml` is still edited in the repo. A new child row needs a line in its parent's nav, and the parent line changes from `slug.md` to the directory name.
- `Piranha Clean SOP` and `RCA Clean SOP` already share one Google Doc id. Two rows, one doc. This plan does not split them.
- Hand-written pages (`deposition/index.md` and the other section homes) are not sheet rows. They do not create a folder. Only a `Parent` cell does.
