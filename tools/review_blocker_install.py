"""Acquire pinned browser extension source for review only. No code is executed."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REV = 'a21ce95c24ce3964416f09ae1862f53f319eb4d0'
FILES = ['chrome/browser/devtools/protocol/extensions_handler.cc',
         'chrome/browser/devtools/protocol/extensions_handler.h',
         'chrome/browser/devtools/protocol/devtools_extensions_browsertest.cc',
         'extensions/browser/unpacked_installer.cc',
         'chrome/browser/devtools/chrome_devtools_manager_delegate.cc',
         'chrome/browser/devtools/remote_debugging_server.cc',
         'chrome/browser/devtools/chrome_devtools_session.cc',
         'chrome/common/chrome_switches.h']
rows = []
for name in FILES:
    target = ROOT / 'analysis/sources/blocker-install' / name
    meta = json.loads(subprocess.check_output(['gh','api',f'repos/chromium/chromium/contents/{name}?ref={REV}']))
    data = base64.b64decode(meta['content'])
    if target.exists() and target.read_bytes() != data:
        raise ValueError('Existing review source changed.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    rows.append({'path': str(target.relative_to(ROOT)), 'sha256': hashlib.sha256(data).hexdigest(), 'url': meta['html_url']})
record = {'scope': 'Source review only; no browser, extension install, or policy change.',
          'chromiumRevision': REV, 'browserVersion': '156.0.8078.79', 'files': rows}
(ROOT / 'evidence/2026-11-09-blocker-install-review.json').write_text(json.dumps(record, indent=2)+'\n')
print('Acquired',len(rows),'pinned source files for review.')
