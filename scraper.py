#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper
Scrapes kids club / family morning showings from 5 local cinemas
and outputs data/showings.json for the GitHub Pages frontend.
"""

import json
import re
import sys
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def get_weekend_dates():
    """Return the next Saturday and Sunday dates."""
    today = datetime.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7  # if today IS Saturday, get next one
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def scrape_arc_beeston(saturday, sunday):
    """Scrape Arc Cinema Beeston kids club page."""
    results = {'saturday': [], 'sunday': []}
    try:
        url = 'https://beeston.arccinema.co.uk/whatson/kidsclub'
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_str = saturday.strftime('%Y-%m-%d')
        sun_str = sunday.strftime('%Y-%m-%d')

        # Arc uses data-date attributes or links with dates
        # Look for film listings - they typically appear as film blocks
        # Try to find showings with dates
        for link in soup.find_all('a', href=True):
            href = link['href']
            # Look for date patterns in URLs or nearby text
            if sat_str in href:
                title = link.get_text(strip=True) or 'Kids Club Film'
                results['saturday'].append({'title': title, 'time': 'Check site', 'price': '£3.50'})
            elif sun_str in href:
                title = link.get_text(strip=True) or 'Kids Club Film'
                results['sunday'].append({'title': title, 'time': 'Check site', 'price': '£3.50'})

        # If no date-specific results, try to find any film titles listed on the kids club page
        if not results['saturday'] and not results['sunday']:
            # Look for session/film blocks
            film_blocks = soup.find_all(['div', 'article', 'li'], class_=re.compile(r'(film|movie|session|showing|event)', re.I))
            for block in film_blocks[:6]:
                text = block.get_text(separator=' ', strip=True)
                if text and len(text) > 3:
                    title = text[:60].strip()
                    results['saturday'].append({'title': title, 'time': 'See website', 'price': '£3.50'})

        print(f"Arc Beeston: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"Arc Beeston error: {e}", file=sys.stderr)
    return results


def scrape_showcase(cinema_slug, cinema_name, saturday, sunday):
    """Scrape Showcase cinema Family Favourites showings."""
    results = {'saturday': [], 'sunday': []}
    try:
        # Showcase lists showings by date - try their listings page
        sat_str = saturday.strftime('%Y-%m-%d')
        sun_str = sunday.strftime('%Y-%m-%d')

        for day_str, day_key in [(sat_str, 'saturday'), (sun_str, 'sunday')]:
            url = f'https://www.showcasecinemas.co.uk/whats-on/?cinema={cinema_slug}&date={day_str}'
            r = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')

            # Look for Family Favourites tagged showings
            # Showcase marks these with "FF" or "Family Favourites" labels
            for session in soup.find_all(string=re.compile(r'(family.favour|FF\b)', re.I)):
                parent = session.find_parent()
                if parent:
                    # Try to get film title from nearby heading
                    heading = parent.find_previous(['h2', 'h3', 'h4'])
                    title = heading.get_text(strip=True) if heading else 'Family Favourites Film'
                    # Try to get time
                    time_el = parent.find(string=re.compile(r'\d{1,2}:\d{2}'))
                    time_str = time_el.strip() if time_el else '10:00'
                    results[day_key].append({
                        'title': title,
                        'time': time_str,
                        'price': '£2.49'
                    })

            # If nothing found with FF label, note it's always 10am Sat/Sun
            if not results[day_key]:
                results[day_key].append({
                    'title': 'Family Favourites (check website for film)',
                    'time': '10:00',
                    'price': '£2.49'
                })

        print(f"{cinema_name}: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"{cinema_name} error: {e}", file=sys.stderr)
        # Fallback - Showcase always has 10am Family Favourites Sat & Sun
        results['saturday'] = [{'title': 'Family Favourites (check website)', 'time': '10:00', 'price': '£2.49'}]
        results['sunday'] = [{'title': 'Family Favourites (check website)', 'time': '10:00', 'price': '£2.49'}]
    return results


def scrape_savoy_nottingham(saturday, sunday):
    """Scrape Savoy Cinema Nottingham kids club showings."""
    results = {'saturday': [], 'sunday': []}
    try:
        url = 'https://savoyonline.co.uk'
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_str = saturday.strftime('%d/%m/%Y')
        sun_str = sunday.strftime('%d/%m/%Y')
        sat_short = saturday.strftime('%-d %b')
        sun_short = sunday.strftime('%-d %b')

        # Savoy marks Kids Club as "KC" in their listings
        full_text = soup.get_text()

        # Look for KC markers
        for line in full_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            if 'KC' in line or 'kids club' in line.lower() or 'kids' in line.lower():
                # Check if Saturday date appears nearby
                context_idx = full_text.find(line)
                context = full_text[max(0, context_idx-200):context_idx+200]
                if sat_short in context or saturday.strftime('%A') in context:
                    results['saturday'].append({
                        'title': line[:80],
                        'time': 'Morning - see website',
                        'price': '£2.15'
                    })
                elif sun_short in context or sunday.strftime('%A') in context:
                    results['sunday'].append({
                        'title': line[:80],
                        'time': 'Morning - see website',
                        'price': '£2.15'
                    })

        # Check for any film titles in the page with KC tag
        for el in soup.find_all(string=re.compile(r'\bKC\b')):
            parent = el.find_parent()
            if parent:
                heading = parent.find_previous(['h2', 'h3', 'h4', 'strong'])
                if heading:
                    title = heading.get_text(strip=True)
                    results['saturday'].append({'title': title, 'time': 'See website', 'price': '£2.15'})

        # Deduplicate
        for day in ['saturday', 'sunday']:
            seen = set()
            deduped = []
            for item in results[day]:
                if item['title'] not in seen:
                    seen.add(item['title'])
                    deduped.append(item)
            results[day] = deduped

        print(f"Savoy Nottingham: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"Savoy Nottingham error: {e}", file=sys.stderr)
    return results


def scrape_odeon_derby(saturday, sunday):
    """Scrape Odeon Derby kids club showings."""
    results = {'saturday': [], 'sunday': []}
    try:
        # Odeon uses a JSON API for listings
        sat_str = saturday.strftime('%Y-%m-%d')
        sun_str = sunday.strftime('%Y-%m-%d')

        cinema_id = '161'  # Odeon Derby

        for day_str, day_key in [(sat_str, 'saturday'), (sun_str, 'sunday')]:
            api_url = f'https://www.odeon.co.uk/api/showtimes/by-cinema-id/{cinema_id}/?date={day_str}&format=json'
            r = requests.get(api_url, headers=HEADERS, timeout=15)

            if r.status_code == 200:
                try:
                    data = r.json()
                    films = data.get('films', []) or data.get('data', {}).get('films', [])
                    for film in films:
                        title = film.get('title', '')
                        attributes = film.get('attributes', [])
                        # Check if it's an Odeon Kids / family showing
                        is_kids = any(
                            'kid' in str(a).lower() or 'family' in str(a).lower() or 'morning' in str(a).lower()
                            for a in attributes
                        )
                        showtimes = film.get('showtimes', [])
                        for showtime in showtimes:
                            time_str = showtime.get('time', '')
                            showtime_attrs = showtime.get('attributes', [])
                            is_kids_show = is_kids or any(
                                'kid' in str(a).lower() for a in showtime_attrs
                            )
                            # Kids shows are typically before 12pm
                            try:
                                hour = int(time_str.split(':')[0])
                                is_morning = hour < 12
                            except:
                                is_morning = False

                            if is_kids_show or is_morning:
                                results[day_key].append({
                                    'title': title,
                                    'time': time_str,
                                    'price': 'Odeon Kids'
                                })
                except json.JSONDecodeError:
                    pass

            # Fallback: try HTML scraping
            if not results[day_key]:
                url = f'https://www.odeon.co.uk/cinemas/derby/161/?date={day_str}'
                r = requests.get(url, headers=HEADERS, timeout=15)
                soup = BeautifulSoup(r.text, 'html.parser')

                for el in soup.find_all(string=re.compile(r'odeon.kids|kids.show', re.I)):
                    parent = el.find_parent()
                    if parent:
                        heading = parent.find_previous(['h2', 'h3'])
                        title = heading.get_text(strip=True) if heading else 'Odeon Kids Film'
                        results[day_key].append({
                            'title': title,
                            'time': 'Morning',
                            'price': 'Odeon Kids'
                        })

        print(f"Odeon Derby: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"Odeon Derby error: {e}", file=sys.stderr)
    return results


def main():
    saturday, sunday = get_weekend_dates()
    print(f"Scraping for: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday': sunday.strftime('%a %d %b')
        },
        'cinemas': {
            'arc_beeston': scrape_arc_beeston(saturday, sunday),
            'showcase_nottingham': scrape_showcase('showcase-cinema-de-lux-nottingham', 'Showcase Nottingham', saturday, sunday),
            'showcase_derby': scrape_showcase('showcase-derby', 'Showcase Derby', saturday, sunday),
            'savoy_nottingham': scrape_savoy_nottingham(saturday, sunday),
            'odeon_derby': scrape_odeon_derby(saturday, sunday),
        }
    }

    import os
    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Written to data/showings.json")
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
