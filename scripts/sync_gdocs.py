"""Sync Google Docs into site pages as Markdown.

Reads the Nanodocs Registry (one workbook, three tabs: groups, assets,
documents), downloads each published Google Doc in Markdown, DOCX and PDF
formats, and writes a site page topped with a row of "Google Doc"
(read-only /preview) / "View PDF" / "Download" pill links. The DOCX is
only used to recover original-resolution images: the Markdown export
downscales embedded images to ~640px. The PDF is hosted in
docs/assets/pdfs/ so "View PDF" opens in the browser's native viewer
instead of forcing a download (Google's export URL sends
Content-Disposition: attachment).

The document labeled SOP is the asset's index.md. A caret is written
only when another published document sits beside it.

The docs and the sheet are link-shared, so no credentials are needed.

Usage:
    uv run python scripts/sync_gdocs.py
    uv run python scripts/sync_gdocs.py --group deposition
    uv run python scripts/sync_gdocs.py --asset pecvd --only SOP
    uv run python scripts/sync_gdocs.py --only "Gold Etch" --watch

With --watch, the sync re-runs every ~20s (pair with `zensical serve` for a
live preview while editing the Google Doc); Ctrl+C stops it.

Last-published Markdown-export SHA-1s live in `.sync-state.json` at the
repo root so a later run (CI or a fresh `--watch`) can skip unchanged
docs without re-downloading the DOCX and PDF. The same file remembers the
path written for each doc; a later path change appends a redirect.
"""

from __future__ import annotations

import argparse
import base64
import csv
import enum
import hashlib
import io
import json
import re
import sys
import time
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
PDFS_DIR = DOCS_DIR / "assets" / "pdfs"
# Repo root, not docs/: Zensical must not serve this. CI and one-shot runs
# use it as the unchanged fast path; --watch used to keep the same map in
# memory only, so every process restart re-downloaded every DOCX.
SYNC_STATE_PATH = REPO_ROOT / ".sync-state.json"
REQUEST_TIMEOUT = 60
GET_ATTEMPTS = 3
DEFAULT_WATCH_INTERVAL = 20.0
# Floor so a typo like --watch 0 can't hammer Google's export endpoints
MIN_WATCH_INTERVAL = 5.0

# Nanodocs Registry. CSV export of each tab; link-shared, no credentials.
REGISTRY_ID = "1wuT0MT50EOu8GzAxCS05bQzJCV9Hevwk7dXe9B28wBo"
REGISTRY_GIDS = {
    "groups": "1564656206",
    "assets": "0",
    "documents": "1004610326",
}
SECTIONS = {"tools", "chemicals", "policy"}
AUDIENCES = {"public", "staff", "admin"}
# The document with this label is the asset's home page (index.md).
HOME_LABEL = "SOP"
ID_RE = re.compile(r"^[a-z0-9-]+$")
REDIRECTS_PATH = DOCS_DIR / "_redirects"


class SyncStatus(enum.Enum):
    SYNCED = "synced"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"


@dataclass
class SyncState:
    """Last published Markdown-export SHA-1 and path per Google Doc id."""

    docs: dict[str, dict[str, str]]
    dirty: bool = False

    def export_sha1(self, doc_id: str) -> str | None:
        entry = self.docs.get(doc_id)
        if entry is None:
            return None
        sha1 = entry.get("export_sha1")
        return sha1 or None

    def path(self, doc_id: str) -> str | None:
        entry = self.docs.get(doc_id)
        if entry is None:
            return None
        return entry.get("path") or None

    def remember(
        self, doc_id: str, *, section: str, name: str, sha1: str, path: str
    ) -> None:
        # A label edit keeps the hash and moves the path. Record the path
        # even when the hash is unchanged, and redirect the old URL.
        existing = self.docs.get(doc_id)
        old_path = (existing or {}).get("path") or ""
        if (
            existing is not None
            and existing.get("export_sha1") == sha1
            and old_path == path
            and existing.get("name") == name
            and existing.get("section") == section
        ):
            return
        if old_path and old_path != path:
            append_redirect(old_path, path)
        self.docs[doc_id] = {
            "name": name,
            "section": section,
            "export_sha1": sha1,
            "path": path,
        }
        self.dirty = True


def load_sync_state(path: Path = SYNC_STATE_PATH) -> SyncState:
    if not path.is_file():
        return SyncState(docs={})
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise TypeError(f"{path} must be a JSON object of doc id → entry")
    docs: dict[str, dict[str, str]] = {}
    for doc_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        sha1 = str(entry.get("export_sha1") or "")
        if not sha1:
            continue
        stored = {
            "name": str(entry.get("name") or ""),
            "section": str(entry.get("section") or ""),
            "export_sha1": sha1,
        }
        remembered = str(entry.get("path") or "")
        if remembered:
            stored["path"] = remembered
        docs[str(doc_id)] = stored
    return SyncState(docs=docs)


def save_sync_state(state: SyncState, path: Path = SYNC_STATE_PATH) -> bool:
    """Write only when a hash was added or changed. Returns True if written."""
    if not state.dirty:
        return False
    text = json.dumps(state.docs, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text() == text:
        state.dirty = False
        return False
    path.write_text(text)
    state.dirty = False
    return True


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
# List item split into indent / marker / spacing / text, for re-indentation
LIST_ITEM_PARTS_RE = re.compile(r"^( *)(\d+\.|[*+-])( +)(.*)$")
ALT_BOILERPLATE_RE = re.compile(r"AI-generated content may be incorrect\.?")
# A heading anchor the export orphaned onto its own line (it belongs on the
# heading); attr_list can't attach it, so it renders as literal text
ORPHAN_ANCHOR_RE = re.compile(r"\{#[^}]*\}")
# A heading line, optionally prefixed by a list marker (docs sometimes nest
# headings in numbered lists); {1,5} so H6 is never pushed past the max level
DEMOTABLE_HEADING_RE = re.compile(r"^((?:\s*(?:\d+\.|[*+-])\s+)?)(#{1,5}\s)")

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
    """Lower-case, and turn every run of non-alphanumerics into one hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch_url(url: str) -> requests.Response:
    """GET with retries. GitHub runners often see one-off Google export stalls."""
    last_exc: requests.RequestException | None = None
    for attempt in range(1, GET_ATTEMPTS + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == GET_ATTEMPTS:
                break
            time.sleep(5 * attempt)
    assert last_exc is not None
    raise last_exc


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
            # Alt text is usually browser-generated (source page titles) and
            # can contain "|", which splits the cell when the image sits in a
            # table — sanitize rather than escape, since "\|" only renders
            # cleanly inside tables
            lambda m, rel=rel, attr=attr: (
                f"![{m.group(1).replace('|', '-')}]({rel}){attr}"
            ),
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
        if ORPHAN_ANCHOR_RE.fullmatch(stripped):
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
    return _demote_body_headings(_normalize_list_indent(_dedent_nested_headings(body)))


def _demote_body_headings(markdown: str) -> str:
    """Shift every heading down one level when the body contains an H1.

    Doc authors often style top-level sections as Heading 1, but the page
    template already supplies its own H1 title, so body H1s become siblings
    of the title. Material's sidebar TOC only lists descendants of the first
    H1 — sibling H1s (and everything under them) silently vanish from it.
    Demoting keeps one H1 per page and the TOC intact.
    """
    lines = markdown.splitlines()
    in_fence = False
    fenced = []
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced.append(True)
            in_fence = not in_fence
        else:
            fenced.append(in_fence)

    has_h1 = any(
        not is_fenced and re.match(r"#\s", line)
        for line, is_fenced in zip(lines, fenced)
    )
    if not has_h1:
        return markdown

    out = [
        line if is_fenced else DEMOTABLE_HEADING_RE.sub(r"\g<1>#\g<2>", line, count=1)
        for line, is_fenced in zip(lines, fenced)
    ]
    return "\n".join(out) + "\n"


def _normalize_list_indent(markdown: str) -> str:
    """Re-indent nested lists to the 4 spaces per level Python-Markdown needs.

    Google indents a child item by the width of its parent's marker (2 for
    "* ", 3 for "1. ", 4 for "10. "), but Python-Markdown only nests at
    tab_length (4 spaces) per level — anything shallower renders as one flat
    list. Rebuild each item's depth from the export's own indentation and
    emit it at 4 spaces per level; continuation lines (e.g. images inside an
    item) are re-indented to stay attached to their item.
    """
    out: list[str] = []
    # Open ancestor items: (item indent, content start column, level)
    stack: list[tuple[int, int, int]] = []
    in_fence = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if in_fence or stripped.startswith("```") or not stripped:
            out.append(line)
            continue
        if m := LIST_ITEM_PARTS_RE.match(line):
            indent, marker, spacing, text = m.groups()
            while stack and len(indent) < stack[-1][1]:
                stack.pop()
            level = stack[-1][2] + 1 if stack else 0
            # Content column is marker width + one space even when the
            # author's spacing is wider (e.g. "10.  text" nests at col 4)
            stack.append((len(indent), len(indent) + len(marker) + 1, level))
            out.append(" " * (4 * level) + marker + spacing + text)
        elif line.startswith(" "):
            content_indent = len(line) - len(line.lstrip(" "))
            while stack and content_indent < stack[-1][1]:
                stack.pop()
            if stack:
                line = " " * (4 * stack[-1][2] + 4) + line.lstrip(" ")
            out.append(line)
        else:
            stack.clear()
            out.append(line)
    return "\n".join(out) + "\n"


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
# Unique to the generated header (closes the button row). Splitting on
# PAGE_BODY_SEP alone would hit a leading YAML `---` fence first.
HEADER_BODY_SEP = "</div>\n" + PAGE_BODY_SEP


def build_page(
    title: str,
    preview_url: str,
    pdf_href: str,
    download_name: str,
    body: str,
    front_matter: str = "",
) -> str:
    prefix = f"{front_matter.rstrip()}\n\n" if front_matter else ""
    return (
        prefix + "<!-- AUTO-GENERATED by scripts/sync_gdocs.py from the Google Doc "
        "below. Edit the Google Doc, not this file. -->\n\n"
        f"# {title}\n\n"
        # Compact labels + pill styling (overrides/stylesheets/extra.css) so
        # all three links share one row on phones instead of stacking
        '<div class="doc-links" markdown="span">\n'
        f"[:material-file-document-outline: Google Doc]({preview_url}){{ .md-button }}\n"
        # Same-tab navigation so the browser back button returns to this page
        f"[:material-file-pdf-box: View PDF]({pdf_href}){{ .md-button }}\n"
        f'[:material-download: Download]({pdf_href}){{ .md-button download="{download_name}" }}\n'
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
    """Write only when content differs, so zensical serve isn't reloaded no-op."""
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def existing_front_matter(page_path: Path) -> str:
    """Leading MkDocs YAML fence, so per-page options survive a re-sync."""
    if not page_path.exists():
        return ""
    text = page_path.read_text()
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end == -1:
        return ""
    return text[: end + 5]


def existing_body(page_path: Path) -> str | None:
    """The current page's doc body (everything after the header rule)."""
    if not page_path.exists():
        return None
    content = page_path.read_text()
    if HEADER_BODY_SEP not in content:
        return None
    return content.split(HEADER_BODY_SEP, 1)[1]


class RegistryError(Exception):
    """A registry row failed validation. The message names the tab and row."""


@dataclass(frozen=True)
class Group:
    id: str
    section: str
    label: str


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    group: str


@dataclass(frozen=True)
class Document:
    asset: str
    label: str
    title: str
    section: str
    audience: str
    doc_id: str
    row_number: int


@dataclass(frozen=True)
class Registry:
    groups: dict[str, Group]
    assets: dict[str, Asset]
    documents: list[Document]


@dataclass
class NavEntry:
    label: str | None
    target: str


def sheet_csv_url(gid: str) -> str:
    return (
        "https://docs.google.com/spreadsheets/d/"
        f"{REGISTRY_ID}/export?format=csv&gid={gid}"
    )


def _cell(row: dict[str, str], column: str) -> str:
    return (row.get(column) or "").strip()


def _require_columns(
    tab: str, fieldnames: list[str] | None, required: tuple[str, ...]
) -> None:
    have = set(fieldnames or [])
    missing = [column for column in required if column not in have]
    if missing:
        raise RegistryError(f"{tab}: missing required column(s): {', '.join(missing)}")


def _blank_row(row: dict[str, str]) -> bool:
    return not any((value or "").strip() for value in row.values())


def load_registry(tables: dict[str, str]) -> Registry:
    """Validate the three tabs. `tables` maps a tab name to CSV text.

    Stops on the first problem. Unknown columns are ignored so the sheet
    can grow attributes the sync does not read yet.
    """
    groups = _load_groups(_strip_bom(tables["groups"]))
    assets = _load_assets(_strip_bom(tables["assets"]), groups)
    documents = _load_documents(_strip_bom(tables["documents"]), groups, assets)
    return Registry(groups=groups, assets=assets, documents=documents)


def _strip_bom(text: str) -> str:
    return text.lstrip("\ufeff")


def _load_groups(text: str) -> dict[str, Group]:
    reader = csv.DictReader(io.StringIO(text))
    _require_columns(
        "groups", list(reader.fieldnames or []), ("id", "section", "label")
    )
    rows = list(reader)
    groups: dict[str, Group] = {}
    for number, row in enumerate(rows, start=2):
        if _blank_row(row):
            continue
        group_id = _cell(row, "id")
        section = _cell(row, "section")
        label = _cell(row, "label")
        where = f"groups row {number} ({group_id or 'blank id'})"
        if not ID_RE.fullmatch(group_id):
            raise RegistryError(f"{where}: id must be lower-case [a-z0-9-]")
        if group_id in groups:
            raise RegistryError(f"{where}: duplicate id")
        if section not in SECTIONS:
            raise RegistryError(f"{where}: section {section!r} is not a known section")
        if not label:
            raise RegistryError(f"{where}: label is empty")
        groups[group_id] = Group(id=group_id, section=section, label=label)
    return groups


def _load_assets(text: str, groups: dict[str, Group]) -> dict[str, Asset]:
    reader = csv.DictReader(io.StringIO(text))
    _require_columns("assets", list(reader.fieldnames or []), ("id", "name", "group"))
    assets: dict[str, Asset] = {}
    for number, row in enumerate(reader, start=2):
        if _blank_row(row):
            continue
        asset_id = _cell(row, "id")
        name = _cell(row, "name")
        group_id = _cell(row, "group")
        where = f"assets row {number} ({asset_id or 'blank id'})"
        if not ID_RE.fullmatch(asset_id):
            raise RegistryError(f"{where}: id must be lower-case [a-z0-9-]")
        if asset_id in assets:
            raise RegistryError(f"{where}: duplicate id")
        if group_id not in groups:
            raise RegistryError(f"{where}: group {group_id!r} is not a groups.id")
        if not name:
            raise RegistryError(f"{where}: name is empty")
        assets[asset_id] = Asset(id=asset_id, name=name, group=group_id)
    return assets


def _load_documents(
    text: str, groups: dict[str, Group], assets: dict[str, Asset]
) -> list[Document]:
    reader = csv.DictReader(io.StringIO(text))
    _require_columns(
        "documents",
        list(reader.fieldnames or []),
        ("asset", "label", "title", "section", "audience", "doc"),
    )
    documents: list[Document] = []
    seen_docs: dict[str, str] = {}
    for number, row in enumerate(reader, start=2):
        if _blank_row(row):
            continue
        asset_id = _cell(row, "asset")
        label = _cell(row, "label")
        title = _cell(row, "title")
        section = _cell(row, "section")
        audience = _cell(row, "audience")
        doc_url = _cell(row, "doc")
        where = f"documents row {number} ({label or 'blank label'})"
        if not label:
            raise RegistryError(f"{where}: label is empty")
        if not title:
            raise RegistryError(f"{where}: title is empty")
        if audience not in AUDIENCES:
            raise RegistryError(
                f"{where}: audience {audience!r} is not a known audience"
            )
        if asset_id:
            if asset_id not in assets:
                raise RegistryError(f"{where}: asset {asset_id!r} is not an assets.id")
        elif section and section not in SECTIONS:
            raise RegistryError(f"{where}: section {section!r} is not a known section")
        doc_id = ""
        if doc_url:
            match = DOC_ID_RE.search(doc_url)
            if match is None:
                raise RegistryError(
                    f"{where}: could not parse a Google Doc id from doc"
                )
            doc_id = match.group(1)
            previous = seen_docs.get(doc_id)
            if previous is not None:
                raise RegistryError(
                    f"{where}: doc {doc_id} is already used by {previous}"
                )
            seen_docs[doc_id] = where
        document = Document(
            asset=asset_id,
            label=label,
            title=title,
            section=section,
            audience=audience,
            doc_id=doc_id,
            row_number=number,
        )
        documents.append(document)
    _assign_document_paths(documents, groups, assets)
    return documents


def _documents_for_asset(documents: list[Document], asset_id: str) -> list[Document]:
    return [document for document in documents if document.asset == asset_id]


def home_document(documents: list[Document], asset_id: str) -> Document:
    """The asset's home page. A SOP row wins; a lone row is home too."""
    rows = _documents_for_asset(documents, asset_id)
    sop = [document for document in rows if document.label == HOME_LABEL]
    if len(sop) > 1:
        listed = ", ".join(f"row {document.row_number}" for document in sop)
        raise RegistryError(
            f"asset {asset_id}: more than one document labeled {HOME_LABEL!r} ({listed})"
        )
    if len(sop) == 1:
        return sop[0]
    if len(rows) == 1:
        return rows[0]
    raise RegistryError(
        f"asset {asset_id}: {len(rows)} documents and no row labeled {HOME_LABEL!r}"
    )


def _require_published_home(documents: list[Document]) -> None:
    """A published sibling needs its home page published for the same audience."""
    asset_ids = {document.asset for document in documents if document.asset}
    for asset_id in sorted(asset_ids):
        rows = _documents_for_asset(documents, asset_id)
        home = home_document(documents, asset_id)
        audiences = sorted({document.audience for document in rows if document.doc_id})
        for audience in audiences:
            if home.doc_id and home.audience == audience:
                continue
            raise RegistryError(
                f"asset {asset_id}: a {audience} document is published but the home "
                f"page (documents row {home.row_number}) is not"
            )


def _assign_document_paths(
    documents: list[Document],
    groups: dict[str, Group],
    assets: dict[str, Asset],
) -> None:
    """Resolve home pages, then reject two rows that would write one file."""
    seen_assets: set[str] = set()
    for document in documents:
        if document.asset and document.asset not in seen_assets:
            seen_assets.add(document.asset)
            home_document(documents, document.asset)
    _require_published_home(documents)
    registry = Registry(groups, assets, documents)
    seen_paths: dict[str, str] = {}
    for document in documents:
        where = f"documents row {document.row_number} ({document.label})"
        rel = document_rel(document, registry)
        if rel == ".md" or rel.endswith("/.md"):
            raise RegistryError(f"{where}: label {document.label!r} has no slug")
        previous_path = seen_paths.get(rel)
        if previous_path is not None:
            raise RegistryError(
                f"{where}: path {rel} is already used by {previous_path}"
            )
        seen_paths[rel] = where


def document_rel(document: Document, registry: Registry) -> str:
    """Page path relative to docs/, per the registry path rule."""
    if document.asset:
        asset = registry.assets[document.asset]
        group = registry.groups[asset.group]
        prefix = f"{group.section}/{group.id}/{asset.id}"
        home = home_document(registry.documents, document.asset)
        if document.row_number == home.row_number:
            return f"{prefix}/index.md"
        return f"{prefix}/{slugify(document.label)}.md"
    slug = slugify(document.label)
    if document.section:
        return f"{document.section}/{slug}.md"
    return f"{slug}.md"


def pdf_rel(page_rel: str) -> Path:
    """PDF key mirrors the page path, so a title edit does not rename the file."""
    return Path(page_rel).with_suffix(".pdf")


def page_url(page_rel: str) -> str:
    """Site path for a docs-relative markdown path, with a trailing slash."""
    stem = page_rel.removesuffix(".md")
    if stem == "index" or stem.endswith("/index"):
        stem = stem[: -len("index")].rstrip("/")
    if not stem:
        return "/"
    return f"/{stem}/"


def download_filename(title: str) -> str:
    """Friendly PDF name for the Download pill. The stored key stays the slug."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip()
    return f"{cleaned or 'document'}.pdf"


def append_redirect(old_rel: str, new_rel: str) -> None:
    """Append one old-URL → new-URL line. A repeat source is left as it was."""
    old_url = page_url(old_rel)
    new_url = page_url(new_rel)
    if old_url == new_url:
        return
    line = f"{old_url} {new_url} 301\n"
    existing = REDIRECTS_PATH.read_text() if REDIRECTS_PATH.is_file() else ""
    if f"{old_url} " in existing:
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    REDIRECTS_PATH.write_text(existing + line)


def published_documents(registry: Registry, audience: str) -> list[Document]:
    return [
        document
        for document in registry.documents
        if document.audience == audience and document.doc_id
    ]


def select_documents(
    documents: list[Document],
    registry: Registry,
    *,
    group: str | None,
    asset: str | None,
    only: str | None,
) -> list[Document]:
    selected = []
    for document in documents:
        if asset and document.asset != asset:
            continue
        if group:
            if not document.asset:
                continue
            if registry.assets[document.asset].group != group:
                continue
        if only and document.label != only:
            continue
        selected.append(document)
    return selected


def _parse_nav_item(body: str) -> NavEntry:
    # "Label: target" — split on the first ": " so a label may contain colons.
    if ": " in body:
        label, target = body.split(": ", 1)
        return NavEntry(label.strip().strip("\"'"), target.strip())
    return NavEntry(None, body.strip())


def load_nav(path: Path) -> tuple[str | None, list[NavEntry]]:
    title: str | None = None
    entries: list[NavEntry] = []
    for line in path.read_text().splitlines():
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("  - "):
            entries.append(_parse_nav_item(line[4:]))
    return title, entries


def dump_nav(title: str | None, entries: list[NavEntry]) -> str:
    lines = []
    if title:
        lines.append(f"title: {title}")
    lines.append("nav:")
    for entry in entries:
        if entry.label is None:
            lines.append(f"  - {entry.target}")
        else:
            lines.append(f"  - {entry.label}: {entry.target}")
    return "\n".join(lines) + "\n"


def merge_nav(path: Path, title: str | None, generated: list[NavEntry]) -> bool:
    """Relabel entries this sync owns and append any that are missing.

    Order of existing lines is kept. Entries whose target this sync did not
    generate are left alone, including a hand-written index.md that is not
    in `generated`. docs/.nav.yml is never this path: callers skip docs root.
    """
    if path.is_file():
        existing_title, entries = load_nav(path)
    else:
        existing_title, entries = None, []
    by_target = {entry.target: entry for entry in generated}
    changed = False
    for entry in entries:
        replacement = by_target.get(entry.target)
        if replacement is not None and entry.label != replacement.label:
            entry.label = replacement.label
            changed = True
    present = {entry.target for entry in entries}
    for entry in generated:
        if entry.target not in present:
            entries.append(entry)
            changed = True
    new_title = existing_title
    if title is not None and existing_title != title:
        new_title = title
        changed = True
    if not path.is_file():
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_nav(new_title, entries))
    return changed


def _groups_with_pages(registry: Registry, documents: list[Document]) -> set[str]:
    return {
        registry.assets[document.asset].group
        for document in documents
        if document.asset
    }


def merge_published_nav(registry: Registry, documents: list[Document]) -> None:
    """Sidebar labels follow the sheet. New rows are appended; nothing is reordered."""
    groups_used = _groups_with_pages(registry, documents)
    assets_used = {document.asset for document in documents if document.asset}

    for section in sorted(SECTIONS):
        generated: list[NavEntry] = []
        for group in registry.groups.values():
            if group.section == section and group.id in groups_used:
                generated.append(NavEntry(group.label, group.id))
        for document in documents:
            if document.asset or document.section != section:
                continue
            generated.append(NavEntry(document.label, f"{slugify(document.label)}.md"))
        if generated:
            merge_nav(DOCS_DIR / section / ".nav.yml", None, generated)

    published_by_asset: dict[str, list[Document]] = {}
    for document in documents:
        if document.asset:
            published_by_asset.setdefault(document.asset, []).append(document)

    for group_id in groups_used:
        group = registry.groups[group_id]
        # Sheet order, not nav order: only used when the line is new.
        ordered = []
        for asset in registry.assets.values():
            if asset.group != group_id or asset.id not in assets_used:
                continue
            published = published_by_asset[asset.id]
            target = _group_nav_target(asset, group, len(published))
            ordered.append(NavEntry(asset.name, target))
        merge_nav(
            DOCS_DIR / group.section / group.id / ".nav.yml", group.label, ordered
        )

    for asset_id, published in published_by_asset.items():
        asset = registry.assets[asset_id]
        group = registry.groups[asset.group]
        nav_path = DOCS_DIR / group.section / group.id / asset_id / ".nav.yml"
        all_rows = _documents_for_asset(registry.documents, asset_id)
        if len(published) < 2:
            # A group with its own index.md can point straight at the SOP.
            # Without one, the first index.md child becomes the group
            # heading's link, so the asset keeps a nav file whose only
            # entry is index.md. The theme draws that as a link, not a caret.
            if _group_has_index(group):
                _drop_asset_nav(nav_path, _owned_nav_targets(all_rows))
            else:
                merge_nav(nav_path, asset.name, [NavEntry(None, "index.md")])
            continue
        home = home_document(registry.documents, asset_id)
        generated = [NavEntry(None, "index.md")]
        for document in published:
            if document.row_number == home.row_number:
                continue
            generated.append(NavEntry(document.label, f"{slugify(document.label)}.md"))
        merge_nav(nav_path, asset.name, generated)


def _group_has_index(group: Group) -> bool:
    return (DOCS_DIR / group.section / group.id / "index.md").is_file()


def _group_nav_target(asset: Asset, group: Group, published_count: int) -> str:
    if published_count >= 2 or not _group_has_index(group):
        return asset.id
    return f"{asset.id}/index.md"


def _owned_nav_targets(rows: list[Document]) -> set[str]:
    return {"index.md", *(f"{slugify(document.label)}.md" for document in rows)}


def _drop_asset_nav(path: Path, owned: set[str]) -> None:
    """Remove a one-document asset's nav file so it does not draw a caret.

    A target this sync did not generate means the file has a hand-written
    child. Leave it in place and stop, rather than deleting that line.
    """
    if not path.is_file():
        return
    _, entries = load_nav(path)
    foreign = [entry.target for entry in entries if entry.target not in owned]
    if foreign:
        rel = path.relative_to(REPO_ROOT)
        raise RegistryError(
            f"{rel}: nav lists {foreign[0]!r}, which this sync did not generate"
        )
    path.unlink()


def _page_title(page_path: Path) -> str | None:
    if not page_path.is_file():
        return None
    for line in page_path.read_text().splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def sync_document(
    document: Document,
    registry: Registry,
    quiet: bool,
    state: SyncState | None,
) -> SyncStatus:
    rel = document_rel(document, registry)
    page_path = DOCS_DIR / rel
    pdf_path = PDFS_DIR / pdf_rel(rel)
    name = f"{document.asset}/{document.label}" if document.asset else document.label
    section = (
        registry.groups[registry.assets[document.asset].group].section
        if document.asset
        else document.section
    )
    preview_url = f"https://docs.google.com/document/d/{document.doc_id}/preview"
    md_url = f"https://docs.google.com/document/d/{document.doc_id}/export?format=md"
    resp = fetch_url(md_url)
    md_digest = hashlib.sha1(resp.content).hexdigest()
    remembered = state.path(document.doc_id) if state is not None else None
    if (
        state is not None
        and state.export_sha1(document.doc_id) == md_digest
        and remembered == rel
        and page_path.is_file()
        and pdf_path.is_file()
        and _page_title(page_path) == document.title
    ):
        return SyncStatus.UNCHANGED

    markdown = ALT_BOILERPLATE_RE.sub("", resp.text)
    docx_url = (
        f"https://docs.google.com/document/d/{document.doc_id}/export?format=docx"
    )
    docx_media = load_docx_media(fetch_url(docx_url).content)
    body = clean_body(markdown)
    body, upgrade_note = extract_images(
        body, page_path.parent / "img", page_path.parent, docx_media
    )
    pdf_href = pdf_path.relative_to(page_path.parent, walk_up=True).as_posix()
    body_changed = existing_body(page_path) != body
    page_changed = write_if_changed(
        page_path,
        build_page(
            document.title,
            preview_url,
            pdf_href,
            download_filename(document.title),
            body,
            front_matter=existing_front_matter(page_path),
        ),
    )
    if body_changed or not pdf_path.exists():
        pdf_url = (
            f"https://docs.google.com/document/d/{document.doc_id}/export?format=pdf"
        )
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(fetch_url(pdf_url).content)

    if state is not None and page_path.is_file() and pdf_path.is_file():
        state.remember(
            document.doc_id, section=section, name=name, sha1=md_digest, path=rel
        )

    if not page_changed:
        if not quiet:
            print(f"  {name}: unchanged")
        return SyncStatus.UNCHANGED

    print(f"  {name}: WROTE {page_path.relative_to(REPO_ROOT)}")
    if upgrade_note:
        print(f"    {upgrade_note}")
    warn_dropped_images(name, body)
    return SyncStatus.SYNCED


def fetch_registry() -> Registry:
    tables = {
        tab: fetch_url(sheet_csv_url(gid)).text for tab, gid in REGISTRY_GIDS.items()
    }
    return load_registry(tables)


def sync_all(
    args: argparse.Namespace,
    quiet: bool = False,
    state: SyncState | None = None,
) -> Counter[SyncStatus]:
    if state is None:
        state = load_sync_state()
    registry = fetch_registry()
    if args.group and args.group not in registry.groups:
        raise RegistryError(f"--group {args.group!r} is not a groups.id")
    if args.asset and args.asset not in registry.assets:
        raise RegistryError(f"--asset {args.asset!r} is not an assets.id")
    published = published_documents(registry, args.audience)
    selected = select_documents(
        published, registry, group=args.group, asset=args.asset, only=args.only
    )
    counts: Counter[SyncStatus] = Counter()
    if not selected:
        save_sync_state(state)
        return counts
    # Nav follows the whole audience, not the download filter, so a title
    # or label edit lands even when one doc is re-synced.
    for document in selected:
        counts[sync_document(document, registry, quiet, state)] += 1
    merge_published_nav(registry, published)
    save_sync_state(state)
    if not quiet:
        print(f"  {summarize(counts)}")
    return counts


def summarize(counts: Counter[SyncStatus]) -> str:
    return ", ".join(f"{status.value} {counts[status]}" for status in SyncStatus)


def watch(args: argparse.Namespace, interval: float) -> int:
    state = load_sync_state()
    print(f"Watching every {interval:g}s — Ctrl+C to stop")
    try:
        while True:
            try:
                totals = sync_all(args, quiet=True, state=state)
            except requests.RequestException as exc:
                print(f"[{time.strftime('%H:%M:%S')}] error: {exc} — will retry")
            except RegistryError as exc:
                print(f"[{time.strftime('%H:%M:%S')}] {exc}")
                return 1
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
        "--audience",
        default="public",
        choices=sorted(AUDIENCES),
        help="publish documents with this audience (default: public)",
    )
    parser.add_argument("--group", help="limit downloads to one groups.id")
    parser.add_argument("--asset", help="limit downloads to one assets.id")
    parser.add_argument("--only", help="limit downloads to documents with this label")
    parser.add_argument(
        "--watch",
        nargs="?",
        const=DEFAULT_WATCH_INTERVAL,
        type=float,
        metavar="SECONDS",
        help=f"re-sync every SECONDS (default {DEFAULT_WATCH_INTERVAL:g}) "
        "until Ctrl+C; pair with `zensical serve` for a live preview",
    )
    args = parser.parse_args()

    if args.watch is not None:
        return watch(args, max(args.watch, MIN_WATCH_INTERVAL))

    try:
        totals = sync_all(args)
    except RegistryError as exc:
        print(exc, file=sys.stderr)
        return 1
    if totals[SyncStatus.SYNCED] + totals[SyncStatus.UNCHANGED] == 0:
        print("No syncable documents matched.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
