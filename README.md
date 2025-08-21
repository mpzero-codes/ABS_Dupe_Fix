# Audiobookshelf Duplicate Checker & Pruner

A Python CLI that **finds duplicate books** in [Audiobookshelf](https://github.com/advplyr/audiobookshelf), **tags** them, and can optionally **prune** (delete) extra copies—with **safety rails** and a **clear, library-by-library summary**.

> Default behavior is **dry-run**. No changes are made unless you set `apply=true` in the INI or pass `--apply` on the CLI.

---

## Table of Contents
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Getting your ABS URL & Token](#getting-your-abs-url--token)
- [Quick Start](#quick-start)
- [Config File Discovery](#config-file-discovery)
- [INI Configuration (All Options)](#ini-configuration-all-options)
- [CLI Flags (Override INI)](#cli-flags-override-ini)
- [Duplicate Detection](#duplicate-detection)
- [Tagging Behavior](#tagging-behavior)
- [Prune Workflow (Interactive or Auto)](#prune-workflow-interactive-or-auto)
- [Filesystem Actions & Safety Rails](#filesystem-actions--safety-rails)
- [Examples](#examples)
- [Output & Summary](#output--summary)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [Contributing](#contributing)
- [License](#license)

---

## Features
- Scan one or more **book** libraries by **name**, **ID**, or **glob**, or use `ALL` to scan every book library.
- Group potential duplicates by **title**, **title+author**, or **title+series** (respects `titleIgnorePrefix` by default).
- Tag duplicates with a configurable tag (default: `Duplicate`). Optionally tag **all copies**, including the one you’re keeping.
- **Prune**: interactively choose which format to keep, or run fully automatic with `--assume-yes` and `preferred_formats`.
- Safe filesystem handling:
  - `delete_files = off | trash | remove`
  - Operations limited to `allow_roots`
  - Optional `path_map` to translate Docker container paths → host paths
- Cleans the duplicate tag on the **kept copy** when auto-pruning is used.
- Clear, **library-by-library summary** of actions (or planned actions in dry-run).

---

## Requirements
- Python 3.9+
- `pip install requests`
- Audiobookshelf reachable via HTTP(S) and an API token

---

## Installation

**Windows**
```powershell
winget install Python.Python.3.11
py -m pip install --upgrade pip requests
```

**macOS**
```bash
# If needed: brew install python
python3 -m pip install --upgrade pip requests
```

**Linux**
```bash
sudo apt-get install -y python3 python3-pip   # Debian/Ubuntu family
python3 -m pip install --upgrade pip requests
```

---

## Getting your ABS URL & Token
- **base_url** is whatever you use to access Audiobookshelf, e.g. `http://localhost:13378` or `https://abs.mydomain.com`.
- **token** is an API token from your ABS account. See the ABS docs/UI for creating a token (wording/placement can differ by version).  
  You can set it in the INI (`token = ...`) or export it as an environment variable `ABS_TOKEN`.

---

## Quick Start
```bash
# 1) Copy & edit config
cp tag_dupes.ini tag_dupes.local.ini
# edit: base_url, token
# (optional) set libraries = ALL (or a comma list of names/IDs)
# set allow_roots and path_map if you plan to move/delete files

# 2) Dry-run (recommended first)
python tag_dupes.py --config tag_dupes.local.ini --prune --assume-yes --delete-files=trash

# 3) Apply changes (after reviewing dry-run output)
python tag_dupes.py --config tag_dupes.local.ini --prune --assume-yes --delete-files=trash --apply
```

---

## Config File Discovery
The script will read the first existing file from:
1. `--config <path>` (explicit)
2. `$ABS_TAG_DUPES_CONFIG` (env var)
3. `./tag_dupes.ini`
4. `~/.config/abs-tools/tag_dupes.ini`

**CLI flags override INI values.**

---

## INI Configuration (All Options)

> All keys live under a single `[default]` section.

| Key | Type / Values | Default | Description | Example |
|-----|----------------|---------|-------------|---------|
| `base_url` | URL | **required** | Your Audiobookshelf URL. | `http://localhost:13378` |
| `token` | string | **required** (or `ABS_TOKEN`) | API token with permissions to list/update/delete library items. | `abcdef...` |
| `libraries` | `ALL` \| comma list of **names/IDs/globs** | *(all book libs)* | Which book libraries to scan. `ALL` includes every book library. Globs like `Audio*` match names. | `libraries = ALL` or `libraries = Main Library, Stephen King, Audio*` |
| `library_id` | comma list of IDs | *(none)* | Explicit library IDs (legacy). If set, these IDs are scanned regardless of names. | `library_id = 7fca..., 92df...` |
| `by` | `title` \| `title+author` \| `title+series` | `title` | How duplicates are grouped. `title+author` is usually best. | `by = title+author` |
| `case_sensitive` | bool | `false` | Whether matching/grouping is case-sensitive. | `case_sensitive = true` |
| `no_ignore_prefixes` | bool | `false` | If `true`, **do not** use `titleIgnorePrefix` from ABS metadata when grouping. | `no_ignore_prefixes = true` |
| `tag` | string | `Duplicate` | Tag to add to duplicates. | `tag = Dupe` |
| `tag_all` | bool | `false` | If `true`, tag **every** copy in a duplicate set (including the kept copy). | `tag_all = true` |
| `prune` | bool | `false` | Enable deletion workflow. | `prune = true` |
| `assume_yes` | bool | `false` | If `true`, no prompts; the **first match** in `preferred_formats` is kept automatically. | `assume_yes = true` |
| `preferred_formats` | comma list | *(empty)* → falls back to `m4b, mp3` | Priority list used when `assume_yes=true`. First format present wins. | `preferred_formats = m4b, mp3, flac` |
| `apply` | bool | `false` | If `true` (or `--apply`), **perform** changes. Otherwise it’s a dry-run. | `apply = true` |
| `delete_files` | `off` \| `trash` \| `remove` | `off` | What to do with the **filesystem folder** of each **removed** ABS item. | `delete_files = trash` |
| `trash_dir` | path | OS-dependent default | Target directory if `delete_files = trash`. | `/mnt/user/.abs-trash` |
| `allow_roots` | comma list of absolute paths | *(empty → file ops skipped with warning when enabled)* | Safety rail. File ops (trash/remove) only occur under these roots. | `allow_roots = /mnt/user/audiobooks, /data/audiobooks` |
| `path_map` | comma list of `src=dest` | *(none)* | Translate **container**-style prefixes to **host** paths **before** safety checks. | `path_map = /audiobooks=/mnt/user/audiobooks, /books=/mnt/user/audiobooks` |
| `insecure` | bool | `false` | Skip TLS verification (self-signed certs). | `insecure = true` |
| `clean_tags_after_prune` | bool | `true` | When **auto**-pruning (`assume_yes=true`), remove the duplicate tag from the **kept copy**. | `clean_tags_after_prune = true` |

### Example `tag_dupes.ini`
```ini
[default]
base_url = http://localhost:13378
token = REPLACE_ME_WITH_ABS_API_TOKEN

libraries = ALL                     ; or: Main Library, Stephen King, Audio*
by = title+author                   ; recommended for most users
tag = Duplicate
tag_all = true

prune = true
assume_yes = true
preferred_formats = m4b, mp3
apply = false                       ; dry-run by default

delete_files = trash                ; off | trash | remove
trash_dir = /mnt/user/.abs-trash

allow_roots = /mnt/user/audiobooks
; path_map = /audiobooks=/mnt/user/audiobooks, /books=/mnt/user/audiobooks

; case_sensitive = false
; no_ignore_prefixes = false
; insecure = false
; clean_tags_after_prune = true
```

---

## CLI Flags (Override INI)

| Flag | Value | Maps to INI | Notes |
|------|-------|-------------|-------|
| `--config PATH` | path | *(n/a)* | Explicit INI to load. |
| `--base-url URL` | string | `base_url` | Required if not in INI. |
| `--token TOKEN` | string | `token` | Or set env var `ABS_TOKEN`. |
| `--libraries "A, B, C"` | list | `libraries` | Names/IDs/globs; or `ALL`. |
| `--library-id ID` | repeatable | `library_id` | Explicit IDs. |
| `--tag TEXT` | string | `tag` | |
| `--apply` | flag | `apply` | Perform changes (else dry-run). |
| `--insecure` | flag | `insecure` | Skip TLS verify. |
| `--case-sensitive` | flag | `case_sensitive` | |
| `--by {title,title+author,title+series}` | enum | `by` | |
| `--tag-all` | flag | `tag_all` | Tag all copies (including kept). |
| `--no-ignore-prefixes` | flag | `no_ignore_prefixes` | Don’t use `titleIgnorePrefix`. |
| `--preferred-formats "m4b, mp3"` | list | `preferred_formats` | Priority when `--assume-yes`. |
| `--prune` | flag | `prune` | Enable deletion flow. |
| `--assume-yes` | flag | `assume_yes` | No prompts; prefer `preferred_formats`. |
| `--delete-files {off,trash,remove}` | enum | `delete_files` | Filesystem action for removed items. |
| `--trash-dir PATH` | path | `trash_dir` | Destination for `trash`. |
| `--allow-roots PATH` | repeatable | `allow_roots` | Safe roots for file ops. |
| `--path-map "src=dest, src2=dest2"` | list | `path_map` | Translate container → host prefixes. |
| `--clean-tags-after-prune` | flag | `clean_tags_after_prune` | Applies when `--assume-yes`. |

---

## Duplicate Detection
Duplicates are items that share the same **grouping key**:
- `title` (default if not set)
- `title+author` *(recommended)*
- `title+series`

The tool normalizes spacing and accents. By default it also respects ABS’s `titleIgnorePrefix` (e.g., “The”, “A”)—disable with `no_ignore_prefixes = true` or `--no-ignore-prefixes`.

**Keeper selection:** Within a duplicate set, the **oldest** item (by `addedAt`) is treated as the “keeper”; the others are candidates to tag (and prune if enabled).

---

## Tagging Behavior
- Adds the configured `tag` (default `Duplicate`) to duplicates.
- If `tag_all = false`, the kept copy is **not** tagged; if `true`, **every** copy gets the tag.
- Tagging uses the ABS batch update API.

---

## Prune Workflow (Interactive or Auto)
When `prune = true`:
- **Interactive:** For each duplicate set, the tool shows the detected formats (e.g., `mp3`, `m4b`) and asks which to keep.
- **Automatic:** When `assume_yes = true`, the first format present in `preferred_formats` is kept without prompting.

After a decision:
1. **Filesystem action** (optional): If `delete_files = trash|remove`, the tool moves or removes the folder of each non-kept copy (limited by `allow_roots`). `path_map` runs **before** safety checks.
2. **ABS delete:** The removed copies are deleted from Audiobookshelf.
3. **Kept tag cleanup (auto mode):** If `clean_tags_after_prune = true` *and* `assume_yes = true`, the duplicate tag is removed from the **kept copy**.

Notes:
- If formats show as **“unknown”**, ABS didn’t return extensions or MIME types. Interactive pruning still works; for auto-prune to be effective, ensure file extensions/MIME types are available.
- File ops are performed **before** ABS delete to avoid the watcher re-adding items immediately.

---

## Filesystem Actions & Safety Rails
- `delete_files = off` → leave files on disk.
- `delete_files = trash` → move to `trash_dir` (keeps directory structure under a trash root).
- `delete_files = remove` → permanent delete.

To avoid accidents:
- **`allow_roots`**: only paths **under** these absolute directories are eligible for file ops. Anything outside is skipped with a note in the summary.
- **`path_map`**: translates container-like prefixes (e.g., `/audiobooks/...`) to your host (e.g., `/mnt/user/audiobooks/...`) *before* checking `allow_roots`.

**Windows example**
```ini
allow_roots = D:\Audiobooks
path_map = /audiobooks=D:\Audiobooks
```

---

## Examples

**Dry-run across all libraries, tag + auto-prune preferring m4b → trash**
```bash
python tag_dupes.py --config tag_dupes.ini --prune --assume-yes --delete-files=trash
```

**Actually apply changes**
```bash
python tag_dupes.py --config tag_dupes.ini --prune --assume-yes --delete-files=trash --apply
```

**Scan only certain libraries (by name; glob allowed)**
```bash
python tag_dupes.py --libraries "Main Library, Audio*"
```

**Use stricter grouping (title+series)**
```bash
python tag_dupes.py --by title+series
```

**Keep interactive prompts (no assume-yes)**
```bash
python tag_dupes.py --prune --delete-files=trash
```

**Permanent delete (be careful)**
```bash
python tag_dupes.py --prune --assume-yes --delete-files=remove --apply
```

---

## Output & Summary
At the end of each run you’ll see a **library-by-library** report, e.g.:
```
Library: Main Library (7fca26a4-...)
  • The Ghostwriter — Julie Clark | formats: mp3×1, m4b×1
    Tagging: added 'Duplicate' to 1 item(s); skipped 1 (already tagged)
    Outcome: would keep **m4b**; would delete 1 other copy/copies.
            Files: would move 1, delete 0, skipped 0.
            Would remove 'Duplicate' tag from kept copy.
```
In **dry-run**, wording uses “would …”. With `--apply`, it reports actual actions.

---

## Troubleshooting & FAQ

**It says “outside allow_roots; not touching files.”**  
Add the path to `allow_roots` or add a `path_map` rule so the path is translated into a location under `allow_roots`.

**Formats are “unknown”. Why?**  
ABS didn’t provide extensions or MIME types for those items. Interactive pruning still works. For auto-prune (`assume_yes=true`) to be useful, ensure your files have recognizable extensions or MIME types in ABS.

**Nothing changed.**  
You’re likely in **dry-run**. Set `apply = true` in INI or pass `--apply`.

**Where does trash go?**  
Controlled by `trash_dir`. The tool mirrors subpaths under it, and appends a timestamp if a path already exists.

**Can I revert?**  
If you used `trash`, move folders back from `trash_dir` and rescan in ABS. There’s no “undo” for permanent deletes.

---

## Contributing
PRs welcome—especially improvements to format detection, new summary outputs (`--summary-md` / `--summary-json`), and more safety checks.

## License
MIT