"""Local routes for unchanged BotD and CreepJS bundles."""
from pathlib import Path

ACCEPT_CH = ", ".join([
    "Sec-CH-UA-Full-Version-List", "Sec-CH-UA-Arch", "Sec-CH-UA-Bitness",
    "Sec-CH-UA-Platform-Version", "Sec-CH-UA-Model", "Sec-CH-UA-WoW64", "Sec-CH-UA-Form-Factors",
])


def response(root: Path, path: str):
    html = "text/html; charset=utf-8"
    js = "text/javascript; charset=utf-8"
    if path == "/detectors/botd.js":
        return (root / ".cache/detectors/botd-2.0.0/dist/botd.esm.js").read_bytes(), js
    if path == "/detectors/botd":
        return b'''<!doctype html><meta charset=utf-8><title>Local BotD</title><body>
<script type=module>
import {load} from '/detectors/botd.js';
const result = document.createElement('pre'); result.id='result';
try {
 const detector = await load({monitoring:false});
 const verdict = detector.detect();
 result.textContent = JSON.stringify({status:'PASS', verdict,
   detections:detector.getDetections(), components:detector.getComponents()});
} catch(error) {result.textContent=JSON.stringify({status:'ERROR',error:String(error)});}
document.body.append(result);
</script>''', html
    creep_root = root / ".cache/detectors/creepjs/docs"
    if path == "/creep/":
        page = (creep_root / "index.html").read_text()
        # Only the result bridge is added. Detector rules stay unchanged.
        bridge = '''<script type=module>
const timer = setInterval(() => {
 if (!window.Fingerprint) return;
 clearInterval(timer);
 const result = document.createElement('pre'); result.id='result';
 result.textContent = JSON.stringify({status:'PASS',fingerprint:window.Fingerprint,creep:window.Creep});
 result.hidden=true; document.body.append(result);
},100);
</script>'''
        return page.replace("</body>", bridge + "</body>").encode(), html
    if path in ("/creep/creep.js", "/creep/style.min.css", "/creep/favicon.ico"):
        kind = js if path.endswith(".js") else "text/css" if path.endswith(".css") else "image/x-icon"
        return (creep_root / path.rsplit("/", 1)[-1]).read_bytes(), kind
    return None
