#!/usr/bin/env python3
"""
Airbnb Review Scraper (Async Version)
=====================================
Automatically scrape all reviews from any Airbnb Experience via internal GraphQL API.
Features: Async support, Anti-bot (UA rotation/Proxy), Incremental scraping, Progress bar.

Usage:
    python scrape_reviews.py --url "https://www.airbnb.com/experiences/4344975"
    python scrape_reviews.py --id 4344975
"""

import argparse
import asyncio
import base64
import json
import os
import random
import re
import sys
import time
from typing import Dict, List, Optional, Set

import httpx
import pandas as pd
from slugify import slugify
from tqdm import tqdm

# ============================================================================
# Constants & Configuration
# ============================================================================

AIRBNB_API_URL = "https://www.airbnb.com/api/v3/ReviewsModalContentQuery"
SHA256_HASH = "04698412017b60fca29eb960d89ed9a84a5ea612800a3ea6964ec42c39aa4323"
API_KEY = "d306zoyjsyarp7ifhu67rjxn52tv0t20"

# Modern User-Agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
]

# Max concurrent requests to avoid being blocked
MAX_CONCURRENT_REQUESTS = 5
# Timeout for API calls
TIMEOUT = 30.0

# ============================================================================
# Helper Functions
# ============================================================================

def get_random_headers() -> dict:
    """Return a fresh set of headers with a random User-Agent."""
    return {
        "x-airbnb-api-key": API_KEY,
        "x-airbnb-graphql-platform": "web",
        "content-type": "application/json",
        "user-agent": random.choice(USER_AGENTS),
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "referer": "https://www.airbnb.com/",
    }

def encode_listing_id(experience_id: int) -> str:
    """Encode experience ID to Airbnb's Base64 format."""
    raw = f"ActivityListing:{experience_id}"
    return base64.b64encode(raw.encode()).decode()

def extract_experience_id(url: str) -> int:
    """Extract the numeric experience ID from an Airbnb URL."""
    match = re.search(r"/experiences/(\d+)", url)
    if match:
        return int(match.group(1))
    raise ValueError(f"Could not find experience ID in URL: {url}")

async def fetch_experience_metadata(client: httpx.AsyncClient, experience_id: int) -> dict:
    """Fetch experience title and basic info from its Airbnb page."""
    url = f"https://www.airbnb.com/experiences/{experience_id}"
    try:
        response = await client.get(url, timeout=10)
        response.raise_for_status()
        
        match = re.search(r"<title>(.*?)</title>", response.text)
        if match:
            title = match.group(1)
            title = re.sub(r"\s*·\s*★.*", "", title)
            title = re.sub(r"\s*-\s*Airbnb.*", "", title)
            return {"name": title.strip(), "url": url}
    except Exception as e:
        print(f"  ⚠️  Warning: Could not fetch experience name: {e}")
    
    return {"name": f"Experience {experience_id}", "url": url}

async def fetch_reviews_page(
    client: httpx.AsyncClient,
    encoded_id: str,
    cursor: Optional[str] = None,
    sort_order: str = "DESCENDING",
) -> dict:
    """Fetch one page of reviews from Airbnb's GraphQL API."""
    variables = {
        "id": encoded_id,
        "sort": {"recency": sort_order},
    }
    if cursor:
        variables["after"] = cursor

    extensions = {
        "persistedQuery": {
            "version": 1,
            "sha256Hash": SHA256_HASH,
        }
    }

    params = {
        "operationName": "ReviewsModalContentQuery",
        "locale": "en",
        "currency": "USD",
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps(extensions, separators=(",", ":")),
    }

    url = f"{AIRBNB_API_URL}/{SHA256_HASH}"
    response = await client.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()

def parse_review(edge: dict) -> Optional[dict]:
    """Parse a single review edge from the API response."""
    try:
        node = edge.get("node", {})
        if not isinstance(node, dict): return None
        review = node.get("review", {})
        if not isinstance(review, dict): return None

        original_comment = ""
        comment_v2 = review.get("commentV2")
        if isinstance(comment_v2, str):
            original_comment = comment_v2
        elif isinstance(comment_v2, dict):
            original_comment = comment_v2.get("text", "") or comment_v2.get("localizedString", "")

        translated_comment = ""
        localized = review.get("localizedCommentV2")
        if isinstance(localized, dict):
            translated_comment = localized.get("localizedString", "") or ""
        elif isinstance(localized, str):
            translated_comment = localized

        comment = translated_comment or original_comment
        if not comment:
            comment = node.get("highlightedComment", "") or ""

        reviewer = review.get("reviewer", {}) or {}
        reviewer_name = reviewer.get("displayFirstName", "Unknown")
        
        ctx_reviewer = review.get("contextualReviewer", {}) or {}
        reviewer_location = ctx_reviewer.get("location", "") or reviewer.get("reviewerLocation", "") or ""

        return {
            "review_id": review.get("id", ""),
            "reviewer_name": reviewer_name,
            "reviewer_location": reviewer_location,
            "rating": review.get("rating"),
            "comment": comment.strip() if comment else "",
            "original_comment": original_comment.strip() if original_comment else "",
            "date": review.get("localizedCreatedAtDate", ""),
            "host_response": (review.get("localizedPublicResponse") or {}).get("localizedString", "").strip() 
                             if isinstance(review.get("localizedPublicResponse"), dict) else ""
        }
    except Exception as e:
        print(f"  ⚠️  Error parsing review: {e}")
        return None

# ============================================================================
# Core Logic
# ============================================================================

async def scrape_all_reviews(
    experience_id: int,
    output_dir: str,
    sort_order: str = "DESCENDING",
    max_reviews: Optional[int] = None,
    delay: float = 0.5,
    proxy: Optional[str] = None,
) -> Dict:
    """Scrape reviews with async concurrency, UA rotation, and incremental check."""
    
    encoded_id = encode_listing_id(experience_id)
    all_reviews = []
    
    # Anti-bot proxy setup
    proxy_mount = proxy if proxy else None
    
    async with httpx.AsyncClient(headers=get_random_headers(), proxy=proxy_mount, follow_redirects=True) as client:
        # 1. Fetch metadata
        metadata_raw = await fetch_experience_metadata(client, experience_id)
        slug = slugify(metadata_raw["name"])
        base_name = f"reviews_{slug}_{experience_id}"
        
        # 2. Incremental Scraping: Check for existing reviews
        existing_ids = set()
        json_path = os.path.join(output_dir, f"{base_name}.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    old_data = json.load(f)
                    all_reviews = old_data.get("reviews", [])
                    existing_ids = {r["review_id"] for r in all_reviews}
                    print(f"🔄 Found {len(existing_ids)} existing reviews. Checking for updates...")
            except Exception as e:
                print(f"⚠️  Could not load existing reviews: {e}")

        print(f"\n🚀 Scraping: {metadata_raw['name']}")
        
        cursor = None
        new_reviews_count = 0
        pbar = tqdm(desc="Fetching reviews", unit=" reviews")
        
        while True:
            # Update headers periodically for rotation
            client.headers.update(get_random_headers())
            
            try:
                data = await fetch_reviews_page(client, encoded_id, cursor, sort_order)
                node = data.get("data", {}).get("node", {})
                reviews_search = node.get("reviewsSearch", {})
                edges = reviews_search.get("edges", [])
                page_info = reviews_search.get("pageInfo", {})

                if not edges: break

                page_reviews = []
                stop_incremental = False
                
                for edge in edges:
                    review = parse_review(edge)
                    if not review: continue
                    
                    if review["review_id"] in existing_ids:
                        stop_incremental = True
                        break
                    
                    page_reviews.append(review)
                    new_reviews_count += 1
                    
                all_reviews = page_reviews + all_reviews # Add new ones to front (since DESCENDING)
                pbar.update(len(page_reviews))

                if stop_incremental:
                    print(f"\n✨ Reached existing reviews. Stopping incremental scrape.")
                    break

                if max_reviews and len(all_reviews) >= max_reviews:
                    all_reviews = all_reviews[:max_reviews]
                    break

                if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                    break

                cursor = page_info.get("endCursor")
                await asyncio.sleep(delay)

            except Exception as e:
                print(f"\n❌ Error during fetch: {e}")
                break

        pbar.close()
        
    return {
        "metadata": {
            "experience_id": experience_id,
            "experience_name": metadata_raw["name"],
            "experience_url": metadata_raw["url"],
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "reviews": all_reviews,
        "new_count": new_reviews_count
    }

def save_results(result: dict, output_dir: str, formats: List[str]):
    """Save results to CSV/JSON."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    metadata = result["metadata"]
    slug = slugify(metadata["experience_name"])
    base_name = f"reviews_{slug}_{metadata['experience_id']}"
    
    if "csv" in formats or "both" in formats:
        path = os.path.join(output_dir, f"{base_name}.csv")
        df = pd.DataFrame(result["reviews"])
        if not df.empty:
            df.insert(0, "experience_name", metadata["experience_name"])
            df.insert(1, "experience_url", metadata["experience_url"])
            df.insert(2, "experience_id", metadata["experience_id"])
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"💾 Saved CSV: {path}")

    if "json" in formats or "both" in formats:
        path = os.path.join(output_dir, f"{base_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"💾 Saved JSON: {path}")

# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    parser = argparse.ArgumentParser(description="🏠 Airbnb Review Scraper (Async/Robust)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Airbnb Experience URL")
    group.add_argument("--id", type=int, help="Experience ID")

    parser.add_argument("--format", choices=["csv", "json", "both"], default="both")
    parser.add_argument("--sort", choices=["newest", "oldest"], default="newest")
    parser.add_argument("--max", type=int, default=None, help="Max reviews to keep")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between pages")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://user:pass@host:port)")

    args = parser.parse_args()
    exp_id = extract_experience_id(args.url) if args.url else args.id
    sort_order = "DESCENDING" if args.sort == "newest" else "ASCENDING"

    start_time = time.time()
    result = await scrape_all_reviews(
        exp_id, args.output_dir, sort_order, args.max, args.delay, args.proxy
    )
    
    if result["reviews"]:
        save_results(result, args.output_dir, [args.format])
        
        elapsed = time.time() - start_time
        print(f"\n✅ Done! Scraped {result['new_count']} new reviews (Total: {len(result['reviews'])}) in {elapsed:.1f}s")
    else:
        print("\n❌ No reviews found.")

if __name__ == "__main__":
    asyncio.run(main())
