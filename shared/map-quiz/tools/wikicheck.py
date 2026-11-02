#!/usr/bin/env python3
"""Checks the Wikipedia article titles in a map image's data against the live
Wikipedia and Wikidata APIs (shared map-quiz tool, stdlib only, Python 3.9+).

Run by hand, with network access, after changing titles or when re-checking
them. The live check never runs in a build or CI: the builds and the data
tests only check that the titles are present and well-formed, offline, and
CI runs wikicheck_test.py, this module's logic on canned answers with the
network blocked.

Each image has a thin entry point, images/<name>/tools/wiki_titles.py, that
puts shared/map-quiz/tools on sys.path (as for mapgen, whose
wiki_title_error this module shares), turns its data into entries and calls
check() (or suggest() to propose titles); its tools/README.md ("Wikipedia
titles") has the method, the date checked and the special cases.

An entry is a dict:
  key           a label for the report ("AUT wiki")
  title         the title as stored (spaces, not underscores)
  item          the Wikidata item the article must belong to, or
  capital_of    a Wikidata item whose current capital the article's item must
                be: in that item's capital (P36), or the city's "capital of"
                (P1376) names it; current = not deprecated, no end time (P582)
                up to today, no start time (P580) after today
  capital_item  (with capital_of, optional) the item expected where Wikidata
                doesn't record the city as a current capital (a documented
                exception in the image's README); the article's item must be
                this one, and the report notes when Wikidata has caught up

A title passes when it is well-formed, the page exists, the stored title is
the canonical one (Wikipedia doesn't normalise it or follow a redirect: the
report names the title to store instead), it is no disambiguation page, and
its Wikidata item is as expected.

Politeness: sequential requests with a pause, a User-Agent naming the
project, maxlag=5 (lag and busy answers waited out, at least the server's
Retry-After, up to LAG_BUDGET per request), at most 50 titles per query,
P36/P1376 read per item with wbgetclaims (small answers).
"""
import datetime
import http.client
import json
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from mapgen import wiki_title_error  # the offline shape rule the builds use too

USER_AGENT = "phw-wiki-titles/1.0 (https://github.com/idlinglight/plausibly-hello-world)"
WIKIDATA = "https://www.wikidata.org/w/api.php"
BATCH = 50      # titles or ids per request (the APIs' limit for normal clients)
PAUSE = 0.25    # seconds between requests
TRIES = 6       # tries on server or network errors
LAG_BUDGET = 900  # seconds to wait out maxlag or busy answers per request
RETRY_CODES = {"maxlag", "ratelimited", "cirrussearch-too-busy-error"}  # API errors worth a retry


def wikipedia(lang):
    return f"https://{lang}.wikipedia.org/w/api.php"


# ------------------------------------------------------------------ network
_last = [0.0]
_urlopen = urllib.request.urlopen  # replaced by the offline tests
_sleep = time.sleep                # likewise
# Passing hiccups, retried with backoff up to `tries` times: network errors,
# read timeouts (socket.timeout is TimeoutError only from Python 3.10 on),
# dropped or broken connections (http.client: RemoteDisconnected,
# IncompleteRead, ...), and a body that isn't JSON (ValueError: e.g. an HTML
# error page from a proxy).
TRANSIENT = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException,
             ValueError)


def _delay(retry_after, attempt):
    try:
        return min(max(float(retry_after), 5.0), 120.0)
    except (TypeError, ValueError):
        return min(5.0 * 2 ** attempt, 60.0)


def api_get(url, params, tries=TRIES, lag_budget=LAG_BUDGET):
    """GET a MediaWiki API: JSON, formatversion 2, maxlag 5. Waits out lag
    and busy answers (RETRY_CODES, HTTP 429 and 503) for up to lag_budget
    seconds; retries TRANSIENT errors and HTTP 500, 502, 504 up to `tries`
    times, with the same backoff. Raises RuntimeError on any other API or
    HTTP error, and when the retries or the lag budget run out."""
    query = dict(params, format="json", formatversion="2", maxlag="5")
    full = url + "?" + urllib.parse.urlencode(query)
    waited, failures, attempt = 0.0, 0, 0
    while True:
        wait = PAUSE - (time.monotonic() - _last[0])
        if wait > 0:
            _sleep(wait)
        req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
        lagged, retry_after, problem = False, None, None
        try:
            with _urlopen(req, timeout=60) as resp:
                retry_after = resp.headers.get("Retry-After")
                body = json.loads(resp.read().decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError(f"a JSON {type(body).__name__}, not an object")
        except urllib.error.HTTPError as e:  # before TRANSIENT: a URLError too
            if e.code in (429, 503):
                lagged, retry_after = True, e.headers.get("Retry-After")
            elif e.code in (500, 502, 504):
                problem = f"HTTP {e.code}"
            else:
                raise RuntimeError(f"{url}: HTTP {e.code} {e.reason}") from e
        except TRANSIENT as e:
            problem = f"{type(e).__name__}: {e}"
        else:
            err = body.get("error")
            if not err:
                _last[0] = time.monotonic()
                return body
            if err.get("code") not in RETRY_CODES:
                raise RuntimeError(f"{url}: {err.get('code')}: {err.get('info')}")
            lagged = True
        _last[0] = time.monotonic()
        if problem:
            failures += 1
            if failures >= tries:
                raise RuntimeError(f"{url}: {problem} (gave up after {tries} tries)")
        delay = _delay(retry_after, attempt)
        attempt += 1
        if lagged:
            if waited + delay > lag_budget:
                raise RuntimeError(f"{url}: still lagged or busy after {waited:.0f} s; try again later")
            waited += delay
        _sleep(delay)


def batches(items, n=BATCH):
    items = list(dict.fromkeys(items))
    return [items[i:i + n] for i in range(0, len(items), n)]


# ------------------------------------------------------------------ pure parts
def resolve(titles, query):
    """Each asked title -> what the API's query part says about it: the
    title it ends up at (after normalisation and redirects), the steps taken,
    and the page's flags. Pure: query is the "query" member of an answer
    (formatversion 2) that asked for these titles."""
    norm = {n["from"]: n["to"] for n in query.get("normalized", [])}
    redir = {r["from"]: (r["to"], r.get("tofragment")) for r in query.get("redirects", [])}
    pages = {p["title"]: p for p in query.get("pages", [])}
    out = {}
    for t in titles:
        cur, steps, fragment = norm.get(t, t), [], None
        if cur != t:
            steps.append(f"normalised to {cur!r}")
        seen = {cur}
        while cur in redir:
            cur, frag = redir[cur]
            fragment = frag or None
            steps.append(f"redirects to {cur!r}" + (f" (section {frag!r})" if frag else ""))
            if cur in seen:
                break
            seen.add(cur)
        p = pages.get(cur)
        props = (p or {}).get("pageprops", {})
        out[t] = {
            "title": cur,
            "steps": steps,
            "fragment": fragment,
            "missing": p is None or bool(p.get("missing")),
            "invalid": p is not None and bool(p.get("invalid")),
            "disambiguation": "disambiguation" in props,
            "item": props.get("wikibase_item"),
        }
    return out


def _time_key(snak):
    """(year, month, day) of a Wikidata time value ('+2019-12-31T00:00:00Z';
    month and day 00 at a coarser precision)."""
    value = snak.get("datavalue", {}).get("value", {}).get("time")
    m = re.match(r"^([+-])(\d+)-(\d\d)-(\d\d)", value) if isinstance(value, str) else None
    if m is None:
        raise ValueError(f"Wikidata time value {value!r} (qualifier {snak.get('property')}): "
                         "not the expected +YYYY-MM-DDThh:mm:ssZ form")
    year = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
    return (year, int(m.group(3)), int(m.group(4)))


def current_values(statements, today=None):
    """Item ids of the current values among a property's statements (the
    wbgetclaims list): not deprecated, no end time (P582) up to today (an
    unknown end time counts as ended), no start time (P580) after today."""
    t = today or datetime.date.today()
    now = (t.year, t.month, t.day)
    vals = set()
    for st in statements:
        snak = st.get("mainsnak", {})
        if st.get("rank") == "deprecated" or snak.get("snaktype") != "value":
            continue
        q = st.get("qualifiers", {})
        ended = any(s.get("snaktype") == "somevalue" or (s.get("snaktype") == "value" and _time_key(s) <= now)
                    for s in q.get("P582", []))
        future = any(s.get("snaktype") == "value" and _time_key(s) > now for s in q.get("P580", []))
        if not ended and not future:
            vals.add(snak["datavalue"]["value"]["id"])
    return vals


def evaluate(entries, info, claims):
    """Results [(entry, ok, message)] for entries, given info = resolve() for
    their titles and claims(item, prop) -> the current values of an item's
    property (set of item ids). Pure, apart from what claims does."""
    results = []
    for e in entries:
        title = e.get("title")
        bad = wiki_title_error(title)
        if bad:
            results.append((e, False, f"malformed title: {bad}"))
            continue
        r = info.get(title)
        if r is None:
            results.append((e, False, "not looked up"))
        elif r["invalid"]:
            results.append((e, False, "invalid title"))
        elif r["missing"]:
            results.append((e, False, f"no article {r['title']!r}" + (f" ({'; '.join(r['steps'])})" if r["steps"] else "")))
        elif r["fragment"]:
            results.append((e, False, f"{'; '.join(r['steps'])}: a section, not an article of its own"))
        elif r["steps"]:
            results.append((e, False, f"{'; '.join(r['steps'])}: store {r['title']!r}"))
        elif r["disambiguation"]:
            results.append((e, False, "a disambiguation page"))
        elif not r["item"]:
            results.append((e, False, "the article has no Wikidata item"))
        elif e.get("item"):
            ok = r["item"] == e["item"]
            results.append((e, ok, f"item {r['item']}" if ok else f"item {r['item']}, expected {e['item']}"))
        elif e.get("capital_of"):
            results.append(_capital(e, r["item"], claims))
        else:
            results.append((e, False, "entry has neither item nor capital_of"))
    return results


def _capital(e, item, claims):
    country = e["capital_of"]
    p36 = claims(country, "P36")
    recorded = item in p36 or country in claims(item, "P1376")
    how = f"P36 of {country}" if item in p36 else f"P1376 of {item}"
    if e.get("capital_item"):
        if item != e["capital_item"]:
            return (e, False, f"item {item}, expected {e['capital_item']} (documented exception)")
        note = f"; Wikidata now records it ({how}): the exception can go" if recorded else ""
        return (e, True, f"item {item}, a documented exception{note}")
    if recorded:
        return (e, True, f"item {item}, a current capital of {country} ({how})")
    return (e, False, f"item {item} is no current capital of {country} "
                      f"(P36 of {country}: {', '.join(sorted(p36)) or 'none'})")


# ------------------------------------------------------------------ lookups
def lookup_titles(lang, titles):
    """resolve() for every title, from the live Wikipedia API."""
    info = {}
    for chunk in batches(titles):
        body = api_get(wikipedia(lang), {
            "action": "query", "titles": "|".join(chunk), "redirects": "1",
            "prop": "pageprops", "ppprop": "disambiguation|wikibase_item",
        })
        info.update(resolve(chunk, body.get("query", {})))
    return info


def claims_lookup(today=None):
    """claims(item, prop) -> current values, from the live Wikidata API
    (wbgetclaims, one request per item and property, cached)."""
    cache = {}

    def claims(item, prop):
        if (item, prop) not in cache:
            body = api_get(WIKIDATA, {"action": "wbgetclaims", "entity": item, "property": prop})
            cache[(item, prop)] = current_values(body.get("claims", {}).get(prop, []), today)
        return cache[(item, prop)]
    return claims


def entities(lang, items):
    """{item: {"title": its <lang>wiki article or None, "label", "aliases"}}."""
    out = {}
    for chunk in batches(items):
        body = api_get(WIKIDATA, {
            "action": "wbgetentities", "ids": "|".join(chunk), "props": "sitelinks|labels|aliases",
            "sitefilter": f"{lang}wiki", "languages": lang,
        })
        for q, ent in body.get("entities", {}).items():
            link = ent.get("sitelinks", {}).get(f"{lang}wiki")
            out[q] = {
                "title": link["title"] if link else None,
                "label": ent.get("labels", {}).get(lang, {}).get("value"),
                "aliases": [a["value"] for a in ent.get("aliases", {}).get(lang, [])],
            }
    return out


def items_with(prop, value):
    """Items that have a statement prop = value (Wikidata's search index,
    any rank or date: filter with claims())."""
    body = api_get(WIKIDATA, {"action": "query", "list": "search", "srsearch": f"haswbstatement:{prop}={value}",
                              "srlimit": "50", "srnamespace": "0"})
    return [h["title"] for h in body.get("query", {}).get("search", [])]


def fold(s):
    """Loose comparison key for names: no accents, case, punctuation or a
    qualifier in brackets / after a comma ('Kingston, Jamaica' ~ 'Kingston')."""
    s = re.sub(r"\s*\(.*\)$", "", s or "").split(",")[0]
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.casefold().replace("saint", "st"))


# ------------------------------------------------------------------ entry points
def check(lang, entries, verbose=False, out=sys.stdout, today=None):
    """Checks entries against the live APIs and prints a report; returns
    the number of failed entries."""
    titles = [e["title"] for e in entries if not wiki_title_error(e.get("title"))]
    info = lookup_titles(lang, titles)
    results = evaluate(entries, info, claims_lookup(today))
    failed = [r for r in results if not r[1]]
    for e, ok, msg in results:
        if verbose or not ok or "can go" in msg:
            print(f"{'ok  ' if ok else 'FAIL'} {e['key']}: {e.get('title')!r}: {msg}", file=out)
    day = (today or datetime.date.today()).isoformat()
    print(f"{lang}.wikipedia.org, {day}: {len(results) - len(failed)} of {len(results)} titles verified"
          + (f", {len(failed)} failed" if failed else ""), file=out)
    return len(failed)


def suggest(lang, rows, out=sys.stdout):
    """Proposes titles: rows are dicts with key, item (expected Wikidata
    item), stored (the title stored now, or None) and, for a capital, name
    (the city as the quiz names it) and capital_of instead of item. Prints
    one line per row: the item's own article, or the current capitals of
    capital_of (its P36; where none matches the name, also the items whose
    P1376 names it) with the matching ones marked "*". Returns {key: the
    proposed title, or None where it isn't one clear match}."""
    claims = claims_lookup()
    ents = {}

    def known(qs):
        missing = [q for q in qs if q not in ents]
        if missing:
            ents.update(entities(lang, missing))

    def matching(qs, name):
        want = fold(name)
        return [q for q in qs if want in {fold(ents.get(q, {}).get("title")), fold(ents.get(q, {}).get("label"))}
                | {fold(a) for a in ents.get(q, {}).get("aliases", [])}]
    cands, hits = {}, {}
    known([r["item"] for r in rows if not r.get("capital_of")])
    for r in rows:
        if not r.get("capital_of"):
            cands[r["key"]] = hits[r["key"]] = [r["item"]]
            continue
        c = r["capital_of"]
        qs = sorted(claims(c, "P36"))
        known(qs)
        if not matching(qs, r.get("name")):
            qs += sorted({q for q in items_with("P1376", c) if c in claims(q, "P1376")} - set(qs))
            known(qs)
        cands[r["key"]], hits[r["key"]] = qs, matching(qs, r.get("name"))
    picked = {}
    for r in rows:
        qs, hit = cands[r["key"]], hits[r["key"]]
        pick = ents.get(hit[0], {}).get("title") if len(hit) == 1 else None
        picked[r["key"]] = pick
        listed = ", ".join(f"{q} {ents.get(q, {}).get('title')!r}" + (" *" if q in hit else "") for q in qs)
        same = "" if r.get("stored") is None else (" (= stored)" if r["stored"] == pick else f" (stored: {r['stored']!r})")
        print(f"{r['key']}: {pick!r}{same}  [{listed or 'no candidates'}]", file=out)
    return picked
