"""Replay exact draft export bytes without rerendering or accepting a release."""
import hashlib
import json
from pathlib import Path


def verify_export(root, manifest_path, *, expected_sha256):
    root = Path(root).resolve(strict=True)
    path = (root / manifest_path).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError('Manifest escapes private sandbox')
    with path.open('rb') as stream:
        content = stream.read(1_000_001)
    if len(content) > 1_000_000 or hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError('Manifest hash differs from recorded export')
    manifest = json.loads(content)
    member_counts = {'agentic-pack-export/v1': 3, 'agentic-memo-export/v1': 2}
    if (manifest.get('contract') not in member_counts or manifest.get('release') != 'blocked'
            or not isinstance(manifest.get('files'), list)
            or len(manifest['files']) != member_counts[manifest['contract']]):
        raise ValueError('Unsupported draft export manifest')
    seen = set()
    for item in manifest['files']:
        name = item['name']
        if not isinstance(name, str) or Path(name).name != name or name in seen:
            raise ValueError('Ambiguous or unsafe export member')
        seen.add(name)
        member = (path.parent / name).resolve(strict=True)
        if member.parent != path.parent or member.stat().st_size != item['bytes']:
            raise ValueError('Export member escaped or changed length')
        hashed = hashlib.sha256()
        with member.open('rb') as stream:
            while True:
                block = stream.read(65536)
                if not block:
                    break
                hashed.update(block)
        if hashed.hexdigest() != item['sha256']:
            raise ValueError('Export member hash differs')
    return {'status': 'exact_bytes_verified', 'release': 'blocked',
            'semantic_validation': 'not_run', 'manifest_sha256': expected_sha256}
