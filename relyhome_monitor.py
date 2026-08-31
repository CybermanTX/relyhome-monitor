#!/usr/bin/env python3
"""
Rely Home Job Monitor
- Scrapes available jobs from the Rely Home portal
- Filters for jobs within 18 miles of Leander, TX
- Outputs matching jobs as JSON for the cron agent to act on
"""

import json
import re
import sys
import urllib.request
import urllib.parse
from html.parser import HTMLParser

RELY_HOME_URL = "https://relyhome.com/jobs/accept/available-swo.php?vid=Lp1QeQv_crnL1vhNn6tEVblKKDvjbswwEP29cJt8Uq0&exp=IMDTobMd79cX80YtOQUjo_hrt0_Z_5Zh0fY-RSIt1NQ&src=listrak&trk_msg=AF3E3B8CM2UKLAT9HCSF1VUJAC&trk_contact=J7JRFE5AT7BARMIE087P4JPKBC&trk_sid=11DOQ1KMJ0OEI521SNVNIEQMK4&trk_link=L83E7LDF8UL4FATK18PNBHETC8"

MAX_DISTANCE_MILES = 18.0
STATE_FILE = "/home/node/.hermes/scripts/relyhome_seen.json"
# Base URL for resolving relative links from the portal
RELY_HOME_BASE = "https://relyhome.com/jobs/accept/"

class RelyHomeParser(HTMLParser):
    """Parse the Rely Home available jobs table."""
    def __init__(self):
        super().__init__()
        self.jobs = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.in_link = False
        self.current_row = []
        self.current_cell = ""
        self.current_href = ""
        self.cell_count = 0
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.current_row = []
            self.cell_count = 0
        elif tag == "td":
            self.in_cell = True
            self.current_cell = ""
            self.cell_count += 1
        elif tag == "a" and self.in_cell:
            href = attrs_dict.get("href", "")
            if "offer.php" in href:
                self.in_link = True
                self.current_href = href
                
    def handle_endtag(self, tag):
        if tag == "td" and self.in_cell:
            self.in_cell = False
            self.current_row.append(self.current_cell.strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            # Expect: Location, System, Distance, Brand, Type, Accept link
            if len(self.current_row) >= 3:
                try:
                    dist = float(self.current_row[2])
                except (ValueError, IndexError):
                    dist = None
                if dist is not None:
                    self.jobs.append({
                        "location": self.current_row[0] if len(self.current_row) > 0 else "",
                        "system": self.current_row[1] if len(self.current_row) > 1 else "",
                        "distance": dist,
                        "brand": self.current_row[3] if len(self.current_row) > 3 else "",
                        "type": self.current_row[4] if len(self.current_row) > 5 else "",
                        "accept_url": self.current_href
                    })
        elif tag == "a":
            self.in_link = False
            
    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def load_seen():
    """Load previously seen job URLs."""
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"seen_urls": []}


def save_seen(seen):
    """Save seen job URLs."""
    with open(STATE_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def fetch_jobs():
    """Fetch and parse available jobs from Rely Home."""
    req = urllib.request.Request(RELY_HOME_URL, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [], f"Fetch error: {e}"
    
    parser = RelyHomeParser()
    parser.feed(html)
    return parser.jobs, None


def fetch_job_details(url):
    """Fetch the job offer page to get service fee and customer details."""
    # Resolve relative URLs against the base portal URL
    if url.startswith("./") or url.startswith("../") or not url.startswith("http"):
        url = urllib.parse.urljoin(RELY_HOME_BASE, url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    })
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e)}
    
    details = {"raw_html_snippet": html[:5000]}
    
    # Try to find service fee / service call fee
    # Common patterns: "$75.00", "Service Fee: $75", "Service Call: $75.00"
    fee_patterns = [
        r'[Ss]ervice\s*(?:[Cc]all|[Ff]ee)[:\s]*\$\s*([\d,]+\.?\d*)',
        r'\$\s*([\d,]+\.?\d*)\s*(?:service|diagnostic)',
        r'(?:fee|charge|cost)[:\s]*\$\s*([\d,]+\.?\d*)',
        r'\$([\d,]+\.\d{2})',
    ]
    for pattern in fee_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            fee_str = match.group(1).replace(",", "")
            try:
                details["service_fee"] = float(fee_str)
                details["service_fee_raw"] = match.group(0)
                break
            except ValueError:
                pass
    
    # Try to find customer info
    for pattern_name, pattern in [
        ("customer_name", r'(?:customer|homeowner|name)[:\s]*([A-Z][a-z]+ [A-Z][a-z]+)'),
        ("phone", r'(?:phone|tel)[:\s]*([\d\-\(\)\s]{10,})'),
        ("email", r'[\w\.\-]+@[\w\.\-]+\.\w+'),
    ]:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            details[pattern_name] = match.group(1) if match.lastindex else match.group(0)
    
    return details


def main():
    jobs, error = fetch_jobs()
    
    if error:
        print(json.dumps({"status": "error", "message": error}))
        sys.exit(1)
    
    # Filter for jobs within distance threshold
    close_jobs = [j for j in jobs if j["distance"] <= MAX_DISTANCE_MILES]
    
    # Load seen URLs to avoid duplicates
    seen = load_seen()
    seen_urls = set(seen.get("seen_urls", []))
    
    # Find new close jobs
    new_close_jobs = [j for j in close_jobs if j["accept_url"] not in seen_urls]
    
    # For new close jobs, fetch their detail pages to get service fee
    for job in new_close_jobs:
        # Resolve relative URLs to absolute for consistent storage
        url = job["accept_url"]
        if url.startswith("./") or url.startswith("../") or not url.startswith("http"):
            url = urllib.parse.urljoin(RELY_HOME_BASE, url)
            job["accept_url"] = url
        details = fetch_job_details(url)
        job["details"] = details
        if "service_fee" in details:
            job["service_fee"] = details["service_fee"]
    
    # Mark all close jobs as seen
    for j in close_jobs:
        seen_urls.add(j["accept_url"])
    
    # Keep only last 200 seen URLs to prevent file bloat
    seen["seen_urls"] = list(seen_urls)[-200:]
    save_seen(seen)
    
    result = {
        "status": "ok",
        "total_available": len(jobs),
        "within_18mi": len(close_jobs),
        "new_within_18mi": len(new_close_jobs),
        "new_jobs": new_close_jobs,
        "all_close_jobs": close_jobs,
        "all_jobs_summary": [
            {"location": j["location"], "distance": j["distance"], "system": j["system"]}
            for j in jobs
        ]
    }
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
