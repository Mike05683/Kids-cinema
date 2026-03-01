#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper - Verified Final Version

Based on actually fetching and reading the HTML of each site:

ARC BEESTON (beeston.arccinema.co.uk/whatson/kidsclub):
- Film title in <h2><a href="/event/...">TITLE</a></h2>
- Date as plain text e.g. "Sun 01 Mar"
- Time in <strong>11:00</strong>
- Only shows upcoming screenings (may be empty mid-week)

SAVOY NOTTINGHAM (savoyonline.co.uk/SavoyNottingham.dll/Page?p=6&m=mm&sp=0):
- Film title in <h3>TITLE</h3>
- Dates as <li> with "Sat 7 Mar" or "Sun 8 Mar"
- Times as plain text "10:00" with "KC" marker next to them

SHOWCASE & ODEON: Block all scraping - show placeholder with correct time/price.
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


def scrape_arc(saturday, sunday):
    """
    Arc Beeston kids club page.
    Structure confirmed by fetching real page:
      ## [MISS MOXY](/event/106501)
      Running time: 108 mins
      Sun 01 Mar
      **11:00** - 12:48
    """
    results = {'saturday': [], 'sunday': []}
    try:
        r = requests.get(
            'https://beeston.arccinema.co.uk/whatson/kidsclub',
            headers=HEADERS, timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')

        # Date strings to match
        sat_d = saturday.strftime('%d %b')  # "07 Mar"
        sun_d = sunday.strftime('%d %b')    # "08 Mar"
        # Also try without leading zero
        sat_d2 = saturday.strftime('%-d %b')  # "7 Mar"
        sun_d2 = sunday.strftime('%-d %b')    # "8 Mar"

        # Each film is in an <article> or <div> containing an h2 link + date + time
        # Find film title links (/event/...)
        for link in soup.find_all('a', href=re.compile(r'^/event/')):
            title = link.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # Walk up to find container with date+time info
            container = link
            for _ in range(8):
                container = container.parent
                if container is None:
                    break
                ctext = container.get_text(separator=' ')
                if re.search(r'\d{1,2}:\d{2}', ctext) and re.search(r'\b(Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Jan|Feb)\b', ctext):
                    break

            if container is None:
                continue

            ctext = container.get_text(separator=' ')

            # Check which day
            for day_key, d1, d2 in [('saturday', sat_d, sat_d2), ('sunday', sun_d, sun_d2)]:
                if d1 in ctext or d2 in ctext:
                    # Get the time
                    t = re.search(r'\b(\d{1,2}:\d{2})\b', ctext)
                    time_str = t.group(1) if t else '11:00'
                    results[day_key].append({
                        'title': title,
                        'time': time_str,
                        'price': '£3.50'
                    })

        # Deduplicate
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
    Structure confirmed by fetching real page:
      <h3>The Scarecrows' Wedding...</h3>
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

        # Date strings
        sat_d  = saturday.strftime('%-d %b')   # "7 Mar"
        sun_d  = sunday.strftime('%-d %b')     # "8 Mar"
        sat_d2 = saturday.strftime('%d %b')    # "07 Mar"
        sun_d2 = sunday.strftime('%d %b')      # "08 Mar"
        sat_long = saturday.strftime('%A')     # "Saturday"
        sun_long = sunday.strftime('%A')       # "Sunday"

        # Each film block: find h3 titles, then look at surrounding content for dates+times
        film_sections = soup.find_all(['h3', 'h2'])

        for heading in film_sections:
            title = heading.get_text(strip=True)
            if not title or len(title) < 3:
                continue
            # Skip navigation headings
            if re.search(r'(club|screen|cinema|event|coming|film|soon|visit|offer|hire|voucher|loyalty|basket|account)', title, re.I):
                continue

            # Get the parent section containing dates and times
            section = heading.find_parent(['div', 'article', 'section', 'li'])
            if not section:
                section = heading.parent

            # Look for sibling/child elements with dates
            section_text = section.get_text(separator='\n')
            lines = [l.strip() for l in section_text.split('\n') if l.strip()]

            current_day = None
            for line in lines:
                # Detect day
                if any(x in line for x in [sat_d, sat_d2, 'Sat ', sat_long]):
                    current_day = 'saturday'
                elif any(x in line for x in [sun_d, sun_d2, 'Sun ', sun_long]):
                    current_day = 'sunday'

                # Detect KC times on this line
                if 'KC' in line and current_day:
                    times = re.findall(r'\b(\d{1,2}:\d{2})\b', line)
                    for t in times:
                        results[current_day].append({
                            'title': title,
                            'time': t,
                            'price': '£3.00'
                        })

        # Deduplicate
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

    arc   = scrape_arc(saturday, sunday)
    time.sleep(2)
    savoy = scrape_savoy(saturday, sunday)

    # Showcase and Odeon block scraping entirely
    showcase_n = {
        'saturday': [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
        'sunday':   [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
    }
    showcase_d = {
        'saturday': [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
        'sunday':   [{'title': 'Family Favourites', 'time': '10:00', 'price': '£2.49'}],
    }
    odeon = {
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
            'showcase_nottingham': showcase_n,
            'showcase_derby':      showcase_d,
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
