"""Verify the blocker assets used by bot-detection integration checks."""
import hashlib
import json
from pathlib import Path


def verify_assets(root: Path):
    record = json.loads((root / 'evidence/local/blocker-acquisition.json').read_text())
    for entry in record['files']:
        path = (root / entry['path']).resolve()
        if not path.is_relative_to(root / '.cache/blocker') or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Blocker asset mismatch: ' + entry['path'])
    assert hashlib.sha256((root / record['archive']).read_bytes()).hexdigest() == record['sha256']
    return record
