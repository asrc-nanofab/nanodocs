# Setting up Mkdocs (with Material Theme)

## Embedding PDFs with PDF.js

Embedding PDFs and having them render properly requires soem javascript add-in magic.  In particular we use PDF.js from Mozilla.  You can find it in the Github repo at [https://github.com/mozilla/pdf.js](https://github.com/mozilla/pdf.js)

To install it in Mkdocs is very simple, and does not require any installation of javascript at all.  This is because everything runs client-side in the browser with the mkdocs website.  

However, you do need to include the `/build` and `/web` directories within the mkdocs directory.  I will tell you how I install it to keep things separate.

## Installing PDF.js

1. Goto the github site to download a zip file of the latest release.  This can be found by going to [https://github.com/mozilla/pdf.js/releases](https://github.com/mozilla/pdf.js/releases) and downloading the `Assets` tab of the most recent stable release.  (It will have the name format of `pdfjs-x.y.z-dist.zip`.  As of the writing of this post, I downloaded `pdfjs-5.2.133-dist.zip`)

2. Extract the files from the zip file.  There shoud be two folders with many files in each.  Very important is to verify that the `viewer.html` is in the `web` folder.  The downloaded file structure will look like the image below.  

```bash
pdfjs/
├── build/
│   └── pdf.js
├── web/
│   ├── viewer.html
│   └── viewer.js
│   └── ...
```

3. If you do not already have an `assets` folder inside of your `/docs` directory, put one there now.  I then have the following hierarchy:

```bash
project-root/
├── mkdocs.yml
├── docs/
│   ├── index.md  ← homepage for your MkDocs site
│   ├── README.md  ← optional, for internal notes
│   ├── assets/
│   │   ├── PDFs/
│   │   │   ├── sample_pdf1.pdf
│   │   │   ├── sample_pdf2.pdf
│   │   │   └── data_sheet.pdf
│   │   ├── PDFJS/  
│   │   │   ├── build/
│   │   │   │   └── pdf.js
│   │   │       ├── ...
│   │   │   └── web/
│   │   │       ├── viewer.html
│   │   │       ├── viewer.js
│   │   │       ├── ...
│   │   └── Images/
│   ├── intro-guide/
│   │   ├── index.md
│   │   ├── getting_started.md
│   │   └── site_structure_explained.md
│   ├── example-folder/
│   │   ├── index.md
│   │   ├── example_file1.md
│   │   └── example_file2.md
│   ├── ...
```

4. Now wherever you want a PDF to be rendered in one of your Markdown documents, you will need to add the following relative link. For example, let us say we want to embed a data sheet into example file one. We would need to write the following `iframe` html tag path:

```md
 <iframe 
   src="/[project-root]/assets/pdfjs/web/viewer.html?file=/[project-root]/assets/pdfs/data_sheet.pdf" 
   width="100%" 
   height="1000px" 
   style="border: none;"></iframe>
```

**NOTE:**  You will see that I put the full path name to the PDF directory, in case I move the file, the iframe willl still load properly.  

5. There is nothing else to do to embed PDFs into your markdown documents. No installation.  Everything is done by properly writing the path to the PDFJS directory and the `viewer.html` as well as the path to the PDF file itself.  

## Formatting the Navagation side panel







