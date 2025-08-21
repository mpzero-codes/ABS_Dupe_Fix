#!/usr/bin/env python3
from __future__ import annotations

"""
Audiobookshelf duplicate tagger & pruner — human-friendly library-by-library summary.
"""

import argparse, configparser, os, sys, time, unicodedata, shutil, platform, fnmatch
from collections import defaultdict, Counter
from typing import Dict, List, Any, Tuple, Optional
import requests

def _bool(v) -> bool:
    if isinstance(v, bool): return v
    return str(v).strip().lower() in ("1","true","yes","on")

def _csv(v) -> List[str]:
    if v is None: return []
    if isinstance(v, list): return v
    return [x.strip() for x in str(v).split(",") if x.strip()]

def _kv_csv(v) -> List[Tuple[str,str]]:
    out = []
    for pair in _csv(v):
        if "=" in pair:
            k, val = pair.split("=", 1)
            out.append((k.strip(), val.strip()))
    return out

def now_suffix() -> str:
    return time.strftime("%Y%m%d-%H%M%S")

def norm(s: str, case_sensitive: bool) -> str:
    if s is None: return ""
    s = " ".join(s.split())
    if not case_sensitive: s = s.lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")
    return s

def get_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def fetch_libraries(base_url: str, token: str, verify_ssl: bool=True) -> List[Dict[str, Any]]:
    r = requests.get(f"{base_url.rstrip('/')}/api/libraries",
                     headers=get_headers(token), timeout=30, verify=verify_ssl)
    r.raise_for_status()
    data = r.json()
    return data.get("libraries") or data

def fetch_library_items(base_url: str, token: str, library_id: str, verify_ssl: bool=True) -> List[Dict[str, Any]]:
    params = {"expanded": 1}
    r = requests.get(f"{base_url.rstrip('/')}/api/libraries/{library_id}/items",
                     headers=get_headers(token), params=params, timeout=120, verify=verify_ssl)
    r.raise_for_status()
    data = r.json()
    items = data.get("libraryItems") or data.get("results") or data
    return [it for it in items if (it.get("media") or {}).get("type") == "book" or it.get("mediaType") == "book"]

def batch_update_tags(base_url: str, token: str, updates: List[Tuple[str, List[str]]],
                      verify_ssl: bool=True, batch_size:int=100) -> int:
    if not updates: return 0
    total = 0
    url = f"{base_url.rstrip('/')}/api/items/batch/update"
    headers = get_headers(token)
    for i in range(0, len(updates), batch_size):
        chunk = updates[i:i+batch_size]
        payload = [{"id": iid, "mediaPayload": {"tags": tags}} for iid, tags in chunk]
        r = requests.post(url, json=payload, headers=headers, timeout=60, verify=verify_ssl)
        if r.status_code >= 400:
            print(f"[ERROR] Batch update failed ({r.status_code}): {r.text}", file=sys.stderr)
            r.raise_for_status()
        try:
            total += int((r.json() or {}).get("updates") or 0)
        except Exception:
            pass
        time.sleep(0.03)
    return total

def delete_item_from_abs(base_url: str, token: str, item_id: str, verify_ssl: bool=True) -> bool:
    r = requests.delete(f"{base_url.rstrip('/')}/api/items/{item_id}",
                        headers=get_headers(token), timeout=30, verify=verify_ssl)
    if r.status_code in (200,204):
        return True
    if r.status_code == 404:
        print(f"[WARN] Item {item_id} already absent in ABS.")
        return True
    print(f"[ERROR] ABS delete failed for {item_id} ({r.status_code}): {r.text}", file=sys.stderr)
    return False

def item_meta(it) -> Dict[str, Any]:
    return (it.get("media") or {}).get("metadata") or {}

def item_title(it) -> str:
    return item_meta(it).get("title") or ""

def title_for_group(it, use_ignore_prefix: bool, case_sensitive: bool) -> str:
    md = item_meta(it)
    t = (md.get("titleIgnorePrefix") if use_ignore_prefix and md.get("titleIgnorePrefix") else md.get("title") or "")
    return norm(t, case_sensitive)

def author_for_group(it, case_sensitive: bool) -> str:
    return norm(item_meta(it).get("authorName") or "", case_sensitive)

def series_for_group(it, case_sensitive: bool) -> str:
    return norm(item_meta(it).get("seriesName") or "", case_sensitive)

def make_key(it, by: str, use_ignore_prefix: bool, case_sensitive: bool) -> str:
    t = title_for_group(it, use_ignore_prefix, case_sensitive)
    if by == "title": return t
    if by == "title+author": return f"{t}||{author_for_group(it, case_sensitive)}"
    if by == "title+series": return f"{t}||{series_for_group(it, case_sensitive)}"
    return t

def current_tags(it) -> List[str]:
    media = it.get("media") or {}
    return list((media.get("tags") if media.get("tags") is not None else it.get("tags")) or [])

def item_added_at(it) -> int:
    return int(it.get("addedAt") or (it.get("media") or {}).get("addedAt") or 0)

def choose_keeper(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return sorted(items, key=item_added_at)[0]

def item_formats(it) -> List[str]:
    fmts: List[str] = []
    for lf in (it.get("libraryFiles") or []):
        if (lf.get("fileType") or "").lower() != "audio":
            continue
        md = lf.get("metadata") or {}
        ext = (md.get("ext") or "").lower().lstrip(".")
        if ext: fmts.append(ext)
        mt = (lf.get("mimeType") or "").lower()
        if "audio/" in mt:
            fmts.append(mt.split("/",1)[1])
        for path_key in ("path","relPath"):
            p = (lf.get(path_key) or md.get(path_key) or "")
            if isinstance(p, str) and "." in p:
                fmts.append(p.lower().rsplit(".",1)[-1])
    if not fmts:
        for tr in ((it.get("media") or {}).get("tracks") or []):
            mt = (tr.get("mimeType") or "").lower()
            if "audio/" in mt:
                fmts.append(mt.split("/",1)[1])
            title = (tr.get("title") or "").lower()
            if "." in title:
                fmts.append(title.rsplit(".",1)[-1])
    normed = []
    for f in fmts:
        if f in ("m4a","mp4"): normed.append("m4a")
        else: normed.append(f)
    seen=set(); out=[]
    for f in normed:
        if f not in seen:
            seen.add(f); out.append(f)
    return out or ["unknown"]

def dominant_format(it) -> str:
    cnt = Counter(item_formats(it))
    return cnt.most_common(1)[0][0]

def _item_folder_from_files(it: Dict[str, Any]) -> Optional[str]:
    p = it.get("path")
    if isinstance(p, str) and p.strip():
        return p
    paths = []
    for lf in (it.get("libraryFiles") or []):
        if (lf.get("fileType") or "").lower() != "audio": continue
        md = lf.get("metadata") or {}
        for path_key in ("path","relPath"):
            fp = lf.get(path_key) or md.get(path_key)
            if isinstance(fp, str) and fp:
                paths.append(os.path.dirname(fp))
    if not paths: return None
    try:
        return os.path.commonpath(paths)
    except Exception:
        return paths[0]

def _apply_path_map(p: str, path_map: List[Tuple[str,str]]) -> str:
    if not p: return p
    for src, dst in path_map:
        if p.startswith(src):
            tail = p[len(src):].lstrip("/\\")
            return os.path.join(dst, tail)
    return p

def _is_within_roots(p: str, roots: List[str]) -> bool:
    if not roots: return True
    try:
        p_real = os.path.realpath(p)
        for r in roots:
            r_real = os.path.realpath(r)
            try:
                if os.path.commonpath([p_real, r_real]) == r_real:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False

def _default_trash_dir() -> str:
    if platform.system().lower().startswith("win"):
        return os.path.join(os.path.expanduser("~"), ".abs-tools", "trash")
    return os.path.join(os.path.expanduser("~/.local/share"), "abs-tools", "trash")

def _move_to_trash(src: str, trash_root: str, roots: List[str]) -> Tuple[bool, str]:
    os.makedirs(trash_root, exist_ok=True)
    rel = None
    for r in roots:
        try:
            if os.path.commonpath([os.path.realpath(src), os.path.realpath(r)]) == os.path.realpath(r):
                rel = os.path.relpath(src, r)
                break
        except Exception:
            continue
    if not rel:
        rel = os.path.basename(src)
    dest = os.path.join(trash_root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        dest = dest + f".{now_suffix()}"
    try:
        shutil.move(src, dest); return True, dest
    except Exception as e:
        print(f"[ERROR] Moving to trash failed: {src} -> {dest}: {e}", file=sys.stderr)
        return False, dest

def _remove_path(src: str) -> bool:
    try:
        if os.path.isdir(src): shutil.rmtree(src)
        else: os.remove(src)
        return True
    except Exception as e:
        print(f"[ERROR] Permanent delete failed: {src}: {e}", file=sys.stderr)
        return False

DEFAULT_LOCATIONS = [
    "./tag_dupes.ini",
    os.path.expanduser("~/.config/abs-tools/tag_dupes.ini"),
]

def load_config(explicit_path: Optional[str]) -> dict:
    cfg = configparser.ConfigParser()
    path = (
        explicit_path
        or os.environ.get("ABS_TAG_DUPES_CONFIG")
        or next((p for p in DEFAULT_LOCATIONS if os.path.exists(p)), None)
    )
    result = {}
    if path and os.path.exists(path):
        cfg.read(path, encoding="utf-8")
        section = "default" if cfg.has_section("default") else cfg.default_section
        g = cfg.get
        result = {
            "base_url": g(section, "base_url", fallback=None),
            "token": g(section, "token", fallback=None),
            "libraries": _csv(g(section, "libraries", fallback=None)),
            "library_id": _csv(g(section, "library_id", fallback=None)),
            "tag": g(section, "tag", fallback=None),
            "apply": _bool(g(section, "apply", fallback=False)),
            "insecure": _bool(g(section, "insecure", fallback=False)),
            "case_sensitive": _bool(g(section, "case_sensitive", fallback=False)),
            "by": g(section, "by", fallback=None),
            "tag_all": _bool(g(section, "tag_all", fallback=False)),
            "no_ignore_prefixes": _bool(g(section, "no_ignore_prefixes", fallback=False)),
            "preferred_formats": _csv(g(section, "preferred_formats", fallback=None)),
            "prune": _bool(g(section, "prune", fallback=False)),
            "assume_yes": _bool(g(section, "assume_yes", fallback=False)),
            "delete_files": g(section, "delete_files", fallback="off").lower(),
            "trash_dir": g(section, "trash_dir", fallback=None),
            "allow_roots": _csv(g(section, "allow_roots", fallback=None)),
            "path_map": _kv_csv(g(section, "path_map", fallback=None)),
            "clean_tags_after_prune": _bool(g(section, "clean_tags_after_prune", fallback=True)),
        }
        result["config_path"] = path
    return result

def resolve_options(cli, cfg):
    token = cli.token or os.environ.get("ABS_TOKEN") or cfg.get("token")
    base_url = cli.base_url or cfg.get("base_url")
    libraries = _csv(cli.libraries) if cli.libraries else (cfg.get("libraries") or [])
    library_id = cli.library_id if cli.library_id else cfg.get("library_id", [])
    tag = cli.tag or cfg.get("tag") or "Duplicate"
    case_sensitive = (cli.case_sensitive if cli.case_sensitive is not None else cfg.get("case_sensitive", False))
    apply = (cli.apply if cli.apply is not None else cfg.get("apply", False))
    verify_ssl = not (cli.insecure if cli.insecure is not None else cfg.get("insecure", False))
    by = cli.by or cfg.get("by") or "title"
    tag_all = (cli.tag_all if cli.tag_all is not None else cfg.get("tag_all", False))
    use_ignore_prefix = not (cli.no_ignore_prefixes if cli.no_ignore_prefixes is not None
                             else cfg.get("no_ignore_prefixes", False))
    preferred_formats = _csv(cli.preferred_formats) if cli.preferred_formats else cfg.get("preferred_formats", [])
    prune = (cli.prune if cli.prune is not None else cfg.get("prune", False))
    assume_yes = (cli.assume_yes if cli.assume_yes is not None else cfg.get("assume_yes", False))
    delete_files = (cli.delete_files or cfg.get("delete_files") or "off").lower()
    if delete_files not in ("off","trash","remove"): delete_files = "off"
    trash_dir = cli.trash_dir or cfg.get("trash_dir") or _default_trash_dir()
    allow_roots = cli.allow_roots if cli.allow_roots else cfg.get("allow_roots", [])
    path_map = _kv_csv(cli.path_map) if cli.path_map else cfg.get("path_map", [])
    clean_tags_after_prune = (cli.clean_tags_after_prune if cli.clean_tags_after_prune is not None
                              else cfg.get("clean_tags_after_prune", True))

    missing = []
    if not base_url: missing.append("--base-url (or base_url in config)")
    if not token: missing.append("--token / $ABS_TOKEN (or token in config)")
    if missing:
        print("Missing required option(s): " + ", ".join(missing), file=sys.stderr)
        sys.exit(2)

    return {
        "base_url": base_url, "token": token,
        "libraries": libraries, "library_id": library_id,
        "tag": tag, "case_sensitive": case_sensitive, "apply": apply, "verify_ssl": verify_ssl,
        "by": by, "tag_all": tag_all, "use_ignore_prefix": use_ignore_prefix,
        "preferred_formats": [f.lower() for f in preferred_formats],
        "prune": prune, "assume_yes": assume_yes,
        "delete_files": delete_files, "trash_dir": trash_dir,
        "allow_roots": allow_roots, "path_map": path_map,
        "clean_tags_after_prune": clean_tags_after_prune
    }

def ask_choice(prompt: str, choices: List[str], default: Optional[str] = None) -> str:
    options = "/".join(choices)
    dflt = f" [{default}]" if default else ""
    while True:
        ans = input(f"{prompt} ({options}){dflt}: ").strip().lower()
        if not ans and default: return default
        if ans in choices: return ans
        print(f"Please type one of: {options}")

def select_libraries(all_libs: List[Dict[str,Any]], wish: List[str], by_ids: List[str]) -> Dict[str,Dict[str,Any]]:
    book_libs = [l for l in all_libs if (l.get("mediaType") or l.get("type")) == "book"]
    if by_ids:
        idset = set(by_ids)
        return {l["id"]: l for l in book_libs if l["id"] in idset}
    if not wish or any(w.upper() == "ALL" for w in wish):
        return {l["id"]: l for l in book_libs}
    chosen = {}
    for lib in book_libs:
        name = lib.get("name","")
        for w in wish:
            if lib["id"] == w or fnmatch.fnmatch(name, w):
                chosen[lib["id"]] = lib
                break
    return chosen

def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", help="Path to INI config")
    known, _ = pre.parse_known_args()

    ap = argparse.ArgumentParser(description="Tag and prune duplicate books in Audiobookshelf")
    ap.add_argument("--config", help="Path to INI config")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--token", default=None)

    ap.add_argument("--libraries", default=None,
                    help="Comma list of library NAMES/IDs (globs allowed); 'ALL' for all book libs")
    ap.add_argument("--library-id", action="append", default=None,
                    help="Explicit library ID(s) (repeatable)")

    ap.add_argument("--tag", default=None, help='Duplicate tag text (default: "Duplicate")')
    ap.add_argument("--apply", action="store_true", default=None, help="Write changes (default: dry run)")
    ap.add_argument("--insecure", action="store_true", default=None, help="Skip TLS verify")
    ap.add_argument("--case-sensitive", action="store_true", default=None)
    ap.add_argument("--by", choices=["title","title+author","title+series"], default=None)
    ap.add_argument("--tag-all", action="store_true", default=None, help="Tag ALL copies, including kept copy")
    ap.add_argument("--no-ignore-prefixes", action="store_true", default=None,
                    help="Do NOT use metadata.titleIgnorePrefix when grouping")

    ap.add_argument("--preferred-formats", default=None, help="Comma-separated format priority, e.g. 'm4b, mp3'")
    ap.add_argument("--prune", action="store_true", default=None, help="Enable deletion workflow")
    ap.add_argument("--assume-yes", action="store_true", default=None, help="Skip prompts; use preferred_formats")

    ap.add_argument("--delete-files", choices=["off","trash","remove"], default=None,
                    help="What to do with files of removed items")
    ap.add_argument("--trash-dir", default=None, help="Where to move deleted items if delete-files=trash")
    ap.add_argument("--allow-roots", action="append", default=None,
                    help="Safe roots to operate within (repeatable)")
    ap.add_argument("--path-map", default=None,
                    help="CSV of src=dest pairs to remap container→host paths")
    ap.add_argument("--clean-tags-after-prune", action="store_true", default=None,
                    help="Remove the duplicate tag from the kept copy after prune (default true)")

    args = ap.parse_args()

    cfg = load_config(known.config or args.config)
    if args.library_id is None: args.library_id = []
    opts = resolve_options(args, cfg)

    stats = defaultdict(int)
    library_breakdown: Dict[str, Dict[str, Any]] = {}
    dup_sets: List[Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]] = []

    def _lb_entries(lib):
        lid = lib["id"]
        if lid not in library_breakdown:
            library_breakdown[lid] = {"name": lib.get("name", lid), "entries": []}
        return library_breakdown[lid]["entries"]

    def _make_entry(group, keeper_id) -> Dict[str, Any]:
        md = (group[0].get("media") or {}).get("metadata") or {}
        fmt_counts = Counter(dominant_format(it) for it in group)
        return {
            "title": md.get("title") or "(no title)",
            "author": md.get("authorName") or "",
            "formats": sorted(fmt_counts.keys()),
            "format_counts": dict(fmt_counts),
            "keeper_id": keeper_id,
            "tag_added": 0,
            "tag_skipped": 0,
            "keep_format": None,
            "to_delete_count": 0,
            "file_moved": 0,
            "file_deleted": 0,
            "file_skipped": 0,
            "skipped_paths": [],
            "abs_deleted": 0,
            "kept_tag_removed": False,
            "dry_run": not opts["apply"],
        }

    if opts["delete_files"] != "off" and not opts["allow_roots"]:
        print("[WARN] delete_files is enabled but allow_roots is empty; file ops will be skipped for safety.", file=sys.stderr)

    try:
        all_libs = fetch_libraries(opts["base_url"], opts["token"], verify_ssl=opts["verify_ssl"])
    except Exception as e:
        print(f"Failed to fetch libraries: {e}", file=sys.stderr); sys.exit(1)
    chosen = select_libraries(all_libs, opts["libraries"], opts["library_id"])
    if not chosen:
        print("No book libraries selected. (Use libraries = ALL or names/IDs)", file=sys.stderr); sys.exit(0)

    stats["libraries_total"] = len([l for l in all_libs if (l.get("mediaType") or l.get("type")) == "book"])
    stats["libraries_scanned"] = len(chosen)

    pending_tag_updates: List[Tuple[str, List[str]]] = []
    tag_text = opts["tag"]

    for lib_id, lib in chosen.items():
        print(f"\n== Library: {lib.get('name', lib_id)} ({lib_id}) ==")
        try:
            items = fetch_library_items(opts["base_url"], opts["token"], lib_id, verify_ssl=opts["verify_ssl"])
        except Exception as e:
            print(f"[ERROR] Failed to fetch items for {lib_id}: {e}", file=sys.stderr); stats["errors"] += 1; continue

        stats["items_total"] += len(items)

        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for it in items:
            key = make_key(it, opts["by"], opts["use_ignore_prefix"], opts["case_sensitive"])
            if key: groups[key].append(it)

        for _, group in groups.items():
            if len(group) <= 1: continue
            stats["dupe_books"] += 1

            keeper = choose_keeper(group)
            keeper_id = keeper["id"]
            print(f"- '{item_title(keeper)}' → {len(group)} copies (keeper {keeper_id})")

            entry = _make_entry(group, keeper_id)
            _lb_entries(lib).append(entry)
            dup_sets.append((lib, group, entry))

            for it in group:
                if not opts["tag_all"] and it["id"] == keeper_id:
                    continue
                tags = current_tags(it)
                if tag_text not in tags:
                    new_tags = tags + [tag_text]
                    print(f"    tag {it['id']} (existing: {tags}) → {new_tags}")
                    entry["tag_added"] += 1
                    if opts["apply"]:
                        pending_tag_updates.append((it["id"], new_tags))
                else:
                    print(f"    skip {it['id']} (already has '{tag_text}')")
                    entry["tag_skipped"] += 1

    if opts["apply"] and pending_tag_updates:
        print(f"\nApplying {len(pending_tag_updates)} tag updates...")
        changed = batch_update_tags(opts["base_url"], opts["token"], pending_tag_updates, verify_ssl=opts["verify_ssl"])
        if changed != len(pending_tag_updates):
            print(f"[INFO] Server reported {changed} item(s) updated.")

    if opts["prune"]:
        if not opts["apply"]:
            print("\n[PRUNE] dry-run only (no deletions). Use --apply to actually delete/move files and remove items.")
        if opts["delete_files"] != "off":
            print(f"[PRUNE] File action: {opts['delete_files']}{' -> trash dir: ' + opts['trash_dir'] if opts['delete_files']=='trash' else ''}")

        preferred = opts["preferred_formats"] or ["m4b","mp3"]
        for lib, group, entry in dup_sets:
            by_fmt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for it in group:
                by_fmt[dominant_format(it)].append(it)
            entry["format_counts"] = {fmt: len(items) for fmt, items in by_fmt.items()}
            fmts = sorted(by_fmt.keys())

            default_fmt = next((f for f in preferred if f in by_fmt), fmts[0] if fmts else None)

            if opts["assume_yes"] and default_fmt:
                chosen_fmt = default_fmt
                print(f"\n[PRUNE] '{entry['title']}': formats {', '.join(fmts) or 'unknown'} -> keeping {chosen_fmt} (auto)")
            else:
                print(f"\n[PRUNE] I found a duplicate book with Title+Author: '{entry['title']}'.")
                human_fmts = ", ".join(fmts[:-1]) + " and " + fmts[-1] if len(fmts) > 1 else (fmts[0] if fmts else "unknown")
                print(f"        You have {human_fmts}. Which would you like to keep?")
                chosen_fmt = ask_choice("Choose", fmts or ["unknown"], default=default_fmt)

            entry["keep_format"] = chosen_fmt
            keep_list = by_fmt.get(chosen_fmt, [])
            if not keep_list:
                continue
            keeper = choose_keeper(keep_list)
            keep_id = keeper["id"]

            to_remove = [it for it in group if it["id"] != keep_id]
            entry["to_delete_count"] = len(to_remove)
            stats["prune_books"] += 1

            for it in to_remove:
                folder = _item_folder_from_files(it)
                if not folder:
                    print(f"    [WARN] Could not determine folder for {it['id']}; skipping file ops.")
                    stats["errors"] += 1
                    continue
                mapped = _apply_path_map(folder, opts["path_map"])
                if opts["delete_files"] == "off":
                    print(f"    [INFO] delete_files=off -> leaving files: {mapped}")
                elif not _is_within_roots(mapped, opts["allow_roots"]):
                    print(f"    [SKIP] {mapped} is outside allow_roots; not touching files.")
                    entry["file_skipped"] += 1
                    if len(entry["skipped_paths"]) < 2:
                        entry["skipped_paths"].append(mapped)
                    stats["files_skipped_outside_roots"] += 1
                elif opts["apply"]:
                    if opts["delete_files"] == "trash":
                        ok, dest = _move_to_trash(mapped, opts["trash_dir"], opts["allow_roots"])
                        print(f"    {'Moved' if ok else 'FAILED move'}: {mapped} -> {dest}")
                        entry["file_moved"] += int(ok)
                        stats["files_moved"] += int(ok)
                        stats["errors"] += int(not ok)
                    elif opts["delete_files"] == "remove":
                        ok = _remove_path(mapped)
                        print(f"    {'Deleted' if ok else 'FAILED delete'}: {mapped}")
                        entry["file_deleted"] += int(ok)
                        stats["files_deleted"] += int(ok)
                        stats["errors"] += int(not ok)
                else:
                    if opts["delete_files"] == "trash":
                        print(f"    [DRY-RUN] Would move to trash: {mapped}")
                        entry["file_moved"] += 1
                    elif opts["delete_files"] == "remove":
                        print(f"    [DRY-RUN] Would delete: {mapped}")
                        entry["file_deleted"] += 1

            for it in to_remove:
                if opts["apply"]:
                    ok = delete_item_from_abs(opts["base_url"], opts["token"], it["id"], verify_ssl=opts["verify_ssl"])
                    print(f"    ABS delete {it['id']}: {'OK' if ok else 'FAILED'}")
                    entry["abs_deleted"] += int(ok)
                    stats["abs_deleted"] += int(ok)
                    stats["errors"] += int(not ok)
                else:
                    print(f"    [DRY-RUN] Would ABS delete {it['id']}")

            if opts["clean_tags_after_prune"] and opts["assume_yes"]:
                survivors = [keeper]
                updates = []
                for s in survivors:
                    tags = [t for t in current_tags(s) if t != opts["tag"]]
                    updates.append((s["id"], tags))
                if opts["apply"]:
                    batch_update_tags(opts["base_url"], opts["token"], updates, verify_ssl=opts["verify_ssl"])
                else:
                    print(f"    [DRY-RUN] Would remove '{opts['tag']}' from kept copy: {', '.join([s['id'] for s in survivors])}")
                entry["kept_tag_removed"] = True
                stats["tag_removed_survivors"] += len(survivors)

    print("\n" + "="*72)
    print("SUMMARY")
    print("-"*72)
    mode = "APPLY (changes performed)" if opts["apply"] else "DRY RUN (no changes)"
    print(f"Mode: {mode}")
    print(f"Libraries scanned: {stats['libraries_scanned']} of {stats['libraries_total']} book libraries")
    print(f"Items scanned: {stats['items_total']}")
    print(f"Books with duplicates: {stats['dupe_books']}")
    print("-"*72)

    if not library_breakdown:
        print("No duplicate books found.")
    else:
        for lib_id, data in library_breakdown.items():
            print(f"\nLibrary: {data['name']} ({lib_id})")
            if not data['entries']:
                print("  No duplicate books.")
                continue
            for e in data['entries']:
                author = f" — {e['author']}" if e['author'] else ""
                if e['format_counts']:
                    parts = []
                    for fmt, cnt in sorted(e['format_counts'].items()):
                        parts.append(f"{fmt}×{cnt}")
                    formats_str = ", ".join(parts)
                else:
                    formats_str = "unknown"
                if set(e['formats']) == {"unknown"}:
                    formats_str = "unknown — ABS didn’t return file extensions or MIME types"
                print(f"  • {e['title']}{author} | formats: {formats_str}")
                if e['tag_added'] or e['tag_skipped']:
                    tagbits = []
                    if e['tag_added']: tagbits.append(f"added '{opts['tag']}' to {e['tag_added']} item(s)")
                    if e['tag_skipped']: tagbits.append(f"skipped {e['tag_skipped']} (already tagged)")
                    print("    Tagging: " + "; ".join(tagbits))
                if opts['prune'] and e.get('keep_format'):
                    if e['dry_run']:
                        line = (f"    Outcome: would keep **{e['keep_format']}**; would delete {e['to_delete_count']} other copy/copies. "
                                f"Files: would move {e['file_moved']}, delete {e['file_deleted']}, skipped {e['file_skipped']}. ")
                        if e['kept_tag_removed']:
                            line += "Would remove 'Duplicate' tag from kept copy."
                        print(line)
                        if e['skipped_paths']:
                            print(f"      Reason: skipped outside allow_roots (e.g., {e['skipped_paths'][0]})")
                    else:
                        line = (f"    Outcome: kept **{e['keep_format']}**; deleted {e['abs_deleted']} other copy/copies. "
                                f"Files: moved {e['file_moved']}, deleted {e['file_deleted']}, skipped {e['file_skipped']}. ")
                        if e['kept_tag_removed']:
                            line += "Removed 'Duplicate' tag from kept copy."
                        print(line)
                        if e['skipped_paths']:
                            print(f"      Note: skipped outside allow_roots (e.g., {e['skipped_paths'][0]})")
                elif opts['prune']:
                    print("    Outcome: (no prune decision; formats not detected)")
    print("="*72)

if __name__ == "__main__":
    main()
