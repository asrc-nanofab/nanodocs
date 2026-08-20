# Drop mkdocstrings, swap awesome-pages for awesome-nav

**Date:** 2026-08-20
**Status:** Steps 1-5 executed; awaiting visual sign-off and deploy

## Description

Two config-level cleanups that simplify the site and remove blockers for a future
migration to Zensical:

1. **Drop `mkdocstrings`** — the plugin is configured in `mkdocs.yml` but nothing in
   `docs/` uses it (no `:::` directives anywhere). Removing it cuts an unused
   dependency and plugin block with zero visible change to the site.
2. **Swap `awesome-pages` for `awesome-nav`** — awesome-nav is the successor plugin
   by the same author, uses `.nav.yml` files instead of `.pages`, and is natively
   supported by Zensical (awesome-pages is not). The `tech-docs` repo already uses
   awesome-nav and serves as a working reference.

Small riders picked up along the way:

- Drop the no-op `navigation.collapsible` theme feature (not a real Material flag).
- Drop the ineffective `title:` in the root nav file (awesome-pages warns
  `TitleInRootHasNoEffect` on every build).
- Add `requires-python = ">=3.12"` to `pyproject.toml` (silences uv warning;
  matches the venv's Python 3.12.4).
- Optional: fix ~19 directory-style relative links (`tool_sops/` → `tool_sops/index.md`)
  in the five index pages so MkDocs can validate them.

**Acceptance:** rendered nav is identical to the current live site. Deploy only after
local visual verification.

## Steps

### Step 1 — Inventory `.pages` files (read-only)

- [x] Read all 16 `.pages` files under `docs/`
- [x] Note any awesome-pages-specific syntax needing translation:
  - `...` rest entries → `"*"` glob in awesome-nav
  - `order:` / `arrange:` / other keys → check awesome-nav equivalents
- [x] Confirm which files are pure `title:` + `nav:` (straight conversion)

### Step 2 — Dependency changes

- [x] `uv remove mkdocstrings`
- [x] `uv remove mkdocs-awesome-pages-plugin`
- [x] `uv add mkdocs-awesome-nav`
- [x] Add `requires-python = ">=3.12"` to `pyproject.toml`
- [x] Leave `pandas` (used by download scripts) and `ipykernel` untouched

### Step 3 — `mkdocs.yml` changes

- [x] Delete the `mkdocstrings:` block under `plugins:`
- [x] Change `- awesome-pages` to `- awesome-nav`
- [x] Delete the no-op `navigation.collapsible` feature line
- [x] Do NOT touch `navigation.sections` (sidebar look is a separate decision)

### Step 4 — Convert nav files

- [x] For each `.pages` file, create the equivalent `.nav.yml` next to it
- [x] Drop the `title:` line from the root `docs/.nav.yml` (has no effect)
- [x] Delete all `.pages` files
- [x] Cross-check syntax against `~/tech-docs` `.nav.yml` files if unsure

Files to convert:

- [x] `docs/.pages`
- [x] `docs/chemicals/.pages`
- [x] `docs/chemicals/caustics_hood/.pages`
- [x] `docs/chemicals/hf_pirahna_hood/.pages`
- [x] `docs/chemicals/litho_hood/.pages`
- [x] `docs/chemicals/rca_hood/.pages`
- [x] `docs/chemicals/solvent_hood/.pages`
- [x] `docs/faq/.pages`
- [x] `docs/policy/.pages`
- [x] `docs/signup/.pages`
- [x] `docs/tool_sops/.pages`
- [x] `docs/tool_sops/deposition/.pages`
- [x] `docs/tool_sops/etch/.pages`
- [x] `docs/tool_sops/lithography/.pages`
- [x] `docs/tool_sops/metrology/.pages`
- [x] `docs/tool_sops/packaging/.pages`

### Step 4½ — Optional link cleanup (DONE 2026-08-20)

Was deferred until after the Google Drive SOP work; that work landed without
changing page structure, so the links were fixed on `try-markdown-conversion`.

- [x] Fix directory-style relative links in `docs/index.md` (5 links)
- [x] Fix links in `docs/chemicals/index.md` (5 links)
- [x] Fix links in `docs/policy/index.md` (4 links)
- [x] Fix links in `docs/tool_sops/index.md` (5 links)

### Step 5 — Verify

- [x] Stop any already-running `mkdocs serve` (port conflict noted earlier)
- [x] `uv run mkdocs build --strict` passes
- [ ] `uv run mkdocs serve` — click through all sections:
  - [ ] Top-level tab order matches live site
  - [ ] Tool SOPs: deposition, etch, lithography, metrology, packaging
  - [ ] Chemical Handling: all five hoods
  - [ ] Lab Safety Policies, Nanofab Signup, FAQ
  - [ ] Section titles and page ordering match live site
- [x] `TitleInRootHasNoEffect` warning is gone

### Step 6 — Deploy

- [ ] `./deploy.sh` after visual sign-off
- [ ] Spot-check the live site
