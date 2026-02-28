#!/usr/bin/env python3
"""
Kids Cinema Weekend Scraper - Playwright version
Uses a headless browser to handle JavaScript-rendered cinema sites.
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


async def scrape_arc_beeston(page, saturday, sunday):
    """Arc Cinema Beeston - kids club page."""
    results = {'saturday': [], 'sunday': []}
    try:
        await page.goto('https://beeston.arccinema.co.uk/whatson/kidsclub', timeout=30000)
        await page.wait_for_load_state('networkidle', timeout=20000)

        content = await page.content()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, 'html.parser')

        sat_str = saturday.strftime('%Y-%m-%d')
        sun_str = sunday.strftime('%Y-%m-%d')
        sat_display = saturday.strftime('%-d %B')
        sun_display = sunday.strftime('%-d %B')

        # Arc cinema - find film blocks with dates
        # Try JSON-LD structured data first
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    items = [data]
                else:
                    items = []
                for item in items:
                    start = item.get('startDate', '')
                    name = item.get('name', '')
                    if sat_str in start:
                        results['saturday'].append({'title': name, 'time': start[11:16] if len(start) > 10 else 'See site', 'price': '£3.50'})
                    elif sun_str in start:
                        results['sunday'].append({'title': name, 'time': start[11:16] if len(start) > 10 else 'See site', 'price': '£3.50'})
            except:
                pass

        # Try finding film/session elements
        if not results['saturday'] and not results['sunday']:
            # Look for links containing the date strings
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)
                if sat_str in href and text:
                    results['saturday'].append({'title': text, 'time': 'See site', 'price': '£3.50'})
                elif sun_str in href and text:
                    results['sunday'].append({'title': text, 'time': 'See site', 'price': '£3.50'})

        # Try Playwright locators for film titles visible on page
        if not results['saturday'] and not results['sunday']:
            # Get all text containing the weekend dates
            full_text = await page.inner_text('body')
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]
            
            current_day = None
            for i, line in enumerate(lines):
                if sat_display in line or saturday.strftime('%d/%m') in line:
                    current_day = 'saturday'
                elif sun_display in line or sunday.strftime('%d/%m') in line:
                    current_day = 'sunday'
                
                # Time pattern - likely a showing time
                time_match = re.search(r'\b(\d{1,2}:\d{2})\b', line)
                if time_match and current_day and i > 0:
                    title = lines[i-1] if i > 0 else 'Kids Club Film'
                    if len(title) > 3 and not re.search(r'^\d', title):
                        results[current_day].append({
                            'title': title,
                            'time': time_match.group(1),
                            'price': '£3.50'
                        })

        print(f"Arc Beeston: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"Arc Beeston error: {e}", file=sys.stderr)
    return results


async def scrape_showcase(page, cinema_slug, cinema_name, saturday, sunday):
    """Showcase cinemas - Family Favourites showings."""
    results = {'saturday': [], 'sunday': []}
    try:
        for day_date, day_key in [(saturday, 'saturday'), (sunday, 'sunday')]:
            day_str = day_date.strftime('%Y-%m-%d')
            url = f'https://www.showcasecinemas.co.uk/whats-on/?cinema={cinema_slug}&date={day_str}'
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=25000)

            # Wait for film listings to appear
            try:
                await page.wait_for_selector('[class*="film"], [class*="movie"], [class*="listing"]', timeout=10000)
            except:
                pass

            full_text = await page.inner_text('body')
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]

            # Find Family Favourites showings
            i = 0
            while i < len(lines):
                line = lines[i]
                if re.search(r'family.favour|FF\b', line, re.I):
                    # Title is likely nearby - look back
                    title = 'Family Favourites Film'
                    for j in range(max(0, i-5), i):
                        candidate = lines[j]
                        if len(candidate) > 3 and not re.search(r'(book|buy|select|certificate|\bU\b|\bPG\b|\d+min)', candidate, re.I):
                            title = candidate
                    # Time
                    time_str = '10:00'
                    for j in range(i, min(len(lines), i+5)):
                        t = re.search(r'\b(\d{1,2}:\d{2})\b', lines[j])
                        if t:
                            time_str = t.group(1)
                            break
                    results[day_key].append({'title': title, 'time': time_str, 'price': '£2.49'})
                i += 1

            # Deduplicate by title+time
            seen = set()
            deduped = []
            for item in results[day_key]:
                key = item['title'] + item['time']
                if key not in seen:
                    seen.add(key)
                    deduped.append(item)
            results[day_key] = deduped

            # If still nothing, add a placeholder (Showcase ALWAYS has FF on weekends)
            if not results[day_key]:
                results[day_key] = [{'title': 'Family Favourites — check website for film title', 'time': '10:00', 'price': '£2.49'}]

        print(f"{cinema_name}: Sat={len(results['saturday'])}, Sun={len(results['sunday'])}")
    except Exception as e:
        print(f"{cinema_name} error: {e}", file=sys.stderr)
        results['saturday'] = [{'title': 'Family Favourites — check website', 'time': '10:00', 'price': '£2.49'}]
        results['sunday'] = [{'title': 'Family Favourites — check website', 'time': '10:00', 'price': '£2.49'}]
    return results


async def scrape_savoy(page, saturday, sunday):
    """Savoy Cinema Nottingham - Kids Club (marked KC)."""
    results = {'saturday': [], 'sunday': []}
    try:
        await page.goto('https://savoyonline.co.uk', timeout=30000)
        await page.wait_for_load_state('networkidle', timeout=20000)

        sat_display = saturday.strftime('%-d %b').upper()
        sun_display = sunday.strftime('%-d %b').upper()
        sat_day = saturday.strftime('%A').upper()
        sun_day = sunday.strftime('%A').upper()

        full_text = await page.inner_text('body')
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]

        current_day = None
        current_title = None

        i = 0
        while i < len(lines):
            line = lines[i]

            # Detect day headers
            if sat_display in line.upper() or sat_day in line.upper():
                current_day = 'saturday'
            elif sun_display in line.upper() or sun_day in line.upper():
                current_day = 'sunday'

            # Detect KC (Kids Club) marker
            if re.search(r'\bKC\b', line) and current_day:
                # Title is nearby - look around
                title = 'Kids Club Film'
                time_str = 'See website'

                for j in range(max(0, i-4), i):
                    candidate = lines[j]
                    if (len(candidate) > 3
                            and not re.search(r'(KC|PG|CERT|\d+:\d+|BOOK|BUY)', candidate, re.I)
                            and not re.search(r'^(SAT|SUN|MON|TUE|WED|THU|FRI)', candidate)):
                        title = candidate

                # Look for time
                time_match = re.search(r'\b(\d{1,2}:\d{2})\b', line)
                if time_match:
                    time_str = time_match.group(1)
                else:
                    for j in range(i, min(len(lines), i+3)):
                        t = re.search(r'\b(\d{1,2}:\d{2})\b', lines[j])
                        if t:
                            time_str = t.group(1)
                            break

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
    """Odeon Derby - Odeon Kids screenings."""
    results = {'saturday': [], 'sunday': []}
    try:
        for day_date, day_key in [(saturday, 'saturday'), (sunday, 'sunday')]:
            day_str = day_date.strftime('%Y-%m-%d')
            url = f'https://www.odeon.co.uk/cinemas/derby/161/?date={day_str}'
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=25000)

            try:
                await page.wait_for_selector('[class*="film-title"], [class*="filmTitle"], h2, h3', timeout=10000)
            except:
                pass

            full_text = await page.inner_text('body')
            lines = [l.strip() for l in full_text.split('\n') if l.strip()]

            i = 0
            while i < len(lines):
                line = lines[i]
                # Odeon Kids showings are flagged with "Odeon Kids" or "Kids" tag
                if re.search(r'odeon.kids|kids.screening', line, re.I):
                    title = 'Odeon Kids Film'
                    time_str = 'Morning'

                    for j in range(max(0, i-6), i):
                        candidate = lines[j]
                        if (len(candidate) > 3
                                and not re.search(r'(kids|cert|pg|book|rating|\d+min)', candidate, re.I)):
                            title = candidate

                    for j in range(i, min(len(lines), i+4)):
                        t = re.search(r'\b(\d{1,2}:\d{2})\b', lines[j])
                        if t:
                            hour = int(t.group(1).split(':')[0])
                            if hour < 13:  # Morning shows only
                                time_str = t.group(1)
                                break

                    results[day_key].append({'title': title, 'time': time_str, 'price': 'Odeon Kids'})
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
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        output = {
            'updated': datetime.now().strftime('%a %d %b %Y at %H:%M'),
            'weekend_dates': {
                'saturday': saturday.strftime('%a %d %b'),
                'sunday': sunday.strftime('%a %d %b')
            },
            'cinemas': {
                'arc_beeston': await scrape_arc_beeston(page, saturday, sunday),
                'showcase_nottingham': await scrape_showcase(page, 'showcase-cinema-de-lux-nottingham', 'Showcase Nottingham', saturday, sunday),
                'showcase_derby': await scrape_showcase(page, 'showcase-derby', 'Showcase Derby', saturday, sunday),
                'savoy_nottingham': await scrape_savoy(page, saturday, sunday),
                'odeon_derby': await scrape_odeon(page, saturday, sunday),
            }
        }

        await browser.close()

    os.makedirs('data', exist_ok=True)
    with open('data/showings.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Written to data/showings.json")


if __name__ == '__main__':
    asyncio.run(main())
