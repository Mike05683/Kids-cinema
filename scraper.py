#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v7
- Uses britinfo.net to get film titles per cinema (reliable, no JS needed)
- Uses IMDB showtimes pages to get actual times
- Kids club shows are genuinely 10:00-12:30, and IMDB shows them in that range
- The earlier versions failed because hour < 9 shows on IMDB are PM shows stored without AM/PM
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
}

# britinfo.net cinema listing page IDs (confirmed from their Nottingham page)
# IMDB cinema IDs and postcodes for showtime lookups
CINEMAS = {
    'arc_beeston': {
        'name': 'Arc Cinema Beeston',
        'britinfo_id': '1220245',
        'imdb_id': 'ci1025115',
        'imdb_postcode': 'NG91GD',
        'price': '£3.50',
        'url': 'https://beeston.arccinema.co.uk/whatson/kidsclub',
    },
    'showcase_nottingham': {
        'name': 'Showcase Nottingham',
        'britinfo_id': '1003946',
        'imdb_id': 'ci0960030',
        'imdb_postcode': 'NG72UW',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-cinema-de-lux-nottingham',
    },
    'showcase_derby': {
        'name': 'Showcase Derby',
        'britinfo_id': '1151889',
        'imdb_id': 'ci0960015',
        'imdb_postcode': 'DE12PQ',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-derby',
    },
    'savoy_nottingham': {
        'name': 'Savoy Cinema Nottingham',
        'britinfo_id': '1003934',
        'imdb_id': 'ci0959999',
        'imdb_postcode': 'NG71QN',
        'price': '£2.15',
        'url': 'https://savoyonline.co.uk',
    },
    'odeon_derby': {
        'name': 'Odeon Derby',
        'britinfo_id': '1003867',
        'imdb_id': 'ci0959806',
        'imdb_postcode': 'DE214SY',
        'price': 'Odeon Kids',
        'url': 'https://www.odeon.co.uk/cinemas/derby/161/',
    },
}

def get_weekend_dates():
    today = datetime.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def is_kids_time(hour, minute):
    """True if this is a genuine morning kids club time (09:00-12:30)."""
    return (hour >= 9 and hour < 12) or (hour == 12 and minute <= 30)


def get_britinfo_films(britinfo_id):
    """Get list of film titles currently showing at a cinema from britinfo.net."""
    url = f'https://www.britinfo.net/cinema/cinema-listings-{britinfo_id}.htm'
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')

        films = []
        # britinfo lists film titles as links to film pages
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)
            # Film links go to /cinema/film-... paths
            if '/cinema/film-' in href and text and len(text) > 2:
                films.append(text)

        # Deduplicate preserving order
        seen = set()
        unique = []
        for f in films:
            if f not in seen:
                seen.add(f)
                unique.append(f)

        print(f"  britinfo films: {unique[:5]}{'...' if len(unique) > 5 else ''} ({len(unique)} total)")
        return unique
    except Exception as e:
        print(f"  britinfo error: {e}")
        return []


def get_imdb_showtimes(imdb_id, postcode, date_str, known_films):
    """
    Get showtimes from IMDB for a cinema on a given date.
    Only returns times for films in known_films list, and only morning times.
    """
    url = f'https://www.imdb.com/showtimes/cinema/UK/{imdb_id}/UK/{postcode}/?date={date_str}'
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  IMDB returned {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator='\n')
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        results = []
        current_film = None

        # IMDB page format:
        # Film Title
        # ...cert/rating info...
        # Standard
        # 10:00 11:30 14:00 17:00 20:00   <- times on one line or separate
        # OR: 10:00  (each time on its own line)

        i = 0
        while i < len(lines):
            line = lines[i]

            # Check if this line matches a known film title
            for film in known_films:
                if film.lower() in line.lower() or line.lower() in film.lower():
                    if len(line) > 3:
                        current_film = film  # use the canonical title from britinfo
                        break

            # Look for times on this line
            time_matches = re.findall(r'\b(\d{1,2}):(\d{2})\b', line)
            for hour_str, minute_str in time_matches:
                hour = int(hour_str)
                minute = int(minute_str)
                # On IMDB UK pages, times are in 24h but kids shows are always 09-12
                # Evening shows appear as 17:00, 19:30, 20:00 etc - never in 09-12 range
                # So filtering hour 9-12 is safe and correct
                if is_kids_time(hour, minute) and current_film:
                    results.append({
                        'title': current_film,
                        'time': f'{hour:02d}:{minute:02d}'
                    })

            i += 1

        # Deduplicate
        seen = set()
        deduped = []
        for item in results:
            k = item['title'] + item['time']
            if k not in seen:
                seen.add(k)
                deduped.append(item)

        print(f"  IMDB morning shows: {len(deduped)}")
        return deduped

    except Exception as e:
        print(f"  IMDB error: {e}")
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
            'sunday': sunday.strftime('%a %d %b')
        },
        'cinemas': {}
    }

    for key, config in CINEMAS.items():
        print(f"\n=== {config['name']} ===")

        # Step 1: Get film titles from britinfo
        films = get_britinfo_films(config['britinfo_id'])
        time.sleep(1)

        # Step 2: Get Saturday showtimes from IMDB
        print(f"  Saturday ({sat_str}):")
        sat_shows = get_imdb_showtimes(config['imdb_id'], config['imdb_postcode'], sat_str, films)
        time.sleep(2)

        # Step 3: Get Sunday showtimes from IMDB
        print(f"  Sunday ({sun_str}):")
        sun_shows = get_imdb_showtimes(config['imdb_id'], config['imdb_postcode'], sun_str, films)
        time.sleep(2)

        # Add price
        for show in sat_shows + sun_shows:
            show['price'] = config['price']

        # If we got films but no times, show the films with "see website" time
        # so user at least knows what's on
        if films and not sat_shows:
            # Check if britinfo shows any films - if it does, IMDB probably blocked us
            # Show films without times rather than empty
            sat_shows = [{'title': f, 'time': 'See website', 'price': config['price']}
                        for f in films[:5]]
        if films and not sun_shows:
            sun_shows = [{'title': f, 'time': 'See website', 'price': config['price']}
                        for f in films[:5]]

        output['cinemas'][key] = {
            'saturday': sat_shows,
            'sunday': sun_shows
        }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDone!")
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
