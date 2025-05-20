# 📁 Nanofab Documentation Structure and Versioning Protocol

This document outlines the standard operating procedure for storing, organizing, and versioning all nanofabrication-related documents using Google Drive and Google Docs.

---

## 📂 Folder Structure

All documents will reside within a **main shared folder** in Google Drive, organized by tool and audience:

```
Nanofab Docs/
├── [TOOL NAME OR ID]/
│   ├── User Docs/
│   │   ├── TOOLID_User_SOP_v1.0
│   │   └── ...
│   ├── Staff Docs/
│   │   ├── TOOLID_Staff_Maintenance_v1.0
│   │   └── ...
│   ├── TOOLID_ChangeLog (Google Sheet or Doc)
│
├── [Another Tool]/
│   └── ...
```

Each tool should have:
- `User Docs`: SOPs and training materials for facility users
- `Staff Docs`: Internal guides, maintenance procedures, troubleshooting
- `ChangeLog`: A log of version updates with summaries

---

## 📄 Document Naming Convention

Use the following naming format:

```
[TOOLID]_[Audience]_[DocumentType]_v[Major.Minor]
```

### Examples:
- `EBL-02_User_SOP_v2.1`
- `RIE-01_Staff_MaintenanceChecklist_v1.0`
- `ALD-03_User_SafetyGuide_v3.2`

- **TOOLID**: Unique short name for each tool (e.g., `SEM-01`, `ALD-03`)
- **Audience**: `User` or `Staff`
- **DocumentType**: SOP, SafetyGuide, Checklist, etc.
- **vX.Y**: Semantic version (e.g., v2.1 = second major version, first minor update)

---

## 📝 Versioning Protocol (Google Docs)

Use **Google Docs' built-in version history** to manage and annotate meaningful changes.

### How to Save a Named Version:
1. Open the Google Doc
2. Go to: **File → Version History → Name current version**
3. Use the format:
   ```
   v2.1 — Updated rinse time; clarified PPE section
   ```
4. Press Enter. This version will now be saved and accessible via:
   **File → Version History → See version history**

> 🔄 Do NOT rename the Google Doc filename for every update.  
> Use named versions instead.

---

## 🛠️ When to Create a New Version

Create a new named version when:
- A procedure step changes
- Safety or chemical information changes
- Equipment configuration changes
- Training or permission access changes

Do **not** create a new version for:
- Typos or formatting
- Clarifying language that doesn't affect procedure

---

## 📌 Additional Guidelines

- File names should only change when the **published version** changes (e.g., from `v2.1` to `v2.2`)
- Keep all versions in the same folder
- Optional: maintain an alias document like `EBL-02_User_SOP_latest` that links to the current official version
- Use the `ChangeLog` document to track updates across all files in the tool folder

---

## ✅ Summary

- Organized by tool → audience → document
- Named with consistent, versioned format
- Version history tracked inside Google Docs (named versions)
- Optional `ChangeLog` per tool folder for transparency

---

# 📁 Transition to Google Workspace for Nanofab Docs

## 🎯 Purpose

This document explains why we are transitioning from a **shared Gmail login** to a more secure, scalable setup using **Google Workspace (Business Standard)** with proper shared access. This will improve:
- Document control and security
- Version tracking by individual
- Stable long-term file ownership
- Ease of collaboration without account sharing

---

## 🧾 Summary of Options Considered

| Option                          | Pros                          | Cons                          |
|---------------------------------|-------------------------------|-------------------------------|
| Shared Gmail login              | Free, simple                  | 🚫 Insecure, violates ToS, no user tracking |
| Google Drive shared folders     | Secure, free with personal Gmail accounts | 🚫 Files still owned by individual users |
| **Google Workspace + Shared Drives** | ✅ Central ownership, access control, scalable | 💲 Requires Business Standard ($12/mo/user) |

---

## ✅ Our New Setup

We are using:
- **1 paid Google Workspace Business Standard account**: `docs@nanofabninjas.com`
- **Shared Drives** created and owned by this account
- All SOPs and documents will be stored in these Shared Drives
- Team members will access content using their **personal Gmail accounts**

This gives us:
- Centralized file ownership (even if staff come/go)
- Role-based permissions (viewer, editor, etc.)
- No more shared login risk

---

## 📂 Shared Drive Structure

Each tool will have a folder inside the Shared Drive:

```
Nanofab Shared Drive/
├── EBL-02/
│   ├── User Docs/
│   ├── Staff Docs/
│   └── EBL-02_ChangeLog
├── ALD-03/
│   └── ...
```

---

## 🛠️ How to Set Up (Admin Instructions)

1. Create a Google Workspace account at: [https://workspace.google.com](https://workspace.google.com)
2. Select **Business Standard** plan ($12/mo)
3. Use your domain or get one during sign-up (optional)
4. After setup:
   - Go to **Google Drive → Shared Drives → Create Drive**
   - Name it something like `Nanofab Docs`
   - Create folders for each tool inside

5. Invite team members to the Shared Drive by their **personal Gmail addresses**, and assign roles:
   - Viewer (read-only)
   - Commenter (can suggest changes)
   - Editor (can make changes)
   - Manager (admin rights)

---

## 👩‍🔬 Staff Instructions

Dear team,

We are moving away from sharing a single Google login. Each of you will now use your **own Gmail address** to access our documentation.

### 🔑 Here's What You Need to Do:

1. Make sure you have a personal Gmail account.
2. You will receive an invite to the **"Nanofab Docs" Shared Drive** from `docs@nanofabninjas.com`.
3. Accept the invite and bookmark the Shared Drive for easy access:
   - Go to [https://drive.google.com/drive/shared-drives](https://drive.google.com/drive/shared-drives)
   - Look for “Nanofab Docs”
4. You’ll be given the appropriate level of access (View / Edit / Comment).
5. Do **not** make copies of files unless requested.
6. All edits will now show **your name**, which helps us track changes and improve transparency.

---

## 🚦 Why This Change?

- We can manage permissions safely and professionally
- Edits will be tracked by person and timestamp
- Files are protected even if a staff member leaves
- It's compliant with Google’s terms of service

---

## 📬 Questions?

Please contact `docs@nanofabninjas.com` if:
- You didn't receive your invite
- You’re unsure of your access level
- You need help accessing a document


