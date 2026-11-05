"""Synthetic archive safety tests; no private inputs or model calls."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest
from scripts import import_local_archives as importer


def make_tar(path, entries):
    with tarfile.open(path, "w") as archive:
        for name, data in entries:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/absolute", "x:stream", "x/CON.txt",
                                  "x/back\\slash", "x/trailing.", "x/trailing ", "x/../escape"])
def test_unsafe_member_paths_are_rejected(name):
    with pytest.raises(ValueError):
        importer.safe_parts(name)


def test_case_collisions_and_links_are_rejected_before_writing(tmp_path):
    path = tmp_path / "fixture.tar"
    make_tar(path, [("models/File", b"a"), ("models/file", b"b")])
    with tarfile.open(path) as archive, pytest.raises(ValueError, match="case-colliding"):
        importer.inventory(archive)
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("unsafe")
        member.type = tarfile.SYMTYPE
        member.linkname = "elsewhere"
        archive.addfile(member)
    with tarfile.open(path) as archive, pytest.raises(ValueError, match="type"):
        importer.inventory(archive)


def test_file_parent_conflicts_are_rejected_in_either_order(tmp_path):
    path = tmp_path / "fixture.tar"
    for entries in ([("x", b"a"), ("x/y", b"b")], [("x/y", b"b"), ("x", b"a")]):
        make_tar(path, entries)
        with tarfile.open(path) as archive, pytest.raises(ValueError, match="conflict"):
            importer.inventory(archive)


def test_private_import_is_byte_exact_and_remains_unapproved_for_training(tmp_path):
    path, destination = tmp_path / "fixture.tar", tmp_path / "private"
    make_tar(path, [("evals/heldout.json", b'{"synthetic": true}'), ("models/data/candidate.jsonl", b"candidate\n")])
    original = path.read_bytes()
    result = importer.extract_private(path, destination, repo=tmp_path / "repo")
    assert (destination / "evals/heldout.json").read_bytes() == b'{"synthetic": true}'
    assert result["training_approved"] is False and result["executed"] is False
    assert "hold_out" in result["evaluation_policy"]
    assert path.read_bytes() == original
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    with pytest.raises(ValueError, match="destination must be new"):
        importer.extract_private(path, destination, repo=tmp_path / "repo")


def test_private_import_inside_repository_is_refused(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = tmp_path / "fixture.tar"
    make_tar(path, [("x", b"data")])
    with pytest.raises(ValueError, match="outside Git"):
        importer.extract_private(path, repo / "private", repo=repo)
    assert not (repo / "private").exists()


def test_bad_blob_hash_fails_without_registration(tmp_path):
    path, destination = tmp_path / "fixture.tar", tmp_path / "private"
    make_tar(path, [("models/blobs/sha256-" + "0" * 64, b"wrong")])
    with pytest.raises(ValueError, match="digest mismatch"):
        importer.extract_private(path, destination, repo=tmp_path / "repo")
    assert (destination / "FAILED-IMPORT.txt").is_file()
    assert not (destination / "import-manifest.json").exists()


def test_registration_adds_verified_model_and_preserves_conflicting_tag(tmp_path):
    path, destination, store = tmp_path / "fixture.tar", tmp_path / "private", tmp_path / "ollama"
    blob = b"synthetic model fixture"
    digest = hashlib.sha256(blob).hexdigest()
    model = json.dumps({"schemaVersion": 2, "config": {"digest": "sha256:" + digest, "size": len(blob)}, "layers": []}).encode()
    relative = Path("manifests/registry.ollama.ai/library/fixture/latest")
    make_tar(path, [("models/blobs/sha256-" + digest, blob), ("models/" + relative.as_posix(), model)])
    manifest = importer.extract_private(path, destination, repo=tmp_path / "repo")
    result = importer.register_ollama(destination, store, manifest, repo=tmp_path / "repo")
    assert result["tags"]["added"] == 1
    assert (store / relative).read_bytes() == model
    (store / relative).write_bytes(b"existing tag must survive")
    result = importer.register_ollama(destination, store, manifest, repo=tmp_path / "repo")
    assert result["tags"]["conflict"] == 1
    assert (store / relative).read_bytes() == b"existing tag must survive"