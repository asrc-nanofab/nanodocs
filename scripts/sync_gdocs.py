"""Sync Google Docs into MkDocs pages as Markdown.

Reads the registry spreadsheets (public CSV export), downloads each linked
Google Doc in Markdown, DOCX and PDF formats, cleans up the Markdown, and
writes a site page topped with a row of "Google Doc" (read-only /preview) /
"View PDF" / "Download" pill links. The DOCX is only used to recover
original-resolution images: the Markdown export downscales embedded images
to ~640px.
The PDF is hosted in docs/assets/pdfs/ so "View PDF" opens in the browser's
native viewer instead of forcing a download (Google's export URL sends
Content-Disposition: attachment).

The docs and sheets are link-shared, so no credentials are needed.

Usage:
    uv run python scripts/sync_gdocs.py tools --category Deposition
    uv run python scripts/sync_gdocs.py tools chem policy
    uv run python scripts/sync_gdocs.py tools --only AFM --watch

With --watch, the sync re-runs every ~20s (pair with `mkdocs serve` for a
live preview while editing the Google Doc); Ctrl+C stops it.
"""

from __future__ import annotations

import argparse
import base64
import csv
import enum
import hashlib
import io
import re
import sys
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
PDFS_DIR = DOCS_DIR / "assets" / "pdfs"
REQUEST_TIMEOUT = 60
DEFAULT_WATCH_INTERVAL = 20.0
# Floor so a typo like --watch 0 can't hammer Google's export endpoints
MIN_WATCH_INTERVAL = 5.0

# Sheet categories → site folders under tool_sops/.
# "Furnace" has no folder yet; its rows currently carry no doc links.
TOOL_CATEGORY_DIRS = {
    "Deposition": "deposition",
    "Etching": "etch",
    "Lithography": "lithography",
    "Metrology": "metrology",
    "Packaging": "packaging",
}

# Tool names whose page filename doesn't match slugify(name)
TOOL_PAGE_OVERRIDES = {
    "ICP-Cl": "icp-cl.md",
    "ICP-Fl": "icp-fl.md",
    "Spinner": "spinners.md",
    "Elionix 100keV": "elionix.md",
}

# Document Name (as in the sheets) → page path relative to docs/
CHEM_PAGE_MAP: dict[str, str] = {
    "Caustics/Metal Etch Hood": "chemicals/caustics_hood/index.md",
    "Aluminum Etch SOP": "chemicals/caustics_hood/aluminum_etch.md",
    "Chromium Etch SOP": "chemicals/caustics_hood/chrome_etch.md",
    "Gold Etch SOP": "chemicals/caustics_hood/gold_etch.md",
    "Nickel Etch SOP": "chemicals/caustics_hood/nickel_etch.md",
    "Isotropic Silicon Etch (HNA) SOP": "chemicals/caustics_hood/silicon_etch.md",
    "Piranha/HF Hood": "chemicals/hf_pirahna_hood/index.md",
    "Hydroflouric Acid SOP": "chemicals/hf_pirahna_hood/hf_etch.md",
    "Piranha Clean SOP": "chemicals/hf_pirahna_hood/piranha.md",
    "RCA Hood": "chemicals/rca_hood/index.md",
    "RCA Clean SOP": "chemicals/rca_hood/rca_clean.md",
    "Litho-Development Hood": "chemicals/litho_hood/index.md",
    "Solvent/Lift-Off Hood": "chemicals/solvent_hood/index.md",
}
POLICY_PAGE_MAP: dict[str, str] = {
    "C-14": "policy/c14.md",
    "Lab Manual": "policy/manual.md",
    "Safety Manual": "policy/safety.md",
    "Lab Suspension": "policy/suspension.md",
}


class SyncStatus(enum.Enum):
    SYNCED = "synced"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Section:
    name: str
    sheet_csv_url: str
    name_column: str
    pdf_dir: str
    pdf_suffix: str = ""


SECTIONS = {
    "tools": Section(
        name="tools",
        sheet_csv_url=(
            "https://docs.google.com/spreadsheets/d/"
            "1b4RRhKAukj9NrFyiJl_I9vbAUnrgDSy1TeNq2QLKJr4/export?format=csv&gid=477704461"
        ),
        name_column="Tool Name",
        pdf_dir="tools",
        pdf_suffix="_SOP",
    ),
    "chem": Section(
        name="chem",
        sheet_csv_url=(
            "https://docs.google.com/spreadsheets/d/"
            "1MIDhZcYGNO53ZC_TXH3RczhNWxavBpAUXlCD3oSKD4o/export?format=csv&gid=921683470"
        ),
        name_column="Document Name",
        pdf_dir="chem",
    ),
    "policy": Section(
        name="policy",
        sheet_csv_url=(
            "https://docs.google.com/spreadsheets/d/"
            "1aPbGrT06l41D4k2mKLl60QIu9VBZXTN9rSgNjj4gAII/export?format=csv&gid=0"
        ),
        name_column="Document Name",
        pdf_dir="policy",
    ),
}

DOC_ID_RE = re.compile(r"/document/d/([\w-]+)")
IMAGE_DEF_RE = re.compile(
    r"^\[(image\d+)\]:\s*<data:image/([a-zA-Z0-9.+-]+);base64,([^>]+)>\s*$",
    re.MULTILINE,
)
# A paragraph that is nothing but an image reference, e.g. "![alt][image1]"
IMAGE_ONLY_LINE_RE = re.compile(r"^!\[[^\]]*\]\[(image\d+)\]\s*$")
# Google Docs TOC entries: full-line links to in-page anchors (may be bolded)
TOC_ENTRY_RE = re.compile(r"^\*{0,2}\[.*\]\(#.*\)\*{0,2}\s*$")
# TOC entries with a tab + page number inside the link text; catches entries
# with stray text outside the link that TOC_ENTRY_RE misses
TOC_PAGENUM_RE = re.compile(r"\t\d+\]\(#")
# The TOC label in all observed doc stylings: plain, bold, or a heading
# with Google's anchor suffix (e.g. "## **Table of Contents:** {#table-of-contents:}")
TOC_LABEL_RE = re.compile(
    r"(#{1,6}\s+)?\*{0,2}Table of Contents:?\*{0,2}(\s*\{#[^}]*\})?"
)
# Page-boundary artifacts from docs converted out of paginated PDFs
PAGE_MARKER_RE = re.compile(r"^Page\s+\*{0,2}\d+\*{0,2}\s+of\s+\*{0,2}\d+\*{0,2}\s*$")
# Canonicalize labels so a scaffold image matches across occurrences even if
# the export assigned each occurrence its own label
IMAGE_LABEL_RE = re.compile(r"\[image\d+\]")
# Headings the doc author indented inside a list; markdown renders these as
# literal text (and their indented paragraphs as code blocks) unless dedented
INDENTED_HEADING_RE = re.compile(r"^\s+(#{1,6}\s.*)$")
LIST_ITEM_RE = re.compile(r"^\s*(\d+\.|[*+-])\s")
ALT_BOILERPLATE_RE = re.compile(r"AI-generated content may be incorrect\.?")

IMAGE_EXTENSIONS = {"jpeg": "jpg", "svg+xml": "svg"}

# Image-upgrade tuning: only swap in a docx original when it is confidently
# the same picture and meaningfully larger than the ~640px-capped version in
# the markdown export. Matching is by pixel content only (24px thumbnails) —
# deliberately NOT by aspect ratio, because authors resize images
# non-proportionally in docs, which changes the export's shape but not its
# content. Genuine matches score ~1-5; unrelated images score 15+.
MATCH_THUMB_SIZE = (24, 24)
MATCH_MAX_DISTANCE = 10.0
UPGRADE_MIN_AREA_RATIO = 1.2
# Google's markdown export caps image width at 640px; below the cap, the
# exported size is the author's chosen display size in the doc. A Google Doc's
# text column is ~620px, so anything close to it was sized "page wide" by the
# author — render those full width instead of pinning the in-doc pixel size.
FULL_WIDTH_MIN = 550


def _flatten(img: Image.Image) -> Image.Image:
    """Convert to RGB on a white background so RGBA/RGB compare equally."""
    rgba = img.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


def _thumb_distance(a: Image.Image, b: Image.Image) -> float:
    ta = _flatten(a).resize(MATCH_THUMB_SIZE)
    tb = _flatten(b).resize(MATCH_THUMB_SIZE)
    pairs = zip(ta.tobytes(), tb.tobytes())
    return sum(abs(x - y) for x, y in pairs) / (
        MATCH_THUMB_SIZE[0] * MATCH_THUMB_SIZE[1] * 3
    )


def load_docx_media(docx_bytes: bytes) -> list[tuple[bytes, Image.Image]]:
    """Raster images from the docx export, which keeps original resolution."""
    media = []
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        for info in zf.infolist():
            if not info.filename.startswith("word/media/"):
                continue
            data = zf.read(info)
            try:
                img = Image.open(io.BytesIO(data))
                img.load()
            except OSError:
                continue  # non-raster media (EMF/WMF/SVG)
            if img.width < 16 or img.height < 16:
                continue  # decorative spacer pixels
            media.append((data, img))
    return media


def _similar(a: Image.Image, b: Image.Image) -> bool:
    return _thumb_distance(a, b) <= MATCH_MAX_DISTANCE


def best_original(
    md_img: Image.Image, media: list[tuple[bytes, Image.Image]]
) -> bytes | None:
    """Return original-resolution bytes for md_img, or None to keep as is."""
    best: tuple[float, bytes, Image.Image] | None = None
    for data, img in media:
        distance = _thumb_distance(md_img, img)
        if best is None or distance < best[0]:
            best = (distance, data, img)
    if best is None:
        return None
    distance, data, img = best
    is_larger = (
        img.width * img.height >= md_img.width * md_img.height * UPGRADE_MIN_AREA_RATIO
    )
    if distance <= MATCH_MAX_DISTANCE and is_larger:
        return data
    return None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def pdf_asset_path(section: Section, name: str) -> Path:
    """Hosted PDF path, matching the legacy download scripts' naming."""
    filename = re.sub(r'[<>:"/\\|?*]', "_", name.replace(" ", "_"))
    return PDFS_DIR / section.pdf_dir / f"{filename}{section.pdf_suffix}.pdf"


def resolve_page_path(
    section: Section, row: dict[str, str], quiet: bool = False
) -> Path | None:
    """Return the target page path for a sheet row, or None if unmappable."""
    name = row[section.name_column].strip()
    if section.name == "tools":
        category = row.get("Type (Category)", "").strip()
        folder = TOOL_CATEGORY_DIRS.get(category)
        if folder is None:
            if not quiet:
                print(f"  SKIP {name!r}: no site folder for category {category!r}")
            return None
        filename = TOOL_PAGE_OVERRIDES.get(name, f"{slugify(name)}.md")
        return DOCS_DIR / "tool_sops" / folder / filename
    page_map = CHEM_PAGE_MAP if section.name == "chem" else POLICY_PAGE_MAP
    rel = page_map.get(name)
    if rel is None:
        if not quiet:
            print(f"  SKIP {name!r}: not in {section.name} page map (Phase B)")
        return None
    return DOCS_DIR / rel


def extract_images(
    markdown: str,
    img_dir: Path,
    page_dir: Path,
    docx_media: list[tuple[bytes, Image.Image]],
) -> tuple[str, str | None]:
    """Decode base64 image definitions into files and inline the references.

    Returns the rewritten markdown and an image-upgrade note (or None), so
    the caller can report it only when the page actually changed.

    The markdown export downscales images to ~640px; where a confidently
    matching original exists in the docx export, that is written instead.
    Because the markdown-export size IS the author's chosen display size in
    the doc (unless capped at 640px), upgraded images below the cap get an
    attr_list width so e.g. QR codes stay small on the page but high-res.
    Files are named by content hash so identical images dedupe and re-runs
    are idempotent.
    """
    defs = {m.group(1): m for m in IMAGE_DEF_RE.finditer(markdown)}
    if not defs:
        return markdown, None

    # Defs whose references clean_body stripped (typically the letterhead
    # logo): don't write them, and exclude look-alike docx media from upgrade
    # matching — the letterhead is in every docx and can otherwise win the
    # match for wide, mostly-white screenshots and replace them on the page.
    referenced = set(re.findall(r"!\[[^\]]*\]\[(image\d+)\]", markdown))
    stripped_imgs: list[Image.Image] = []
    for label in [label for label in defs if label not in referenced]:
        match = defs.pop(label)
        try:
            img = Image.open(io.BytesIO(base64.b64decode(match.group(3))))
            img.load()
            stripped_imgs.append(img)
        except OSError:
            pass
        markdown = markdown.replace(match.group(0), "")
    if stripped_imgs:
        docx_media = [
            (data, img)
            for data, img in docx_media
            if not any(_similar(stripped, img) for stripped in stripped_imgs)
        ]
    if not defs:
        return markdown, None

    img_dir.mkdir(parents=True, exist_ok=True)
    upgraded = 0
    for label, match in defs.items():
        subtype, b64 = match.group(2), match.group(3)
        data = base64.b64decode(b64)
        ext = IMAGE_EXTENSIONS.get(subtype, subtype)
        display_width = None
        try:
            md_img = Image.open(io.BytesIO(data))
            md_img.load()
        except OSError:
            md_img = None
        if md_img is not None:
            original = best_original(md_img, docx_media)
            if original is not None:
                data = original
                img_format = Image.open(io.BytesIO(data)).format or "png"
                ext = IMAGE_EXTENSIONS.get(img_format.lower(), img_format.lower())
                upgraded += 1
                if md_img.width < FULL_WIDTH_MIN:
                    display_width = md_img.width
        filename = f"{hashlib.sha1(data).hexdigest()[:12]}.{ext}"
        # Content-hash name: if the file exists, its bytes are identical
        if not (img_dir / filename).exists():
            (img_dir / filename).write_bytes(data)
        rel = (img_dir / filename).relative_to(page_dir).as_posix()

        attr = f'{{ width="{display_width}" }}' if display_width else ""
        markdown = re.sub(
            rf"!\[([^\]]*)\]\[{label}\]",
            lambda m, rel=rel, attr=attr: f"![{m.group(1)}]({rel}){attr}",
            markdown,
        )
        markdown = markdown.replace(match.group(0), "")

    note = f"{upgraded}/{len(defs)} images upgraded to docx originals"
    return markdown, note if upgraded else None


def _strip_page_scaffold(lines: list[str]) -> list[str]:
    """Drop page-boundary blocks baked in by PDF → Google Doc conversion.

    Converted docs carry each PDF page's header/footer as body text: a
    "Page N of M" line with the same few lines (logo image, revision line,
    doc title) recurring at every boundary. Markers are always dropped;
    neighbor lines are dropped only when they recur near two or more
    markers, so genuine content adjacent to a single page break survives.
    """

    def canon(line: str) -> str:
        return IMAGE_LABEL_RE.sub("[image]", line.strip())

    def window(center: int) -> list[int]:
        """Indices of the 3 nearest non-blank lines on each side."""
        idxs = []
        for step in (-1, 1):
            found, j = 0, center
            while found < 3:
                j += step
                if j < 0 or j >= len(lines):
                    break
                if lines[j].strip():
                    idxs.append(j)
                    found += 1
        return idxs

    markers = [i for i, ln in enumerate(lines) if PAGE_MARKER_RE.match(ln.strip())]
    if not markers:
        return lines

    near_counts: Counter[str] = Counter()
    for i in markers:
        for j in window(i):
            near_counts[canon(lines[j])] += 1
    scaffold = {text for text, count in near_counts.items() if count >= 2}

    drop = set(markers)
    for i in markers:
        drop.update(j for j in window(i) if canon(lines[j]) in scaffold)
    return [ln for k, ln in enumerate(lines) if k not in drop]


def clean_body(markdown: str) -> str:
    """Strip Google's export artifacts: leading logo, original H1, inline TOC."""
    lines = _strip_page_scaffold(markdown.splitlines())
    out: list[str] = []
    seen_content = False
    title_consumed = False
    for line in lines:
        stripped = line.strip()
        if not seen_content:
            # Drop the letterhead logo image and the doc's own title H1
            # (which may be empty, e.g. "# "); the page supplies its own
            # title. Only the first H1 is treated as the title so a doc
            # that opens with a real section heading keeps it.
            if not stripped or IMAGE_ONLY_LINE_RE.match(stripped):
                continue
            if not title_consumed and re.fullmatch(r"#(\s.*)?", stripped):
                title_consumed = True
                continue
            seen_content = True
        # Empty heading lines are Google Doc styling leftovers with no content
        if re.fullmatch(r"#{1,6}", stripped):
            continue
        if TOC_LABEL_RE.fullmatch(stripped) or TOC_ENTRY_RE.match(stripped):
            continue
        if TOC_PAGENUM_RE.search(stripped):
            continue
        # TOC remnants with unresolved Google anchors (e.g. partially bolded
        # entries that escape TOC_ENTRY_RE); "#heading=" is never a valid target
        if "](#heading=" in stripped:
            continue
        out.append(line)
    # Collapse blank-line runs left behind by the stripping above
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    return _dedent_nested_headings(body)


def _dedent_nested_headings(markdown: str) -> str:
    """Un-indent headings the doc author nested inside lists.

    Google exports them with leading spaces, which markdown renders as
    literal text — and the further-indented paragraphs under them as code
    blocks. Dedent the heading and its following paragraphs, stopping at
    the next list item or column-0 line so real nested lists are untouched.
    """
    out: list[str] = []
    dedent_mode = False
    for line in markdown.splitlines():
        if m := INDENTED_HEADING_RE.match(line):
            line = m.group(1)
            dedent_mode = True
        elif dedent_mode and line.strip():
            if LIST_ITEM_RE.match(line) or not line[0].isspace():
                dedent_mode = False
            else:
                line = line.lstrip()
        out.append(line)
    return "\n".join(out) + "\n"


# Separates the generated header (H1 + link row) from the doc body; also
# used to recover the body of an existing page so template-only changes can
# be told apart from doc-content changes.
PAGE_BODY_SEP = "\n---\n\n"


def build_page(title: str, preview_url: str, pdf_href: str, body: str) -> str:
    pdf_filename = pdf_href.rsplit("/", 1)[-1]
    return (
        "<!-- AUTO-GENERATED by scripts/sync_gdocs.py from the Google Doc "
        "below. Edit the Google Doc, not this file. -->\n\n"
        f"# {title}\n\n"
        # Compact labels + pill styling (overrides/stylesheets/extra.css) so
        # all three links share one row on phones instead of stacking
        '<div class="doc-links" markdown="span">\n'
        f"[:material-file-document-outline: Google Doc]({preview_url}){{ .md-button }}\n"
        # Same-tab navigation so the browser back button returns to this page
        f"[:material-file-pdf-box: View PDF]({pdf_href}){{ .md-button }}\n"
        f'[:material-download: Download]({pdf_href}){{ .md-button download="{pdf_filename}" }}\n'
        f"</div>\n{PAGE_BODY_SEP}"
        f"{body}"
    )


CAPTION_RE = re.compile(r"^\W{0,3}Image \d+", re.IGNORECASE)


def warn_dropped_images(name: str, body: str) -> None:
    """Flag figure captions with no image directly above them.

    Google's markdown export silently drops images whose layout is "Wrap
    text" / "Break text" (only "In line with text" exports), so an orphaned
    caption usually means the doc author needs to change the image layout.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if not CAPTION_RE.match(line.strip()):
            continue
        prev = [ln for ln in lines[max(0, i - 4) : i] if ln.strip()]
        if not any("](img/" in ln for ln in prev[-2:]):
            print(
                f"  WARNING {name!r}: caption {line.strip()[:60]!r} has no image "
                "above it — likely a wrapped image the Google export dropped; "
                'set it to "In line with text" in the doc'
            )


def write_if_changed(path: Path, content: str) -> bool:
    """Write only when content differs, so mkdocs serve isn't reloaded no-op."""
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def existing_title(page_path: Path, fallback: str) -> str:
    """Keep the current page's H1 so on-page titles don't churn."""
    if page_path.exists():
        for line in page_path.read_text().splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return fallback


def existing_body(page_path: Path) -> str | None:
    """The current page's doc body (everything after the header rule)."""
    if not page_path.exists():
        return None
    content = page_path.read_text()
    if PAGE_BODY_SEP not in content:
        return None
    return content.split(PAGE_BODY_SEP, 1)[1]


def sync_row(
    section: Section,
    row: dict[str, str],
    quiet: bool = False,
    md_cache: dict[str, str] | None = None,
) -> SyncStatus:
    name = (row.get(section.name_column) or "").strip()
    pdf_url = (row.get("PDF Link") or "").strip()
    if not name or not pdf_url.startswith("http"):
        return SyncStatus.SKIPPED

    doc_id_match = DOC_ID_RE.search(pdf_url)
    if doc_id_match is None:
        if not quiet:
            print(f"  SKIP {name!r}: could not parse doc id from {pdf_url}")
        return SyncStatus.SKIPPED
    doc_id = doc_id_match.group(1)

    page_path = resolve_page_path(section, row, quiet)
    if page_path is None:
        return SyncStatus.SKIPPED
    pdf_path = pdf_asset_path(section, name)

    preview_url = f"https://docs.google.com/document/d/{doc_id}/preview"

    md_url = f"https://docs.google.com/document/d/{doc_id}/export?format=md"
    resp = requests.get(md_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    # Watch-mode fast path: a byte-identical export means nothing to do,
    # skipping the docx download, image matching, and PDF logic entirely
    md_digest = hashlib.sha1(resp.content).hexdigest()
    if (
        md_cache is not None
        and md_cache.get(doc_id) == md_digest
        and page_path.exists()
        and pdf_path.exists()
    ):
        return SyncStatus.UNCHANGED
    markdown = ALT_BOILERPLATE_RE.sub("", resp.text)

    docx_url = f"https://docs.google.com/document/d/{doc_id}/export?format=docx"
    resp = requests.get(docx_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    docx_media = load_docx_media(resp.content)

    body = clean_body(markdown)
    body, upgrade_note = extract_images(
        body, page_path.parent / "img", page_path.parent, docx_media
    )

    # Relative href so mkdocs build --strict verifies the PDF exists
    pdf_href = pdf_path.relative_to(page_path.parent, walk_up=True).as_posix()

    title = existing_title(page_path, name)
    body_changed = existing_body(page_path) != body
    page_changed = write_if_changed(
        page_path, build_page(title, preview_url, pdf_href, body)
    )

    # Google's PDF export is not byte-stable, so refresh it only when the doc
    # content changed (or the file is missing, e.g. on a fresh checkout).
    # Keyed to the body, not the whole page, so header-template tweaks don't
    # re-download and rewrite every hosted PDF.
    if body_changed or not pdf_path.exists():
        resp = requests.get(pdf_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(resp.content)

    # Only cache after the full pipeline, so disk is known to match the export
    if md_cache is not None:
        md_cache[doc_id] = md_digest

    if not page_changed:
        if not quiet:
            print(f"  {name}: unchanged")
        return SyncStatus.UNCHANGED

    print(f"  {name}: WROTE {page_path.relative_to(DOCS_DIR.parent)}")
    if upgrade_note:
        print(f"    {upgrade_note}")
    warn_dropped_images(name, body)
    return SyncStatus.SYNCED


def sync_section(
    section: Section,
    category: str | None,
    only: str | None,
    quiet: bool = False,
    md_cache: dict[str, str] | None = None,
) -> Counter[SyncStatus]:
    if not quiet:
        print(f"Section: {section.name}")
    resp = requests.get(section.sheet_csv_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))

    counts: Counter[SyncStatus] = Counter()
    for row in rows:
        if category and row.get("Type (Category)", "").strip() != category:
            continue
        if only and (row.get(section.name_column) or "").strip() != only:
            continue
        counts[sync_row(section, row, quiet, md_cache)] += 1
    if not quiet:
        print(f"  {summarize(counts)}")
    return counts


def summarize(counts: Counter[SyncStatus]) -> str:
    return ", ".join(f"{status.value} {counts[status]}" for status in SyncStatus)


def sync_all(
    args: argparse.Namespace,
    quiet: bool = False,
    md_cache: dict[str, str] | None = None,
) -> Counter[SyncStatus]:
    totals: Counter[SyncStatus] = Counter()
    for section_name in args.sections:
        totals += sync_section(
            SECTIONS[section_name], args.category, args.only, quiet, md_cache
        )
    return totals


def watch(args: argparse.Namespace, interval: float) -> int:
    md_cache: dict[str, str] = {}
    print(f"Watching every {interval:g}s — Ctrl+C to stop")
    try:
        while True:
            try:
                totals = sync_all(args, quiet=True, md_cache=md_cache)
            except requests.RequestException as exc:
                print(f"[{time.strftime('%H:%M:%S')}] error: {exc} — will retry")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] {summarize(totals)}")
                if totals[SyncStatus.SYNCED] + totals[SyncStatus.UNCHANGED] == 0:
                    print("No syncable documents matched.")
                    return 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sections",
        nargs="+",
        choices=sorted(SECTIONS),
        help="which registry sheet(s) to sync",
    )
    parser.add_argument(
        "--category", help="tools only: limit to one Type (Category), e.g. Deposition"
    )
    parser.add_argument("--only", help="limit to a single document by name")
    parser.add_argument(
        "--watch",
        nargs="?",
        const=DEFAULT_WATCH_INTERVAL,
        type=float,
        metavar="SECONDS",
        help=f"re-sync every SECONDS (default {DEFAULT_WATCH_INTERVAL:g}) "
        "until Ctrl+C; pair with `mkdocs serve` for a live preview",
    )
    args = parser.parse_args()

    if args.watch is not None:
        return watch(args, max(args.watch, MIN_WATCH_INTERVAL))

    totals = sync_all(args)
    # Skipped-only still errors: nothing syncable matched the selection
    # (e.g. a typo in --only, or a registry row with no doc link yet)
    if totals[SyncStatus.SYNCED] + totals[SyncStatus.UNCHANGED] == 0:
        print("No syncable documents matched.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
