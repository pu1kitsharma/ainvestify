"""Import untrusted local tar archives into private storage outside Git.

No extractall, code/config execution, hosted requests, inference or weight updates.
Evaluation artifacts retain held-out status. Registration only adds verified Ollama
blobs/manifests and never replaces an existing file or tag.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.I)
BLOB = re.compile(r"sha256-([0-9a-f]{64})$")


def safe_parts(name):
    if not isinstance(name, str) or "\\" in name or name.startswith("/"):
        raise ValueError("Unsafe archive path")
    parts = tuple(p for p in name.split("/") if p not in ("", "."))
    if not parts or any(p == ".." or ":" in p or p.endswith((" ", "."))
                        or RESERVED.fullmatch(p) or any(ord(c) < 32 for c in p) for p in parts):
        raise ValueError("Unsafe archive path")
    return parts


def real_path(path):
    """Refuse symlinks/junctions in any existing ancestor, including Windows."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError("Linked import path is not permitted")
    return path


def outside_repo(path, repo=ROOT):
    path = real_path(path)
    if path.resolve().is_relative_to(Path(repo).resolve()):
        raise ValueError("Private archive contents must stay outside Git")
    return path


def digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(archive, *, max_files=20000, max_bytes=50 * 1024**3):
    members, seen, total = [], {}, 0
    for member in archive:
        if len(members) >= max_files or not (member.isfile() or member.isdir()):
            raise ValueError("Archive member type or count is unsupported")
        parts = safe_parts(member.name)
        key = "/".join(parts).casefold()
        if key in seen:
            raise ValueError("Duplicate or case-colliding archive path")
        # A regular file cannot be a parent directory of any other member.
        parents = ["/".join(parts[:i]).casefold() for i in range(1, len(parts))]
        if any(seen.get(parent) == "file" for parent in parents):
            raise ValueError("Archive file/directory conflict")
        if member.isfile() and any(old.startswith(key + "/") for old in seen):
            raise ValueError("Archive file/directory conflict")
        seen[key] = "file" if member.isfile() else "directory"
        total += member.size
        if member.size < 0 or total > max_bytes or member.issparse():
            raise ValueError("Archive size or sparse member is unsupported")
        members.append((member, parts))
    return members, total


def extract_private(source, destination, *, repo=ROOT, progress=None):
    source = real_path(source)
    destination = outside_repo(destination, repo)
    if not source.is_file() or destination.exists():
        raise ValueError("Source must exist and destination must be new")
    original_stat = source.stat()
    signature = (original_stat.st_size, original_stat.st_mtime_ns)
    with tarfile.open(source, "r:") as archive:
        members, total = inventory(archive)
        if shutil.disk_usage(destination.parent).free < total + 1024**3:
            raise ValueError("Insufficient free private storage")
        source_hash = digest_file(source)
        if progress:
            progress("Archive checksum complete; extracting verified regular files.")
        destination.mkdir(mode=0o700)
        files = {}
        last_report = time.monotonic()
        copied = 0
        try:
            for member, parts in members:
                target = destination.joinpath(*parts)
                if member.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                digest = hashlib.sha256()
                count = 0
                with archive.extractfile(member) as incoming, target.open("xb") as outgoing:
                    for chunk in iter(lambda: incoming.read(8 * 1024 * 1024), b""):
                        outgoing.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                if count != member.size:
                    raise ValueError("Archive member length mismatch")
                if "blobs" in parts and (match := BLOB.fullmatch(parts[-1])) and digest.hexdigest() != match.group(1):
                    raise ValueError("Ollama blob content digest mismatch")
                files["/".join(parts)] = {"bytes": count, "sha256": digest.hexdigest()}
                copied += count
                if progress and time.monotonic() - last_report >= 20:
                    progress(f"Extracted {copied // 1024**2} MiB; private contents omitted.")
                    last_report = time.monotonic()
            current = source.stat()
            if (current.st_size, current.st_mtime_ns) != signature:
                raise ValueError("Source archive changed during import")
            manifest = {"contract": "private-local-archive-import-v1", "source": str(source),
                        "source_bytes": signature[0], "source_sha256": source_hash,
                        "members": len(members), "declared_bytes": total, "files": files,
                        "executed": False, "training_approved": False,
                        "evaluation_policy": "hold_out; never promote failures or gold to training automatically"}
            with (destination / "import-manifest.json").open("x", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2)
            return manifest
        except Exception:
            with (destination / "FAILED-IMPORT.txt").open("x", encoding="utf-8") as handle:
                handle.write("Import failed. Preserve this directory; no model was registered or trained.\n")
            raise


def add_file(source, target, expected):
    """Create atomically; a concurrent or existing destination is never replaced."""
    target = real_path(target)
    if target.exists():
        if not target.is_file() or digest_file(target) != expected:
            return "conflict"
        return "unchanged"
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".import-", delete=False) as handle:
            temporary = Path(handle.name)
            with open(source, "rb") as incoming:
                shutil.copyfileobj(incoming, handle, length=8 * 1024 * 1024)
        if digest_file(temporary) != expected:
            raise ValueError("Staged model copy failed verification")
        try:
            os.link(temporary, target)
        except FileExistsError:
            return "unchanged" if target.is_file() and digest_file(target) == expected else "conflict"
        return "added"
    finally:
        if temporary is not None:
            temporary.unlink()


def register_ollama(extracted, target, manifest, *, repo=ROOT, progress=None):
    extracted = outside_repo(extracted, repo)
    target = outside_repo(target, repo)
    model_root = extracted / "models"
    manifests = sorted((model_root / "manifests").rglob("*"))
    manifests = [p for p in manifests if p.is_file()]
    if not manifests:
        raise ValueError("No Ollama manifests in imported archive")
    # Validate every manifest and referenced blob before publishing any model tag.
    needed, tags = {}, []
    for path in manifests:
        relative = path.relative_to(model_root / "manifests")
        if len(relative.parts) != 4 or relative.parts[:2] != ("registry.ollama.ai", "library"):
            raise ValueError("Unapproved Ollama registry layout")
        key = path.relative_to(extracted).as_posix()
        if key not in manifest["files"] or digest_file(path) != manifest["files"][key]["sha256"]:
            raise ValueError("Imported model manifest changed")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schemaVersion") != 2 or not isinstance(data.get("layers"), list):
            raise ValueError("Unsupported Ollama manifest")
        for layer in [data["config"], *data["layers"]]:
            digest = layer.get("digest", "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Unsupported model blob identifier")
            name = digest.replace(":", "-")
            entry = manifest["files"].get("models/blobs/" + name)
            if not entry or entry["sha256"] != digest[7:] or entry["bytes"] != layer.get("size"):
                raise ValueError("Model references an absent, changed or invalid blob")
            needed[name] = entry
        tags.append((path, relative, manifest["files"][key]["sha256"]))
    result = {"blobs": Counter(), "tags": Counter(), "models": []}
    for name, entry in needed.items():
        outcome = add_file(model_root / "blobs" / name, target / "blobs" / name, entry["sha256"])
        result["blobs"][outcome] += 1
        if outcome == "conflict":
            raise ValueError("Existing model blob conflicts; preserved without replacement")
        if progress:
            progress(f"Model blobs checked: {sum(result['blobs'].values())}/{len(needed)}")
    for source, relative, digest in tags:
        outcome = add_file(source, target / "manifests" / relative, digest)
        result["tags"][outcome] += 1
        result["models"].append({"model": relative.parts[2] + ":" + relative.parts[3], "status": outcome})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--register-ollama", action="store_true")
    parser.add_argument("--ollama-store", type=Path, default=Path.home() / ".ollama/models")
    args = parser.parse_args()
    try:
        manifest = extract_private(args.source, args.destination, progress=lambda text: print(text, flush=True))
        summary = {"members": manifest["members"], "bytes": manifest["declared_bytes"],
                   "source_sha256": manifest["source_sha256"], "training_approved": False}
        if args.register_ollama:
            registration = register_ollama(args.destination, args.ollama_store, manifest,
                                          progress=lambda text: print(text, flush=True))
            with (args.destination / "ollama-registration.json").open("x", encoding="utf-8") as handle:
                json.dump(registration, handle, indent=2)
            summary["registration"] = registration
        print(json.dumps(summary, indent=2))
        return 0
    except (OSError, ValueError, tarfile.TarError, KeyError, TypeError):
        print("Archive import blocked; existing files were preserved. Inspect the private import directory.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())