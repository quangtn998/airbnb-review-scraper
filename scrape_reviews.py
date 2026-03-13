#!/usr/bin/env python3
"""
Airbnb Review Scraper
=====================
Automatically scrape all reviews from any Airbnb Experience via internal GraphQL API.

Usage:
    python scrape_reviews.py --url "https://www.airbnb.com/experiences/4344975"
    python scrape_reviews.py --id 4344975
    python scrape_reviews.py --id 4344975 --format csv
    python scrape_reviews.py --id 4344975 --format json
    python scrape_reviews.py --id 4344975 --format both
"""

import argparse
import base64
import json
import re
import sys
import time
from typing import Dict, List, Optional

import pandas as pd
import requests

# ============================================================================
# Constants
# ============================================================================

AIRBNB_API_URL = "https://www.airbnb.com/api/v3/ReviewsModalContentQuery"
SHA256_HASH = "04698412017b60fca29eb960d89ed9a84a5ea612800a3ea6964ec42c39aa4323"
API_KEY = "d306zoyjsyarp7ifhu67rjxn52tv0t20"

HEADERS = {
    "x-airbnb-api-key": API_KEY,
    "x-airbnb-graphql-platform": "web",
    "content-type": "application/json",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "referer": "https://www.airbnb.com/",
}

# Number of reviews per API call (Airbnb default)
PAGE_SIZE = 10

# Delay between requests (seconds) to be polite
REQUEST_DELAY = 0.5


# ============================================================================
# Helper Functions
# ============================================================================


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


def fetch_reviews_page(
    encoded_id: str,
    cursor: Optional[str] = None,
    sort_order: str = "DESCENDING",
) -> dict:
    """
    Fetch one page of reviews from Airbnb's GraphQL API.

    Args:
        encoded_id: Base64-encoded listing ID
        cursor: Pagination cursor (None for first page)
        sort_order: 'DESCENDING' (newest first) or 'ASCENDING' (oldest first)

    Returns:
        Raw JSON response as dict
    """
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

    response = requests.get(url, headers=HEADERS, params=params, timeout=30)
    response.raise_for_status()

    return response.json()


def parse_review(edge: dict) -> Optional[dict]:
    """
    Parse a single review edge from the API response.

    Returns a flat dict with review data, or None if parsing fails.
    """
    try:
        node = edge.get("node", {})
        if not isinstance(node, dict):
            return None

        review = node.get("review", {})
        if not isinstance(review, dict):
            return None

        # Get comment text (original language)
        # commentV2 is a plain string in the API response
        original_comment = ""
        comment_v2 = review.get("commentV2")
        if isinstance(comment_v2, str):
            original_comment = comment_v2
        elif isinstance(comment_v2, dict):
            original_comment = comment_v2.get("text", "") or comment_v2.get("localizedString", "")

        # Get translated comment (English)
        translated_comment = ""
        localized = review.get("localizedCommentV2")
        if isinstance(localized, dict):
            translated_comment = localized.get("localizedString", "") or ""
            source_locale = localized.get("sourceLocale", "")
        elif isinstance(localized, str):
            translated_comment = localized

        # Use translated if available, otherwise original
        comment = translated_comment or original_comment

        # Also check highlightedComment at node level as fallback
        if not comment:
            comment = node.get("highlightedComment", "") or ""

        # Get reviewer info
        reviewer = review.get("reviewer", {}) or {}
        reviewer_name = reviewer.get("displayFirstName", "Unknown")

        # Get reviewer location - try contextualReviewer first (has better data)
        ctx_reviewer = review.get("contextualReviewer", {}) or {}
        reviewer_location = ctx_reviewer.get("location", "")
        if not reviewer_location:
            reviewer_location = reviewer.get("reviewerLocation", "") or ""

        # Get rating
        rating = review.get("rating", None)

        # Get review date
        localized_date = review.get("localizedCreatedAtDate", "")

        # Get review ID
        review_id = review.get("id", "")

        # Get host response
        host_response = ""
        public_response = review.get("localizedPublicResponse")
        if isinstance(public_response, dict):
            host_response = public_response.get("localizedString", "") or ""
        elif isinstance(public_response, str):
            host_response = public_response

        return {
            "review_id": review_id,
            "reviewer_name": reviewer_name,
            "reviewer_location": reviewer_location,
            "rating": rating,
            "comment": comment.strip() if comment else "",
            "original_comment": original_comment.strip() if original_comment else "",
            "date": localized_date,
            "host_response": host_response.strip() if host_response else "",
        }
    except Exception as e:
        print(f"  ⚠️  Error parsing review: {e}")
        return None


def scrape_all_reviews(
    experience_id: int,
    sort_order: str = "DESCENDING",
    max_reviews: Optional[int] = None,
) -> List[dict]:
    """
    Scrape ALL reviews for an Airbnb Experience.

    Args:
        experience_id: Numeric experience ID
        sort_order: 'DESCENDING' (newest) or 'ASCENDING' (oldest)
        max_reviews: Maximum number of reviews to fetch (None = all)

    Returns:
        List of parsed review dicts
    """
    encoded_id = encode_listing_id(experience_id)
    all_reviews = []
    cursor = None
    page = 1

    print(f"\n🚀 Starting review scrape for Experience #{experience_id}")
    print(f"   Encoded ID: {encoded_id}")
    print(f"   Sort order: {'Newest' if sort_order == 'DESCENDING' else 'Oldest'} first")
    if max_reviews:
        print(f"   Limit: {max_reviews} reviews")
    print()

    while True:
        try:
            print(f"📄 Fetching page {page}...", end=" ", flush=True)

            data = fetch_reviews_page(encoded_id, cursor, sort_order)

            # Navigate to review edges
            node = data.get("data", {}).get("node", {})
            reviews_search = node.get("reviewsSearch", {})
            edges = reviews_search.get("edges", [])
            page_info = reviews_search.get("pageInfo", {})

            if not edges:
                print("No reviews found.")
                break

            # Parse each review
            page_reviews = []
            for edge in edges:
                review = parse_review(edge)
                if review:
                    page_reviews.append(review)

            all_reviews.extend(page_reviews)
            print(f"✅ Got {len(page_reviews)} reviews (total: {len(all_reviews)})")

            # Check if we've reached the limit
            if max_reviews and len(all_reviews) >= max_reviews:
                all_reviews = all_reviews[:max_reviews]
                print(f"\n🎯 Reached limit of {max_reviews} reviews.")
                break

            # Check pagination
            has_next = page_info.get("hasNextPage", False)
            if not has_next:
                print(f"\n✅ All reviews fetched!")
                break

            cursor = page_info.get("endCursor")
            if not cursor:
                print(f"\n⚠️  No cursor for next page.")
                break

            page += 1

            # Be polite - delay between requests
            time.sleep(REQUEST_DELAY)

        except requests.exceptions.HTTPError as e:
            print(f"\n❌ HTTP Error: {e}")
            if e.response is not None and e.response.status_code == 429:
                print("   Rate limited! Waiting 10 seconds...")
                time.sleep(10)
                continue
            break
        except requests.exceptions.ConnectionError as e:
            print(f"\n❌ Connection Error: {e}")
            print("   Waiting 5 seconds before retrying...")
            time.sleep(5)
            continue
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            break

    print(f"\n📊 Summary: Scraped {len(all_reviews)} reviews")
    return all_reviews


def save_to_csv(reviews: List[dict], filepath: str) -> None:
    """Save reviews to CSV file."""
    df = pd.DataFrame(reviews)
    df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"💾 Saved CSV: {filepath} ({len(reviews)} reviews)")


def save_to_json(reviews: List[dict], filepath: str) -> None:
    """Save reviews to JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved JSON: {filepath} ({len(reviews)} reviews)")


# ============================================================================
# Main
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="🏠 Airbnb Review Scraper - Automatically scrape reviews from Airbnb Experiences"
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--url",
        type=str,
        help="Airbnb Experience URL (e.g. https://www.airbnb.com/experiences/4344975)",
    )
    group.add_argument(
        "--id",
        type=int,
        help="Numeric Experience ID (e.g. 4344975)",
    )

    parser.add_argument(
        "--format",
        choices=["csv", "json", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--sort",
        choices=["newest", "oldest"],
        default="newest",
        help="Sort order (default: newest)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Maximum number of reviews to fetch (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory (default: current directory)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in seconds (default: 0.5)",
    )

    args = parser.parse_args()

    # Get experience ID
    if args.url:
        experience_id = extract_experience_id(args.url)
    else:
        experience_id = args.id

    # Set delay
    global REQUEST_DELAY
    REQUEST_DELAY = args.delay

    # Sort order
    sort_order = "DESCENDING" if args.sort == "newest" else "ASCENDING"

    print("=" * 60)
    print("🏠 AIRBNB REVIEW SCRAPER")
    print("=" * 60)
    print(f"Experience ID: {experience_id}")
    print(f"URL: https://www.airbnb.com/experiences/{experience_id}")
    print(f"Format: {args.format}")
    print(f"Sort: {args.sort}")
    print(f"Delay: {args.delay}s")
    if args.max:
        print(f"Max reviews: {args.max}")

    # Scrape
    start_time = time.time()
    reviews = scrape_all_reviews(experience_id, sort_order, args.max)
    elapsed = time.time() - start_time

    if not reviews:
        print("\n❌ No reviews were scraped!")
        sys.exit(1)

    # Save output
    output_dir = args.output_dir.rstrip("/")
    base_name = f"reviews_{experience_id}"

    if args.format in ("csv", "both"):
        csv_path = f"{output_dir}/{base_name}.csv"
        save_to_csv(reviews, csv_path)

    if args.format in ("json", "both"):
        json_path = f"{output_dir}/{base_name}.json"
        save_to_json(reviews, json_path)

    # Summary
    print()
    print("=" * 60)
    print("📊 RESULTS")
    print("=" * 60)
    print(f"  Total reviews: {len(reviews)}")
    print(f"  Time elapsed: {elapsed:.1f}s")

    # Rating stats
    ratings = [r["rating"] for r in reviews if r.get("rating") is not None]
    if ratings:
        avg_rating = sum(ratings) / len(ratings)
        print(f"  Average rating: {avg_rating:.2f}/5")
        print(f"  Rating 5⭐: {ratings.count(5)} ({ratings.count(5)/len(ratings)*100:.1f}%)")
        print(f"  Rating 4⭐: {ratings.count(4)} ({ratings.count(4)/len(ratings)*100:.1f}%)")
        print(f"  Rating 3⭐: {ratings.count(3)} ({ratings.count(3)/len(ratings)*100:.1f}%)")
        print(f"  Rating 2⭐: {ratings.count(2)} ({ratings.count(2)/len(ratings)*100:.1f}%)")
        print(f"  Rating 1⭐: {ratings.count(1)} ({ratings.count(1)/len(ratings)*100:.1f}%)")

    print()
    print("✅ Done!")


if __name__ == "__main__":
    main()
