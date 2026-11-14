"""Browser-only search using the existing Pi engine registry. No fallback engine."""
import base64
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from .errors import StealthishError
from .extraction import readable
from .protocol import http_url

ENGINES = {item["id"]: item for item in json.loads(
    Path(__file__).with_name("search-engines.json").read_text())}
NO_RESULTS = {
    "kagi": ["no results found", "we couldn't find any results", "no results for your search"],
    "google": ["did not match any documents", "no results found for"],
    "bing": ["there are no results for", "no results found for"],
    "yahoo": ["we did not find results for", "no results found for"],
    "duckduckgo": ["no results found for"],
    "brave": ["no results found", "couldn't find any results"],
}
COLLECT = r"""({engine, empty}) => {
    const visible=e => !!e && getComputedStyle(e).visibility!=='hidden' && e.getClientRects().length>0;
    const has=s => [...document.querySelectorAll(s)].some(visible);
    const nodes=[...document.querySelectorAll(engine.containers)];
    const results=[]; let sourceTruncated=nodes.length>100;
    for (const node of nodes.slice(0,100)) {
        if (!visible(node)) continue;
        const ad=node.getAttribute('data-ad');
        if ((ad!==null && !['0','false','no'].includes(ad.toLowerCase())) || node.querySelector('[data-testid="ad"]')) continue;
        const link=node.querySelector(engine.link);
        if (!visible(link)) continue;
        const heading=link.querySelector('h3,h2,.title');
        const title=(heading || link).innerText.replace(/\s+/g,' ').trim();
        const desc=node.querySelector(engine.snippet);
        const snippet=visible(desc) ? desc.innerText.replace(/\s+/g,' ').trim() : '';
        if (title.length>5000 || snippet.length>5000 || link.href.length>8192) sourceTruncated=true;
        if (link.href.length>8192) continue;
        results.push({title:title.slice(0,5000),url:link.href,snippet:snippet.slice(0,5000)});
    }
    const main=document.querySelector('main,#search-results') || document.body;
    const text=main ? main.innerText.slice(0,100000).toLowerCase() : '';
    const emptyHeading=engine.id==='kagi' && [...document.querySelectorAll('main h1')].some(e=>
        visible(e) && ["we haven't found anything.", "we haven’t found anything."].includes(e.innerText.trim().toLowerCase()));
    const noResults=!results.length && (emptyHeading || (empty.some(phrase=>text.includes(phrase)) &&
        !has('h2 a[href], h3 a[href], a:has(h2), a:has(h3)')));
    return {results,noResults,sourceTruncated};
}"""


def engine_info(engine):
    if not isinstance(engine, str) or engine not in ENGINES:
        raise StealthishError("INVALID_REQUEST")
    return ENGINES[engine]


def query_url(query, engine="kagi"):
    info = engine_info(engine)
    if not isinstance(query, str) or not query.strip() or len(query) > 8192 or "\x00" in query:
        raise StealthishError("INVALID_REQUEST")
    return info["url"] + "?" + info["queryParam"] + "=" + quote(query, safe="")


def target_url(engine, href, page_url):
    # Decode known redirects locally. Do not fetch or follow result targets.
    try:
        url = urljoin(page_url, href)
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        qs = parse_qs(parsed.query)
        if engine == "google" and host in {"google.com", "www.google.com"} and parsed.path == "/url":
            url = (qs.get("q") or qs.get("url") or [""])[0]
        elif engine == "duckduckgo" and (host == "duckduckgo.com" or host.endswith(".duckduckgo.com")) and parsed.path.startswith("/l/"):
            url = (qs.get("uddg") or [""])[0]
        elif engine == "bing" and host in {"bing.com", "www.bing.com"} and parsed.path.startswith("/ck/"):
            value = (qs.get("u") or [""])[0]
            encoded = value[2:]
            url = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode() if value.startswith("a1") else value
        elif engine == "yahoo" and host == "r.search.yahoo.com":
            match = re.search(r"/RU=([^/]+)/R[KST]=", parsed.path)
            url = unquote(match[1]) if match else ""
        http_url(url)
        origin = urlsplit(ENGINES[engine]["url"]).hostname
        if urlsplit(url).hostname in {origin, origin.removeprefix("www.")}:
            return None
        return url
    except (ValueError, UnicodeError, StealthishError):
        return None


def bounded_results(observed, budget, engine="kagi", page_url="https://kagi.com/search"):
    clean, seen = [], set()
    for entry in observed["results"]:
        url = target_url(engine, entry["url"], page_url)
        title = entry["title"].strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        snippet = entry["snippet"].strip()
        if engine == "kagi":
            snippet = re.sub(r"\s*Summarize\s*$", "", snippet, flags=re.I).strip()
        clean.append({"title": title, "url": url, "domain": urlsplit(url).hostname, "snippet": snippet})
    full = "\n\n".join(f"{i}. {r['title']} [{r['domain']}]\n{r['url']}\n{r['snippet']}"
                       for i, r in enumerate(clean, 1))
    selected, left = [], budget
    for entry in clean:
        fixed = len(entry["url"]) + len(entry["domain"])
        if left <= fixed:
            break
        title = entry["title"][:left-fixed]
        snippet = entry["snippet"][:max(0, left-fixed-len(title))]
        item = dict(entry, title=title, snippet=snippet)
        selected.append(item)
        left -= sum(len(v) for v in item.values())
    return selected, full, {"truncated": observed["sourceTruncated"] or len(full) > budget,
                            "characters": len(full), "limit": budget,
                            "sourceTruncated": observed["sourceTruncated"], "observedResults": len(clean)}


async def collect(page, budget, engine="kagi"):
    info = engine_info(engine)
    location = urlsplit(page.url)
    host = location.hostname or ""
    if host == info["domain"] or host.endswith("." + info["domain"]):
        state = await page.evaluate(COLLECT, {"engine": info, "empty": NO_RESULTS[engine]})
        results, full, truncation = bounded_results(state, budget, engine, page.url)
        if truncation["observedResults"]:
            return {"kind": "results", "results": results, "text": full[:budget], "method": engine+"-dom"}, truncation, [], full
        if state["noResults"]:
            return {"kind": "no-results", "results": [], "text": "No results found.", "method": engine+"-dom"}, truncation, [], "No results found."
        kind, warning = "fallback", "Search result markup was not identified; this is not a zero-result verdict."
    else:
        kind, warning = "redirect", "Search redirected away from the selected engine; no fallback engine was used."
    text, method, warnings = await readable(page)
    return {"kind": kind, "results": [], "text": text[:budget], "method": method}, {
        "truncated": len(text) > budget, "characters": len(text), "limit": budget,
    }, [warning, *warnings], text
