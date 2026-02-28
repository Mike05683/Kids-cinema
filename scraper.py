#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v6
Uses IMDB showtimes pages. Fixed title extraction and cinema IDs.
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
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

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

# Words that are NOT film titles - screen formats, UI labels etc
NOT_A_TITLE = re.compile(
    r'^(standard|imax|4dx|screen\s*\d|superscreen|vip|d-box|dolby|3d|2d|'
    r'subtitled|audio.described|relaxed|book|buy|select|all\s*times|'
    r'showtimes|showing|listings|today|tomorrow|monday|tuesday|wednesday|'
    r'thursday|friday|saturday|sunday|january|february|march|april|may|'
    r'june|july|august|september|october|november|december|'
    r'cert|certificate|rating|pg|12a?|15|18|uu|u\b|'
    r'sign\s*in|log\s*in|menu|search|filter|sort|imdb|'
    r'morning|afternoon|evening|night|am|pm)$',
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


def is_morning(time_str):
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
        return (hour >= 9 and hour < 12) or (hour == 12 and minute <= 30)
    except:
        return False


def fmt_time(time_str):
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


def looks_like_title(text):
    """Return True if text looks like a film title."""
    text = text.strip()
    if len(text) < 2 or len(text) > 100:
        return False
    if NOT_A_TITLE.match(text):
        return False
    if re.match(r'^\d', text):  # starts with digit - probably a time or number
        return False
    return True


def scrape_imdb(cinema_id, date_str, cinema_name):
    """Scrape IMDB showtimes and return morning shows."""
    url = f'https://www.imdb.com/showtimes/cinema/UK/{cinema_id}/?date={date_str}'
    print(f"  GET {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f"  Status: {r.status_code}, Size: {len(r.text)} chars")

        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        # Save debug output to help diagnose issues
        debug_path = f"data/debug_{cinema_id}_{date_str}.txt"
        os.makedirs('data', exist_ok=True)
        with open(debug_path, 'w') as f:
            # Write just the text content for debugging
            f.write(soup.get_text(separator='\n'))

        results = []

        # IMDB showtimes page structure:
        # Each film has a container with a link to the film page + showtime buttons
        # Film links go to /title/tt... 
        
        # Find all film title links (they point to /title/tt...)
        film_links = soup.find_all('a', href=re.compile(r'/title/tt\d+'))
        
        seen_titles = {}  # title -> list of times
        
        for link in film_links:
            title = link.get_text(strip=True)
            if not looks_like_title(title):
                continue
            
            # Find the parent container that holds both title and times
            container = link.parent
            for _ in range(6):  # Walk up max 6 levels
                if container is None:
                    break
                container_text = container.get_text()
                # Check if times are in this container
                if re.search(r'\d{1,2}:\d{2}', container_text):
                    break
                container = container.parent

            if container is None:
                continue

            # Extract times from this container
            time_matches = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b', 
                                       container.get_text(), re.I)
            
            for t in time_matches:
                if is_morning(t):
                    if title not in seen_titles:
                        seen_titles[title] = set()
                    seen_titles[title].add(fmt_time(t))

        # Convert to list
        for title, times in seen_titles.items():
            for t in sorted(times):
                results.append({'title': title, 'time': t})

        # If no results from link method, fall back to text parsing
        if not results:
            print("  Link method found nothing, trying text parse...")
            text = soup.get_text(separator='\n')
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            
            current_title = None
            for i, line in enumerate(lines):
                if looks_like_title(line):
                    current_title = line
                
                time_matches = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM)?)\b', line, re.I)
                for t in time_matches:
                    if is_morning(t) and current_title:
                        results.append({
                            'title': current_title,
                            'time': fmt_time(t)
                        })

        # Deduplicate
        seen = set()
        deduped = []
        for item in results:
            k = item['title'] + item['time']
            if k not in seen:
                seen.add(k)
                deduped.append(item)

        print(f"  -> {len(deduped)} morning shows")
        return deduped

    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()
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
        print(f"\n=== {config['name']} ===")

        sat_shows = scrape_imdb(config['imdb_id'], sat_str, config['name'])
        time.sleep(3)
        sun_shows = scrape_imdb(config['imdb_id'], sun_str, config['name'])
        time.sleep(3)

        for show in sat_shows + sun_shows:
            show['price'] = config['price']

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
