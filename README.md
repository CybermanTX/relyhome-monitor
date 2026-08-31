# Rely Home Job Monitor

Automated job monitoring for Elite Climate Comfort LLC (Geaux PRO Air).

## What it does
- Scrapes Rely Home portal for available HVAC jobs every 5 minutes
- Filters for jobs within 18 miles of Leander, TX
- Auto-accepts qualifying jobs
- Creates work orders in dispatch.me with customer info and service fee
- Assigns Joe Reinninger to the work order

## Files
- `relyhome_monitor.py` — Main monitoring script
- `relyhome_seen.json` — State file tracking previously seen jobs (auto-generated)

## Setup
Requires dispatch.me credentials in `~/.hermes/.env`:
```
DISPATCH_ME_EMAIL=your@email.com
DISPATCH_ME_PASSWORD=yourpassword
```

## Cron Job
Runs every 5 minutes via Hermes Agent cron system.
