#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper

Schedule: Every day at 06:00 UTC and 13:00 UTC via GitHub Actions.

Weekend date logic:
- Sat / Sun before 13:05  -> show THIS weekend
- Sun at/after 13:05      -> show NEXT weekend
- Mon–Fri                 -> show NEXT weekend

Cinemas:
- Arc Beeston:           requests first, Playwright fallback (handles CSR)
- Savoy Nottingham:      direct HTML scraping (server-rendered, working)
- Showcase Nottingham:   Playwright primary (Next.js CSR site)
- Showcase Derby:        Playwright primary (Next.js CSR site)
- Odeon Derby:           Playwright primary (Cloudflare bypass attempt), SerpAPI fallback
"""

import json, re, os, time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

SERPAPI_KEY = os.environ.get('SERPAPI_KEY')


# ---------------------------------------------------------------------------
# Date logic
# ---------------------------------------------------------------------------

def get_weekend_dates():
    """
    TEMP (troubleshooting): returns this Tuesday and Wednesday so we can
    verify scraping against dates that definitely have cinema listings.
    Revert to Sat/Sun logic once confirmed working.
    """
    now = datetime.utcnow()
    days_to_tuesday = (1 - now.weekday()) % 7
    if days_to_tuesday == 0:
        days_to_tuesday = 7  # if today is already Tuesday, use next week's
    tuesday = (now + timedelta(days=days_to_tuesday)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    wednesday = tuesday + timedelta(days=1)
    return tuesday, wednesday


# ---------------------------------------------------------------------------
# Playwright helper
# ---------------------------------------------------------------------------

def _playwright_fetch(url, timeout=30000):
    """
    Fetch a URL with headless Chromium, wait for JS to finish loading.
    Returns (html_string, next_data_dict).
    next_data_dict is the parsed window.__NEXT_DATA__ object (empty dict if absent).
    Returns (None, {}) on any failure.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("  Playwright not installed — skipping")
        return None, {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                locale='en-GB',
                extra_http_headers={
                    'Accept-Language': 'en-GB,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                },
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until='networkidle', timeout=timeout)
            except Exception:
                # networkidle can time out on heavy SPAs — fall back to domcontentloaded
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=timeout)
                    page.wait_for_timeout(3000)  # give JS 3 s to render
                except Exception as inner:
                    print(f"  Playwright goto failed for {url}: {inner}")
                    browser.close()
                    return None, {}

            html = page.content()

            # Extract Next.js data store (populated even on CSR pages after hydration)
            try:
                nd_str = page.evaluate('() => JSON.stringify(window.__NEXT_DATA__ || {})')
                nd = json.loads(nd_str)
            except Exception:
                nd = {}

            browser.close()
            print(f"  Playwright OK: {url} — {len(html)} bytes, "
                  f"__NEXT_DATA__ keys={list(nd.get('props', {}).get('pageProps', {}).keys())[:8]}")
            return html, nd

    except Exception as e:
        print(f"  Playwright error on {url}: {e}")
        return None, {}


# ---------------------------------------------------------------------------
# Arc Beeston
# ---------------------------------------------------------------------------

def _parse_arc(soup, saturday, sunday, results):
    """Parse Arc Beeston HTML (works on both requests and Playwright output)."""
    sat_d  = saturday.strftime('%d %b')
    sat_d2 = saturday.strftime('%-d %b')
    sun_d  = sunday.strftime('%d %b')
    sun_d2 = sunday.strftime('%-d %b')

    SKIP_TITLES = {'details', 'book now', 'more info', 'info', 'back', 'next', 'prev'}

    for link in soup.find_all('a', href=re.compile(r'(/event/|arccinema\.co\.uk/event/)')):
        title = link.get_text(strip=True)
        if not title or len(title) < 2 or title.lower() in SKIP_TITLES:
            continue

        container = link
        for _ in range(8):
            container = container.parent
            if container is None:
                break
            ctext = container.get_text(separator=' ')
            if re.search(r'\d{1,2}:\d{2}', ctext) and re.search(
                    r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b', ctext):
                break

        if container is None:
            continue

        ctext = container.get_text(separator=' ')

        for day_key, d1, d2 in [('saturday', sat_d, sat_d2), ('sunday', sun_d, sun_d2)]:
            if d1 in ctext or d2 in ctext:
                t = re.search(r'\b(\d{1,2}:\d{2})\b', ctext)
                time_str = t.group(1) if t else '11:00'
                results[day_key].append({'title': title, 'time': time_str, 'price': '£3.50'})

    for day in ['saturday', 'sunday']:
        seen = set()
        results[day] = [
            x for x in results[day]
            if not (x['title'] + x['time'] in seen or seen.add(x['title'] + x['time']))
        ]


def scrape_arc(saturday, sunday):
    """
    Arc Beeston – try requests on both /kidsclub and /all pages.
    Arc is client-side rendered so requests usually returns minimal HTML;
    Playwright is used as fallback.
    """
    results = {'saturday': [], 'sunday': []}
    # TEMP: use /whatson/all to catch Tue/Wed films (not just kids club)
    urls = [
        'https://beeston.arccinema.co.uk/whatson/all',
        'https://beeston.arccinema.co.uk/whatson/kidsclub',
    ]

    for url in urls:
        if results['saturday'] or results['sunday']:
            break
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"Arc Beeston requests {url.split('/')[-1]}: HTTP {r.status_code}, {len(r.text)} bytes")
            if r.status_code == 200:
                _parse_arc(BeautifulSoup(r.text, 'html.parser'), saturday, sunday, results)
        except Exception as e:
            print(f"Arc requests error ({url}): {e}")

    if not results['saturday'] and not results['sunday']:
        print("Arc Beeston: 0 results from requests — trying Playwright on /whatson/all...")
        html, _ = _playwright_fetch('https://beeston.arccinema.co.uk/whatson/all')
        if html:
            print(f"Arc Playwright HTML snippet: {html[:500]!r}")
            _parse_arc(BeautifulSoup(html, 'html.parser'), saturday, sunday, results)

    print(f"Arc Beeston: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    return results


# ---------------------------------------------------------------------------
# Savoy Nottingham
# ---------------------------------------------------------------------------

def scrape_savoy(saturday, sunday):
    """
    Savoy Nottingham kids club page — direct HTML scraping (server-rendered, working).
    """
    results = {'saturday': [], 'sunday': []}
    # TEMP: try general whatson page first (has Tue/Wed films); kids-club page is Sat-only
    savoy_urls = [
        'https://savoyonline.co.uk/SavoyNottingham.dll/WhatsOn',
        'https://savoyonline.co.uk/SavoyNottingham.dll/Page?p=6&m=mm&sp=0',
    ]
    try:
        soup = None
        for url in savoy_urls:
            r = requests.get(url, headers=HEADERS, timeout=15)
            print(f"Savoy {url.split('/')[-1]}: HTTP {r.status_code}, {len(r.text)} bytes")
            if r.status_code == 200 and len(r.text) > 500:
                soup = BeautifulSoup(r.text, 'html.parser')
                break
        if soup is None:
            print("Savoy: all URLs failed")
            return results

        # Log all headings found so we can debug structure changes
        all_headings = [h.get_text(strip=True) for h in soup.find_all(['h2', 'h3', 'h4'])]
        print(f"Savoy headings found: {all_headings[:20]}")

        sat_d    = saturday.strftime('%-d %b')
        sat_d2   = saturday.strftime('%d %b')
        sat_long = saturday.strftime('%A')
        sun_d    = sunday.strftime('%-d %b')
        sun_d2   = sunday.strftime('%d %b')
        sun_long = sunday.strftime('%A')
        print(f"Savoy looking for dates: day1='{sat_d}'/'{sat_long}', day2='{sun_d}'/'{sun_long}'")

        NAV_EXACT = re.compile(
            r'^(coming soon|visit us?|gift vouchers?|loyalty(?: card)?|'
            r'my basket|your basket|my account|your account|newsletter|'
            r'login|log in|sign in|register|home|contact us?|'
            r'silverscreen club|toddler (tuesday|club)|parent & baby|'
            r'baby cinema|what\'s on|whats on|book (now|tickets))$',
            re.I
        )

        for heading in soup.find_all(['h2', 'h3', 'h4']):
            title = heading.get_text(strip=True)
            if not title or len(title) < 3 or NAV_EXACT.search(title):
                continue

            section = (
                heading.find_parent(['div', 'article', 'section', 'td', 'li'])
                or heading.parent
            )
            section_text = section.get_text(separator='\n')
            lines = [l.strip() for l in section_text.split('\n') if l.strip()]

            current_day = None
            for line in lines:
                sat_abbr = saturday.strftime('%a ')
                sun_abbr = sunday.strftime('%a ')
                if any(x in line for x in [sat_d, sat_d2, sat_long, sat_abbr]):
                    current_day = 'saturday'
                elif any(x in line for x in [sun_d, sun_d2, sun_long, sun_abbr]):
                    current_day = 'sunday'

                if current_day and re.search(r'\b\d{1,2}:\d{2}\b', line):
                    for t in re.findall(r'\b(\d{1,2}:\d{2})\b', line):
                        results[current_day].append(
                            {'title': title, 'time': t, 'price': '£3.00'}
                        )

        for day in ['saturday', 'sunday']:
            seen = set()
            results[day] = [
                x for x in results[day]
                if not (x['title'] + x['time'] in seen or seen.add(x['title'] + x['time']))
            ]

        print(f"Savoy Nottingham: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")

    except Exception as e:
        print(f"Savoy error: {e}")
        import traceback; traceback.print_exc()

    return results


# ---------------------------------------------------------------------------
# SerpAPI helper (shared by Showcase + Odeon)
# ---------------------------------------------------------------------------

def _serpapi_showtimes(query, cinema_name_fragment, saturday, sunday, price, morning_only=True):
    """
    Query SerpAPI's Google engine for cinema showtimes.
    Returns {'saturday': [...], 'sunday': [...]} or None if key not set.
    """
    if not SERPAPI_KEY:
        return None

    results = {'saturday': [], 'sunday': []}

    for day_key, target_date in [('saturday', saturday), ('sunday', sunday)]:
        try:
            date_str = target_date.strftime('%A %-d %B %Y')
            params = {
                'engine': 'google',
                'q': f'{query} {date_str}',
                'api_key': SERPAPI_KEY,
                'hl': 'en',
                'gl': 'gb',
            }
            r = requests.get('https://serpapi.com/search', params=params, timeout=25)
            if r.status_code != 200:
                print(f"  SerpAPI HTTP {r.status_code} for '{query} {date_str}'")
                continue

            data = r.json()

            for day_entry in data.get('showtimes', []):
                for theater in day_entry.get('theaters', []):
                    t_name = theater.get('name', '')
                    if cinema_name_fragment.lower() not in t_name.lower():
                        continue
                    for showing in theater.get('showing', []):
                        title = showing.get('name', '').strip()
                        for raw_time in showing.get('time', []):
                            m = re.search(r'(\d{1,2}):(\d{2})', raw_time)
                            if not m:
                                continue
                            hour = int(m.group(1))
                            if 'PM' in raw_time.upper() and hour != 12:
                                hour += 12
                            if morning_only and hour >= 13:
                                continue
                            time_str = f'{hour:02d}:{m.group(2)}'
                            results[day_key].append(
                                {'title': title, 'time': time_str, 'price': price}
                            )

            print(f"  SerpAPI '{query}' {day_key}: {len(results[day_key])} result(s)")
            time.sleep(1)

        except Exception as e:
            print(f"  SerpAPI error ({query}, {day_key}): {e}")

    return results


# ---------------------------------------------------------------------------
# Showcase Nottingham & Derby
# ---------------------------------------------------------------------------

def _walk_showcase_json(obj, sat_iso, sun_iso, results, restrict_key):
    """Recursively walk a JSON blob looking for film + session structures."""
    if isinstance(obj, dict):
        title = (obj.get('title') or obj.get('filmTitle') or obj.get('name')
                 or obj.get('movieTitle') or obj.get('film') or '')
        sessions = (
            obj.get('sessions') or obj.get('showings') or obj.get('screenings')
            or obj.get('performances') or obj.get('showtimes') or obj.get('times') or []
        )
        if title and isinstance(sessions, list) and sessions:
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                start = str(s.get('startTime') or s.get('date') or s.get('time')
                            or s.get('dateTime') or s.get('showTime') or '')
                m = re.search(r'T?(\d{1,2}:\d{2})', start)
                time_str = m.group(1) if m else '10:00'
                for day_key, d_iso in [('saturday', sat_iso), ('sunday', sun_iso)]:
                    if d_iso in start:
                        results[restrict_key][day_key].append(
                            {'title': str(title), 'time': time_str, 'price': '£2.49'}
                        )
        for v in obj.values():
            _walk_showcase_json(v, sat_iso, sun_iso, results, restrict_key)
    elif isinstance(obj, list):
        for item in obj:
            _walk_showcase_json(item, sat_iso, sun_iso, results, restrict_key)


def _parse_showcase_html(soup, key, saturday, sunday, results):
    """Parse rendered Showcase HTML for film cards (post-JS-render fallback)."""
    sat_short = saturday.strftime('%-d %b')
    sun_short = sunday.strftime('%-d %b')
    sat_iso   = saturday.strftime('%Y-%m-%d')
    sun_iso   = sunday.strftime('%Y-%m-%d')

    # JSON-LD structured data
    for ld_script in soup.find_all('script', type='application/ld+json'):
        try:
            ld = json.loads(ld_script.string or '')
            for item in (ld if isinstance(ld, list) else [ld]):
                if item.get('@type') in ('ScreeningEvent', 'Movie', 'Event'):
                    title = item.get('name', '')
                    start = str(item.get('startDate', ''))
                    m = re.search(r'T(\d{2}:\d{2})', start)
                    if title and m:
                        for day_key, d_iso in [('saturday', sat_iso), ('sunday', sun_iso)]:
                            if d_iso in start:
                                results[key][day_key].append(
                                    {'title': title, 'time': m.group(1), 'price': '£2.49'}
                                )
        except Exception:
            pass

    # HTML film cards
    for card in soup.find_all(['article', 'div', 'li'],
                               class_=re.compile(r'film|card|listing|event|movie', re.I)):
        title_el = card.find(['h2', 'h3', 'h4'])
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        card_text = card.get_text(separator=' ')
        for day_key, d_short in [('saturday', sat_short), ('sunday', sun_short)]:
            if d_short in card_text:
                m = re.search(r'\b(\d{1,2}:\d{2})\b', card_text)
                results[key][day_key].append(
                    {'title': title, 'time': m.group(1) if m else '10:00', 'price': '£2.49'}
                )


def scrape_showcase(saturday, sunday):
    """
    Showcase Nottingham and Derby — Playwright primary (Next.js CSR site).

    After full JS load we extract window.__NEXT_DATA__ via page.evaluate(),
    which gives us the React page props (including film/session arrays) regardless
    of how the component fetches them.  Rendered HTML is parsed as a secondary path.
    SerpAPI is the final fallback if SERPAPI_KEY is set.
    """
    results = {
        'showcase_nottingham': {'saturday': [], 'sunday': []},
        'showcase_derby':      {'saturday': [], 'sunday': []},
    }

    sat_date = saturday.strftime('%Y-%m-%d')
    sun_date = sunday.strftime('%Y-%m-%d')

    CINEMAS = {
        'showcase_nottingham': {
            'url':         'https://www.showcasecinemas.co.uk/showtimes/showcase-cinema-de-lux-nottingham',
            'serp_query':  'Family Favourites Showcase Nottingham',
            'serp_filter': 'Showcase',
        },
        'showcase_derby': {
            'url':         'https://www.showcasecinemas.co.uk/showtimes/showcase-cinema-de-lux-derby',
            'serp_query':  'Family Favourites Showcase Derby',
            'serp_filter': 'Showcase',
        },
    }

    # 1. Try Family Favourites landing pages via Playwright
    for ff_url in [
        'https://www.showcasecinemas.co.uk/family-favourites/',
        'https://www.showcasecinemas.co.uk/showcase-family/',
    ]:
        html, nd = _playwright_fetch(ff_url)
        label = ff_url.rstrip('/').split('/')[-1]
        if nd and nd != {}:
            for key in results:
                _walk_showcase_json(nd, sat_date, sun_date, results, key)
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            for key in results:
                _parse_showcase_html(soup, key, saturday, sunday, results)

    # 2. Cinema-specific showtimes pages via Playwright for any still empty
    for key, cfg in CINEMAS.items():
        if results[key]['saturday'] or results[key]['sunday']:
            continue
        html, nd = _playwright_fetch(cfg['url'])
        if nd and nd != {}:
            _walk_showcase_json(nd, sat_date, sun_date, results, key)
        if html and not (results[key]['saturday'] or results[key]['sunday']):
            soup = BeautifulSoup(html, 'html.parser')
            _parse_showcase_html(soup, key, saturday, sunday, results)

    # 3. SerpAPI fallback
    if SERPAPI_KEY:
        for key, cfg in CINEMAS.items():
            if results[key]['saturday'] or results[key]['sunday']:
                continue
            print(f"Showcase {key}: trying SerpAPI fallback...")
            serp = _serpapi_showtimes(
                cfg['serp_query'], cfg['serp_filter'], saturday, sunday, '£2.49'
            )
            if serp:
                results[key] = serp
    else:
        print("SERPAPI_KEY not set — skipping SerpAPI fallback for Showcase")

    # Deduplicate
    for key in results:
        for day in ['saturday', 'sunday']:
            seen = set()
            results[key][day] = [
                x for x in results[key][day]
                if not (x['title'] + x['time'] in seen or seen.add(x['title'] + x['time']))
            ]
        print(f"Showcase {key}: Sat={len(results[key]['saturday'])}, Sun={len(results[key]['sunday'])}")

    return results


# ---------------------------------------------------------------------------
# Odeon Derby
# ---------------------------------------------------------------------------

def _walk_odeon_json(obj, sat_iso, sun_iso, results):
    """Recursively walk Odeon's JSON for film + session data, filtered to Derby."""
    if isinstance(obj, dict):
        title = (obj.get('title') or obj.get('filmTitle') or obj.get('name')
                 or obj.get('movieTitle') or '')
        sessions = (
            obj.get('sessions') or obj.get('showings') or obj.get('screenings')
            or obj.get('performances') or obj.get('showtimes') or []
        )
        if title and isinstance(sessions, list) and sessions:
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                cinema = str(
                    s.get('cinemaName') or s.get('cinema') or
                    s.get('siteId') or s.get('cinemaId') or ''
                ).lower()
                if cinema and 'derby' not in cinema and '161' not in cinema:
                    continue
                start = str(s.get('startTime') or s.get('date') or s.get('time')
                            or s.get('dateTime') or s.get('showTime') or '')
                m = re.search(r'T?(\d{1,2}:\d{2})', start)
                time_str = m.group(1) if m else '10:00'
                for day_key, d_iso in [('saturday', sat_iso), ('sunday', sun_iso)]:
                    if d_iso in start:
                        results[day_key].append(
                            {'title': str(title), 'time': time_str,
                             'price': 'Odeon Kids pricing'}
                        )
        for v in obj.values():
            _walk_odeon_json(v, sat_iso, sun_iso, results)
    elif isinstance(obj, list):
        for item in obj:
            _walk_odeon_json(item, sat_iso, sun_iso, results)


def scrape_odeon_derby(saturday, sunday):
    """
    Odeon Derby — Playwright primary (attempts to bypass Cloudflare bot protection
    by presenting a real browser fingerprint).  SerpAPI fallback if still blocked.
    """
    results = {'saturday': [], 'sunday': []}
    sat_date = saturday.strftime('%Y-%m-%d')
    sun_date = sunday.strftime('%Y-%m-%d')

    URLS = [
        'https://www.odeon.co.uk/films/odeon-kids/',
        'https://www.odeon.co.uk/cinemas/derby/161/',
    ]

    for url in URLS:
        if results['saturday'] or results['sunday']:
            break
        html, nd = _playwright_fetch(url)
        label = url.rstrip('/').split('/')[-2]
        if not html:
            print(f"Odeon Derby ({label}): Playwright blocked/failed")
            continue
        print(f"Odeon Derby ({label}): {len(html)} bytes")

        if nd and nd != {}:
            _walk_odeon_json(nd, sat_date, sun_date, results)

        if not (results['saturday'] or results['sunday']):
            soup = BeautifulSoup(html, 'html.parser')
            # JSON-LD
            for ld_script in soup.find_all('script', type='application/ld+json'):
                try:
                    ld = json.loads(ld_script.string or '')
                    for item in (ld if isinstance(ld, list) else [ld]):
                        title = item.get('name', '')
                        start = str(item.get('startDate', ''))
                        m = re.search(r'T(\d{2}:\d{2})', start)
                        if title and m:
                            for day_key, d_iso in [('saturday', sat_date), ('sunday', sun_date)]:
                                if d_iso in start:
                                    results[day_key].append(
                                        {'title': title, 'time': m.group(1),
                                         'price': 'Odeon Kids pricing'}
                                    )
                except Exception:
                    pass

    # SerpAPI fallback
    if SERPAPI_KEY and not (results['saturday'] or results['sunday']):
        print("Odeon Derby: trying SerpAPI fallback...")
        serp = _serpapi_showtimes(
            'Odeon Kids Derby', 'Odeon', saturday, sunday, 'Odeon Kids pricing'
        )
        if serp:
            results = serp
    elif not SERPAPI_KEY:
        print("SERPAPI_KEY not set — skipping SerpAPI fallback for Odeon")

    # Deduplicate
    for day in ['saturday', 'sunday']:
        seen = set()
        results[day] = [
            x for x in results[day]
            if not (x['title'] + x['time'] in seen or seen.add(x['title'] + x['time']))
        ]

    print(f"Odeon Derby: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.utcnow()
    print(f"Run time: {now.strftime('%A %d %b at %H:%M UTC')}")
    print(f"SerpAPI key: {'set' if SERPAPI_KEY else 'NOT SET'}")

    saturday, sunday = get_weekend_dates()
    print(f"Weekend: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    arc = scrape_arc(saturday, sunday)
    time.sleep(1)
    savoy = scrape_savoy(saturday, sunday)
    time.sleep(1)
    showcase = scrape_showcase(saturday, sunday)
    time.sleep(1)
    odeon = scrape_odeon_derby(saturday, sunday)

    cinemas = {
        'arc_beeston':         arc,
        'showcase_nottingham': showcase['showcase_nottingham'],
        'showcase_derby':      showcase['showcase_derby'],
        'savoy_nottingham':    savoy,
        'odeon_derby':         odeon,
    }

    total = sum(
        len(v['saturday']) + len(v['sunday'])
        for v in cinemas.values()
    )

    if total == 0:
        print("No showings found for any cinema — listings may not be live yet.")
        print("Writing empty JSON so Pages always rebuilds with a fresh timestamp.")

    output = {
        'updated': now.strftime('%a %d %b %Y at %H:%M UTC'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday':   sunday.strftime('%a %d %b'),
        },
        'cinemas': cinemas,
    }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('\nDone!')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
