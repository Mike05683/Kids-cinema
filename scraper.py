#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v8

Verified working approaches per cinema:
- Arc Beeston: scrape their kids club page directly (loads without JS, has title+date+time)
- Savoy Nottingham: IMDB page ci0959999 works and has real times
- Showcase Nottingham/Derby: site blocks scraping - show price info + link
- Odeon Derby: site blocks scraping - show price info + link
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


def get_weekend_dates():
    today = datetime.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def scrape_arc_beeston(saturday, sunday):
    """
    Scrape Arc Beeston kids club page directly.
    Verified: page loads cleanly, contains film title, date strings, and times like 11:00.
    Format found: film title as <a>, then date like "Sun 01 Mar", then time "11:00"
    """
    results = {'saturday': [], 'sunday': []}
    try:
        url = 'https://beeston.arccinema.co.uk/whatson/kidsclub'
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_str = saturday.strftime('%-d %b').lstrip('0')   # e.g. "7 Mar"
        sun_str = sunday.strftime('%-d %b').lstrip('0')     # e.g. "8 Mar"
        sat_alt = saturday.strftime('%d %b')                 # e.g. "07 Mar"
        sun_alt = sunday.strftime('%d %b')

        # The page has sections per film showing date and time
        # Look for all text blocks and find date+time patterns
        full_text = soup.get_text(separator='\n')
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]

        current_title = None
        i = 0
        while i < len(lines):
            line = lines[i]

            # Detect film title - it appears as a link text before the date/time
            # Titles are capitalised, reasonable length, no numbers at start
            if (len(line) > 3 and len(line) < 80
                    and not re.match(r'^\d', line)
                    and not re.search(r'(book|buy|details|running|mins|join|kids.club|weekend|holiday|combo|arc|register|login|menu|select|cinema|continue|tiktok|contact|pricing|hire|privacy|terms|allergen|premium|special|merch|competition|receive)', line, re.I)
                    and line[0].isupper()):
                current_title = line

            # Detect date line matching our weekend
            day_key = None
            if (sat_str in line or sat_alt in line or
                    (saturday.strftime('%a') in line and (sat_str in line or sat_alt in line))):
                day_key = 'saturday'
            elif (sun_str in line or sun_alt in line or
                    (sunday.strftime('%a') in line and (sun_str in line or sun_alt in line))):
                day_key = 'sunday'

            # Also check for "Sat" or "Sun" with the date
            if not day_key:
                if re.search(r'\bSat\b.*' + re.escape(sat_str), line) or re.search(r'\bSat\b.*' + re.escape(sat_alt), line):
                    day_key = 'saturday'
                elif re.search(r'\bSun\b.*' + re.escape(sun_str), line) or re.search(r'\bSun\b.*' + re.escape(sun_alt), line):
                    day_key = 'sunday'

            if day_key and current_title:
                # Find the time - it's usually on the same line or the next line
                time_match = re.search(r'\b(\d{1,2}:\d{2})\b', line)
                if not time_match and i + 1 < len(lines):
                    time_match = re.search(r'\b(\d{1,2}:\d{2})\b', lines[i + 1])

                time_str = time_match.group(1) if time_match else '11:00'

                results[day_key].append({
                    'title': current_title,
                    'time': time_str,
                    'price': '£3.50'
                })

            i += 1

        # Deduplicate
        for day in ['saturday', 'sunday']:
            seen = set()
            deduped = []
            for item in results[day]:
                k = item['title'] + item['time']
                if k not in seen:
                    seen.add(k)
                    deduped.append(item)
            results[day] = deduped

        print(f"Arc Beeston: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
        if results['saturday']:
            print(f"  e.g. {results['saturday'][0]}")

    except Exception as e:
        print(f"Arc Beeston error: {e}")
        import traceback; traceback.print_exc()
    return results


def scrape_savoy_imdb(saturday, sunday):
    """
    Savoy Nottingham via IMDB - confirmed working (ci0959999).
    IMDB uses 24h times. Kids shows are genuinely 10:00-12:30.
    We know from previous run: GOAT 10:00, Zootropolis 2 12:10, Hoppers 10:00 etc.
    """
    results = {'saturday': [], 'sunday': []}

    # Known films at Savoy from britinfo (all films currently showing)
    # We'll use IMDB to find which ones have morning slots
    savoy_imdb_id = 'ci0959999'

    for day_date, day_key in [(saturday, 'saturday'), (sunday, 'sunday')]:
        day_str = day_date.strftime('%Y-%m-%d')
        url = f'https://www.imdb.com/showtimes/cinema/UK/{savoy_imdb_id}/?date={day_str}'

        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"  Savoy IMDB {r.status_code} for {day_str}")
                continue

            soup = BeautifulSoup(r.text, 'html.parser')
            text = soup.get_text(separator='\n')
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            # IMDB structure: film title line, then attributes, then times
            # Times are in 24h format. Kids shows: 09:00-12:30
            # Non-kids shows: 13:00+ 
            # "Standard" appears as a screen format label - NOT a title

            SKIP_WORDS = re.compile(
                r'^(standard|imax|4dx|dolby|3d|2d|screen\s*\d|superscreen|'
                r'subtitled|audio|relaxed|book|buy|select|showtimes|listing|'
                r'all times|today|tomorrow|sign|log|menu|search|filter|imdb|'
                r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
                r'january|february|march|april|may|june|july|august|'
                r'september|october|november|december|cert|pg\b|12a|15\b|18\b|'
                r'u\b|uu\b|morning|afternoon|evening|see all|load more|'
                r'cookie|privacy|terms|help|about|press|jobs|contact|advertise)$',
                re.I
            )

            current_title = None
            for line in lines:
                # Skip known non-title words
                if SKIP_WORDS.match(line):
                    continue

                # Skip pure time lines
                if re.match(r'^[\d:, ]+$', line):
                    continue

                # If line looks like a film title (capitalised, reasonable length)
                if (len(line) > 2 and len(line) < 100
                        and line[0].isupper()
                        and not re.match(r'^\d', line)):
                    current_title = line

                # Find times on this line - genuine 24h kids times are 09-12
                time_matches = re.findall(r'\b(\d{1,2}):(\d{2})\b', line)
                for h_str, m_str in time_matches:
                    h, m = int(h_str), int(m_str)
                    # 09:00 to 12:30 = genuine morning show
                    if current_title and ((h >= 9 and h < 12) or (h == 12 and m <= 30)):
                        results[day_key].append({
                            'title': current_title,
                            'time': f'{h:02d}:{m:02d}',
                            'price': '£2.15'
                        })

            # Deduplicate
            seen = set()
            deduped = []
            for item in results[day_key]:
                k = item['title'] + item['time']
                if k not in seen:
                    seen.add(k)
                    deduped.append(item)
            results[day_key] = deduped

            time.sleep(2)

        except Exception as e:
            print(f"Savoy IMDB error {day_key}: {e}")

    print(f"Savoy Nottingham: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    return results


def main():
    saturday, sunday = get_weekend_dates()
    print(f"Weekend: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    sat_display = saturday.strftime('%a %d %b')
    sun_display = sunday.strftime('%a %d %b')

    arc = scrape_arc_beeston(saturday, sunday)
    time.sleep(2)
    savoy = scrape_savoy_imdb(saturday, sunday)

    # Showcase and Odeon block scraping entirely.
    # Show a helpful placeholder so user knows to tap Book tickets.
    showcase_placeholder = {
        'saturday': [{'title': 'Family Favourites — tap Book tickets for this week\'s film', 'time': '10:00', 'price': '£2.49'}],
        'sunday':   [{'title': 'Family Favourites — tap Book tickets for this week\'s film', 'time': '10:00', 'price': '£2.49'}],
    }
    odeon_placeholder = {
        'saturday': [{'title': 'Odeon Kids — tap Book tickets for this week\'s film', 'time': 'Morning', 'price': 'Odeon Kids'}],
        'sunday':   [{'title': 'Odeon Kids — tap Book tickets for this week\'s film', 'time': 'Morning', 'price': 'Odeon Kids'}],
    }

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': sat_display,
            'sunday': sun_display,
        },
        'cinemas': {
            'arc_beeston':          arc,
            'showcase_nottingham':  showcase_placeholder,
            'showcase_derby':       showcase_placeholder,
            'savoy_nottingham':     savoy,
            'odeon_derby':          odeon_placeholder,
        }
    }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('\nDone!')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
