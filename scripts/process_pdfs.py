import pandas as pd
import requests
import os
import re

# Paste your export CSV URL here
sheet_csv_url = "https://docs.google.com/spreadsheets/d/1b4RRhKAukj9NrFyiJl_I9vbAUnrgDSy1TeNq2QLKJr4/export?format=csv&gid=477704461"

# Read the CSV into a DataFrame
df = pd.read_csv(sheet_csv_url)

# Set this to the exact column name with the PDF URLs
pdf_column = "pdf link"  # e.g., 'PDF Link'
tool_name_column = "Tool Name"  # Column containing the tool names

output_folder = "pdf_downloads"
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
        tool_name = str(row[tool_name_column]).strip()
        # Replace spaces with underscores
        tool_name = tool_name.replace(" ", "_")
        # Replace any invalid filename characters with underscores
        tool_name = re.sub(r'[<>:"/\\|?*]', "_", tool_name)
        filename = f"{tool_name}_SOP.pdf"
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
