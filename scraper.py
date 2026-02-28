#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v5
Uses IMDB showtimes pages with known cinema IDs.
IMDB gets data from The Box Office Company and is reliable.
We scrape the HTML listing pages for Saturday & Sunday morning shows.
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

# IMDB cinema IDs - confirmed from IMDB showtimes URLs
CINEMAS = {
    'arc_beeston': {
        'name': 'Arc Cinema Beeston',
        'imdb_id': 'ci1025115',
        'price': '£3.50',
        'url': 'https://beeston.arccinema.co.uk/whatson/kidsclub',
    },
    'showcase_nottingham': {
        'name': 'Showcase Nottingham',
        'imdb_id': 'ci0960030',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-cinema-de-lux-nottingham',
    },
    'showcase_derby': {
        'name': 'Showcase Derby',
        'imdb_id': 'ci0960015',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-derby',
    },
    'savoy_nottingham': {
        'name': 'Savoy Cinema Nottingham',
        'imdb_id': 'ci0959999',
        'price': '£2.15',
        'url': 'https://savoyonline.co.uk',
    },
    'odeon_derby': {
        'name': 'Odeon Derby',
        'imdb_id': 'ci0959806',
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


def is_morning(time_str):
    """True if time is at or before 12:30pm."""
    try:
        # Handle both 24h (10:00) and 12h (10:00 AM) formats
        time_str = time_str.strip().upper()
        if 'PM' in time_str:
            parts = time_str.replace('PM', '').strip().split(':')
            hour = int(parts[0])
            if hour != 12:
                hour += 12
            minute = int(parts[1]) if len(parts) > 1 else 0
        elif 'AM' in time_str:
            parts = time_str.replace('AM', '').strip().split(':')
            hour = int(parts[0]) % 12
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            parts = time_str.split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        return (hour < 12) or (hour == 12 and minute <= 30)
    except:
        return False


def format_time(time_str):
    """Normalise time to HH:MM 24h format."""
    try:
        time_str = time_str.strip().upper()
        if 'PM' in time_str:
            parts = time_str.replace('PM', '').strip().split(':')
            hour = int(parts[0])
            if hour != 12:
                hour += 12
            minute = int(parts[1]) if len(parts) > 1 else 0
        elif 'AM' in time_str:
            parts = time_str.replace('AM', '').strip().split(':')
            hour = int(parts[0]) % 12
            minute = int(parts[1]) if len(parts) > 1 else 0
        else:
            parts = time_str.split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        return f"{hour:02d}:{minute:02d}"
    except:
        return time_str


def scrape_imdb_showtimes(cinema_id, date_str):
    """
    Scrape IMDB showtimes page for a cinema on a given date.
    Returns list of {'title': ..., 'time': ...} for morning shows.
    date_str format: YYYY-MM-DD
    """
    url = f'https://www.imdb.com/showtimes/cinema/UK/{cinema_id}/?date={date_str}'
    print(f"  Fetching: {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}")
            return []

        soup = BeautifulSoup(r.text, 'html.parser')
        results = []

        # IMDB showtimes structure: each film is in an article or div
        # Film title in h3 or .lister-item-header, times in .showtimes-list or similar
        film_blocks = soup.find_all('div', class_=re.compile(r'list[-_]item|lister[-_]item', re.I))

        if not film_blocks:
            # Try alternative structure
            film_blocks = soup.find_all('article')

        if not film_blocks:
            # Try finding all h3 tags with film titles
            film_blocks = soup.find_all(['div', 'section'], attrs={'data-testid': re.compile(r'film|movie|show', re.I)})

        print(f"  Found {len(film_blocks)} film blocks")

        for block in film_blocks:
            # Get film title
            title_el = (block.find('h3') or
                       block.find('h4') or
                       block.find(class_=re.compile(r'title|name', re.I)))

            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            # Clean up title (remove cert, year etc)
            title = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip()
            title = re.sub(r'\s*(PG|U|12A|15|18)\s*$', '', title).strip()

            if not title or len(title) < 2:
                continue

            # Get times
            times_text = block.get_text()
            time_matches = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b', times_text, re.I)

            for t in time_matches:
                if is_morning(t):
                    results.append({
                        'title': title,
                        'time': format_time(t)
                    })

        # If block parsing failed, try raw text parsing
        if not results:
            print("  Block parsing failed, trying text parse...")
            text = soup.get_text(separator='\n')
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            current_title = None
            for line in lines:
                # Detect film titles: capitalised, reasonable length, not a UI element
                if (len(line) > 3 and len(line) < 100
                        and line[0].isupper()
                        and not re.search(r'(showtimes|book|buy|select|screen|imdb|sign|log|menu|filter|today|tomorrow|back|next|prev)', line, re.I)
                        and not re.search(r'^\d', line)
                        and not re.search(r'(PG|12A|15|18|cert|\bU\b)', line)):
                    current_title = line

                time_matches = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b', line, re.I)
                for t in time_matches:
                    if is_morning(t) and current_title:
                        results.append({
                            'title': current_title,
                            'time': format_time(t)
                        })

        # Deduplicate
        seen = set()
        deduped = []
        for item in results:
            k = item['title'] + item['time']
            if k not in seen:
                seen.add(k)
                deduped.append(item)

        print(f"  -> {len(deduped)} morning shows found")
        return deduped

    except Exception as e:
        print(f"  Error: {e}")
        return []


def main():
    saturday, sunday = get_weekend_dates()
    sat_str = saturday.strftime('%Y-%m-%d')
    sun_str = sunday.strftime('%Y-%m-%d')

    print(f"Scraping for: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday': sunday.strftime('%a %d %b')
        },
        'cinemas': {}
    }

    for key, config in CINEMAS.items():
        print(f"\n{config['name']}:")

        sat_shows = scrape_imdb_showtimes(config['imdb_id'], sat_str)
        time.sleep(2)
        sun_shows = scrape_imdb_showtimes(config['imdb_id'], sun_str)
        time.sleep(2)

        # Add price to each showing
        for show in sat_shows + sun_shows:
            show['price'] = config['price']

        output['cinemas'][key] = {
            'saturday': sat_shows,
            'sunday': sun_shows
        }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Written to data/showings.json")
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
