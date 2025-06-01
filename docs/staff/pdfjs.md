# 🧩 Embedding PDFs in MkDocs with PDF.js

This guide explains how to install and use [PDF.js](https://mozilla.github.io/pdf.js/) to display PDFs inline in your MkDocs site using a clean viewer — without relying on browser rendering.

---

## ✅ Folder Layout

Assume your `docs/` folder has:

```
docs/
├── assets/
│   ├── pdfs/             ← put your PDFs here
│   └── pdfjs/            ← we will install PDF.js here
│       ├── build/
│       └── web/
│           └── viewer.html
```

---

## 📥 Step-by-Step Installation Instructions (WSL2 or Windows)

### 1. Download PDF.js

- Go to: [https://github.com/mozilla/pdf.js/releases](https://github.com/mozilla/pdf.js/releases)
- Download: `pdfjs-<version>-dist.zip` (e.g., `pdfjs-5.2.133-dist.zip`)
- Extract it

You will see:
```
pdfjs/
├── build/
├── web/
```

---

### 2. Copy Required Files into MkDocs

From the extracted folder, copy into your project:

```bash
# Inside your project root
mkdir -p docs/assets/pdfjs
cp -r ~/Downloads/pdfjs-*/build docs/assets/pdfjs/
cp -r ~/Downloads/pdfjs-*/web docs/assets/pdfjs/
```

Make sure the following file exists:
```
docs/assets/pdfjs/web/viewer.html
```

---

### 3. Place Your PDFs

Put your PDF files in:

```
docs/assets/pdfs/
```

For example:
```
docs/assets/pdfs/Aluminum_Etch_SOP.pdf
```

---

## 🧪 Test the Viewer in Browser

Start your MkDocs dev server:

```bash
mkdocs serve
```

Then test these URLs:

- Viewer:  
  `http://127.0.0.1:8000/assets/pdfjs/web/viewer.html`

- Direct PDF:  
  `http://127.0.0.1:8000/assets/pdfs/Aluminum_Etch_SOP.pdf`

- Viewer with embedded PDF:  
  `http://127.0.0.1:8000/assets/pdfjs/web/viewer.html?file=/assets/pdfs/Aluminum_Etch_SOP.pdf`

---

## ✅ Embed in Markdown

Use this code block in any `.md` file:

```html
<iframe src="/assets/pdfjs/web/viewer.html?file=/assets/pdfs/Aluminum_Etch_SOP.pdf"
        width="100%" height="800px" style="border: none;"></iframe>
```

---

## ⚙️ Optional Viewer Tweaks

- Hide sidebar:
  ```html
  ?file=/...pdf#pagemode=none
  ```

- Start on page 3:
  ```html
  ?file=/...pdf#page=3
  ```

- Zoom to 150%:
  ```html
  ?file=/...pdf#zoom=150
  ```

Example:
```html
<iframe src="/assets/pdfjs/web/viewer.html?file=/assets/pdfs/Aluminum_Etch_SOP.pdf#pagemode=none&zoom=100"
        width="100%" height="800px" style="border: none;"></iframe>
```

---

## 🧼 GitHub Pages Notes

If you deploy using GitHub Pages, and your site URL is something like:

```
https://yourname.github.io/nanonotes/
```

Then you must prefix all paths with `/nanonotes/`, like:

```html
<iframe src="/nanonotes/assets/pdfjs/web/viewer.html?file=/nanonotes/assets/pdfs/Aluminum_Etch_SOP.pdf"
        width="100%" height="800px" style="border: none;"></iframe>
```

Alternatively, in `mkdocs.yml`, set:

```yaml
site_url: https://yourname.github.io/nanonotes
```

---

## 🧠 Troubleshooting

- 404? → Check for exact filename, spaces, capitalization
- Viewer loads but no PDF? → Wrong path in `file=...`
- `pdf.mjs` not found? → You forgot to copy the `build/` folder

---

End of guide.

