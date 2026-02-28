#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper v3
Strategy: Use Playwright to load each cinema's listings page for Saturday/Sunday,
then grab ALL morning showings (before 12:30pm) as these are the kids club slots.
This avoids relying on "KC" or "Family Favourites" labels which are hard to find.
"""

import json
import re
import sys
import os
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout


def get_weekend_dates():
    today = datetime.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def is_morning(time_str):
    """Return True if time is before 12:30pm - likely a kids/family showing."""
    try:
        parts = time_str.replace('.', ':').split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return (hour < 12) or (hour == 12 and minute <= 30)
    except:
        return False


def is_kids_title(title):
    """Return True if title looks like a kids film (extra check)."""
    ADULT_KEYWORDS = ['horror', 'thriller', 'rated 15', 'rated 18', '15 cert', '18 cert']
    return not any(kw in title.lower() for kw in ADULT_KEYWORDS)


async def scrape_arc_beeston(page, saturday, sunday):
    """Arc Cinema Beeston - Kids Club every Sat & Sun ~11am."""
    results = {'saturday': [], 'sunday': []}
    try:
        # Go to their kids club page
        await page.goto('https://beeston.arccinema.co.uk/whatson/kidsclub', timeout=30000)
        await page.wait_for_load_state('networkidle', timeout=20000)

        # Get all text
        body = await page.inner_text('body')
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        sat_display = saturday.strftime('%-d %B')   # e.g. "7 March"
        sun_display = sunday.strftime('%-d %B')
        sat_short   = saturday.strftime('%a %-d')   # e.g. "Sat 7"
        sun_short   = sunday.strftime('%a %-d')

        current_day = None
        i = 0
        while i < len(lines):
            line = lines[i]

            # Detect which day we're looking at
            if sat_display in line or sat_short in line or saturday.strftime('%d/%m') in line:
                current_day = 'saturday'
            elif sun_display in line or sun_short in line or sunday.strftime('%d/%m') in line:
                current_day = 'sunday'

            # Detect a time on this line
            time_match = re.search(r'\b(\d{1,2}[:.]\d{2})\b', line)
            if time_match and current_day:
                time_str = time_match.group(1).replace('.', ':')
                if is_morning(time_str):
                    # Film title is usually 1-3 lines before the time
                    title = 'Kids Club Film'
                    for j in range(max(0, i-4), i):
                        candidate = lines[j]
                        if (len(candidate) > 3
                                and not re.search(r'(\d{1,2}[:.]\d{2}|book|cert|pg|uu\b|rating|kids.club|£)', candidate, re.I)
                                and len(candidate) < 80):
                            title = candidate
                    results[current_day].append({
                        'title': title,
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
    except Exception as e:
        print(f"Arc Beeston error: {e}", file=sys.stderr)
    return results


async def scrape_showcase(page, cinema_slug, cinema_name, saturday, sunday):
    """Showcase - grab all morning showings on Sat/Sun (Family Favourites is always ~10am)."""
    results = {'saturday': [], 'sunday': []}
    try:
        for day_date, day_key in [(saturday, 'saturday'), (sunday, 'sunday')]:
            day_str = day_date.strftime('%Y-%m-%d')
            url = f'https://www.showcasecinemas.co.uk/whats-on/?cinema={cinema_slug}&date={day_str}'

            await page.goto(url, timeout=30000)
            # Wait for film listings to load
            try:
                await page.wait_for_selector('[class*="film"], [class*="listing"], [class*="movie"]', timeout=12000)
            except:
                await page.wait_for_timeout(4000)

            # Try to get structured data from the page
            # Showcase sometimes embeds JSON in script tags
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    content = await script.inner_text()
                    data = json.loads(content)
                    events = data if isinstance(data, list) else [data]
                    for event in events:
                        start = event.get('startDate', '')
                        name = event.get('name', '')
                        if day_str in start and name:
                            time_str = start[11:16] if len(start) >= 16 else ''
                            if time_str and is_morning(time_str):
                                results[day_key].append({
                                    'title': name,
                                    'time': time_str,
                                    'price': '£2.49'
                                })
                except:
                    pass

            # If no structured data, fall back to text parsing
            if not results[day_key]:
                body = await page.inner_text('body')
                lines = [l.strip() for l in body.split('\n') if l.strip()]

                i = 0
                while i < len(lines):
                    line = lines[i]
                    time_match = re.search(r'\b(\d{1,2}[:.]\d{2})\b', line)
                    if time_match:
                        time_str = time_match.group(1).replace('.', ':')
                        if is_morning(time_str):
                            # Look back for a film title
                            title = 'Family Favourites Film'
                            for j in range(max(0, i-6), i):
                                candidate = lines[j]
                                if (len(candidate) > 3
                                        and not re.search(r'(\d{1,2}[:.]\d{2}|book|cert|pg\b|uu\b|rating|£|showing|screen)', candidate, re.I)
                                        and len(candidate) < 100
                                        and candidate[0].isupper()):
                                    title = candidate
                            results[day_key].append({
                                'title': title,
                                'time': time_str,
                                'price': '£2.49'
                            })
                    i += 1

            # Deduplicate
            seen = set()
            deduped = []
            for item in results[day_key]:
                k = item['title'] + item['time']
                if k not in seen:
                    seen.add(k)
                    deduped.append(item)
            results[day_key] = deduped

            # Fallback if still nothing
            if not results[day_key]:
                results[day_key] = [{
                    'title': 'Family Favourites — tap Book tickets to see film',
                    'time': '10:00',
                    'price': '£2.49'
                }]

        print(f"{cinema_name}: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"{cinema_name} error: {e}", file=sys.stderr)
        results['saturday'] = [{'title': 'Family Favourites — tap Book tickets', 'time': '10:00', 'price': '£2.49'}]
        results['sunday'] = [{'title': 'Family Favourites — tap Book tickets', 'time': '10:00', 'price': '£2.49'}]
    return results


async def scrape_savoy(page, saturday, sunday):
    """Savoy Nottingham - grab morning showings."""
    results = {'saturday': [], 'sunday': []}
    try:
        await page.goto('https://savoyonline.co.uk', timeout=30000)
        await page.wait_for_load_state('networkidle', timeout=20000)

        # Check for an iframe - Savoy sometimes embeds their listings
        frames = page.frames
        target_frame = page
        for frame in frames:
            url = frame.url
            if 'savoy' in url.lower() and frame != page.main_frame:
                target_frame = frame
                break

        body = await target_frame.inner_text('body')
        lines = [l.strip() for l in body.split('\n') if l.strip()]

        sat_display = saturday.strftime('%-d %b')    # e.g. "7 Mar"
        sun_display = sunday.strftime('%-d %b')
        sat_long    = saturday.strftime('%A')         # e.g. "Saturday"
        sun_long    = sunday.strftime('%A')

        current_day = None
        i = 0
        while i < len(lines):
            line = lines[i]

            # Day detection
            if sat_display.lower() in line.lower() or sat_long.lower() in line.lower():
                current_day = 'saturday'
            elif sun_display.lower() in line.lower() or sun_long.lower() in line.lower():
                current_day = 'sunday'

            # Look for KC marker (Kids Club)
            if re.search(r'\bKC\b', line) and current_day:
                time_str = 'See website'
                time_match = re.search(r'\b(\d{1,2}[:.]\d{2})\b', line)
                if time_match:
                    time_str = time_match.group(1).replace('.', ':')

                # Find title nearby
                title = 'Kids Club Film'
                for j in range(max(0, i-5), i):
                    candidate = lines[j]
                    if (len(candidate) > 3
                            and not re.search(r'(KC|PG|cert|\d{1,2}[:.]\d{2}|book|saturday|sunday)', candidate, re.I)
                            and len(candidate) < 80
                            and candidate[0].isupper()):
                        title = candidate

                results[current_day].append({'title': title, 'time': time_str, 'price': '£2.15'})

            # Also catch morning times even without KC label
            elif current_day:
                time_match = re.search(r'\b(\d{1,2}[:.]\d{2})\b', line)
                if time_match:
                    time_str = time_match.group(1).replace('.', ':')
                    if is_morning(time_str):
                        title = 'Kids Club Film'
                        for j in range(max(0, i-4), i):
                            candidate = lines[j]
                            if (len(candidate) > 3
                                    and not re.search(r'(PG|cert|\d{1,2}[:.]\d{2}|book|saturday|sunday|£)', candidate, re.I)
                                    and len(candidate) < 80
                                    and candidate[0].isupper()):
                                title = candidate
                        results[current_day].append({'title': title, 'time': time_str, 'price': '£2.15'})

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

        print(f"Savoy Nottingham: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"Savoy error: {e}", file=sys.stderr)
    return results


async def scrape_odeon(page, saturday, sunday):
    """Odeon Derby - morning showings (Odeon Kids is always before noon)."""
    results = {'saturday': [], 'sunday': []}
    try:
        for day_date, day_key in [(saturday, 'saturday'), (sunday, 'sunday')]:
            day_str = day_date.strftime('%Y-%m-%d')
            url = f'https://www.odeon.co.uk/cinemas/derby/161/?date={day_str}'

            await page.goto(url, timeout=30000)
            try:
                await page.wait_for_selector('[class*="film"], [data-testid*="film"], h2, h3', timeout=12000)
            except:
                await page.wait_for_timeout(5000)

            # Try JSON-LD first
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    content = await script.inner_text()
                    data = json.loads(content)
                    events = data if isinstance(data, list) else [data]
                    for event in events:
                        start = event.get('startDate', '')
                        name = event.get('name', '')
                        if day_str in start and name:
                            time_str = start[11:16] if len(start) >= 16 else ''
                            if time_str and is_morning(time_str) and is_kids_title(name):
                                results[day_key].append({
                                    'title': name,
                                    'time': time_str,
                                    'price': 'Odeon Kids'
                                })
                except:
                    pass

            # Text fallback
            if not results[day_key]:
                body = await page.inner_text('body')
                lines = [l.strip() for l in body.split('\n') if l.strip()]

                i = 0
                current_title = None
                while i < len(lines):
                    line = lines[i]

                    # Odeon Kids label
                    if re.search(r'odeon.kids|kids.showing', line, re.I):
                        time_str = 'Morning'
                        title = current_title or 'Odeon Kids Film'
                        # find time nearby
                        for j in range(i, min(len(lines), i+5)):
                            t = re.search(r'\b(\d{1,2}[:.]\d{2})\b', lines[j])
                            if t:
                                time_str = t.group(1).replace('.', ':')
                                break
                        if is_morning(time_str) or time_str == 'Morning':
                            results[day_key].append({
                                'title': title,
                                'time': time_str,
                                'price': 'Odeon Kids'
                            })

                    # Track potential film title (capitalised line, not a time/label)
                    elif (len(line) > 3
                          and line[0].isupper()
                          and not re.search(r'(\d{1,2}[:.]\d{2}|book|cert|screen|odeon|buy|select)', line, re.I)
                          and len(line) < 80):
                        current_title = line

                    i += 1

            # Deduplicate
            seen = set()
            deduped = []
            for item in results[day_key]:
                k = item['title'] + item['time']
                if k not in seen:
                    seen.add(k)
                    deduped.append(item)
            results[day_key] = deduped

        print(f"Odeon Derby: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"Odeon Derby error: {e}", file=sys.stderr)
    return results


async def main():
    saturday, sunday = get_weekend_dates()
    print(f"Scraping for: {saturday.strftime('%A %d %b')} & {sunday.strftime('%A %d %b')}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()

        output = {
            'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
            'weekend_dates': {
                'saturday': saturday.strftime('%a %d %b'),
                'sunday': sunday.strftime('%a %d %b')
            },
            'cinemas': {}
        }

        output['cinemas']['arc_beeston'] = await scrape_arc_beeston(page, saturday, sunday)
        output['cinemas']['showcase_nottingham'] = await scrape_showcase(page, 'showcase-cinema-de-lux-nottingham', 'Showcase Nottingham', saturday, sunday)
        output['cinemas']['showcase_derby'] = await scrape_showcase(page, 'showcase-derby', 'Showcase Derby', saturday, sunday)
        output['cinemas']['savoy_nottingham'] = await scrape_savoy(page, saturday, sunday)
        output['cinemas']['odeon_derby'] = await scrape_odeon(page, saturday, sunday)

        await browser.close()

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Written to data/showings.json")
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
