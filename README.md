# HarvestLink

**From field to future.** A full-stack farm-to-market concept built with **Flask, SQLite, Jinja2, HTML, CSS and vanilla JavaScript**. Created as a next-generation redesign of AgriTrack, with an editorial visual direction inspired by the supplied recording.

Colors: **Espresso** `#29241E` · **Linen** `#F5F2E9` · **Celadon** `#A6C8AF`.

## What's included

- **Responsive landing website:** immersive farm landscape, layered depth, subtle tilt effects, on-scroll transitions, product illustrations, soft editorial typography and a minimal loading screen. Effects respect reduced-motion preferences.
- **Farm studio:** harvest pipeline dashboard, KPI cards, weather context and suggested action alerts.
- **Fields & crops:** register fields and plant crops with their variety, planting date, growth duration, expected quantity and expected price.
- **Rule-based harvest forecasts:** planting date + estimated crop maturity, with an *illustrative* adjustment when live seven-day weather forecasts are available.
- **Automatic activity schedule:** watering, fertilizing, pest scouting and harvest preparation tasks generated from planting records. Mark tasks done or add your own.
- **Equipment inventory:** keep machines and service dates; each new piece of equipment gets a servicing reminder.
- **Market listings:** each crop automatically appears in the buyer-facing marketplace as *Coming soon* or *Ready now*. Visitors can search and browse.
- **Buyer reservations:** reserve a quantity ahead of harvest, track remaining supply and generate a unique order link and QR.
- **Optional payment-link QR:** set an HTTPS URL from an authorized, external payment provider in Farm settings. A second QR on the reservation page will open that external URL. HarvestLink does not charge buyers or verify payments automatically.
- **Finance ledger:** record sales and expenses; a seller can manually confirm an externally received reservation payment, adding it to sales.
- **Low-reservation alerts:** when a crop is within 21 days of harvest and under 35% reserved, an alert suggests sharing its listing or setting a small discount.
- **Public farm profile:** farmer story, location, and upcoming produce. Default demo identity is *Mavuno Family Farm, Nakuru, Kenya*; it is editable in Settings.

## Getting started

Requires **Python 3.10+**.

```bash
# 1. Unzip HarvestLink.zip and open a terminal inside the HarvestLink folder.

# 2. Optional, but recommended: create a virtual environment.
python -m venv .venv

# Windows PowerShell:
.venv\Scripts\Activate.ps1

# macOS / Linux:
# source .venv/bin/activate

# 3. Install libraries.
pip install -r requirements.txt

# 4. Start the app.
python app.py
```

Go to **http://127.0.0.1:5000**.

The SQLite database is automatically created under `data/harvestlink.db` on first launch, with illustrative crops, fields, sales, reservations and tasks. No passwords or login forms are included. Delete the database while the server is stopped to recreate a clean demonstration dataset.

### Where everything lives

```text
HarvestLink/
├── app.py                       Flask routes, SQLite schema, business rules
├── requirements.txt
├── Procfile                     Gunicorn start command
├── .render.yaml                 Example Render service configuration
├── static/
│   ├── app.js                   Modals, depth, filters, loading, copy links
│   ├── style.css                Design system and responsive layouts
│   └── images/                  Offline SVG illustrations and landscape fallback
├── templates/
│   ├── base.html                Global layout and navigation
│   ├── index.html               Public editorial homepage
│   ├── dashboard.html           Farm studio overview
│   ├── fields.html              Fields and crop records
│   ├── activities.html          Reminders and tasks
│   ├── equipment.html           Inventory and servicing
│   ├── marketplace.html         Buyer-facing listings
│   ├── listing.html             Crop detail + reservation form
│   ├── reservations.html        Seller order list
│   ├── checkout.html            Buyer order page + QR codes
│   ├── finance.html             Income and expenses
│   ├── insights.html            Forecast explanations and sales alerts
│   ├── profile.html             Public farmer page
│   ├── settings.html            Farm name, contacts, currency, location
│   └── error.html
└── data/                         Auto-created database; do not commit real data
```

## Suggested walkthrough

1. Start at `/` and explore the interactive homepage.
2. Select **Open studio** to see live demo records.
3. Go to **Fields & crops → Plant a crop**. This creates reminders **and** a marketplace listing at the same time.
4. Visit **Marketplace**, open a crop and make a demo buyer reservation.
5. Scan the order QR: it opens that particular order page. Quantity is reflected immediately in the listing and the seller's Reservations page.
6. In **Reservations**, manually mark a payment as received (only after confirming externally). That sale then appears in **Farm finances**.
7. Visit **Insights & alerts** to adjust a low-demand crop's displayed price or copy its listing link.
8. Change your farm identity, weather location, currency and optional external merchant payment URL in **Farm settings**.

## Forecast and alert rules

Current implementation is intentionally transparent, not an ML model:

- `harvest_date = planting_date + crop_days_to_maturity`.
- If Open-Meteo returns seven-day weather and forecast rainfall is at least 90 mm, add **2 days**.
- Alternatively, when peak forecast temperature is at least 35°C and rainfall is below 8 mm, add **2 days**.
- Otherwise no adjustment. Without weather access, the calendar date is used on its own.
- Every crop is listed automatically. A crop is *Coming soon* until its estimated date and *Ready now* afterward.
- Flag an alert when it is at most **21 days** before harvest, with **under 35%** of expected yield reserved.

**Important:** These generic rules are an early-stage demonstration, **not scientifically validated yield or maturity predictions**. Farming advice and production decisions should use local agronomic expertise. The seven-day weather look-ahead is not a long-range seasonal forecast. Weather is fetched from [Open-Meteo](https://open-meteo.com/) when online (1-hour in-memory cache, short timeout).

## QR payment, WhatsApp, SMS and security

The **reservation QR** works immediately and points to a specific order. It is **not a payment code**. For a **payment QR**, enter your authorized merchant-hosted HTTPS payment URL in Settings. A separate QR for that external link will appear on the buyer order page. Payment stays on the provider's site. HarvestLink currently cannot verify it: sellers record receipt manually.

**Automatic WhatsApp and SMS notifications are future integrations, not active features.** The studio provides internal alerts and shareable marketplace links. To deliver messages automatically, connect an approved SMS/WhatsApp provider, with opt-in consent, delivery error handling and secure secret storage.

**Do not deploy this demo with real private records.** As requested, **login and sign-up are removed**, so anyone with access to the web app can view buyer contact information and modify the farm ledger, settings, listings and reservations. Before real deployment, add account roles, authorization checks for all writes and private views, CSRF protection (basic form CSRF is already included), rate-limiting, privacy/consent, order validation and a verified payment gateway. Consider PostgreSQL for multi-user production use.

## Deploying to Render or similar

- Connect the repository as a Python web service.
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`
- Environment variable: `SECRET_KEY` = a secure, stable random secret (necessary for form CSRF tokens).
- **Important:** standard free/ephemeral disk deployments lose the SQLite database on restart/redeploy. Attach a persistent disk, set `HARVESTLINK_DB` to its path and ensure your plan supports persistence, or migrate to a managed database for real use.

## Notes on media and source project

- Farm landscape images are remotely sourced from [Unsplash](https://unsplash.com/). The design includes an original, bundled SVG landscape fallback, so the homepage still looks polished offline. All produce illustrations are bundled SVG assets.
- No user/password records from AgriTrack were carried into HarvestLink. The original uploaded database had no sales, expense or task rows to migrate.
- HarvestLink is an **early-stage prototype**, not an operational payment service or verified predictive agriculture system.
