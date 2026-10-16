# Pinora Lead Intelligence & Simple CRM

A zero-paid-API-cost local lead workspace, advertising verification system, and follow-up CRM.

## Features
- **Lead Discovery Engine**: OpenStreetMap Overpass API, Photon geocoding, and web indexing.
- **Official Website Verification**: Guarantees all leads have a valid official business website.
- **Contact Enrichment**: Scrapes public emails, phones, and WhatsApp direct links.
- **Advertising Transparency Verification**: Fast manual checks for Google Ads Transparency Center & Meta Ad Library.
- **Simple CRM**: Follow-up reminders, outreach status pipelines, sticky notes, and personalized message drafts.
- **Cloud & Local Mode**: Runs on localhost with SQLite, and deploys on Vercel with persistent browser storage (IndexedDB).

## Local Usage
Double-click `start.bat` on Windows or run:
```bash
python -c "from app.server import run_server; run_server(port=3847)"
```
Then open `http://localhost:3847` in your browser.

## Cloud Deployment (Vercel)
Deploy this repository to Vercel with 1-click. All 116 seed leads are pre-loaded and auto-saved in your browser's persistent IndexedDB.
