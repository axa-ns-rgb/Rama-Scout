import re
import logging
import httpx

logger = logging.getLogger(__name__)

LINKEDIN_URL_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?")

_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:title|og:description|og:image)["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def find_linkedin_url(text: str) -> str | None:
    match = LINKEDIN_URL_RE.search(text)
    return match.group(0) if match else None


async def fetch_linkedin_preview(url: str) -> dict | None:
    """Read the Open Graph meta tags LinkedIn serves on a logged-out profile
    request (title/headline, sometimes a short summary snippet).

    This is a single unauthenticated GET, same as any link-preview unfurl —
    no login, no session cookies, no bypassing LinkedIn's login wall. It only
    recovers what LinkedIn already exposes to anonymous requests, which means
    LinkedIn is free to (and often does) return little or nothing.
    """
    try:
        async with httpx.AsyncClient(timeout=10, headers=HEADERS, follow_redirects=True) as http:
            response = await http.get(url)
        if response.status_code != 200:
            logger.info("LinkedIn fetch non-200 for %s: %s", url, response.status_code)
            return None

        og = dict(_META_RE.findall(response.text))
        if not og:
            return None

        return {
            "title": og.get("og:title"),
            "description": og.get("og:description"),
            "image": og.get("og:image"),
            "url": url,
        }
    except Exception as e:
        logger.warning("LinkedIn preview fetch failed for %s: %s", url, e)
        return None
