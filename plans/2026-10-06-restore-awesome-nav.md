# Restore awesome-nav directory files

**Date:** 2026-10-06
**Status:** Draft

## Description

Zensical 0.0.58 added a native `awesome-nav` replacement. This repo is locked
at 0.0.57, and the `.nav.yml` files were deleted in `261e7e6` when the sidebar
was flattened into `mkdocs.yml`. Restore directory nav files so a new page is
one line next to its siblings, and drop the hand-maintained `nav:` tree.

Do not install `mkdocs-awesome-nav`. Zensical reimplements the plugin. Keep
`mkdocs.yml`; `zensical.toml` is still unnecessary.

Pin **0.0.68** (latest as of this plan), not 0.0.58. 0.0.59 fixed configured
nav titles being ignored and section `index.md` pages appearing twice
([zensical#906](https://github.com/zensical/zensical/issues/906)). 0.0.63
stopped copying dotfiles into `site/`, so `.nav.yml` is not published. CI
already uses Python 3.12; 0.0.68 only drops Python 3.10.

The live `nav:` tree wins over git history. Restoring `261e7e6^` would revert
top-level order, omit the two authoring pages added since, and point Aluminum
Etch at a `pdf.md` that no longer exists. `title:` inside a directory file is
only the fallback; the parent entry's label is what the sidebar shows. Set
both to the live label. Do not put `title:` on `docs/.nav.yml` — at the root
it has no effect and warns.

Index-only directories are pages in the live nav, not sections. Reference the
`index.md` file and do not recreate a `.nav.yml` for them:

- `faq/index.md`
- `chemicals/litho_hood/index.md`
- `chemicals/solvent_hood/index.md`
- `chemicals/caustics_hood/aluminum_etch/index.md`

Sections that contain real children keep a `.nav.yml`, with `index.md` first
so `navigation.indexes` still makes the section header the section home.

If `nav:` stays in `mkdocs.yml` after the plugin is enabled, awesome-nav
replaces it and logs `nav_override`. Delete that block in the same change
that enables the plugin.

## Steps

### Phase A — Upgrade Zensical, leave nav alone

- [ ] In `pyproject.toml`, change `zensical>=0.0.57` to `zensical>=0.0.68`.
- [ ] `uv lock` so `uv.lock` resolves 0.0.68 (or newer if 0.0.68 is no longer
      the newest 0.0.x that still reads `mkdocs.yml` the same way).
- [ ] Do not add a plugin entry and do not add `.nav.yml` files.
- [ ] `uv run zensical build --strict` passes. Sidebar is unchanged because
      the explicit `nav:` tree is still the only navigation.

### Phase A review gate — STOP for sign-off

- [ ] `uv run zensical --version` is 0.0.68 or newer.
- [ ] Strict build passes with no new warnings.
- [ ] Decision: proceed / adjust / abandon

### Phase B — Swap the nav tree for `.nav.yml` files

Enable the plugin and delete `nav:` together. Write these files. Labels and
order match the current `mkdocs.yml` `nav:` block. Paths are relative to the
file's directory.

- [ ] `mkdocs.yml`: under `plugins:`, after `search`, add `- awesome-nav`.
      Delete the `nav:` block and the comment above it.
- [ ] `docs/.nav.yml` (no `title:`)

```yaml
nav:
  - Home: index.md
  - Lab Safety Policies: policy
  - Tool SOPs: tool_sops
  - Chemical Handling: chemicals
  - Nanofab Signup: signup.md
  - About This Site: authoring
  - FAQ: faq/index.md
```

- [ ] `docs/policy/.nav.yml`

```yaml
title: Lab Safety Policies
nav:
  - index.md
  - Rules of Conduct: manual.md
  - Safety Manual: safety.md
  - C14 Application: c14.md
  - Suspension Policy: suspension.md
```

- [ ] `docs/tool_sops/.nav.yml`

```yaml
title: Tool SOPs
nav:
  - index.md
  - Lithography SOPs: lithography
  - Deposition SOPs: deposition
  - Etcher SOPs: etch
  - Metrology SOPs: metrology
  - Packaging SOPs: packaging
```

- [ ] `docs/tool_sops/lithography/.nav.yml`

```yaml
title: Lithography SOPs
nav:
  - index.md
  - Elionix E-Beam Lithography: elionix.md
  - EVG Photo-Mask Aligner: mask_aligner.md
  - Nanoscribe 3D Lithography: nanoscribe.md
  - Spinners: spinners.md
  - Hot Plates: hot_plates.md
```

- [ ] `docs/tool_sops/deposition/.nav.yml`

```yaml
title: Deposition SOPs
nav:
  - index.md
  - AJA Sputter: aja_sputter.md
  - AJA Metal Evaporator: metal_evap.md
  - AJA Organic Evaporator: organic_evap.md
  - AJA Thermal Evaporator: thermal_evap.md
  - Fuji ALD: ald.md
  - Oxford PECVD: pecvd.md
  - Gold Sputter Coater: gold_sputter.md
```

- [ ] `docs/tool_sops/etch/.nav.yml`

```yaml
title: Etcher SOPs
nav:
  - index.md
  - Reactive Ion Etcher: rie.md
  - ICP-Fluorine Etcher: icp-fl.md
  - ICP-Chlorine Etcher: icp-cl.md
```

- [ ] `docs/tool_sops/metrology/.nav.yml`

```yaml
title: Metrology SOPs
nav:
  - index.md
  - Atomic Force Microscope: afm.md
  - Scanning Electron Microscope: sem.md
  - Optical Profilometer: optical_profilometer.md
  - Profilometer: profilometer.md
  - Ellipsometer: ellipsometer.md
```

- [ ] `docs/tool_sops/packaging/.nav.yml`

```yaml
title: Packaging SOPs
nav:
  - index.md
  - Dicing Saw: dicing_saw.md
```

- [ ] `docs/chemicals/.nav.yml`

```yaml
title: Chemical Handling
nav:
  - index.md
  - Litho-Development Hood: litho_hood/index.md
  - Solvent Hood: solvent_hood/index.md
  - Caustics/Metal Etch Hood: caustics_hood
  - HF and Piranha Hood: hf_pirahna_hood
  - RCA Hood: rca_hood
```

- [ ] `docs/chemicals/caustics_hood/.nav.yml`

```yaml
title: Caustics/Metal Etch Hood
nav:
  - index.md
  - Aluminum Etch: aluminum_etch/index.md
  - Nickel Etch: nickel_etch.md
  - Chrome Etch: chrome_etch.md
  - Gold Etch: gold_etch.md
  - Silicon Etch: silicon_etch.md
```

- [ ] `docs/chemicals/hf_pirahna_hood/.nav.yml` — untitled children, titles
      come from each page's H1, same as today:

```yaml
title: HF and Piranha Hood
nav:
  - index.md
  - hf_etch.md
  - piranha.md
```

- [ ] `docs/chemicals/rca_hood/.nav.yml`

```yaml
title: RCA Hood
nav:
  - index.md
  - rca_clean.md
```

- [ ] `docs/authoring/.nav.yml` — includes the two pages the old file lacked:

```yaml
title: About This Site
nav:
  - index.md
  - Writing Documentation: writing_documentation.md
  - How the Docs Chat Works: how_chat_works.md
  - Wiring a Docs Chat Agent: chat_agent.md
```

- [ ] Do not recreate `docs/faq/.nav.yml`,
      `docs/chemicals/solvent_hood/.nav.yml`,
      `docs/chemicals/caustics_hood/aluminum_etch/.nav.yml`, or
      `docs/signup/.nav.yml`.
- [ ] `AGENTS.md`: replace the "Zensical does not read awesome-nav" paragraph.
      New pages get a line in the `.nav.yml` of their directory. A nested tool
      is still `slug/index.md` plus a `.nav.yml` in that directory for its
      children. Keep the "do not add `zensical.toml`" line.
- [ ] `README.md`: same change in "What is generated vs. hand-written", in
      step 4 of "Adding or updating a document" (the line goes in the
      category `.nav.yml`, not `mkdocs.yml`), and in the repo-map row for
      `mkdocs.yml`.
- [ ] `uv run zensical build --strict` passes.
- [ ] Build log has no `nav_override`, `root_title`, or `no_matches` warning.

### Phase B review gate — STOP for sign-off

Serve with `uv run zensical serve` and compare the sidebar to the live site
(or to a build from before Phase B). Check:

- [ ] Top-level order: Home, Lab Safety Policies, Tool SOPs, Chemical
      Handling, Nanofab Signup, About This Site, FAQ.
- [ ] FAQ, Litho-Development Hood, Solvent Hood, and Aluminum Etch are single
      links, not sections with an empty or duplicate child.
- [ ] Section headers still open the section index (Lithography, Deposition,
      Etch, Metrology, Packaging, Caustics, HF and Piranha, RCA, policy,
      authoring).
- [ ] HF etch, piranha, and RCA clean labels match their page H1s.
- [ ] About This Site lists Writing Documentation, How the Docs Chat Works,
      and Wiring a Docs Chat Agent.
- [ ] Decision: proceed / adjust / abandon

## Known limits / notes

- A new SOP is still a manual nav line. These files are explicit lists, not
  `"*"` globs. Globs can come later if auto-include is wanted; they are a
  separate behavior change.
- Zensical's awesome-nav does not support extglob or MkDocs `not_in_nav`.
  None of these files need either.
- The sync script does not write nav entries. That stays a hand edit, now in
  the directory `.nav.yml`.
- Deploy is a push to `main` after the Phase B sign-off. The sync workflow
  uses `uv run`, so the updated `uv.lock` is what CI builds with.
