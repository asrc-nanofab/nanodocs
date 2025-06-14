import pandas as pd
import requests
import os
import re

# Paste your export CSV URL here
sheet_csv_url = "https://docs.google.com/spreadsheets/d/1MIDhZcYGNO53ZC_TXH3RczhNWxavBpAUXlCD3oSKD4o/export?format=csv&gid=921683470"

# Read the CSV into a DataFrame
df = pd.read_csv(sheet_csv_url)

# Set this to the exact column name with the PDF URLs
pdf_column = "PDF Link"  # e.g., 'PDF Link'
document_name_column = "Document Name"  # Column containing the tool names

output_folder = "../docs/assets/pdfs/chem"
os.makedirs(output_folder, exist_ok=True)

# URL validation pattern
url_pattern = re.compile(r"^https?://")

for idx, row in df.iterrows():
    pdf_url = row[pdf_column]
    if pd.isna(pdf_url):
        continue
    if not url_pattern.match(str(pdf_url)):
        print(f"Skipping non-URL value: {pdf_url}")
        continue
    try:
        # Get the tool name and clean it for use as a filename
        document_name = str(row[document_name_column]).strip()
        # Replace spaces with underscores
        document_name = document_name.replace(" ", "_")
        # Replace any invalid filename characters with underscores
        document_name = re.sub(r'[<>:"/\\|?*]', "_", document_name)
        filename = f"{document_name}.pdf"
        filepath = os.path.join(output_folder, filename)
        print(f"Downloading {pdf_url} ...")
        resp = requests.get(pdf_url)
        if resp.status_code == 200:
            with open(filepath, "wb") as f:
                f.write(resp.content)
            print(f"Saved: {filepath}")
        else:
            print(f"Failed to download {pdf_url}: {resp.status_code}")
    except Exception as e:
        print(f"Error with {pdf_url}: {e}")
