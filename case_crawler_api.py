#!/usr/bin/env python3
"""
CourtListener Law Case Crawler (API Version)

This script uses the CourtListener Legal Search API to download law cases.
It uses the same input parameters as the web scraper version but leverages
the API for more reliable and structured data extraction.
"""

import argparse
import json
import os
import re
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode, quote


BASE_URL = "https://www.courtlistener.com"
API_BASE_URL = f"{BASE_URL}/api/rest/v4/search"
OPINION_API_BASE = f"{BASE_URL}/api/rest/v4/opinions"
REQUEST_DELAY = 1.0  # Delay between requests to be respectful
OUTPUT_DIR = "law_cases"

# Default court filter for Massachusetts courts
DEFAULT_COURTS = "mass massappct masssuperct massdistct masslandct maworkcompcom"


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Create a safe filename from a case name or URL.
    
    Args:
        name: The name or URL to sanitize
        max_length: Maximum length of the filename
        
    Returns:
        Sanitized filename string
    """
    # Remove or replace invalid filename characters
    # Keep alphanumeric, spaces, hyphens, underscores, and periods
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    # Replace multiple spaces with single space
    sanitized = re.sub(r'\s+', ' ', sanitized)
    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')
    # Remove leading/trailing underscores and dots
    sanitized = sanitized.strip('_.')
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    return sanitized


def get_case_filename(case_data: Dict, output_path: Path, case_index: Optional[int] = None) -> Path:
    """
    Generate a filename for a case JSON file.
    
    Args:
        case_data: The case data dictionary
        output_path: Output directory path
        case_index: Optional index number for uniqueness
        
    Returns:
        Path to the case JSON file
    """
    # Try to use case name first
    case_name = case_data.get('Case Name', case_data.get('caseName', ''))
    if case_name:
        filename = sanitize_filename(case_name)
    else:
        # Fall back to docket number
        docket = case_data.get('Docket Number', case_data.get('docketNumber', ''))
        if docket:
            filename = sanitize_filename(docket)
        else:
            # Fall back to cluster ID
            cluster_id = case_data.get('cluster_id', '')
            if cluster_id:
                filename = f"case_{cluster_id}"
            else:
                # Last resort: use index
                filename = f"case_{case_index or 'unknown'}"
    
    # Add index if provided for uniqueness
    if case_index is not None:
        filename = f"{case_index:05d}_{filename}"
    
    # Ensure filename is not empty
    if not filename:
        filename = f"case_{case_index or 'unknown'}"
    
    return output_path / f"{filename}.json"


def save_case_to_file(case_data: Dict, output_path: Path, case_index: Optional[int] = None) -> Path:
    """
    Save a single case to its own JSON file.
    
    Args:
        case_data: The case data dictionary
        output_path: Output directory path
        case_index: Optional index number for uniqueness
        
    Returns:
        Path to the saved file
    """
    case_file = get_case_filename(case_data, output_path, case_index)
    
    # Handle filename collisions by appending a number
    counter = 1
    original_file = case_file
    while case_file.exists():
        stem = original_file.stem
        case_file = output_path / f"{stem}_{counter}.json"
        counter += 1
    
    with open(case_file, 'w', encoding='utf-8') as f:
        json.dump(case_data, f, indent=2, ensure_ascii=False)
    
    return case_file


def get_downloaded_urls(output_path: Path) -> set:
    """
    Scan the output folder for existing case JSON files and return the set of
    case URLs that have already been downloaded.
    
    Args:
        output_path: Output directory path
        
    Returns:
        Set of case URLs that are already in the output folder
    """
    downloaded = set()
    if not output_path.exists():
        return downloaded
    
    for json_file in output_path.glob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                url = data.get('url')
                if url:
                    downloaded.add(url)
        except (json.JSONDecodeError, OSError):
            continue
    
    return downloaded


def make_api_request(url: str, api_token: Optional[str] = None, max_retries: int = 3) -> Optional[requests.Response]:
    """
    Make an API request with retry logic and error handling.
    
    Args:
        url: The URL to request
        api_token: API token for authentication (optional but recommended)
        max_retries: Maximum number of retry attempts
        
    Returns:
        Response object, or None if request failed
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": "CourtListener-Case-Crawler/1.0"
    }
    
    if api_token:
        headers["Authorization"] = f"Token {api_token}"
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            time.sleep(REQUEST_DELAY)  # Be respectful to the API
            return response
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"  Retry {attempt + 1}/{max_retries} for {url}")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f"  Error fetching {url}: {e}")
                return None
    
    return None


def get_decade_folder(year: int) -> str:
    """Return decade folder name for a year, e.g. 1975 -> '1970s'."""
    decade_start = (year // 10) * 10
    return f"{decade_start}s"


def parse_year_or_decade(value: str) -> List[int]:
    """
    Parse a year or decade string into a list of years.
    
    - "1960s" or "1960S" -> [1960, 1961, ..., 1969]
    - "2024" -> [2024]
    
    Args:
        value: Either a 4-digit year or a decade like 1960s
        
    Returns:
        List of years (one element for single year, 10 for a decade)
        
    Raises:
        ValueError: If value is not a valid year or decade
    """
    value = value.strip()
    if re.match(r"^\d{4}s$", value, re.IGNORECASE):
        start = int(value[:4])
        return list(range(start, start + 10))
    if re.match(r"^\d{4}$", value):
        return [int(value)]
    raise ValueError(f"Invalid year or decade: {value!r}. Use a 4-digit year (e.g. 2024) or decade (e.g. 1960s).")


def build_api_url_from_year(year: int, courts: str = DEFAULT_COURTS, api_token: Optional[str] = None) -> str:
    """
    Build a CourtListener API URL from a target year.
    
    Args:
        year: Target year (e.g., 2025)
        courts: Court filter string (default: Massachusetts courts)
        api_token: API token (optional)
        
    Returns:
        Constructed API URL with proper date range parameters
    """
    # Date range: from January 1 of the year to January 1 of the next year
    filed_after = f"{year}-01-01"
    filed_before = f"{year + 1}-01-01"
    
    # Build API parameters
    params = {
        'q': '',
        'type': 'o',  # Case law opinions
        'order_by': 'dateFiled desc',
        'stat_Published': 'on',
        'filed_after': filed_after,
        'filed_before': filed_before,
        'court': courts
    }
    
    # Construct URL with encoded parameters
    query_string = urlencode(params, doseq=True)
    url = f"{API_BASE_URL}/?{query_string}"
    
    return url


def convert_api_result_to_case_data(api_result: Dict) -> Dict:
    """
    Convert an API result to the standardized case data format.
    
    Args:
        api_result: Result from the API
        
    Returns:
        Dictionary with standardized case information
    """
    case_data = {
        "url": f"{BASE_URL}{api_result.get('absolute_url', '')}",
        "Case Name": api_result.get('caseName', api_result.get('caseNameFull', '')),
        "Court": api_result.get('court', ''),
        "Docket Number": api_result.get('docketNumber', ''),
        "Dates": api_result.get('dateFiled', ''),
        "Citations": ', '.join(api_result.get('citation', [])) if api_result.get('citation') else None,
        "cluster_id": api_result.get('cluster_id'),
        "docket_id": api_result.get('docket_id'),
    }
    
    # Extract judges from panel_names if available
    panel_names = api_result.get('panel_names', [])
    if panel_names:
        case_data["Judges"] = ', '.join(panel_names)
    else:
        # Try to get from judge field
        judge = api_result.get('judge', '')
        if judge:
            case_data["Judges"] = judge
    
    # Extract dates - try to get date range if available
    date_filed = api_result.get('dateFiled', '')
    if date_filed:
        case_data["Dates"] = date_filed
    
    # Extract keywords/subjects if available in opinions
    opinions = api_result.get('opinions', [])
    if opinions:
        # Get snippet from first opinion
        first_opinion = opinions[0]
        snippet = first_opinion.get('snippet', '')
        if snippet:
            # Store snippet as content preview
            case_data["content_preview"] = snippet[:500]  # First 500 chars
    
    # Add other useful fields
    case_data["status"] = api_result.get('status', '')
    case_data["posture"] = api_result.get('posture', '')
    case_data["suitNature"] = api_result.get('suitNature', '')
    
    # full_text is always a field; populated when fetched from Opinion API
    case_data["full_text"] = None
    
    # Store full API response for reference
    case_data["api_data"] = api_result
    
    return case_data


def fetch_opinion_full_text(opinion_id: int, api_token: Optional[str] = None) -> Optional[str]:
    """
    Fetch the full text of a single opinion from the CourtListener Opinion API.
    
    Args:
        opinion_id: The opinion ID (from api_result['opinions'][i]['id'])
        api_token: API token (optional but recommended)
        
    Returns:
        Plain text of the opinion, or None if failed/unavailable
    """
    url = f"{OPINION_API_BASE}/{opinion_id}/"
    response = make_api_request(url, api_token)
    if not response:
        return None
    try:
        data = response.json()
        text = data.get("plain_text")
        if text and isinstance(text, str):
            return text.strip()
        # Fall back to HTML and strip tags for readable text
        html = data.get("html") or data.get("html_with_citations")
        if html and isinstance(html, str):
            # Simple tag strip: remove tags, collapse whitespace
            plain = re.sub(r"<[^>]+>", " ", html)
            plain = re.sub(r"\s+", " ", plain).strip()
            return plain if plain else None
        return None
    except (json.JSONDecodeError, KeyError):
        return None


def fetch_full_text_for_case(api_result: Dict, api_token: Optional[str] = None) -> Optional[str]:
    """
    Fetch full opinion text for all opinions in a search result and combine them.
    
    Args:
        api_result: One result from the search API (cluster with nested opinions)
        api_token: API token (optional)
        
    Returns:
        Combined full text of all opinions, or None if none could be fetched
    """
    opinions = api_result.get("opinions", [])
    if not opinions:
        return None
    parts = []
    for op in opinions:
        op_id = op.get("id")
        if op_id is None:
            continue
        text = fetch_opinion_full_text(op_id, api_token)
        if text:
            parts.append(text)
        time.sleep(REQUEST_DELAY)
    if not parts:
        return None
    return "\n\n---\n\n".join(parts)


def fetch_case_content(case_url: str, api_token: Optional[str] = None) -> Optional[str]:
    """
    Fetch the full content of a case from its detail page.
    This is a fallback if the API doesn't provide full content.
    
    Args:
        case_url: URL of the case detail page
        api_token: API token (optional)
        
    Returns:
        Full text content, or None if failed
    """
    # Full content is now fetched via fetch_opinion_full_text / fetch_full_text_for_case
    return None


def crawl_cases_api(
    index_url: str,
    api_token: Optional[str] = None,
    max_results: Optional[int] = None,
    output_dir: str = OUTPUT_DIR,
    fetch_full_text: bool = True,
) -> None:
    """
    Main function to crawl cases from the API.
    
    Args:
        index_url: Starting API URL or search URL
        api_token: API token for authentication
        max_results: Maximum number of results to fetch (None for all)
        output_dir: Directory to save JSON files
        fetch_full_text: If True, fetch full opinion text from Opinion API for each case
    """
    output_path = Path(output_dir)
    # Directory is created lazily when the first case is saved (see below)
    print(f"Output directory: {output_path.absolute()}\n")
    
    # Load set of already-downloaded case URLs (skip these)
    downloaded_urls = get_downloaded_urls(output_path)
    if downloaded_urls:
        print(f"  Found {len(downloaded_urls)} already-downloaded cases in output folder (will skip).\n")
    
    current_url = index_url
    total_cases_saved = 0
    total_skipped = 0
    case_counter = 0
    
    print(f"Starting API crawl from: {index_url}\n")
    
    while current_url:
        if max_results and total_cases_saved >= max_results:
            print(f"\nReached maximum results limit ({max_results})")
            break
        
        print(f"Fetching results from API...")
        print(f"  URL: {current_url}")
        
        # Make API request
        response = make_api_request(current_url, api_token)
        if not response:
            print("  Failed to fetch from API. Stopping.")
            break
        
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            print(f"  Error parsing JSON response: {e}")
            break
        
        # Extract results
        results = data.get('results', [])
        count = data.get('count', 0)
        next_url = data.get('next')
        
        print(f"  Found {len(results)} cases in this batch (total available: {count})")
        
        if not results:
            print("  No more cases found. Stopping.")
            break
        
        # Process each case
        for api_result in results:
            if max_results and total_cases_saved >= max_results:
                break
            
            case_url = f"{BASE_URL}{api_result.get('absolute_url', '')}"
            if case_url in downloaded_urls:
                case_counter += 1
                total_skipped += 1
                case_name = api_result.get('caseName', api_result.get('caseNameFull', 'Unknown'))
                print(f"    [{case_counter}] Skipped (already downloaded): {case_name}")
                continue
            
            case_counter += 1
            case_name = api_result.get('caseName', api_result.get('caseNameFull', 'Unknown'))
            print(f"    [{case_counter}] Processing: {case_name}")
            
            # Convert API result to standardized format
            case_data = convert_api_result_to_case_data(api_result)
            
            # Optionally fetch full opinion text (detailed case context)
            if fetch_full_text:
                full_text = fetch_full_text_for_case(api_result, api_token)
                if full_text:
                    case_data["full_text"] = full_text
                    print(f"      Fetched full text ({len(full_text)} chars)")
                else:
                    print(f"      No full text available (snippet only)")
            
            # Lazy-create year dir when first case is saved
            output_path.mkdir(parents=True, exist_ok=True)
            # Save each case to its own file immediately
            case_file = save_case_to_file(case_data, output_path, case_counter)
            total_cases_saved += 1
            downloaded_urls.add(case_url)
            print(f"      ✓ Saved: {case_file.name}")
        
        # Check for next page
        if next_url:
            # Extract cursor from next URL
            if 'cursor=' in next_url:
                current_url = next_url
                print(f"\n  Moving to next page...")
            else:
                print("\n  No more pages found. Crawl complete.")
                current_url = None
        else:
            print("\n  No more pages found. Crawl complete.")
            current_url = None
    
    print(f"\n✓ Download complete! Saved {total_cases_saved} new cases ({total_skipped} already present) to: {output_path.absolute()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Crawl law cases from CourtListener.com using the Legal Search API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single year (creates output_dir/2020s/2025/)
  python case_crawler_api.py --year 2025 --api-token YOUR_TOKEN
  
  # Multiple years (creates output_dir/2020s/2023/, output_dir/2020s/2024/, etc.)
  python case_crawler_api.py --year 2023 2024 2025 --api-token YOUR_TOKEN
  
  # Decade: download 1960-1969 (creates output_dir/1960s/1960/, ... output_dir/1960s/1969/)
  python case_crawler_api.py --year 1960s --api-token YOUR_TOKEN
  
  # Mix years and decades (e.g. 1960s plus 2024)
  python case_crawler_api.py --year 1960s 2024 2025 --api-token YOUR_TOKEN
  
  # Use custom URL (no year/decade subfolder; saves directly to output_dir)
  python case_crawler_api.py --url "https://www.courtlistener.com/api/rest/v4/search/?q=..." --api-token YOUR_TOKEN
  
  # Multiple courts (same run, cases from any of the listed courts)
  python case_crawler_api.py --year 2024 -c mass ca1 --api-token YOUR_TOKEN
  
  # Limit to first 100 results per year
  python case_crawler_api.py --year 2024 2025 --max-results 100 --api-token YOUR_TOKEN
  
  # Get API token from environment variable
  export COURTLISTENER_API_TOKEN=your_token_here
  python case_crawler_api.py --year 2025
        """
    )
    
    # Create mutually exclusive group for URL source
    url_group = parser.add_mutually_exclusive_group(required=True)
    url_group.add_argument(
        "-y", "--year",
        type=str,
        nargs="+",
        dest="years",
        metavar="YEAR_OR_DECADE",
        help="Years and/or decades (e.g. -y 2024 2025 or -y 1960s). Decade like 1960s downloads 1960-1969. Creates output_dir/<decade>/<year>/."
    )
    url_group.add_argument(
        "-u", "--url",
        type=str,
        dest="index_url",
        help="Custom API URL of the search endpoint to start crawling from (no year subfolder)"
    )
    
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=OUTPUT_DIR,
        help=f"Output directory for downloaded cases (default: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "-m", "--max-results",
        type=int,
        default=None,
        help="Maximum number of results to fetch (default: all results)"
    )
    parser.add_argument(
        "-c", "--courts",
        type=str,
        nargs="+",
        default=None,
        metavar="COURT",
        help=f"One or more court IDs (e.g. -c mass ca1). Default: {DEFAULT_COURTS!r}. Only used with --year option."
    )
    parser.add_argument(
        "-t", "--api-token",
        type=str,
        default=None,
        help="API token for authentication. Can also be set via COURTLISTENER_API_TOKEN environment variable."
    )
    parser.add_argument(
        "--no-full-text",
        action="store_true",
        help="Do not fetch full opinion text (only metadata and snippet). Use to speed up or reduce API calls."
    )
    
    args = parser.parse_args()
    
    # Get API token from argument or environment variable
    api_token = args.api_token or os.getenv('COURTLISTENER_API_TOKEN')
    if not api_token:
        print("Warning: No API token provided. Some requests may be rate-limited.")
        print("  Get a token at: https://www.courtlistener.com/api/rest-info/")
        print("  Or set COURTLISTENER_API_TOKEN environment variable\n")
    
    if args.years is not None:
        # Parse year/decade args (e.g. 2024, 1960s -> [2024] or [1960..1969])
        try:
            years = sorted(set(y for arg in args.years for y in parse_year_or_decade(arg)))
        except ValueError as e:
            parser.error(str(e))
        if not years:
            parser.error("No years to crawl")
        courts_param = " ".join(args.courts) if args.courts else DEFAULT_COURTS
        output_base = Path(args.output)
        for year in years:
            decade = get_decade_folder(year)
            year_output = str(output_base / decade / str(year))
            index_url = build_api_url_from_year(year, courts_param, api_token)
            print(f"\n{'='*60}")
            print(f"Year {year} -> {year_output}")
            print(f"API URL: {index_url}")
            print(f"{'='*60}\n")
            crawl_cases_api(
                index_url,
                api_token,
                args.max_results,
                year_output,
                fetch_full_text=not args.no_full_text,
            )
    else:
        # Custom URL: single run, save directly to output_dir
        index_url = args.index_url
        if '/api/rest/v4/search' not in index_url:
            print("Warning: URL doesn't appear to be an API endpoint. Expected /api/rest/v4/search/")
        crawl_cases_api(
            index_url,
            api_token,
            args.max_results,
            args.output,
            fetch_full_text=not args.no_full_text,
        )
