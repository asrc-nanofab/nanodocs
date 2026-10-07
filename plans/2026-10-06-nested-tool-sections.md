# Nest any page under its own caret

**Date:** 2026-10-06
**Status:** Phase A done — awaiting sign-off

## Description

A sidebar caret is a directory that has its own `.nav.yml`. Awesome-nav
loads that file when the parent lists the directory name. The theme draws
the disclosure because `navigation.sections` is on and `navigation.expand`
is off. `navigation.indexes` makes the section title the link to that
directory's `index.md`: the caret opens children, and the title still
opens the section home.

This is already how Caustics sits under Chemical Handling.
`chemicals/.nav.yml` points at the directory `caustics_hood`.
`caustics_hood/.nav.yml` lists `index.md` first, then the etch pages. A
folder with no `.nav.yml` stays a single link (`litho_hood/index.md`).

The same move works in every directory that has a `.nav.yml`. Nothing in
`mkdocs.yml` changes, and there is no per-folder special case. Lithography,
deposition, etch, metrology, packaging, policy, and the chemical hoods all
use one checklist.

The bold sidebar headings stay. With `navigation.tabs` and
`navigation.sections`, the theme marks only two levels as sections
(`md-nav__item--section` in `nav-item.html`):

- Level 1 is the tab (Tool SOPs, Chemical Handling).
- Level 2, while that tab is open, is the bold group: Deposition SOPs,
  Lithography SOPs, the hood names, and so on. Those titles stay bold
  and open. They are not collapse carets.

A folder under Deposition is level 3. It is not a section, so it gets a
real caret and starts collapsed (`navigation.expand` is off). "Deposition
SOPs" does not turn into a caret, and "Oxford PECVD" does not become a
second bold heading. `navigation.indexes` makes the PECVD title the link
to the SOP. The child is the only row under the caret. The SOP is not
listed twice.

Nothing on the site is a level-3 folder yet, so that combination is what
the sample is for. Caustics is level 2: a bold heading, not a caret under
one.

Do not promote a page until it has at least one real child. An index-only
directory is a page, not a section: point the parent at `slug/index.md`
and do not add a `.nav.yml`. A `.nav.yml` whose only entry is `index.md`
is the duplicate-index case fixed in Zensical 0.0.59. Pre-creating empty
folders for every current leaf would add carets with nothing under them.

The public URL of the promoted page does not change. With directory URLs,
both `deposition/pecvd.md` and `deposition/pecvd/index.md` publish as
`/tool_sops/deposition/pecvd/`. A child publishes as
`/tool_sops/deposition/pecvd/<child>/`. Same for every other section:
`etch/rie.md` and `etch/rie/index.md` are both `/tool_sops/etch/rie/`.

One more caret under a child is the same checklist again. Lists stay
explicit. No `"*"` globs.

### Where it applies

Every leaf below can become a directory. Section homes (`index.md` of a
folder that already has children) stay as they are.

| Directory | Leaves that can grow a caret |
| --- | --- |
| `docs/tool_sops/lithography/` | `elionix.md`, `mask_aligner.md`, `nanoscribe.md`, `spinners.md`, `hot_plates.md` |
| `docs/tool_sops/deposition/` | `aja_sputter.md`, `metal_evap.md`, `organic_evap.md`, `thermal_evap.md`, `ald.md`, `pecvd.md`, `gold_sputter.md` |
| `docs/tool_sops/etch/` | `rie.md`, `icp-fl.md`, `icp-cl.md` |
| `docs/tool_sops/metrology/` | `afm.md`, `sem.md`, `optical_profilometer.md`, `profilometer.md`, `ellipsometer.md` |
| `docs/tool_sops/packaging/` | `dicing_saw.md` |
| `docs/policy/` | `manual.md`, `safety.md`, `c14.md`, `suspension.md` |
| `docs/chemicals/caustics_hood/` | `nickel_etch.md`, `chrome_etch.md`, `gold_etch.md`, `silicon_etch.md`. `aluminum_etch/index.md` is already a folder with no `.nav.yml`; add one only when it has a sibling. |
| `docs/chemicals/hf_pirahna_hood/` | `hf_etch.md`, `piranha.md` |
| `docs/chemicals/rca_hood/` | `rca_clean.md` |
| `docs/authoring/` | `writing_documentation.md`, `how_chat_works.md`, `chat_agent.md` |

`faq/index.md`, `signup.md`, `litho_hood/index.md`, and
`solvent_hood/index.md` are single links today. Promote them with the
same checklist when they gain a child. Do not add a `.nav.yml` before
that.

### Sync has to follow the move

The next sync recreates the old flat path unless the page map points at
the new file. Both files would claim the same URL.

Tools resolve to `docs/tool_sops/<category>/<override>`. The override
value may contain a slash. Existing keys stay; only the value changes
when that tool is promoted:

| Sheet tool name | Override today | After promotion |
| --- | --- | --- |
| `ICP-Cl` | `icp-cl.md` | `icp-cl/index.md` |
| `ICP-Fl` | `icp-fl.md` | `icp-fl/index.md` |
| `Spinner` | `spinners.md` | `spinners/index.md` |
| `Elionix 100keV` | `elionix.md` | `elionix/index.md` |
| any other tool | slugify(name) + `.md` | `<slug>/index.md` added to `TOOL_PAGE_OVERRIDES` |

`PECVD` is the last kind: the sheet name slugifies to `pecvd.md`, so
promotion adds `"PECVD": "pecvd/index.md"`.

Chem and policy already use full paths. Change the map value from
`chemicals/hf_pirahna_hood/hf_etch.md` to
`chemicals/hf_pirahna_hood/hf_etch/index.md` (and the same for policy).

A child Google Doc that should sit under the page uses the same map:
tools get `<slug>/<child>.md` and stay in that tool's category; chem and
policy get a full path under the new directory. A hand-written child is
only a markdown file plus a nav line. The sync never writes `.nav.yml`.

On the sync after the move, images go to `page_path.parent / "img"`
(`pecvd/img/`, `rie/img/`, and so on) and the PDF href gains one `../`
by itself. The R2 key does not change. Do not hand-edit the generated
page. Delete the old flat `.md` in the same change as the nav update,
before `zensical build --strict`. Unreferenced files left in the old
`img/` directory can be removed once nothing links them.

Each category index (`deposition/index.md`, `etch/index.md`, and the
rest) links to the flat filenames. Update only the links for pages
promoted in that change.

## Steps

### Phase A — PECVD sample, one dummy child

Local look only. One tool, one throwaway page, so the Tool SOPs tab can
be compared to today. Do not add real process docs in this phase. Do not
deploy.

- [x] Add `"PECVD": "pecvd/index.md"` to `TOOL_PAGE_OVERRIDES`.
- [x] `uv run python scripts/sync_gdocs.py tools --only "PECVD"`.
      Wrote `docs/tool_sops/deposition/pecvd/index.md`. The new path had
      no H1 to keep, so the sync titled it `PECVD`; the H1 was set back
      to `Oxford PECVD` so later syncs preserve it.
- [x] Delete `docs/tool_sops/deposition/pecvd.md`.
- [x] In `docs/tool_sops/deposition/.nav.yml`, replace
      `Oxford PECVD: pecvd.md` with `Oxford PECVD: pecvd`.
- [x] Add `docs/tool_sops/deposition/pecvd/.nav.yml`:

```yaml
title: Oxford PECVD
nav:
  - index.md
  - PECVD Processes: pecvd_processes.md
```

- [x] Add a hand-written `docs/tool_sops/deposition/pecvd/pecvd_processes.md`
      with H1 `PECVD Processes` and one line saying it is a nav sample.
      Do not register it in the sheet.
- [x] In `docs/tool_sops/deposition/index.md`, change the equipment-list
      link from `pecvd.md` to `pecvd/index.md`.
- [x] `uv run ruff check .` and `uv run ruff format .`. All checks passed.
- [x] `uv run zensical build --strict` passes. 0.63s, "No issues found".

### Phase A review gate — STOP for sign-off

`uv run zensical serve`, open Tool SOPs, and look at Deposition:

- [ ] **Deposition SOPs** is still a bold heading, open, with no caret.
      Lithography, Etcher, Metrology, and Packaging headings are unchanged.
- [ ] Oxford PECVD is a collapsed row under that heading, not a new bold
      heading. The caret opens one row, PECVD Processes.
- [ ] The SOP is not repeated under the caret. Clicking Oxford PECVD
      still opens `/tool_sops/deposition/pecvd/`.
- [ ] PECVD Processes opens at
      `/tool_sops/deposition/pecvd/pecvd_processes/`.
- [ ] SOP images and both PDF buttons still resolve. The other deposition
      tools are unchanged.
- [ ] Decision: keep this shape / adjust / revert the sample.

Reverting puts `pecvd.md` back, deletes `deposition/pecvd/`, and removes
the `PECVD` override. The dummy is not a real page either way. A later
real child replaces `pecvd_processes.md` instead of sitting beside it.

### Phase B — Promote whichever page gains a child

Only after the Phase A look is accepted. Repeat this for each page, in
any directory from the table. One page per change. Skip the page if it
has no child yet. PECVD is already in this shape; replace the dummy
rather than promoting it again.

- [ ] Point the sync at `<slug>/index.md` (`TOOL_PAGE_OVERRIDES`, or
      `CHEM_PAGE_MAP` / `POLICY_PAGE_MAP`).
- [ ] Re-sync that doc only, for example
      `uv run python scripts/sync_gdocs.py tools --only "PECVD"`.
      Confirm the file is `<dir>/<slug>/index.md` and the H1 is unchanged.
- [ ] Delete the old `<dir>/<slug>.md`.
- [ ] In the parent `.nav.yml`, replace `Label: slug.md` with
      `Label: slug`.
- [ ] Add `<dir>/<slug>/.nav.yml`. The parent label is what the sidebar
      shows; `title:` is the fallback and matches that label. `index.md`
      is first.

```yaml
title: <same label as the parent entry>
nav:
  - index.md
  - <Child label>: <child>.md
```

- [ ] If the child is a registry Google Doc, map it under `<slug>/` and
      sync it. If it is hand-written, add the markdown file only.
- [ ] Update that page's link on the section index (`slug.md` →
      `slug/index.md`). Packaging's index links Tape Mounting and UV
      Release at `dicing_saw.md`; those two move with the dicing saw.
- [ ] `uv run ruff check .` and `uv run ruff format .` after a Python
      map edit.
- [ ] `uv run zensical build --strict` passes, with no `nav_override`
      or duplicate-page warning.

### Phase B review gate — STOP for sign-off

Serve with `uv run zensical serve`. For each page promoted in the
change, confirm the same shape as the PECVD sample: bold level-2
heading unchanged, caret on the promoted page only.

- [ ] The title is a collapsed caret. Opening it shows the child and
      does not list the original page a second time.
- [ ] Clicking the title opens the original page at its old URL.
- [ ] The child opens at `/<section path>/<slug>/<child>/`.
- [ ] Images and both PDF buttons still resolve.
- [ ] The section index link still reaches the page.
- [ ] Sibling pages in that folder are unchanged.
- [ ] Decision: proceed / adjust / abandon

## Known limits / notes

- The sync does not write `.nav.yml`. Each new child is a hand edit in
  that page's directory nav file, in whichever folder it lives.
- A tool row is joined onto its sheet category. A Deposition child
  cannot be filed under `etch/` by an override. Keep children in the
  parent's category, or make them hand-written pages.
- Empty carets are out of scope. Folders stay flat until a real child
  exists.
- Deploy is a push to `main` after sign-off. No R2 upload unless the
  PDF bytes changed.
