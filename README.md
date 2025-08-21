# Audiobookshelf Duplicate Checker & Pruner

A small Python CLI to **find/tag duplicate books** in Audiobookshelf and (optionally) **prune** them. It prints a **library-by-library** summary that’s easy to read.

> Default is **dry-run**. Nothing changes unless you set `apply=true` in the INI or pass `--apply`.

## Quick start
```bash
python -m pip install --upgrade pip requests
cp tag_dupes.ini tag_dupes.local.ini
# edit tag_dupes.local.ini (base_url, token, allow_roots/path_map)
python tag_dupes.py --config tag_dupes.local.ini --prune --assume-yes --delete-files=trash
# when happy:
python tag_dupes.py --config tag_dupes.local.ini --prune --assume-yes --delete-files=trash --apply
```

### Windows
```powershell
winget install Python.Python.3.11
py -m pip install --upgrade pip requests
py tag_dupes.py --config tag_dupes.ini --prune --assume-yes
```

### macOS
```bash
python3 -m pip install --upgrade pip requests
python3 tag_dupes.py --config tag_dupes.ini --prune --assume-yes
```

### Linux
```bash
sudo apt-get install -y python3 python3-pip   # Debian/Ubuntu family
python3 -m pip install --upgrade pip requests
python3 tag_dupes.py --config tag_dupes.ini --prune --assume-yes
```

## INI keys
- `base_url`, `token` (or env var `ABS_TOKEN`)
- `libraries = ALL` or names/IDs/globs
- `by = title | title+author | title+series`
- `tag = Duplicate`, `tag_all = true|false`
- `prune = true|false`, `assume_yes = true|false`, `preferred_formats = m4b, mp3`
- `apply = true|false` (default false → dry-run)
- `delete_files = off|trash|remove`, `trash_dir = /mnt/user/.abs-trash`
- `allow_roots = /mnt/user/audiobooks`
- `path_map = /audiobooks=/mnt/user/audiobooks, /books=/mnt/user/audiobooks`
- `case_sensitive`, `no_ignore_prefixes`, `insecure`, `clean_tags_after_prune`

## Notes
- If you see “outside allow_roots”, add that path to `allow_roots` or translate it via `path_map`.
- If formats show “unknown”, ABS didn’t return file extensions/MIME types—interact to choose, or ensure files have extensions.
- File ops (trash/remove) happen **before** ABS delete.
# ABS_Dupe_Fix
