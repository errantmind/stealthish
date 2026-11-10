"""Extract only browser-loaded content. No HTTP client or extraction URL is used."""
import asyncio

from .errors import StealthishError

# Bound parsing work. An oversized document is an explicit error, not a partial article.
MAX_DOCUMENT = 2_000_000
MAX_NODES = 50000
CAPTURE = r"""({maxChars,maxNodes}) => {
    const root = document.documentElement;
    if (!root) return {html:'',text:'',source:'empty'};
    const raw = root.outerHTML;
    if (raw.length > maxChars) return {tooLarge:true};
    const originals = [root, ...root.querySelectorAll('*')];
    if (originals.length > maxNodes) return {tooLarge:true};
    // Work on a detached clone. Never change the live DOM or read field values.
    const copy = root.cloneNode(true);
    const copies = [copy, ...copy.querySelectorAll('*')];
    const omit = 'script,style,noscript,template,input,textarea,select,option,[contenteditable]:not([contenteditable="false"]),[hidden],[aria-hidden="true"]';
    for (let i=1; i<originals.length; i++) {
        const node=originals[i], style=getComputedStyle(node);
        if (node.matches(omit) || style.display==='none' || style.visibility==='hidden' || style.visibility==='collapse')
            copies[i].remove();
    }
    const main=copy.querySelector('main,article') || copy.querySelector('body');
    const text=main ? main.textContent.replace(/\s+/g,' ').trim() : '';
    return {html:copy.outerHTML, text, source:copy.querySelector('main,article') ? 'main' : 'body'};
}"""
RAW_HTML = """maxChars => {
    const text=document.documentElement ? document.documentElement.outerHTML : '';
    return text.length > maxChars ? {tooLarge:true} : {html:'<!doctype html>\\n'+text};
}"""


def article(html):
    # This library call parses the supplied string. No URL, download, date lookup,
    # language model, or metadata extraction is requested.
    from trafilatura import extract
    return extract(html, output_format="txt", include_comments=False,
                   include_tables=True, with_metadata=False, favor_precision=True) or ""


async def readable(page):
    captured = await page.evaluate(CAPTURE, {"maxChars": MAX_DOCUMENT, "maxNodes": MAX_NODES})
    if captured.get("tooLarge"):
        raise StealthishError("CONTENT_LIMIT")
    text = ""
    failed = False
    if captured["html"]:
        try:
            text = await asyncio.to_thread(article, captured["html"])
        except Exception:
            failed = True
    if text.strip():
        return text.strip(), "trafilatura", []
    warnings = ["Article extraction failed; using filtered browser text." if failed
                else "No article was identified; using filtered browser text."]
    return captured["text"], "browser-filtered-text", warnings


async def raw_html(page):
    captured = await page.evaluate(RAW_HTML, MAX_DOCUMENT)
    if captured.get("tooLarge"):
        raise StealthishError("CONTENT_LIMIT")
    return captured["html"]
