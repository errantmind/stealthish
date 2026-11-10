"""Runtime tab selection. No browsing history is saved by this module."""
from urllib.parse import urlsplit


def domain(url):
    from tld import get_fld
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return ""
    return get_fld(url, fail_silently=True) or host.removeprefix("www.")


async def info(session, tab):
    page = session.pages[tab]
    paused = tab in session.paused or urlsplit(page.url).hostname in session.paused_sites
    # Do not observe sign-in or challenge contents through a metadata operation.
    title = ""
    if not paused and not page.is_closed():
        title = (await page.title())[:1000]
    return {"tabId": tab, "selected": tab == session.selected, "paused": paused,
            "url": "" if paused else page.url, "title": title,
            "domain": "" if paused else domain(page.url)}


async def context(session, tab=None):
    tab = tab or session.selected
    data = {"selectedTab": session.selected, "liveTabs": len(session.pages),
            "maxTabs": session.config.tab_limit}
    if tab in session.pages:
        data.update(tabId=tab, tab=await info(session, tab))
    return data


async def choose(session, url, policy, tab=None):
    if tab is not None:
        return session.page({"tabId": tab})
    if policy == "new" or not session.pages:
        return await session.new_page()
    if policy == "current":
        return session.page({})
    active, page = session.page({})
    target = domain(url)
    if policy == "auto" and (page.url == "about:blank" or domain(page.url) == target):
        return active, page
    matches = [key for key, page in session.pages.items() if domain(page.url) == target]
    if matches:
        return session.page({"tabId": max(matches, key=lambda key: session.access.get(key, 0))})
    return await session.new_page()
