# 🎬 Kids Cinema Weekend

A mobile-friendly web app that shows kids club and family morning screenings at 5 local cinemas in the Nottingham/Derby area. Refreshes automatically every week via GitHub Actions.

## Cinemas covered
- Arc Cinema Beeston (Kids Club – £3.50)
- Showcase Nottingham (Family Favourites – £2.49)
- Showcase Derby (Family Favourites – £2.49)
- Savoy Cinema Nottingham (Kids Club – £2.15)
- Odeon Derby (Odeon Kids)

## Setup (one-time)

### 1. Create the GitHub repo
- Go to [github.com](https://github.com) → New repository
- Name it e.g. `kids-cinema`
- Make it **Public** (required for free GitHub Pages)
- Upload all these files

### 2. Enable GitHub Pages
- In your repo, go to **Settings → Pages**
- Under "Source", select **Deploy from branch**
- Branch: `main`, folder: `/ (root)`
- Click Save
- Your site will be live at `https://YOUR-USERNAME.github.io/kids-cinema/`

### 3. Enable Actions write permissions
- Go to **Settings → Actions → General**
- Scroll to "Workflow permissions"
- Select **Read and write permissions**
- Save

### 4. Run the scraper for the first time
- Go to **Actions** tab in your repo
- Click "Scrape Kids Cinema Showings"
- Click **Run workflow** → Run workflow
- Wait ~1 minute for it to complete
- Refresh your GitHub Pages site

After that it runs automatically every Tuesday at 8am.

## Add to your Android home screen
1. Open Chrome on your Samsung phone
2. Go to your GitHub Pages URL
3. Tap the three-dot menu → **Add to Home screen**
4. It'll appear as an app icon on your home screen

## Troubleshooting
If showings say "see website" instead of film titles, it means the cinema's website structure changed and the scraper needs updating. Open an issue or edit `scraper.py`.

Note: Cinema websites use JavaScript-heavy rendering which can be hard to scrape automatically. If the scraper consistently fails for a cinema, the best fallback is clicking the "Book tickets →" link which goes directly to that cinema's website.
