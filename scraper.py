#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper - Final Version

Runs: Wednesday 00:01am and Thursday 00:01am via GitHub Actions.

If run on a Sunday after 12pm, exits early with a message in the JSON
telling users to check back Wednesday when next weekend's listings go live.

Arc Beeston and Savoy Nottingham are scraped directly.
Showcase and Odeon block scraping - shown as placeholders with correct price/time.
"""

import json, re, os, time
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


def too_early_to_scrape():
    """
    Returns True if it's Sunday after 12pm - next weekend's listings
    won't be published until Wednesday evening so scraping is pointless.
    """
    now = datetime.now()
    is_sunday = now.weekday() == 6
    is_afternoon = now.hour >= 12
    return is_sunday and is_afternoon


def write_wait_message(saturday, sunday):
    """Write a friendly 'check back Wednesday' message to the JSON."""
    placeholder = [{'title': 'Listings not published yet - check back after Wednesday', 'time': '—', 'price': '—'}]
    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday':   sunday.strftime('%a %d %b'),
        },
        'cinemas': {
            'arc_beeston':         {'saturday': placeholder, 'sunday': placeholder},
            'showcase_nottingham': {'saturday': placeholder, 'sunday': placeholder},
            'showcase_derby':      {'saturday': placeholder, 'sunday': placeholder},
            'savoy_nottingham':    {'saturday': placeholder, 'sunday': placeholder},
            'odeon_derby':         {'saturday': placeholder, 'sunday': placeholder},
        }
    }
    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)
    print('Too early - listings not published yet. Written wait message to JSON.')


def scrape_arc(saturday, sunday):
    """
    Arc Beeston kids club page.
    Confirmed structure:
      ## [FILM TITLE](/event/XXXXX)
      Running time: 108 mins
      Sat 07 Mar  (or Sun 08 Mar)
      **11:00** - 12:48
    """
    results = {'saturday': [], 'sunday': []}
    try:
        r = requests.get(
            'https://beeston.arccinema.co.uk/whatson/kidsclub',
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_d  = saturday.strftime('%d %b')   # "07 Mar"
        sat_d2 = saturday.strftime('%-d %b')  # "7 Mar"
        sun_d  = sunday.strftime('%d %b')     # "08 Mar"
        sun_d2 = sunday.strftime('%-d %b')    # "8 Mar"

        for link in soup.find_all('a', href=re.compile(r'^/event/')):
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # Walk up to find a container that has both a date and a time
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
                    results[day_key].append({
                        'title': title,
                        'time': time_str,
                        'price': '£3.50'
                    })

        for day in ['saturday', 'sunday']:
            seen = set()
            results[day] = [
                x for x in results[day]
                if not (x['title']+x['time'] in seen or seen.add(x['title']+x['time']))
            ]

        print(f"Arc Beeston: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")

    except Exception as e:
        print(f"Arc error: {e}")
        import traceback; traceback.print_exc()

    return results


def scrape_savoy(saturday, sunday):
    """
    Savoy Nottingham kids club page.
    Confirmed structure:
      <h3>Film Title</h3>
      <li>Sun 1 Mar
        10:00 KC TC
        11:15 KC TC
      </li>
    """
    results = {'saturday': [], 'sunday': []}
    try:
        r = requests.get(
            'https://savoyonline.co.uk/SavoyNottingham.dll/Page?p=6&m=mm&sp=0',
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')

        sat_d    = saturday.strftime('%-d %b')  # "7 Mar"
        sat_d2   = saturday.strftime('%d %b')   # "07 Mar"
        sat_long = saturday.strftime('%A')       # "Saturday"
        sun_d    = sunday.strftime('%-d %b')    # "8 Mar"
        sun_d2   = sunday.strftime('%d %b')     # "08 Mar"
        sun_long = sunday.strftime('%A')         # "Sunday"

        NAV_WORDS = re.compile(
            r'(club|screen|cinema|event|coming|film|soon|visit|offer|hire|'
            r'voucher|loyalty|basket|account|menu|newsletter|calendar|login|'
            r'password|register|silverscreen|toddler|parent|baby)', re.I
        )

        for heading in soup.find_all(['h3', 'h2']):
            title = heading.get_text(strip=True)
            if not title or len(title) < 3 or NAV_WORDS.search(title):
                continue

            section = heading.find_parent(['div', 'article', 'section']) or heading.parent
            section_text = section.get_text(separator='\n')
            lines = [l.strip() for l in section_text.split('\n') if l.strip()]

            current_day = None
            for line in lines:
                if any(x in line for x in [sat_d, sat_d2, 'Sat ', sat_long]):
                    current_day = 'saturday'
                elif any(x in line for x in [sun_d, sun_d2, 'Sun ', sun_long]):
                    current_day = 'sunday'

                if 'KC' in line and current_day:
                    for t in re.findall(r'\b(\d{1,2}:\d{2})\b', line):
                        results[current_day].append({
                            'title': title,
                            'time': t,
                            'price': '£3.00'
                        })

        for day in ['saturday', 'sunday']:
            seen = set()
            results[day] = [
                x for x in results[day]
                if not (x['title']+x['time'] in seen or seen.add(x['title']+x['time']))
            ]

        print(f"Savoy Nottingham: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")

    except Exception as e:
        print(f"Savoy error: {e}")
        import traceback; traceback.print_exc()

    return results


def main():
    saturday, sunday = get_weekend_dates()
    print(f"Weekend: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")
    print(f"Run time: {datetime.now().strftime('%A %d %b at %H:%M')}")

    # If it's Sunday afternoon, listings for next weekend aren't out yet
    if too_early_to_scrape():
        write_wait_message(saturday, sunday)
        return

    arc   = scrape_arc(saturday, sunday)
    time.sleep(2)
    savoy = scrape_savoy(saturday, sunday)

    showcase_placeholder = {
        'saturday': [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
        'sunday':   [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
    }
    odeon_placeholder = {
        'saturday': [{'title': 'Odeon Kids', 'time': 'Morning', 'price': 'Odeon Kids pricing'}],
        'sunday':   [{'title': 'Odeon Kids', 'time': 'Morning', 'price': 'Odeon Kids pricing'}],
    }

    output = {
        'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
        'weekend_dates': {
            'saturday': saturday.strftime('%a %d %b'),
            'sunday':   sunday.strftime('%a %d %b'),
        },
        'cinemas': {
            'arc_beeston':         arc,
            'showcase_nottingham': showcase_placeholder,
            'showcase_derby':      {
                'saturday': [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
                'sunday':   [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
            },
            'savoy_nottingham':    savoy,
            'odeon_derby':         odeon_placeholder,
        }
    }

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print('\nDone!')
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
