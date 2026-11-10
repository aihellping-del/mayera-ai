"""JARVIS - play any YouTube video by voice (v3.4).

The user asked for this directly: "YouTube par koi bhi video select
kar sake." No API key and no screen-watching needed:

  * youtube_search(query) - fetch the public search-results page and
    read back the top videos (number + title), so he can choose.
  * youtube_play(query, number) - open the chosen result straight in
    his browser at its watch URL, so it starts playing.

The page fetch is plain urllib (stdlib) with a short timeout; any
failure returns a clean error dict and JARVIS falls back to just
opening YouTube. The fetcher and opener are injectable for tests.
"""

import re
import urllib.parse
import urllib.request
import webbrowser

_SEARCH_URL = "https://www.youtube.com/results?search_query="
_WATCH_URL = "https://www.youtube.com/watch?v="
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0 Safari/537.36")


def _default_fetcher(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_title(raw):
    try:
        return (raw.replace("\\u0026", "&").replace('\\"', '"')
                   .replace("\\'", "'").strip())
    except Exception:  # noqa: BLE001
        return raw


def search_videos(query, limit=5, fetcher=None):
    """Top results for a query: [{'id': ..., 'title': ...}, ...]."""
    fetcher = fetcher or _default_fetcher
    url = _SEARCH_URL + urllib.parse.quote_plus(query or "")
    html = fetcher(url)
    videos, seen = [], set()
    # Each result lives in a "videoRenderer" chunk of the page JSON;
    # take the first videoId + title inside each chunk, in order.
    for chunk in html.split('"videoRenderer"')[1:]:
        idm = re.search(r'"videoId":"([\w-]{11})"', chunk)
        if not idm or idm.group(1) in seen:
            continue
        tm = re.search(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
                       chunk)
        seen.add(idm.group(1))
        videos.append({"id": idm.group(1),
                       "title": _clean_title(tm.group(1)) if tm else ""})
        if len(videos) >= limit:
            break
    return videos


class YoutubePlayer:
    def __init__(self, opener=None, fetcher=None):
        self._opener = opener or webbrowser.open
        self._fetcher = fetcher
        self._cache = {}  # query -> results: "list sunao" ke baad
        # "dusri wali chalao" par dobara net nahi lagta (v3.5 speed)

    def _videos(self, query):
        key = query.lower()
        if key not in self._cache:
            self._cache[key] = search_videos(query, fetcher=self._fetcher)
        return self._cache[key]

    def search(self, query):
        query = (query or "").strip()
        if not query:
            return {"status": "error", "message": "khaali search"}
        try:
            videos = self._videos(query)
        except Exception as exc:  # noqa: BLE001 - network, markup, ...
            return {"status": "error",
                    "message": f"YouTube search nahi ho paya: {exc}"}
        if not videos:
            return {"status": "error",
                    "message": "koi video nahi mili is naam se"}
        return {"status": "ok", "query": query,
                "results": [{"number": i + 1, "title": v["title"]}
                            for i, v in enumerate(videos)]}

    def play(self, query, number=1):
        query = (query or "").strip()
        if not query:
            return {"status": "error", "message": "khaali search"}
        try:
            number = max(1, int(number))
        except (TypeError, ValueError):
            number = 1
        try:
            videos = self._videos(query)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error",
                    "message": f"YouTube search nahi ho paya: {exc}"}
        if not videos:
            return {"status": "error",
                    "message": "koi video nahi mili is naam se"}
        if number > len(videos):
            number = len(videos)
        chosen = videos[number - 1]
        self._opener(_WATCH_URL + chosen["id"])
        return {"status": "playing", "number": number,
                "title": chosen["title"],
                "url": _WATCH_URL + chosen["id"]}
