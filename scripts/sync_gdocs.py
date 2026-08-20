"""Sync Google Docs into MkDocs pages as Markdown.

Reads the registry spreadsheets (public CSV export), downloads each linked
Google Doc in Markdown, DOCX and PDF formats, cleans up the Markdown, and
writes a site page topped with "Open the Google Doc" (read-only /preview) /
"View PDF" / "Download PDF" buttons. The DOCX is only used to recover
original-resolution images: the Markdown export downscales embedded images
to ~640px.
The PDF is hosted in docs/assets/pdfs/ so "View PDF" opens in the browser's
native viewer instead of forcing a download (Google's export URL sends
Content-Disposition: attachment).

The docs and sheets are link-shared, so no credentials are needed.

Usage:
    uv run python scripts/sync_gdocs.py tools --category Deposition
    uv run python scripts/sync_gdocs.py tools chem policy
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
PDFS_DIR = DOCS_DIR / "assets" / "pdfs"
REQUEST_TIMEOUT = 60

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
# Google Docs TOC entries: full-line links to in-page anchors
TOC_ENTRY_RE = re.compile(r"^\[.*\]\(#.*\)\s*$")
ALT_BOILERPLATE_RE = re.compile(r"AI-generated content may be incorrect\.?")

IMAGE_EXTENSIONS = {"jpeg": "jpg", "svg+xml": "svg"}

# Image-upgrade tuning: only swap in a docx original when it is confidently
# the same picture (aspect + pixel match) and meaningfully larger than the
# ~640px-capped version in the markdown export.
MATCH_THUMB_SIZE = (24, 24)
MATCH_MAX_DISTANCE = 30.0
MATCH_ASPECT_TOLERANCE = 0.05
UPGRADE_MIN_AREA_RATIO = 1.2


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


def best_original(
    md_img: Image.Image, media: list[tuple[bytes, Image.Image]]
) -> bytes | None:
    """Return original-resolution bytes for md_img, or None to keep as is."""
    md_aspect = md_img.width / md_img.height
    best: tuple[float, bytes, Image.Image] | None = None
    for data, img in media:
        if abs(img.width / img.height - md_aspect) > MATCH_ASPECT_TOLERANCE * md_aspect:
            continue
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


def resolve_page_path(section: Section, row: dict[str, str]) -> Path | None:
    """Return the target page path for a sheet row, or None if unmappable."""
    name = row[section.name_column].strip()
    if section.name == "tools":
        category = row.get("Type (Category)", "").strip()
        folder = TOOL_CATEGORY_DIRS.get(category)
        if folder is None:
            print(f"  SKIP {name!r}: no site folder for category {category!r}")
            return None
        filename = TOOL_PAGE_OVERRIDES.get(name, f"{slugify(name)}.md")
        return DOCS_DIR / "tool_sops" / folder / filename
    page_map = CHEM_PAGE_MAP if section.name == "chem" else POLICY_PAGE_MAP
    rel = page_map.get(name)
    if rel is None:
        print(f"  SKIP {name!r}: not in {section.name} page map (Phase B)")
        return None
    return DOCS_DIR / rel


def extract_images(
    markdown: str,
    img_dir: Path,
    page_dir: Path,
    docx_media: list[tuple[bytes, Image.Image]],
) -> str:
    """Decode base64 image definitions into files and rewrite the references.

    The markdown export downscales images to ~640px; where a confidently
    matching original exists in the docx export, that is written instead.
    Files are named by content hash so identical images dedupe and re-runs
    are idempotent.
    """
    defs = {m.group(1): m for m in IMAGE_DEF_RE.finditer(markdown)}
    if not defs:
        return markdown

    img_dir.mkdir(parents=True, exist_ok=True)
    replacements = {}
    upgraded = 0
    for label, match in defs.items():
        subtype, b64 = match.group(2), match.group(3)
        data = base64.b64decode(b64)
        ext = IMAGE_EXTENSIONS.get(subtype, subtype)
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
        filename = f"{hashlib.sha1(data).hexdigest()[:12]}.{ext}"
        (img_dir / filename).write_bytes(data)
        rel = (img_dir / filename).relative_to(page_dir)
        replacements[match.group(0)] = f"[{label}]: {rel.as_posix()}"

    if upgraded:
        print(f"    {upgraded}/{len(defs)} images upgraded to docx originals")
    for old, new in replacements.items():
        markdown = markdown.replace(old, new)
    return markdown


def clean_body(markdown: str) -> str:
    """Strip Google's export artifacts: leading logo, original H1, inline TOC."""
    lines = markdown.splitlines()
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
        if stripped == "Table of Contents" or TOC_ENTRY_RE.match(stripped):
            continue
        # TOC remnants with unresolved Google anchors (e.g. partially bolded
        # entries that escape TOC_ENTRY_RE); "#heading=" is never a valid target
        if "](#heading=" in stripped:
            continue
        out.append(line)
    return "\n".join(out).strip() + "\n"


def build_page(title: str, preview_url: str, pdf_href: str, body: str) -> str:
    pdf_filename = pdf_href.rsplit("/", 1)[-1]
    return (
        "<!-- AUTO-GENERATED by scripts/sync_gdocs.py from the Google Doc "
        "below. Edit the Google Doc, not this file. -->\n\n"
        f"# {title}\n\n"
        f"[:material-file-document-outline: Open the Google Doc]({preview_url})"
        "{ .md-button }\n"
        # Same-tab navigation so the browser back button returns to this page
        f"[:material-file-pdf-box: View PDF]({pdf_href}){{ .md-button }}\n"
        f'[:material-download: Download PDF]({pdf_href}){{ .md-button download="{pdf_filename}" }}\n\n'
        "---\n\n"
        f"{body}"
    )


def existing_title(page_path: Path, fallback: str) -> str:
    """Keep the current page's H1 so on-page titles don't churn."""
    if page_path.exists():
        for line in page_path.read_text().splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return fallback


def sync_row(section: Section, row: dict[str, str]) -> bool:
    name = (row.get(section.name_column) or "").strip()
    pdf_url = (row.get("PDF Link") or "").strip()
    if not name or not pdf_url.startswith("http"):
        return False

    doc_id_match = DOC_ID_RE.search(pdf_url)
    if doc_id_match is None:
        print(f"  SKIP {name!r}: could not parse doc id from {pdf_url}")
        return False
    doc_id = doc_id_match.group(1)

    page_path = resolve_page_path(section, row)
    if page_path is None:
        return False

    preview_url = f"https://docs.google.com/document/d/{doc_id}/preview"

    md_url = f"https://docs.google.com/document/d/{doc_id}/export?format=md"
    print(f"  {name}: downloading markdown ...")
    resp = requests.get(md_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    markdown = ALT_BOILERPLATE_RE.sub("", resp.text)

    docx_url = f"https://docs.google.com/document/d/{doc_id}/export?format=docx"
    resp = requests.get(docx_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    docx_media = load_docx_media(resp.content)

    body = clean_body(markdown)
    body = extract_images(body, page_path.parent / "img", page_path.parent, docx_media)

    pdf_path = pdf_asset_path(section, name)
    print(f"  {name}: downloading pdf ...")
    resp = requests.get(pdf_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(resp.content)
    # Relative href so mkdocs build --strict verifies the PDF exists
    pdf_href = pdf_path.relative_to(page_path.parent, walk_up=True).as_posix()

    title = existing_title(page_path, name)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(build_page(title, preview_url, pdf_href, body))
    print(f"  WROTE {page_path.relative_to(DOCS_DIR.parent)}")
    return True


def sync_section(section: Section, category: str | None, only: str | None) -> int:
    print(f"Section: {section.name}")
    resp = requests.get(section.sheet_csv_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.text)))

    written = 0
    for row in rows:
        if category and row.get("Type (Category)", "").strip() != category:
            continue
        if only and (row.get(section.name_column) or "").strip() != only:
            continue
        if sync_row(section, row):
            written += 1
    print(f"  {written} page(s) written")
    return written


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
    args = parser.parse_args()

    total = 0
    for section_name in args.sections:
        total += sync_section(SECTIONS[section_name], args.category, args.only)
    if total == 0:
        print("Nothing written.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
