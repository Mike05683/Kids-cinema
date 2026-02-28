#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v4
Uses the CineList API (api.cinelist.co.uk) which pulls from FindAnyFilm.
Much more reliable than scraping cinema sites directly.
"""

import json
import re
import sys
import os
import time
from datetime import datetime, timedelta
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# CineList cinema IDs - found by searching their API
# We'll look these up dynamically using postcode search
CINEMA_CONFIG = {
    'arc_beeston': {
        'name': 'Arc Cinema Beeston',
        'search': 'Beeston',
        'match': 'arc',
        'price': '£3.50',
        'url': 'https://beeston.arccinema.co.uk/whatson/kidsclub',
        'badge': 'ARC'
    },
    'showcase_nottingham': {
        'name': 'Showcase Nottingham',
        'search': 'Nottingham',
        'match': 'showcase',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-cinema-de-lux-nottingham',
        'badge': 'SHOWCASE'
    },
    'showcase_derby': {
        'name': 'Showcase Derby',
        'search': 'Derby',
        'match': 'showcase',
        'price': '£2.49',
        'url': 'https://www.showcasecinemas.co.uk/whats-on/?cinema=showcase-derby',
        'badge': 'SHOWCASE'
    },
    'savoy_nottingham': {
        'name': 'Savoy Cinema Nottingham',
        'search': 'Nottingham',
        'match': 'savoy',
        'price': '£2.15',
        'url': 'https://savoyonline.co.uk',
        'badge': 'SAVOY'
    },
    'odeon_derby': {
        'name': 'Odeon Derby',
        'search': 'Derby',
        'match': 'odeon',
        'price': 'Odeon Kids',
        'url': 'https://www.odeon.co.uk/cinemas/derby/161/',
        'badge': 'ODEON'
    }
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
    """True if time is before 12:30 - the kids club slot."""
    try:
        parts = time_str.replace('.', ':').split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return (hour < 12) or (hour == 12 and minute <= 30)
    except:
        return False


def find_cinema_id(search_term, match_keyword):
    """Use CineList API to find a cinema's ID by location and name keyword."""
    try:
        url = f'https://api.cinelist.co.uk/search/cinemas/location/{requests.utils.quote(search_term)}'
        r = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        cinemas = data.get('cinemas', [])
        for cinema in cinemas:
            name = cinema.get('name', '').lower()
            if match_keyword.lower() in name:
                print(f"  Found: {cinema['name']} (ID: {cinema['id']})")
                return cinema['id']
        print(f"  No match for '{match_keyword}' in {search_term}. Available: {[c['name'] for c in cinemas[:5]]}")
    except Exception as e:
        print(f"  Cinema search error for {search_term}: {e}", file=sys.stderr)
    return None


def get_showings_for_day(cinema_id, day_offset):
    """Get all showings for a cinema on a given day offset (0=today, 1=tomorrow etc)."""
    try:
        url = f'https://api.cinelist.co.uk/get/times/cinema/{cinema_id}?day={day_offset}'
        r = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        return data.get('listings', [])
    except Exception as e:
        print(f"  Showings fetch error: {e}", file=sys.stderr)
        return []


def filter_morning_showings(listings, price, kids_focus=False):
    """Filter listings to morning shows only (kids club slot)."""
    results = []
    for film in listings:
        title = film.get('title', 'Unknown Film')
        times = film.get('times', [])
        morning_times = [t for t in times if is_morning(t)]

        # If kids_focus, only include if it looks like a family/kids film
        # Otherwise include all morning showings
        if morning_times:
            for t in morning_times:
                results.append({
                    'title': title,
                    'time': t,
                    'price': price
                })
    return results


def calculate_day_offset(target_date):
    """Calculate how many days from today the target date is."""
    today = datetime.today().date()
    delta = target_date.date() - today
    return delta.days


def main():
    saturday, sunday = get_weekend_dates()
    sat_offset = calculate_day_offset(saturday)
    sun_offset = calculate_day_offset(sunday)

    print(f"Scraping for: {saturday.strftime('%A %d %b')} (offset +{sat_offset}) & {sunday.strftime('%A %d %b')} (offset +{sun_offset})")

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday': sunday.strftime('%a %d %b')
        },
        'cinemas': {}
    }

    for cinema_key, config in CINEMA_CONFIG.items():
        print(f"\nLooking up: {config['name']}")
        cinema_id = find_cinema_id(config['search'], config['match'])

        if cinema_id:
            time.sleep(1)  # Be polite to the API
            sat_listings = get_showings_for_day(cinema_id, sat_offset)
            time.sleep(1)
            sun_listings = get_showings_for_day(cinema_id, sun_offset)

            sat_showings = filter_morning_showings(sat_listings, config['price'])
            sun_showings = filter_morning_showings(sun_listings, config['price'])

            print(f"  Sat: {len(sat_showings)} morning shows, Sun: {len(sun_showings)} morning shows")

            output['cinemas'][cinema_key] = {
                'saturday': sat_showings,
                'sunday': sun_showings
            }
        else:
            # Cinema not found in CineList - use fallback
            output['cinemas'][cinema_key] = {
                'saturday': [{'title': 'Check website for this week\'s film', 'time': 'Morning', 'price': config['price']}],
                'sunday': [{'title': 'Check website for this week\'s film', 'time': 'Morning', 'price': config['price']}]
            }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Written to data/showings.json")
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
