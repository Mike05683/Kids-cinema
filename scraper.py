#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v9

Key insight from inspecting real IMDB page content:
- Times appear as "11:10 AM", "12:10 PM" (12-hour AM/PM format)
- "Mark as watched" appears repeatedly - NOT a film title
- "Rate" appears as button text - NOT a film title  
- "Standard:" appears before each time block - NOT a film title
- Film titles come BEFORE the rating/runtime info
- IMDB URL format: /showtimes/cinema/UK/{id}/UK/{postcode_prefix}/

Arc Beeston: confirmed 11:10 AM morning show visible in search results
Savoy: confirmed working previously with 10:00, 11:15, 12:10 etc
"""

import json
import re
import os
import time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

# Confirmed IMDB IDs and correct postcode prefix format
CINEMAS = {
    'arc_beeston': {
        'name': 'Arc Cinema Beeston',
        'imdb_id': 'ci1025115',
        'postcode': 'NG9',
        'price': '£3.50',
        'url': 'https://beeston.arccinema.co.uk/whatson/kidsclub',
    },
    'showcase_nottingham': {
        'name': 'Showcase Nottingham',
        'imdb_id': 'ci0960030',
        'postcode': 'NG7',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-cinema-de-lux-nottingham',
    },
    'showcase_derby': {
        'name': 'Showcase Derby',
        'imdb_id': 'ci0960015',
        'postcode': 'DE1',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-derby',
    },
    'savoy_nottingham': {
        'name': 'Savoy Cinema Nottingham',
        'imdb_id': 'ci0959999',
        'postcode': 'NG1',
        'price': '£2.15',
        'url': 'https://savoyonline.co.uk',
    },
    'odeon_derby': {
        'name': 'Odeon Derby',
        'imdb_id': 'ci0959806',
        'postcode': 'DE1',
        'price': 'Odeon Kids',
        'url': 'https://www.odeon.co.uk/cinemas/derby/161/',
    },
}

# Lines that are definitely NOT film titles
NOT_TITLE = re.compile(
    r'^(standard|imax|4dx|dolby|3d|2d|superscreen|vip|d-box|'
    r'subtitled|audio.described|relaxed|sensory|'
    r'mark as watched|rate|ratemark|add to watchlist|'
    r'book|buy|select|tickets|see all times|load more|'
    r'showtimes|listings|all times|choose date|'
    r'today|tomorrow|'
    r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
    r'january|february|march|april|may|june|july|august|'
    r'september|october|november|december|'
    r'cert|certificate|pg\b|12a?|15\b|18\b|u\b|uu\b|r\b|'
    r'sign in|log in|register|menu|search|filter|sort|'
    r'imdb|amazon|privacy|terms|help|about|contact|jobs|press|'
    r'morning|afternoon|evening|night|'
    r'running time|mins|minutes|watch trailer|details|'
    r'\d+h\s*\d+m|\d+\s*mins?)$',
    re.I
)


def get_weekend_dates():
    today = datetime.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def parse_ampm_time(time_str):
    """
    Parse a 12-hour AM/PM time string and return (hour_24, minute, formatted_str).
    e.g. "11:10 AM" -> (11, 10, "11:10")
         "12:10 PM" -> (12, 10, "12:10")
         "1:30 PM"  -> (13, 30, "13:30")
    Returns None if can't parse.
    """
    time_str = time_str.strip().upper()
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str)
    if not m:
        return None
    h, mn, period = int(m.group(1)), int(m.group(2)), m.group(3)
    if period == 'AM':
        h = h % 12  # 12 AM -> 0, rest stay same
    else:
        if h != 12:
            h += 12  # 1 PM -> 13, 12 PM -> 12
    return (h, mn, f'{h:02d}:{mn:02d}')


def is_morning_show(h, mn):
    """True if time is between 09:00 and 12:30 - the kids club window."""
    return (h >= 9 and h < 12) or (h == 12 and mn <= 30)


def scrape_imdb(cinema_id, postcode, date_str, cinema_name, price):
    """Scrape IMDB showtimes page for morning shows on a given date."""
    url = f'https://www.imdb.com/showtimes/cinema/UK/{cinema_id}/UK/{postcode}/?date={date_str}'
    print(f"  GET {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f"  Status: {r.status_code}, Size: {len(r.text)}")
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        # Save raw text for debugging
        raw_text = soup.get_text(separator='\n')
        debug_file = f"data/debug_{cinema_id}_{date_str}.txt"
        os.makedirs('data', exist_ok=True)
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(raw_text)

        lines = [l.strip() for l in raw_text.split('\n') if l.strip()]

        results = []
        current_title = None

        for line in lines:
            # Skip known non-title lines
            if NOT_TITLE.match(line):
                continue

            # Skip pure numbers/times/punctuation
            if re.match(r'^[\d\s:.,\-/()]+$', line):
                continue

            # Check if line contains AM/PM times
            time_matches = re.findall(r'\d{1,2}:\d{2}\s*(?:AM|PM)', line, re.I)

            if time_matches:
                # This line has times - pair with current title
                if current_title:
                    for t in time_matches:
                        parsed = parse_ampm_time(t)
                        if parsed:
                            h, mn, fmt = parsed
                            if is_morning_show(h, mn):
                                results.append({
                                    'title': current_title,
                                    'time': fmt,
                                    'price': price
                                })
            else:
                # Potential film title line
                if (len(line) > 2 and len(line) < 100
                        and line[0].isupper()
                        and not re.match(r'^\d', line)):
                    current_title = line

        # Deduplicate
        seen = set()
        deduped = []
        for item in results:
            k = item['title'] + item['time']
            if k not in seen:
                seen.add(k)
                deduped.append(item)

        print(f"  -> {len(deduped)} morning shows found")
        if deduped:
            for d in deduped:
                print(f"     {d['title']} @ {d['time']}")
        return deduped

    except Exception as e:
        print(f"  Error: {e}")
        import traceback; traceback.print_exc()
        return []


def main():
    saturday, sunday = get_weekend_dates()
    sat_str = saturday.strftime('%Y-%m-%d')
    sun_str = sunday.strftime('%Y-%m-%d')

    print(f"Weekend: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday': sunday.strftime('%a %d %b'),
        },
        'cinemas': {}
    }

    for key, config in CINEMAS.items():
        print(f"\n=== {config['name']} ===")

        sat_shows = scrape_imdb(config['imdb_id'], config['postcode'],
                                sat_str, config['name'], config['price'])
        time.sleep(3)
        sun_shows = scrape_imdb(config['imdb_id'], config['postcode'],
                                sun_str, config['name'], config['price'])
        time.sleep(3)

        output['cinemas'][key] = {
            'saturday': sat_shows,
            'sunday': sun_shows,
        }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('\nDone!')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
