#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper - SerpApi version
Uses Google search via SerpApi to find kids club showings for each cinema.
"""

import json
import re
import os
import time
from datetime import datetime, timedelta
import requests

SERP_API_KEY = os.environ.get('SERP_API_KEY', '')


def get_weekend_dates():
    today = datetime.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def google_search(query):
    """Search Google via SerpApi and return results."""
    params = {
        'q': query,
        'api_key': SERP_API_KEY,
        'engine': 'google',
        'gl': 'uk',
        'hl': 'en',
        'num': 10,
    }
    try:
        r = requests.get('https://serpapi.com/search', params=params, timeout=20)
        data = r.json()
        return data
    except Exception as e:
        print(f"  SerpApi error: {e}")
        return {}


def extract_showings_from_results(data, saturday, sunday, price, cinema_name):
    """
    Extract film titles and times from Google search results.
    Looks in: knowledge graph, showtimes panel, organic results snippets.
    """
    results = {'saturday': [], 'sunday': []}

    sat_str = saturday.strftime('%d %B')       # "07 March"
    sun_str = sunday.strftime('%d %B')         # "08 March"
    sat_short = saturday.strftime('%-d %b')    # "7 Mar"
    sun_short = sunday.strftime('%-d %b')      # "8 Mar"
    sat_day = saturday.strftime('%A')          # "Saturday"
    sun_day = sunday.strftime('%A')            # "Sunday"

    def matches_saturday(text):
        return any(x in text for x in [sat_str, sat_short, sat_day, 'Sat '])

    def matches_sunday(text):
        return any(x in text for x in [sun_str, sun_short, sun_day, 'Sun '])

    def extract_times_and_films(text):
        """Pull film title + time pairs from a block of text."""
        found = []
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        current_title = None

        SKIP = re.compile(
            r'^(book|buy|select|standard|imax|cert|pg\b|12a|15\b|18\b|u\b|'
            r'mark as watched|rate|add to|see all|load more|tickets|'
            r'monday|tuesday|wednesday|thursday|friday|saturday|sunday|'
            r'today|tomorrow|morning|afternoon|evening|'
            r'kids club|family favourites|odeon kids|'
            r'running time|\d+\s*mins?|\d+h\s*\d+m)$',
            re.I
        )

        for line in lines:
            if SKIP.match(line):
                continue

            # Check for time patterns (both 12h and 24h)
            times_12h = re.findall(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b', line, re.I)
            times_24h = re.findall(r'\b(\d{1,2}:\d{2})\b', line)

            all_times = []
            for t in times_12h:
                parsed = parse_time(t)
                if parsed and is_morning(*parsed[:2]):
                    all_times.append(parsed[2])
            if not times_12h:
                for t in times_24h:
                    h, m = int(t.split(':')[0]), int(t.split(':')[1])
                    if is_morning(h, m):
                        all_times.append(f'{h:02d}:{m:02d}')

            if all_times and current_title:
                for t in all_times:
                    found.append({'title': current_title, 'time': t})
            elif (len(line) > 3 and len(line) < 100
                  and line[0].isupper()
                  and not re.match(r'^\d', line)):
                current_title = line

        return found

    # Check showtimes panel (Google's built-in cinema widget)
    showtimes = data.get('showtimes', [])
    for day_block in showtimes:
        day_name = day_block.get('day', '')
        is_sat = sat_day in day_name or sat_short in day_name
        is_sun = sun_day in day_name or sun_short in day_name
        if not is_sat and not is_sun:
            continue

        day_key = 'saturday' if is_sat else 'sunday'
        movies = day_block.get('movies', [])
        for movie in movies:
            title = movie.get('name', '')
            for showing in movie.get('showing', []):
                for t in showing.get('time', []):
                    parsed = parse_time(t)
                    if parsed and is_morning(*parsed[:2]):
                        results[day_key].append({
                            'title': title,
                            'time': parsed[2],
                            'price': price
                        })

    # Check knowledge graph
    kg = data.get('knowledge_graph', {})
    kg_text = json.dumps(kg)
    if cinema_name.lower() in kg_text.lower():
        found = extract_times_and_films(kg_text)
        for item in found:
            text_context = kg_text
            if matches_saturday(text_context):
                results['saturday'].append({**item, 'price': price})
            elif matches_sunday(text_context):
                results['sunday'].append({**item, 'price': price})

    # Check organic results snippets
    organic = data.get('organic_results', [])
    for result in organic:
        snippet = result.get('snippet', '')
        title_text = result.get('title', '')
        combined = snippet + ' ' + title_text

        found = extract_times_and_films(snippet)
        for item in found:
            if matches_saturday(combined):
                results['saturday'].append({**item, 'price': price})
            elif matches_sunday(combined):
                results['sunday'].append({**item, 'price': price})

    # Deduplicate each day
    for day in ['saturday', 'sunday']:
        seen = set()
        deduped = []
        for item in results[day]:
            k = item['title'] + item['time']
            if k not in seen:
                seen.add(k)
                deduped.append(item)
        results[day] = deduped

    return results


def parse_time(time_str):
    """Parse 12h or 24h time. Returns (hour, minute, formatted) or None."""
    time_str = str(time_str).strip().upper()
    # 12h AM/PM
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str)
    if m:
        h, mn, period = int(m.group(1)), int(m.group(2)), m.group(3)
        if period == 'AM':
            h = h % 12
        else:
            if h != 12:
                h += 12
        return (h, mn, f'{h:02d}:{mn:02d}')
    # 24h
    m = re.match(r'(\d{1,2}):(\d{2})', time_str)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        return (h, mn, f'{h:02d}:{mn:02d}')
    return None


def is_morning(h, mn):
    return (h >= 9 and h < 12) or (h == 12 and mn <= 30)


def search_cinema(cinema_name, location, price, saturday, sunday):
    """Run targeted Google searches for a cinema's kids showings."""
    sat_date = saturday.strftime('%-d %B %Y')
    sun_date = sunday.strftime('%-d %B %Y')

    results = {'saturday': [], 'sunday': []}

    # Search queries to try
    queries = [
        f'{cinema_name} kids club {sat_date} {sun_date}',
        f'{cinema_name} family favourites {sat_date} showings',
        f'{cinema_name} kids morning showing {saturday.strftime("%B %Y")}',
    ]

    for query in queries:
        print(f"  Searching: {query}")
        data = google_search(query)
        found = extract_showings_from_results(data, saturday, sunday, price, cinema_name)

        results['saturday'].extend(found['saturday'])
        results['sunday'].extend(found['sunday'])

        if results['saturday'] or results['sunday']:
            break  # Got results, no need to try more queries

        time.sleep(2)

    # Final dedup
    for day in ['saturday', 'sunday']:
        seen = set()
        deduped = []
        for item in results[day]:
            k = item['title'] + item['time']
            if k not in seen:
                seen.add(k)
                deduped.append(item)
        results[day] = deduped

    print(f"  {cinema_name}: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    return results


def main():
    if not SERP_API_KEY:
        print("ERROR: SERP_API_KEY environment variable not set!")
        exit(1)

    saturday, sunday = get_weekend_dates()
    print(f"Weekend: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    CINEMA_SEARCHES = [
        ('arc_beeston',         'Arc Cinema Beeston',          'Beeston Nottingham',  '£3.50'),
        ('showcase_nottingham', 'Showcase Cinema Nottingham',  'Nottingham',          '£2.49'),
        ('showcase_derby',      'Showcase Cinema Derby',       'Derby',               '£2.49'),
        ('savoy_nottingham',    'Savoy Cinema Nottingham',     'Nottingham',          '£2.15'),
        ('odeon_derby',         'Odeon Derby',                 'Derby',               'Odeon Kids'),
    ]

    CINEMA_URLS = {
        'arc_beeston':         'https://beeston.arccinema.co.uk/whatson/kidsclub',
        'showcase_nottingham': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-cinema-de-lux-nottingham',
        'showcase_derby':      'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-derby',
        'savoy_nottingham':    'https://savoyonline.co.uk',
        'odeon_derby':         'https://www.odeon.co.uk/cinemas/derby/161/',
    }

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday': sunday.strftime('%a %d %b'),
        },
        'cinemas': {}
    }

    for key, name, location, price in CINEMA_SEARCHES:
        print(f"\n=== {name} ===")
        cinema_results = search_cinema(name, location, price, saturday, sunday)

        # If search found nothing, show a helpful placeholder
        for day in ['saturday', 'sunday']:
            if not cinema_results[day]:
                cinema_results[day] = [{
                    'title': f'Tap "Book tickets" to see this week\'s film',
                    'time': '10:00' if 'Showcase' in name else 'Morning',
                    'price': price
                }]

        output['cinemas'][key] = cinema_results
        time.sleep(3)

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('\nDone!')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
