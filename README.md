# Airbnb Experience Review Scraper 🏠

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Automatically scrape **all reviews** from any Airbnb Experience using Airbnb's internal GraphQL API. No browser needed, no manual copy-paste — just pure API calls.

## ✨ Features

- 🚀 **Fully automated** — no browser or manual interaction needed
- ⚡ **Fast** — scrapes ~1,300 reviews in ~2 minutes
- 🌍 **Auto-translation** — captures both original language and English translation
- 📊 **Multiple formats** — export to CSV, JSON, or both
- 🔄 **Pagination handling** — automatically fetches all pages
- 🛡️ **Rate limiting** — configurable delay to avoid being blocked
- 📈 **Stats** — shows rating breakdown and summary after scraping

## 📦 Installation

```bash
git clone https://github.com/YOUR_USERNAME/airbnb-review-scraper.git
cd airbnb-review-scraper
pip install -r requirements.txt
```

## 🚀 Quick Start

```bash
# Scrape all reviews from an experience
python scrape_reviews.py --url "https://www.airbnb.com/experiences/4344975"

# Or use the experience ID directly
python scrape_reviews.py --id 4344975
```

Output:
```
============================================================
🏠 AIRBNB EXPERIENCE REVIEW SCRAPER
============================================================
Experience ID: 4344975
URL: https://www.airbnb.com/experiences/4344975

📄 Đang lấy trang 1... ✅ Lấy được 10 review (tổng: 10)
📄 Đang lấy trang 2... ✅ Lấy được 10 review (tổng: 20)
...
📄 Đang lấy trang 128... ✅ Lấy được 9 review (tổng: 1279)

✅ Đã lấy hết tất cả review!

📊 KẾT QUẢ
  Tổng review: 1279
  Thời gian: 135.2 giây
  Rating trung bình: 4.97/5
```

## 📋 Usage

```bash
# Basic usage
python scrape_reviews.py --id <EXPERIENCE_ID>
python scrape_reviews.py --url <AIRBNB_URL>

# Output format (default: both)
python scrape_reviews.py --id 4344975 --format csv
python scrape_reviews.py --id 4344975 --format json
python scrape_reviews.py --id 4344975 --format both

# Limit number of reviews
python scrape_reviews.py --id 4344975 --max 100

# Sort order (default: newest)
python scrape_reviews.py --id 4344975 --sort newest
python scrape_reviews.py --id 4344975 --sort oldest

# Custom output directory
python scrape_reviews.py --id 4344975 --output-dir ./data

# Adjust delay between requests (seconds, default: 0.5)
python scrape_reviews.py --id 4344975 --delay 1.0
```

## 📊 Output Data

Each review contains:

| Field | Description | Example |
|-------|-------------|---------|
| `review_id` | Unique review ID | `QWN0aXZpdH...` |
| `reviewer_name` | Reviewer's first name | `John` |
| `reviewer_location` | Reviewer's location | `London, United Kingdom` |
| `rating` | Star rating (1-5) | `5` |
| `comment` | Review text (English) | `Amazing experience!` |
| `original_comment` | Review text (original language) | `Incroyable expérience!` |
| `date` | Localized date | `March 2024` |
| `host_response` | Host's response (if any) | `Thank you!` |

### CSV Example

```csv
review_id,reviewer_name,reviewer_location,rating,comment,original_comment,date,host_response
QWN0...,Carina,"Munich, Germany",5,"It was interesting...",Es war auf so vielen...,Today,
QWN0...,Robert,"Vancouver, Canada",5,"What can I say...",What can I say...,Today,
```

## 🔧 How It Works

This tool uses Airbnb's internal GraphQL API (`ReviewsModalContentQuery`) to fetch reviews. It:

1. Encodes the experience ID to Airbnb's Base64 format
2. Sends GET requests to the GraphQL endpoint with proper headers
3. Parses the JSON response to extract review data
4. Uses cursor-based pagination to fetch all pages
5. Exports the collected data to CSV/JSON

```
Airbnb Experience URL
        │
        ▼
  Extract ID (4344975)
        │
        ▼
  Encode to Base64 (QWN0aXZpdHlMaXN0aW5nOjQzNDQ5NzU=)
        │
        ▼
  ┌─────────────────────────┐
  │  GraphQL API Request    │ ◄─── cursor pagination
  │  (GET with headers)     │
  └─────────┬───────────────┘
            │
            ▼
  Parse JSON → Extract reviews
            │
            ▼
  hasNextPage? ──Yes──► Next cursor ──► Loop back
       │
       No
       │
       ▼
  Export CSV/JSON
```

## ⚠️ Disclaimer

- This tool is for **educational and personal use only**
- Scraping may violate Airbnb's Terms of Service
- The internal API may change at any time without notice
- Use responsibly and respect rate limits
- The author is not responsible for any misuse of this tool

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions are welcome! Feel free to:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 💡 Ideas for Contribution

- [ ] Support for Airbnb **listing** reviews (not just experiences)
- [ ] Add proxy rotation support
- [ ] Export to Google Sheets
- [ ] Add sentiment analysis
- [ ] Docker containerization
- [ ] GitHub Actions for scheduled scraping
