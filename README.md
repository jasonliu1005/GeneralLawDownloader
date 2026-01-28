# Massachusetts General Laws Downloader & CourtListener Case Crawler

This repository contains two Python scripts:

1. **Massachusetts General Laws Downloader** - Downloads all Massachusetts General Laws from the [Massachusetts Legislature API](https://malegislature.gov/api/swagger/index.html?url=/api/swagger/v1/swagger.json#/).
2. **CourtListener Case Crawler** - Crawls [CourtListener.com](https://www.courtlistener.com) to download law cases from search results.

## Features

- Traverses the three-level hierarchy: **Parts → Chapters → Sections**
- Downloads complete text for each section
- Creates one markdown document per Part
- Automatically fixes HTTP to HTTPS URL bug in API responses
- Includes error handling and retry logic
- Respectful API usage with request delays

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Run the script with optional output directory:

```bash
# Use default output directory (ma_laws/)
python downloader.py

# Specify a custom output directory
python downloader.py -o /path/to/output
python downloader.py --output ./my_laws
```

### Command-line Options

- `-o, --output`: Specify the output directory for downloaded documents (default: `ma_laws/`)

The script will:
1. Fetch all Parts from the API
2. For each Part, fetch all Chapters
3. For each Chapter, fetch all Sections
4. For each Section, fetch the full text
5. Create a markdown document per Part in the specified output directory

Each document includes:
- Part number and title
- Chapter numbers and titles
- Section numbers, titles, and full text

## Output Structure

Documents are saved as `Part_{number}.md` in the output directory (default: `ma_laws/`). Each document follows this structure:

```markdown
# Part 1: Title

## Chapter 1: Chapter Title

### Section 1: Section Title

Section text content here...

---
```

## API Notes

- The API returns URLs with `http://` but they need to be `https://` to work. The script automatically fixes this.
- The script includes a small delay between requests to be respectful to the API server.
- Error handling and retry logic are included for robustness.

---

## CourtListener Case Crawler

The `case_crawler.py` script crawls CourtListener.com to download law cases from search results pages.

### Features

- Parses index/search results pages with time range parameters
- Extracts case detail URLs from search results
- Handles pagination automatically
- Extracts structured case information (Citations, Docket Number, Judges, Dates, County, Keywords, etc.)
- Filters HTML to extract plain text content
- Outputs structured JSON format

### Usage

```bash
# Use year parameter (recommended - automatically constructs URL)
python case_crawler.py --year 2025

# Use custom URL instead
python case_crawler.py --url "https://www.courtlistener.com/?q=&type=o&order_by=dateFiled%20desc&stat_Published=on&filed_after=01%2F01%2F2025&filed_before=01%2F01%2F2026&court=mass%20massappct%20masssuperct%20massdistct%20masslandct%20maworkcompcom"

# Specify output directory
python case_crawler.py --year 2025 -o ./my_cases

# Limit to first 5 pages (for testing)
python case_crawler.py --year 2025 -p 5

# Use different court filter with year
python case_crawler.py --year 2025 -c "mass massappct"
```

### Command-line Options

- `-y, --year`: Target year to crawl (e.g., 2025). Automatically constructs URL with date range 01/01/YEAR to 01/01/YEAR+1. Mutually exclusive with `--url`.
- `-u, --url`: Custom URL of the index/search results page to start crawling from. Mutually exclusive with `--year`.
- `-o, --output`: Output directory for downloaded cases (default: `law_cases/`)
- `-p, --max-pages`: Maximum number of pages to crawl (default: all pages)
- `-c, --courts`: Court filter string (default: Massachusetts courts). Only used with `--year` option.

### Output Format

Cases are saved as `cases.json` in the output directory. Each case includes:

- `url`: Case detail page URL
- `content`: Plain text content from the main document (HTML filtered out)
- `Case Name`: Name of the case
- `Court`: Court name
- `Citations`: Case citations
- `Docket Number`: Docket number
- `Judges`: Judge(s) name(s)
- `Docket`: Docket information
- `Dates`: Filing/decision dates
- `County`: County information
- `Keywords`: Case keywords/subjects

### How It Works

1. Starts from the provided index/search results URL
2. Parses the `div#search-results` to extract case detail page URLs
3. For each case, visits the detail page and extracts content from `div.col-sm-9.main-document`
4. Filters out HTML tags to get plain text
5. Extracts structured metadata fields
6. Handles pagination by detecting next page links or incrementing `&page=` parameter
7. Saves all cases to a single JSON file

### Notes

- The crawler includes delays between requests to be respectful to CourtListener's servers
- Includes retry logic for failed requests
- Automatically handles pagination until no more results are found
- Each case is saved to its own JSON file for better organization

---

## CourtListener Case Crawler (API Version)

The `case_crawler_api.py` script uses the [CourtListener Legal Search API](https://www.courtlistener.com/help/api/rest/search/) to download law cases. This version is more reliable than web scraping and provides structured JSON data directly from the API.

### Features

- Uses the official CourtListener Legal Search API (`/api/rest/v4/search/`)
- Same input parameters as the web scraper version for consistency
- Cursor-based pagination (more efficient than page-based)
- Structured JSON data (no HTML parsing needed)
- Each case saved to its own JSON file
- Supports API token authentication

### Prerequisites

You'll need a CourtListener API token. Get one at: https://www.courtlistener.com/api/rest-info/

### Usage

```bash
# Use year parameter with API token
python case_crawler_api.py --year 2025 --api-token YOUR_TOKEN

# Use environment variable for API token (recommended)
export COURTLISTENER_API_TOKEN=your_token_here
python case_crawler_api.py --year 2025

# Use custom API URL
python case_crawler_api.py --url "https://www.courtlistener.com/api/rest/v4/search/?q=foo&type=o" --api-token YOUR_TOKEN

# Specify output directory
python case_crawler_api.py --year 2025 -o ./my_cases --api-token YOUR_TOKEN

# Limit to first 100 results
python case_crawler_api.py --year 2025 --max-results 100 --api-token YOUR_TOKEN

# Use different court filter with year
python case_crawler_api.py --year 2025 -c "mass massappct" --api-token YOUR_TOKEN
```

### Command-line Options

- `-y, --year`: Target year to crawl (e.g., 2025). Automatically constructs API URL with date range YEAR-01-01 to (YEAR+1)-01-01. Mutually exclusive with `--url`.
- `-u, --url`: Custom API URL of the search endpoint to start crawling from. Mutually exclusive with `--year`.
- `-o, --output`: Output directory for downloaded cases (default: `law_cases/`)
- `-m, --max-results`: Maximum number of results to fetch (default: all results)
- `-c, --courts`: Court filter string (default: Massachusetts courts). Only used with `--year` option.
- `-t, --api-token`: API token for authentication. Can also be set via `COURTLISTENER_API_TOKEN` environment variable.

### Output Format

Each case is saved as a separate JSON file. Each case includes:

- `url`: Case detail page URL
- `Case Name`: Name of the case
- `Court`: Court name
- `Docket Number`: Docket number
- `Judges`: Judge(s) name(s) from panel_names
- `Dates`: Filing date (dateFiled)
- `Citations`: Case citations (comma-separated)
- `cluster_id`: Opinion cluster ID
- `docket_id`: Docket ID
- `status`: Publication status
- `content_preview`: First 500 characters of opinion snippet
- `api_data`: Full API response for reference

### How It Works

1. Constructs API URL from year parameter or uses provided URL
2. Makes authenticated API requests to `/api/rest/v4/search/`
3. Uses cursor-based pagination (follows `next` field in response)
4. Converts API results to standardized format
5. Saves each case to its own JSON file immediately
6. Continues until all results are fetched or max-results limit is reached

### API vs Web Scraper

**Use the API version (`case_crawler_api.py`) when:**
- You have an API token
- You want more reliable data extraction
- You need structured JSON data
- You want better performance

**Use the web scraper version (`case_crawler.py`) when:**
- You don't have an API token
- You need full case content (API provides snippets)
- You want to extract additional metadata from HTML

### Notes

- API token is recommended but not strictly required (some requests may be rate-limited without it)
- The API uses cursor-based pagination, which is more efficient than page-based
- Results are cached for 10 minutes on CourtListener's side
- Each case is saved immediately after fetching, so progress is preserved if interrupted
