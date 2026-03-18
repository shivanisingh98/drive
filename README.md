# Google Drive Consolidator

**A CLI tool that scans multiple Google Drive accounts, detects duplicate files across them, and consolidates everything into a single primary drive.**

Built to solve a real problem: years of iPhone photo backups, work documents, and shared files scattered across 4 Google accounts — with no native way to deduplicate across account boundaries.

---

## The Problem

Google makes it easy to accumulate accounts. A personal Gmail, a work Workspace account, an old university account, a family-shared account. Each one backing up photos from the same phone, receiving the same shared documents, downloading the same attachments.

There's no built-in way to see across these silos. Google Takeout can export, but it doesn't deduplicate. Third-party tools want you to download everything locally — impractical when you're looking at 200GB+ spread across accounts with different storage tiers.

**This tool works entirely through the Google Drive API.** Files are compared using Drive's native MD5 checksums (no downloads needed for detection), transferred server-side where possible, and duplicates are trashed — not permanently deleted — so nothing is irreversible.

---

## How It Works

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  Personal    │  │    Work     │  │ Old Account │  │   Backup    │
│  (primary)   │  │ (secondary) │  │  (source)   │  │  (source)   │
└──────┬───────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                 │                │                 │
       └────────┬────────┴────────┬───────┴─────────┬──────┘
                │                 │                  │
         ┌──────▼──────┐  ┌──────▼───────┐  ┌──────▼──────┐
         │   Scan &    │  │  Deduplicate │  │ Consolidate │
         │   Index     │──▶  (MD5 hash)  │──▶  & Clean up │
         └─────────────┘  └──────────────┘  └─────────────┘
```

**Three commands, progressive trust:**

| Command | What it does | Modifies anything? |
|---|---|---|
| `scan` | Indexes every file across all accounts, shows totals | No |
| `analyze` | Finds duplicates, calculates waste, previews the consolidation plan | No |
| `consolidate` | Executes the plan — transfers unique files, trashes duplicates | Yes (with confirmation) |

---

## Key Design Decisions

### Two-phase duplicate detection
Google Drive provides native MD5 checksums for uploaded files — no need to download anything. For files without checksums (Google Docs, Sheets), the tool falls back to filename + file size matching. This covers both binary files and cloud-native documents.

### Keeper selection priority
When duplicates span multiple accounts, the tool keeps the copy on your primary drive (avoiding unnecessary transfers), falls back to secondary, then picks the oldest file by creation date. This minimizes data movement and preserves original metadata.

### Space-aware overflow
The tool tracks remaining free space on the primary drive during execution. If a file won't fit, it automatically overflows to the secondary drive. No silent failures, no partial transfers.

### Non-destructive by default
Duplicates are trashed, not permanently deleted. Google Drive retains trashed files for 30 days. The `analyze` command is a pure dry-run. The `consolidate` command requires explicit confirmation. Every irreversible action has a safety net.

### Folder structure preservation
Transferred files maintain their original directory hierarchy, reconstructed under a `Consolidated Media/` folder on the destination drive. A photo at `Old Account/Photos/2023/vacation/img_001.jpg` lands at `Primary/Consolidated Media/Photos/2023/vacation/img_001.jpg`.

---

## Architecture

```
drive_consolidator/
├── cli.py             # Command routing, config validation, output formatting
├── auth.py            # Multi-account OAuth with token caching & refresh
├── scanner.py         # Drive indexing with folder path reconstruction
├── dedup.py           # Two-phase duplicate detection (MD5 + name/size fallback)
└── consolidator.py    # Plan builder, file transfer, safe deletion
```

**~950 lines of Python.** No database, no local file storage, no background services. Stateless except for cached OAuth tokens.

| Dependency | Why |
|---|---|
| `google-api-python-client` | Drive API v3 — file listing, transfers, metadata |
| `google-auth-oauthlib` | Browser-based OAuth flow for desktop apps |
| `click` | CLI framework with subcommands and flags |
| `rich` | Progress bars, formatted tables, colored output |

---

## Quick Start

```bash
# 1. Set up Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Add your Google OAuth credentials (see Setup below)
mkdir credentials
cp ~/Downloads/client_secret_*.json credentials/oauth_client.json

# 3. Configure accounts
cp config.example.json config.json
# Edit config.json with your account names and roles

# 4. Dry-run first — always
python -m drive_consolidator.cli analyze

# 5. Execute when the plan looks right
python -m drive_consolidator.cli consolidate
```

---

## Setup

### Google Cloud credentials (one-time, ~5 minutes)

You need **one** OAuth client — it works for all accounts.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project
2. Enable the **Google Drive API** (APIs & Services → Library)
3. Configure the **OAuth consent screen** (External, add your email addresses as test users)
4. Create an **OAuth 2.0 Client ID** (Desktop app) and download the JSON

### Configuration

```json
{
  "accounts": [
    { "name": "personal",    "credentials_file": "credentials/oauth_client.json", "role": "primary"   },
    { "name": "work",        "credentials_file": "credentials/oauth_client.json", "role": "secondary"  },
    { "name": "old-account", "credentials_file": "credentials/oauth_client.json", "role": "source"     },
    { "name": "backup",      "credentials_file": "credentials/oauth_client.json", "role": "source"     }
  ]
}
```

**Roles:**
- **`primary`** — Destination for all consolidated files. Exactly one required.
- **`secondary`** — Overflow when primary runs out of space. Optional.
- **`source`** — Drives to scan and pull unique files from. Duplicates here get trashed.

### First-run authentication

On the first run, the tool opens your browser once per account for OAuth consent. Sign into the correct Google account each time. Tokens are cached in `tokens/` — subsequent runs are instant.

---

## Usage

```bash
# See what's on each drive
python -m drive_consolidator.cli scan

# Find duplicates and preview the plan (read-only)
python -m drive_consolidator.cli analyze

# Execute the consolidation
python -m drive_consolidator.cli consolidate

# Skip the confirmation prompt
python -m drive_consolidator.cli consolidate --yes

# Use a custom config
python -m drive_consolidator.cli analyze -c ~/my-config.json
```

---

## Safety Guarantees

- **`analyze` is read-only** — run it as many times as you want, nothing changes
- **`consolidate` requires confirmation** — shows the full plan before asking "Proceed?"
- **Duplicates are trashed, not deleted** — recoverable from Drive's trash for 30 days
- **Folder structure is preserved** — files land in the same directory hierarchy on the destination
- **Failures don't cascade** — if one transfer fails, the tool continues and reports failures at the end
- **Rate-limited** — built-in delays between API calls to stay within Google's quotas

---

## Built With

Python 3.11 / Google Drive API v3 / Click / Rich
