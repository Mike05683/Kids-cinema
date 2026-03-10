#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper

Schedule: Wednesday 20:00 UTC and Thursday 00:01 UTC via GitHub Actions.

Weekend date logic:
- Sat/Sun morning     -> show THIS weekend
- Sun after 12pm      -> too early, leave existing JSON untouched
- Mon/Tue             -> too early, leave existing JSON untouched
- Wed/Thu/Fri         -> show NEXT weekend (listings now live)

Cinemas:
- Arc Beeston:           direct HTML scraping
- Savoy Nottingham:      direct HTML scraping
- Showcase Nottingham:   direct HTTP attempt, then SerpAPI fallback
- Showcase Derby:        direct HTTP attempt, then SerpAPI fallback
- Odeon Derby:           direct HTTP attempt (Next.js __NEXT_DATA__), then SerpAPI fallback
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
    Returns the upcoming (or current) Saturday and Sunday.
    - Sat/Sun morning  -> return this weekend
    - Mon/Tue          -> too early (caller checks too_early_to_scrape)
    - Wed/Thu/Fri      -> return next Saturday/Sunday
    """
    today = datetime.today()
    weekday = today.weekday()  # 0=Mon … 5=Sat, 6=Sun

    if weekday == 5:       # Saturday
        saturday = today
    elif weekday == 6:     # Sunday
        saturday = today - timedelta(days=1)
    else:                  # Mon-Fri: find next Saturday
        days_ahead = (5 - weekday) % 7
        saturday = today + timedelta(days=days_ahead)

    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def too_early_to_scrape():
    """
    True if listings for next weekend aren't published yet.
    Listings go live Wednesday evening, so scraping before then is pointless.
    Set FORCE_SCRAPE=1 to bypass (used for manual runs).
    """
    if os.environ.get('FORCE_SCRAPE') == '1':
        print("FORCE_SCRAPE set - skipping early check.")
        return False
    now = datetime.now()
    weekday = now.weekday()
    is_sunday_afternoon = (weekday == 6 and now.hour > 12)
    is_monday_or_tuesday = weekday in (0, 1)
    return is_sunday_afternoon or is_monday_or_tuesday


# ---------------------------------------------------------------------------
# Arc Beeston
# ---------------------------------------------------------------------------

def scrape_arc(saturday, sunday):
    """
    Arc Beeston – all weekend showings (no kids-club-only filter; shows everything).
    Structure:
      ## [FILM TITLE](/event/XXXXX)
      Sat 07 Mar
      **11:00** - 12:48
    """
    results = {'saturday': [], 'sunday': []}
    try:
        r = requests.get(
            'https://beeston.arccinema.co.uk/whatson/',
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_d  = saturday.strftime('%d %b')
        sat_d2 = saturday.strftime('%-d %b')
        sun_d  = sunday.strftime('%d %b')
        sun_d2 = sunday.strftime('%-d %b')

        SKIP_TITLES = {'details', 'book now', 'more info', 'info', 'back', 'next', 'prev'}

        for link in soup.find_all('a', href=re.compile(r'^/event/')):
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

        print(f"Arc Beeston: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")

    except Exception as e:
        print(f"Arc error: {e}")
        import traceback; traceback.print_exc()

    return results


# ---------------------------------------------------------------------------
# Savoy Nottingham
# ---------------------------------------------------------------------------

def scrape_savoy(saturday, sunday):
    """
    Savoy Nottingham kids club page.
    Structure:
      <h3>Film Title</h3>
      <li>Sun 1 Mar
        10:00 KC TC
      </li>

    Fix: The original NAV_WORDS regex used re.search() with broad terms like
    'club', 'screen', 'film', 'event' which matched INSIDE film titles, causing
    valid headings to be silently dropped. Replaced with an exact-match list of
    known navigation phrases.
    """
    results = {'saturday': [], 'sunday': []}
    try:
        r = requests.get(
            'https://savoyonline.co.uk/SavoyNottingham.dll/Page?p=6&m=mm&sp=0',
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_d    = saturday.strftime('%-d %b')
        sat_d2   = saturday.strftime('%d %b')
        sat_long = saturday.strftime('%A')
        sun_d    = sunday.strftime('%-d %b')
        sun_d2   = sunday.strftime('%d %b')
        sun_long = sunday.strftime('%A')

        # Only skip definite navigation/UI items — anchored exact match so
        # film titles containing these words (e.g. "The Baby's Night Out",
        # "Film Stars Don't Die in Liverpool") are NOT incorrectly discarded.
        NAV_EXACT = re.compile(
            r'^(coming soon|visit us?|gift vouchers?|loyalty(?: card)?|'
            r'my basket|your basket|my account|your account|newsletter|'
            r'login|log in|sign in|register|home|contact us?|'
            r'silverscreen club|toddler (tuesday|club)|parent & baby|'
            r'baby cinema|what\'s on|whats on|book (now|tickets))$',
            re.I
        )

        for heading in soup.find_all(['h3', 'h2']):
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
                sat_abbr = saturday.strftime('%a ')   # e.g. "Sat " or "Wed "
                sun_abbr = sunday.strftime('%a ')     # e.g. "Sun " or "Thu "
                if any(x in line for x in [sat_d, sat_d2, sat_long, sat_abbr]):
                    current_day = 'saturday'
                elif any(x in line for x in [sun_d, sun_d2, sun_long, sun_abbr]):
                    current_day = 'sunday'

                # Include any timed showing (no KC-only filter)
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

    Google's showtimes panel is extracted by SerpAPI as response['showtimes'].
    Each entry has 'day' and 'theaters' -> 'showing' -> 'name' / 'time'.
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
            time.sleep(1)  # be polite between API calls

        except Exception as e:
            print(f"  SerpAPI error ({query}, {day_key}): {e}")

    return results


# ---------------------------------------------------------------------------
# Showcase Nottingham & Derby
# ---------------------------------------------------------------------------

def scrape_showcase(saturday, sunday):
    """
    Attempt to scrape Showcase Family Favourites for Nottingham and Derby.

    Strategy:
    1. Fetch the Family Favourites landing page and each cinema's what's-on page.
       Look for embedded JSON (__NEXT_DATA__, JSON-LD) and HTML film cards.
    2. If direct scraping yields nothing (site blocks bots), fall back to
       SerpAPI to get Google's showtimes panel.
    """
    results = {
        'showcase_nottingham': {'saturday': [], 'sunday': []},
        'showcase_derby':      {'saturday': [], 'sunday': []},
    }

    sat_date  = saturday.strftime('%Y-%m-%d')
    sun_date  = sunday.strftime('%Y-%m-%d')
    sat_short = saturday.strftime('%-d %b')
    sun_short = sunday.strftime('%-d %b')

    CINEMAS = {
        'showcase_nottingham': {
            'slug':         'showcase-cinema-de-lux-nottingham',
            'serp_query':   'Family Favourites Showcase Nottingham',
            'serp_filter':  'Showcase',
        },
        'showcase_derby': {
            'slug':         'showcase-derby',
            'serp_query':   'Family Favourites Showcase Derby',
            'serp_filter':  'Showcase',
        },
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    def _try_parse(soup, key):
        """Try all extraction strategies on a BeautifulSoup object."""
        sat_iso, sun_iso = sat_date, sun_date

        # -- Strategy 1: __NEXT_DATA__ embedded JSON --
        script = soup.find('script', id='__NEXT_DATA__')
        if script and script.string:
            try:
                ndata = json.loads(script.string)
                _walk_showcase_json(ndata, sat_iso, sun_iso, results, key)
            except Exception as e:
                print(f"  {key} __NEXT_DATA__ error: {e}")

        # -- Strategy 2: JSON-LD structured data --
        for ld_script in soup.find_all('script', type='application/ld+json'):
            try:
                ld = json.loads(ld_script.string)
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

        # -- Strategy 3: HTML film cards --
        # All film cards (no Family Favourites filter)
        for card in soup.find_all(['article', 'div', 'li'],
                                   class_=re.compile(r'film|card|listing|event', re.I)):
            title_el = card.find(['h2', 'h3', 'h4'])
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if not title or len(title) < 3:
                continue
            for day_key, d_short in [('saturday', sat_short), ('sunday', sun_short)]:
                if d_short in card_text:
                    m = re.search(r'\b(\d{1,2}:\d{2})\b', card_text)
                    results[key][day_key].append(
                        {'title': title, 'time': m.group(1) if m else '10:00', 'price': '£2.49'}
                    )

    # Family Favourites landing page (shows all cinemas)
    try:
        r = session.get('https://www.showcasecinemas.co.uk/family-favourites/', timeout=20)
        print(f"Showcase FF page: HTTP {r.status_code}, {len(r.text)} bytes")
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for key in results:
                _try_parse(soup, key)
    except Exception as e:
        print(f"Showcase FF page error: {e}")

    # Cinema-specific what's-on pages for any cinema still missing data
    for key, cfg in CINEMAS.items():
        if results[key]['saturday'] or results[key]['sunday']:
            continue
        try:
            url = f"https://www.showcasecinemas.co.uk/whats-on/?cinema={cfg['slug']}"
            r = session.get(url, timeout=20)
            print(f"Showcase {key}: HTTP {r.status_code}, {len(r.text)} bytes")
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                _try_parse(soup, key)
        except Exception as e:
            print(f"Showcase {key} error: {e}")

    # SerpAPI fallback for anything still empty
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


def _walk_showcase_json(obj, sat_iso, sun_iso, results, restrict_key):
    """Recursively walk a JSON blob looking for film + sessions structures."""
    if isinstance(obj, dict):
        title = obj.get('title') or obj.get('filmTitle') or obj.get('name') or ''
        sessions = (obj.get('sessions') or obj.get('showings') or
                    obj.get('screenings') or [])
        if title and isinstance(sessions, list) and sessions:
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                start = str(s.get('startTime') or s.get('date') or s.get('time') or '')
                m = re.search(r'T?(\d{1,2}:\d{2})', start)
                time_str = m.group(1) if m else '10:00'
                for day_key, d_iso in [('saturday', sat_iso), ('sunday', sun_iso)]:
                    if d_iso in start:
                        results[restrict_key][day_key].append(
                            {'title': title, 'time': time_str, 'price': '£2.49'}
                        )
        for v in obj.values():
            _walk_showcase_json(v, sat_iso, sun_iso, results, restrict_key)
    elif isinstance(obj, list):
        for item in obj:
            _walk_showcase_json(item, sat_iso, sun_iso, results, restrict_key)


# ---------------------------------------------------------------------------
# Odeon Derby
# ---------------------------------------------------------------------------

def scrape_odeon_derby(saturday, sunday):
    """
    Odeon Derby - Odeon Kids programme.

    Strategy:
    1. Fetch the Odeon Kids page and Derby cinema page.
       Extract __NEXT_DATA__ JSON (Odeon uses Next.js) or JSON-LD.
    2. Fall back to SerpAPI if nothing found.
    """
    results = {'saturday': [], 'sunday': []}
    sat_date = saturday.strftime('%Y-%m-%d')
    sun_date = sunday.strftime('%Y-%m-%d')

    session = requests.Session()
    session.headers.update(HEADERS)

    URLS = [
        'https://www.odeon.co.uk/films/odeon-kids/',
        'https://www.odeon.co.uk/cinemas/derby/161/',
    ]

    for url in URLS:
        if results['saturday'] or results['sunday']:
            break
        try:
            r = session.get(url, timeout=20)
            print(f"Odeon Derby ({url.split('/')[-2]}): HTTP {r.status_code}, {len(r.text)} bytes")
            if r.status_code != 200:
                continue

            soup = BeautifulSoup(r.text, 'html.parser')

            # __NEXT_DATA__
            script = soup.find('script', id='__NEXT_DATA__')
            if script and script.string:
                try:
                    ndata = json.loads(script.string)
                    _walk_odeon_json(ndata, sat_date, sun_date, results)
                    print(f"  After __NEXT_DATA__: Sat={len(results['saturday'])}, "
                          f"Sun={len(results['sunday'])}")
                except Exception as e:
                    print(f"  Odeon __NEXT_DATA__ error: {e}")

            # JSON-LD
            for ld_script in soup.find_all('script', type='application/ld+json'):
                try:
                    ld = json.loads(ld_script.string)
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

        except Exception as e:
            print(f"Odeon Derby fetch error: {e}")

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


def _walk_odeon_json(obj, sat_iso, sun_iso, results):
    """Recursively walk Odeon's Next.js JSON for film + session data for Derby."""
    if isinstance(obj, dict):
        title = obj.get('title') or obj.get('filmTitle') or obj.get('name') or ''
        sessions = (obj.get('sessions') or obj.get('showings') or
                    obj.get('screenings') or obj.get('performances') or [])
        if title and isinstance(sessions, list) and sessions:
            for s in sessions:
                if not isinstance(s, dict):
                    continue
                # Filter to Derby only when cinema info is present
                cinema = str(
                    s.get('cinemaName') or s.get('cinema') or
                    s.get('siteId') or s.get('cinemaId') or ''
                ).lower()
                if cinema and 'derby' not in cinema and '161' not in cinema:
                    continue
                start = str(s.get('startTime') or s.get('date') or s.get('time') or '')
                m = re.search(r'T?(\d{1,2}:\d{2})', start)
                time_str = m.group(1) if m else '10:00'
                for day_key, d_iso in [('saturday', sat_iso), ('sunday', sun_iso)]:
                    if d_iso in start:
                        results[day_key].append(
                            {'title': title, 'time': time_str, 'price': 'Odeon Kids pricing'}
                        )
        for v in obj.values():
            _walk_odeon_json(v, sat_iso, sun_iso, results)
    elif isinstance(obj, list):
        for item in obj:
            _walk_odeon_json(item, sat_iso, sun_iso, results)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now = datetime.now()
    print(f"Run time: {now.strftime('%A %d %b at %H:%M')}")
    print(f"SerpAPI key: {'set' if SERPAPI_KEY else 'NOT SET'}")

    if too_early_to_scrape():
        print("Too early to scrape - next weekend listings not published yet.")
        print("Leaving existing JSON untouched so site shows last weekend's data.")
        return

    saturday, sunday = get_weekend_dates()
    print(f"Weekend: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    arc = scrape_arc(saturday, sunday)
    time.sleep(1)
    savoy = scrape_savoy(saturday, sunday)
    time.sleep(1)
    showcase = scrape_showcase(saturday, sunday)
    time.sleep(1)
    odeon = scrape_odeon_derby(saturday, sunday)

    output = {
        'updated': now.strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday':   sunday.strftime('%a %d %b'),
        },
        'cinemas': {
            'arc_beeston':         arc,
            'showcase_nottingham': showcase['showcase_nottingham'],
            'showcase_derby':      showcase['showcase_derby'],
            'savoy_nottingham':    savoy,
            'odeon_derby':         odeon,
        }
    }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('\nDone!')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
