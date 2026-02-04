#!/usr/bin/env python3
"""
CourtListener Law Case Crawler

This script crawls CourtListener.com to download law cases from search results.
It parses index pages, extracts case detail URLs, handles pagination, and
extracts structured case information in JSON format.
"""

import argparse
import json
import re
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse, quote
from bs4 import BeautifulSoup


BASE_URL = "https://www.courtlistener.com"
REQUEST_DELAY = 1.0  # Delay between requests to be respectful
OUTPUT_DIR = "law_cases"

# Default court filter for Massachusetts courts
DEFAULT_COURTS = "mass massappct masssuperct massdistct masslandct maworkcompcom"

# Global session for maintaining cookies
_session = None


def get_session():
    """Get or create a requests session with proper headers."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
            "Referer": "https://www.courtlistener.com/"
        })
    return _session


def make_request(url: str, max_retries: int = 3) -> Optional[requests.Response]:
    """
    Make an HTTP request with retry logic and error handling.
    
    Args:
        url: The URL to request
        max_retries: Maximum number of retry attempts
        
    Returns:
        Response object, or None if request failed
    """
    session = get_session()
    for attempt in range(max_retries):
        try:
            response = session.get(url, timeout=30, allow_redirects=True)
            # Don't raise for status - we want to check the status code ourselves
            # response.raise_for_status()
            time.sleep(REQUEST_DELAY)  # Be respectful to the server
            return response
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"  Retry {attempt + 1}/{max_retries} for {url}")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f"  Error fetching {url}: {e}")
                return None
    
    return None


def is_aws_waf_challenge(response: requests.Response) -> bool:
    """
    Detect if the response is an AWS WAF JavaScript challenge page.
    When the site returns 202 (or sometimes 200) with a challenge page,
    the body contains awsWafCookieDomainList, challenge.js, or AwsWafIntegration.
    """
    if not response.content or len(response.content) < 200:
        return False
    try:
        text = response.content.decode("utf-8", errors="ignore")
        return (
            "awsWafCookieDomainList" in text
            or "challenge.js" in text
            or "AwsWafIntegration" in text
            or "token.awswaf.com" in text
        )
    except Exception:
        return False


def get_case_urls_from_index(index_url: str) -> tuple[List[str], Optional[BeautifulSoup]]:
    """
    Parse an index page to extract case detail page URLs.
    
    Args:
        index_url: URL of the index/search results page
        
    Returns:
        Tuple of (list of case detail page URLs, BeautifulSoup object for pagination check)
    """
    response = make_request(index_url)
    if not response:
        return [], None
    
    if is_aws_waf_challenge(response):
        print(
            "  Error: The site returned an AWS WAF challenge page (anti-bot). "
            "Use a browser or a headless browser (e.g. Playwright/Selenium) to pass the challenge, "
            "or try again later from a different network."
        )
        return [], None
    
    if response.status_code not in (200, 202):
        print(f"  Warning: Search index returned status {response.status_code} for {index_url}")
        return [], None
    
    soup = BeautifulSoup(response.content, 'lxml')
    case_urls = []
    
    # Find the search results div
    search_results = soup.find('div', id='search-results')
    if not search_results:
        print(f"  Warning: Could not find search-results div in {index_url}")
        return [], soup
    
    # Find all result items - they might be in various structures
    # Look for result items (could be divs, articles, or list items)
    result_items = search_results.find_all(['article', 'div', 'li'], class_=re.compile(r'result|item|case', re.I))
    
    if not result_items:
        # Fallback: find all links within search-results
        result_items = [search_results]
    
    # Extract URLs from result items
    for item in result_items:
        # Look for links to opinion pages
        links = item.find_all('a', href=True)
        for link in links:
            href = link.get('href', '')
            # CourtListener uses /opinion/ for case opinions
            if '/opinion/' in href:
                full_url = urljoin(BASE_URL, href)
                # Remove any fragment or query params that might be duplicates
                parsed = urlparse(full_url)
                clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
                if clean_url not in case_urls:
                    case_urls.append(clean_url)
    
    return case_urls, soup


def has_next_page(soup: BeautifulSoup, current_url: str, found_cases: int) -> Optional[str]:
    """
    Check if there's a next page and return its URL.
    
    Args:
        soup: BeautifulSoup object of the current page
        current_url: Current page URL
        found_cases: Number of cases found on current page
        
    Returns:
        URL of next page if exists, None otherwise
    """
    # Strategy 1: Look for pagination links - try various common patterns
    pagination = (soup.find('div', class_=re.compile(r'pagination', re.I)) or 
                  soup.find('nav', class_=re.compile(r'pagination', re.I)) or
                  soup.find('ul', class_=re.compile(r'pagination', re.I)) or
                  soup.find('div', class_=re.compile(r'page', re.I)))
    
    if pagination:
        # Look for next link with multiple strategies
        next_link = None
        
        # Try aria-label
        next_link = pagination.find('a', {'aria-label': re.compile(r'next', re.I)})
        
        # Try class containing 'next'
        if not next_link:
            next_link = pagination.find('a', class_=lambda x: x and 'next' in ' '.join(x).lower())
        
        # Try text content containing 'next' or '>'
        if not next_link:
            for link in pagination.find_all('a', href=True):
                text = link.get_text().strip().lower()
                if 'next' in text or text == '>' or text == '»':
                    next_link = link
                    break
        
        if next_link and next_link.get('href'):
            href = next_link['href']
            # Check if it's disabled or not a real link
            classes = next_link.get('class', [])
            class_str = ' '.join(classes).lower() if isinstance(classes, list) else str(classes).lower()
            if 'disabled' not in class_str and href not in ['#', '', None]:
                full_url = urljoin(BASE_URL, href)
                print(f"  Debug: Found next page link: {full_url}")
                return full_url
    
    # Strategy 2: Check for page number links and find the next one
    if pagination:
        # Find all page number links
        page_links = pagination.find_all('a', href=True)
        current_page_num = None
        
        # Parse current URL to get current page
        parsed = urlparse(current_url)
        query_params = parse_qs(parsed.query)
        current_page_num = int(query_params.get('page', ['1'])[0])
        
        # Look for a link with page number = current + 1
        next_page_num = current_page_num + 1
        for link in page_links:
            href = link.get('href', '')
            if href:
                # Check if href contains page parameter
                if f'page={next_page_num}' in href or f'&page={next_page_num}' in href:
                    full_url = urljoin(BASE_URL, href)
                    print(f"  Debug: Found next page via page number: {full_url}")
                    return full_url
        
        # Check if there's a link with a higher page number
        for link in page_links:
            href = link.get('href', '')
            text = link.get_text().strip()
            # Try to extract page number from link
            if href:
                href_match = re.search(r'[?&]page=(\d+)', href)
                if href_match:
                    page_num = int(href_match.group(1))
                    if page_num > current_page_num:
                        full_url = urljoin(BASE_URL, href)
                        print(f"  Debug: Found higher page number: {full_url}")
                        return full_url
    
    # Strategy 3: If we found cases on this page, try constructing next page URL
    if found_cases > 0:
        parsed = urlparse(current_url)
        query_params = parse_qs(parsed.query)
        
        current_page = int(query_params.get('page', ['1'])[0])
        next_page = current_page + 1
        
        # Construct next page URL
        query_params['page'] = [str(next_page)]
        new_query = urlencode(query_params, doseq=True)
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        print(f"  Debug: Constructed next page URL: {new_url}")
        return new_url
    
    return None


def extract_text_from_html(html_content: str) -> str:
    """
    Extract plain text from HTML, filtering out HTML tags.
    
    Args:
        html_content: HTML string
        
    Returns:
        Plain text content
    """
    soup = BeautifulSoup(html_content, 'lxml')
    
    # Remove script and style elements
    for script in soup(["script", "style", "nav", "footer", "header"]):
        script.decompose()
    
    # Replace <br>, <br/>, <br /> tags with spaces before extracting text
    # This prevents words from different lines being concatenated
    # BeautifulSoup handles all variations: <br>, <br/>, <br />, <BR>, etc.
    for br in soup.find_all('br'):
        br.replace_with(' ')
    
    # Get text and clean it up
    text = soup.get_text()
    
    # Clean up whitespace
    # Replace multiple newlines with single space (handles paragraph breaks)
    text = re.sub(r'\n\s*\n+', ' ', text)
    # Replace single newlines with space (handles line breaks)
    text = re.sub(r'\n+', ' ', text)
    # Clean up multiple spaces
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    # Final cleanup: remove any remaining excessive spaces
    text = re.sub(r' +', ' ', text)
    
    return text


def extract_field_value(soup: BeautifulSoup, label_text: str) -> Optional[str]:
    """
    Extract a field value by looking for a label and getting the following value.
    
    Args:
        soup: BeautifulSoup object
        label_text: Text of the label to find
        
    Returns:
        Field value as string, or None if not found
    """
    # Try multiple strategies to find the field
    
    # Strategy 1: Look for dt/dd pairs (common in definition lists)
    dt = soup.find('dt', string=re.compile(label_text, re.I))
    if dt:
        dd = dt.find_next_sibling('dd')
        if dd:
            return extract_text_from_html(str(dd)).strip()
    
    # Strategy 2: Look for label elements
    label = soup.find('label', string=re.compile(label_text, re.I))
    if label:
        # Try to find associated value
        parent = label.find_parent()
        if parent:
            value_elem = (parent.find('span') or 
                         parent.find('div', class_=re.compile(r'value|field', re.I)) or
                         parent.find_next_sibling())
            if value_elem:
                return extract_text_from_html(str(value_elem)).strip()
    
    # Strategy 3: Look for strong/bold labels followed by text
    strong = soup.find(['strong', 'b'], string=re.compile(label_text, re.I))
    if strong:
        parent = strong.find_parent()
        if parent:
            text = parent.get_text()
            # Extract text after the label
            match = re.search(re.escape(label_text) + r'[:\s]+(.+?)(?:\n\n|\n[A-Z]|$)', text, re.I | re.DOTALL)
            if match:
                return match.group(1).strip()
    
    # Strategy 4: Look for divs or spans with class containing the label
    field_div = soup.find('div', class_=re.compile(label_text.lower().replace(' ', r'[\s_-]'), re.I))
    if field_div:
        value = extract_text_from_html(str(field_div))
        if value and value != label_text:
            return value.strip()
    
    # Strategy 5: Search in the main document area for label: value patterns
    # But be more careful - only capture up to the next line or reasonable length
    main_doc = soup.select_one('div.col-sm-9.main-document')
    if main_doc:
        text = main_doc.get_text()
        # Look for "Label: Value" pattern, but stop at newline or next label
        # Limit to first 500 chars to avoid capturing entire document
        pattern = re.compile(rf'{re.escape(label_text)}[:\s]+(.+?)(?:\n|$)', re.I | re.DOTALL)
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            # Only return if reasonable length (not entire document)
            if len(value) <= 500:
                # Stop at first newline or next label pattern
                value = re.split(r'\n|(?:\n[A-Z][a-z]+\s*:)', value)[0].strip()
                if value:
                    return value
    
    return None


def parse_case_detail(case_url: str) -> Optional[Dict]:
    """
    Parse a case detail page and extract structured information.
    
    Args:
        case_url: URL of the case detail page
        
    Returns:
        Dictionary with case information, or None if parsing failed
    """
    response = make_request(case_url)
    if not response:
        return None
    
    if is_aws_waf_challenge(response):
        print(
            f"  Error: Got AWS WAF challenge page for {case_url}. "
            "The site is blocking automated requests. Use a browser or headless browser, or try again later."
        )
        return None
    
    # Some sites return 202 (Accepted) or other codes that still contain content
    if response.status_code not in [200, 202]:
        print(f"  Warning: Got status code {response.status_code} for {case_url}")
        return None
    
    # For 202, check if we actually got HTML content (and it's not a WAF page)
    if response.status_code == 202:
        if not response.content or len(response.content) < 500:
            print(f"  Warning: Got 202 with insufficient content (length: {len(response.content) if response.content else 0})")
            if len(response.content) < 100:
                return None
    
    # Debug: Check if we got HTML content
    if not response.content or len(response.content) < 100:
        print(f"  Warning: Response content is too short or empty for {case_url} (length: {len(response.content) if response.content else 0})")
        return None
    
    # Check content type
    content_type = response.headers.get('Content-Type', '')
    if 'text/html' not in content_type.lower():
        print(f"  Warning: Unexpected content type: {content_type} for {case_url}")
    
    soup = BeautifulSoup(response.content, 'lxml')
    
    # Debug: Check if soup was created successfully and has basic structure
    if not soup:
        print(f"  Warning: Failed to parse HTML for {case_url}")
        return None
    
    # Debug: Verify we have HTML structure
    html_tag = soup.find('html')
    if not html_tag:
        print(f"  Warning: No <html> tag found in response for {case_url}")
        # Try to continue anyway - maybe it's a fragment
    
    # Find the main document div - try multiple strategies
    main_doc = None
    
    # Strategy 1: Use CSS selector (most reliable for multiple classes)
    # BeautifulSoup stores multiple classes as a list, so CSS selectors work best
    try:
        # Try different CSS selector variations
        main_doc = soup.select_one('div.col-sm-9.main-document')
        if not main_doc:
            # Try with space (though this shouldn't work, but just in case)
            main_doc = soup.select_one('div.col-sm-9 .main-document')
        if not main_doc:
            # Try finding any div with main-document class that's inside col-sm-9
            col_sm_9 = soup.select_one('div.col-sm-9')
            if col_sm_9:
                main_doc = col_sm_9.select_one('.main-document')
        if main_doc:
            print(f"  Debug: Found div using CSS selector")
    except Exception as e:
        print(f"  Debug: CSS selector failed: {e}")
    
    # Strategy 2: Helper function to check if classes match (handles both string and list)
    def has_all_classes(elem, class_names):
        """Check if element has ALL specified classes."""
        if not elem:
            return False
        classes = elem.get('class', [])
        if isinstance(classes, str):
            classes = classes.split()
        # Convert to lowercase for comparison
        classes_lower = [c.lower() for c in classes]
        class_names_lower = [c.lower() for c in class_names]
        return all(name in classes_lower for name in class_names_lower)
    
    # Strategy 3: Try finding divs with both classes manually (most reliable)
    if not main_doc:
        for div in soup.find_all('div', class_=True):
            if has_all_classes(div, ['col-sm-9', 'main-document']):
                main_doc = div
                print(f"  Debug: Found div using manual class check")
                break
    
    # Strategy 4: Try exact string match (in case classes are stored as string)
    if not main_doc:
        main_doc = soup.find('div', class_='col-sm-9 main-document')
        if main_doc:
            print(f"  Debug: Found div using string match")
    
    # Strategy 6: Try finding by class pattern
    if not main_doc:
        main_doc = soup.find('div', class_=re.compile(r'main.*document', re.I))
    
    # Strategy 3: Try finding by ID
    if not main_doc:
        main_doc = soup.find('div', id='opinion-content') or soup.find('div', id=re.compile(r'opinion|content|document', re.I))
    
    # Strategy 4: Try finding article tag
    if not main_doc:
        main_doc = soup.find('article')
    
    # Strategy 5: Try finding main content area by role or semantic HTML
    if not main_doc:
        main_doc = soup.find('main') or soup.find('div', role='main')
    
    # Strategy 6: Try finding by looking for common content containers
    if not main_doc:
        # Look for divs with class containing 'content' or 'opinion'
        for div in soup.find_all('div', class_=True):
            classes = div.get('class', [])
            if isinstance(classes, str):
                classes = classes.split()
            classes_str = ' '.join(classes).lower()
            if any(term in classes_str for term in ['content', 'opinion', 'text', 'document']):
                # Make sure it's not a navigation or sidebar
                if not any(skip in classes_str for skip in ['nav', 'header', 'footer', 'sidebar', 'menu', 'aside']):
                    main_doc = div
                    break
    
    # Strategy 7: Try finding the largest text-containing div (fallback)
    if not main_doc:
        # Find all divs and pick the one with most text content
        all_divs = soup.find_all('div')
        if all_divs:
            # Filter out navigation, header, footer, sidebar
            content_divs = []
            for d in all_divs:
                classes = d.get('class', [])
                if isinstance(classes, str):
                    classes = classes.split()
                classes_str = ' '.join(classes).lower()
                if not any(skip in classes_str for skip in ['nav', 'header', 'footer', 'sidebar', 'menu', 'aside']):
                    text_len = len(d.get_text().strip())
                    if text_len > 100:  # Only consider divs with substantial content
                        content_divs.append(d)
            if content_divs:
                # Get the div with the most text
                main_doc = max(content_divs, key=lambda d: len(d.get_text()))
    
    if not main_doc:
        # Debug: Let's see what divs with classes we can find
        divs_with_classes = soup.find_all('div', class_=True)
        print(f"  Debug: Found {len(divs_with_classes)} divs with classes")
        if divs_with_classes:
            # Check if any have the classes we're looking for
            found_relevant = False
            for div in divs_with_classes[:10]:  # Check first 10 for debugging
                classes = div.get('class', [])
                classes_str = ' '.join(classes) if isinstance(classes, list) else str(classes)
                if 'col-sm-9' in classes_str or 'main-document' in classes_str:
                    print(f"  Debug: Found div with classes: {classes_str}")
                    found_relevant = True
            if not found_relevant and len(divs_with_classes) > 0:
                # Show first few div classes for debugging
                print(f"  Debug: Sample div classes found: {[div.get('class') for div in divs_with_classes[:3]]}")
        
        # Debug: Check if body exists
        body = soup.find('body')
        if body:
            print(f"  Debug: Body tag found, using it as fallback")
            main_doc = body
        else:
            # Debug: Check what tags we do have
            print(f"  Debug: No body tag found. Root tag: {soup.name if soup.name else 'None'}")
            print(f"  Debug: First few tags: {[tag.name for tag in list(soup.children)[:5] if hasattr(tag, 'name')]}")
            print(f"  Warning: Could not find main-document div or body in {case_url}")
            # Still try to extract metadata even if we can't find content
            main_doc = soup if soup else None
    
    # Extract plain text content from main document (filter out HTML)
    if main_doc:
        content = extract_text_from_html(str(main_doc))
    else:
        content = ""
    
    # Initialize case data with URL and content
    case_data = {
        "url": case_url,
        "content": content,
    }
    
    # Extract structured fields - try multiple label variations
    citations = (extract_field_value(soup, "Citation") or 
                extract_field_value(soup, "Citations") or
                extract_field_value(soup, "Cite"))
    if citations:
        case_data["Citations"] = citations
    
    docket_number = (extract_field_value(soup, "Docket Number") or 
                    extract_field_value(soup, "Docket No") or
                    extract_field_value(soup, "Docket"))
    if docket_number:
        case_data["Docket Number"] = docket_number
    
    # Extract judges - look for "Present:" or "Judges:" pattern in the document
    judges = None
    # Try structured extraction first
    judges = (extract_field_value(soup, "Judge") or 
             extract_field_value(soup, "Judges") or
             extract_field_value(soup, "Author") or
             extract_field_value(soup, "Opinion By"))
    
    # If not found, look for "Present:" pattern in the main document
    if not judges or len(judges) > 200:  # If too long, it's probably wrong
        main_doc = soup.select_one('div.col-sm-9.main-document')
        if main_doc:
            text = main_doc.get_text()
            # Look for "Present:" pattern which is common in court opinions
            # Pattern: "Present: Name1, Name2, & Name3, JJ."
            present_match = re.search(r'Present:\s*([A-Z][^.\n]+?)(?:\.|$|\n)', text, re.I)
            if present_match:
                judges = present_match.group(1).strip()
                # Clean up common suffixes
                judges = re.sub(r',\s*JJ\.?$', '', judges, flags=re.I).strip()
            # Also try "Judges:" pattern
            if not judges or len(judges) > 200:
                judges_match = re.search(r'Judges?:\s*([A-Z][^.\n]+?)(?:\.|$|\n)', text, re.I)
                if judges_match:
                    judges = judges_match.group(1).strip()
    
    if judges and len(judges) <= 200:  # Only use if reasonable length
        case_data["Judges"] = judges
    
    docket = extract_field_value(soup, "Docket")
    if docket:
        case_data["Docket"] = docket
    
    # Extract dates - look for "Dates:" pattern in the document
    dates = None
    # Try structured extraction first
    dates = (extract_field_value(soup, "Date") or 
            extract_field_value(soup, "Filed") or 
            extract_field_value(soup, "Date Filed") or
            extract_field_value(soup, "Dates") or
            extract_field_value(soup, "Date Decided"))
    
    # If not found or too long, look for "Dates:" pattern in the main document
    if not dates or len(dates) > 200:  # If too long, it's probably wrong
        main_doc = soup.select_one('div.col-sm-9.main-document')
        if main_doc:
            text = main_doc.get_text()
            # Look for "Dates:" pattern followed by date range (handles both en-dash and hyphen)
            dates_match = re.search(r'Dates?:\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s*[–—-]\s*[A-Z][a-z]+\s+\d{1,2},\s+\d{4})', text, re.I)
            if dates_match:
                dates = dates_match.group(1).strip()
            # Also try single date patterns "Filed:" or "Decided:"
            if not dates or len(dates) > 200:
                filed_match = re.search(r'(?:Filed|Decided):\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})', text, re.I)
                if filed_match:
                    dates = filed_match.group(1).strip()
            # Try "Date Filed:" pattern
            if not dates or len(dates) > 200:
                date_filed_match = re.search(r'Date\s+Filed:\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})', text, re.I)
                if date_filed_match:
                    dates = date_filed_match.group(1).strip()
    
    if dates and len(dates) <= 200:  # Only use if reasonable length
        case_data["Dates"] = dates
    
    county = extract_field_value(soup, "County")
    if county:
        case_data["County"] = county
    
    keywords = (extract_field_value(soup, "Keyword") or 
               extract_field_value(soup, "Keywords") or
               extract_field_value(soup, "Subject"))
    if keywords:
        case_data["Keywords"] = keywords
    
    # Try to extract title/case name
    title_elem = (soup.find('h1') or 
                 soup.find('h2', class_=re.compile(r'case.*name', re.I)) or
                 soup.find('h2', id=re.compile(r'title', re.I)))
    if title_elem:
        case_name = extract_text_from_html(str(title_elem)).strip()
        if case_name:
            case_data["Case Name"] = case_name
    
    # Try to extract court name
    court_elem = (soup.find('span', class_=re.compile(r'court', re.I)) or 
                 soup.find('div', class_=re.compile(r'court', re.I)) or
                 soup.find('a', class_=re.compile(r'court', re.I)))
    if court_elem:
        court = extract_text_from_html(str(court_elem)).strip()
        if court:
            case_data["Court"] = court
    
    return case_data


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
    case_name = case_data.get('Case Name', '')
    if case_name:
        filename = sanitize_filename(case_name)
    else:
        # Fall back to docket number
        docket = case_data.get('Docket Number', '')
        if docket:
            filename = sanitize_filename(docket)
        else:
            # Fall back to URL
            url = case_data.get('url', '')
            if url:
                # Extract opinion ID from URL
                match = re.search(r'/opinion/(\d+)/', url)
                if match:
                    filename = f"case_{match.group(1)}"
                else:
                    filename = sanitize_filename(url.split('/')[-1] or 'case')
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


def build_index_url_from_year(year: int, courts: str = DEFAULT_COURTS) -> str:
    """
    Build a CourtListener index URL from a target year.
    
    Args:
        year: Target year (e.g., 2025)
        courts: Court filter string (default: Massachusetts courts)
        
    Returns:
        Constructed URL with proper date range parameters
    """
    # Date range: from January 1 of the year to January 1 of the next year
    filed_after = f"01/01/{year}"
    filed_before = f"01/01/{year + 1}"
    
    # Build URL parameters
    params = {
        'q': '',
        'type': 'o',
        'order_by': 'dateFiled desc',
        'stat_Published': 'on',
        'filed_after': filed_after,
        'filed_before': filed_before,
        'court': courts
    }
    
    # Construct URL with encoded parameters
    query_string = '&'.join(f"{key}={quote(str(value))}" for key, value in params.items())
    url = f"{BASE_URL}/?{query_string}"
    
    return url


def crawl_cases(index_url: str, max_pages: Optional[int] = None, output_dir: str = OUTPUT_DIR) -> None:
    """
    Main function to crawl cases from index pages.
    
    Args:
        index_url: Starting index/search results URL
        max_pages: Maximum number of pages to crawl (None for all)
        output_dir: Directory to save JSON files
    """
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_path.absolute()}\n")
    
    # Load set of already-downloaded case URLs so we can skip them
    downloaded_urls = get_downloaded_urls(output_path)
    if downloaded_urls:
        print(f"  Found {len(downloaded_urls)} already-downloaded cases in output folder (will skip).\n")
    
    current_url = index_url
    page_num = 1
    total_cases_saved = 0
    case_counter = 0  # Incremented only when we save a new case
    total_skipped = 0
    
    print(f"Starting crawl from: {index_url}\n")
    
    while current_url:
        if max_pages and page_num > max_pages:
            print(f"\nReached maximum page limit ({max_pages})")
            break
        
        print(f"Processing page {page_num}...")
        print(f"  URL: {current_url}")
        
        # Get case URLs from this page (also returns soup for pagination check)
        case_urls, page_soup = get_case_urls_from_index(current_url)
        print(f"  Found {len(case_urls)} cases on this page")
        
        if not case_urls:
            print("  No more cases found. Stopping.")
            break
        
        # Process each case
        for idx, case_url in enumerate(case_urls, 1):
            # Normalize URL for comparison (strip trailing slash, etc.)
            case_url_normalized = case_url.rstrip('/')
            
            # Skip if already downloaded
            if case_url_normalized in downloaded_urls or case_url in downloaded_urls:
                total_skipped += 1
                case_counter += 1  # Increment so filename IDs don't collide with existing files
                print(f"    [{idx}/{len(case_urls)}] Skipping (already downloaded): {case_url}")
                continue
            
            print(f"    [{idx}/{len(case_urls)}] Processing: {case_url}")
            case_data = parse_case_detail(case_url)
            
            if case_data:
                case_counter += 1
                # Save each case to its own file immediately
                case_file = save_case_to_file(case_data, output_path, case_counter)
                total_cases_saved += 1
                # Add to downloaded set so we don't re-download if seen again
                downloaded_urls.add(case_data.get('url', case_url))
                downloaded_urls.add(case_url_normalized)
                downloaded_urls.add(case_url)
                case_name = case_data.get('Case Name', 'Unknown')
                print(f"      ✓ Extracted and saved: {case_name}")
                print(f"        Saved to: {case_file.name}")
            else:
                print(f"      ✗ Failed to parse case")
        
        # Check for next page using the soup we already have
        if page_soup:
            next_url = has_next_page(page_soup, current_url, len(case_urls))
            
            if next_url and next_url != current_url:
                # Verify the next page actually exists by checking if it has results
                # (This prevents infinite loops if pagination is broken)
                print(f"  Checking next page: {next_url}")
                test_response = make_request(next_url)
                if test_response and is_aws_waf_challenge(test_response):
                    print(
                        "  Error: Next page returned AWS WAF challenge. Stopping. "
                        "Use a browser or headless browser, or try again later."
                    )
                    current_url = None
                elif test_response:
                    test_soup = BeautifulSoup(test_response.content, 'lxml')
                    test_results = test_soup.find('div', id='search-results')
                    if test_results:
                        # Check if there are any opinion links on the next page
                        test_links = test_results.find_all('a', href=True)
                        has_opinions = any('/opinion/' in link.get('href', '') for link in test_links)
                        if has_opinions:
                            current_url = next_url
                            page_num += 1
                            print(f"\n  ✓ Moving to page {page_num}...")
                        else:
                            print("\n  Next page has no results. Crawl complete.")
                            current_url = None
                    else:
                        print("\n  Next page has no search results. Crawl complete.")
                        current_url = None
                else:
                    print("\n  Could not fetch next page. Stopping.")
                    current_url = None
            else:
                print("\n  No more pages found. Crawl complete.")
                current_url = None
        else:
            print("\n  Could not parse page for pagination check. Stopping.")
            current_url = None
    
    if total_skipped > 0:
        print(f"\n✓ Download complete! Saved {total_cases_saved} new cases, skipped {total_skipped} already-downloaded. Output: {output_path.absolute()}")
    else:
        print(f"\n✓ Download complete! Saved {total_cases_saved} cases to individual JSON files in: {output_path.absolute()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Crawl law cases from CourtListener.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single year (creates output/2025/)
  python case_crawler.py --year 2025
  
  # Multiple years (creates output/2016/, output/2017/, output/2020/)
  python case_crawler.py --year 2016 2017 2020 -o ma_cases
  
  # Use custom URL (no year subfolder)
  python case_crawler.py --url "https://www.courtlistener.com/?q=..."
  
  # Limit to first 3 pages per year
  python case_crawler.py --year 2025 -p 3
        """
    )
    
    # Create mutually exclusive group for URL source
    url_group = parser.add_mutually_exclusive_group(required=True)
    url_group.add_argument(
        "-y", "--year",
        type=int,
        nargs="+",
        metavar="YEAR",
        help="Target year(s) to crawl (e.g., 2025 or 2016 2017 2020). Creates a subfolder per year. URL uses date range 01/01/YEAR to 01/01/YEAR+1"
    )
    url_group.add_argument(
        "-u", "--url",
        type=str,
        dest="index_url",
        help="Custom URL of the index/search results page to start crawling from (no year subfolder)"
    )
    
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=OUTPUT_DIR,
        help=f"Output directory for downloaded cases (default: {OUTPUT_DIR}). With --year, a subfolder per year is created (e.g. {OUTPUT_DIR}/2025/)."
    )
    parser.add_argument(
        "-p", "--max-pages",
        type=int,
        default=None,
        help="Maximum number of pages to crawl per year (default: all pages)"
    )
    parser.add_argument(
        "-c", "--courts",
        type=str,
        default=DEFAULT_COURTS,
        help=f"Court filter string (default: '{DEFAULT_COURTS}'). Only used with --year option."
    )
    
    args = parser.parse_args()
    
    if args.year is not None:
        # One or more years: create subfolder per year and crawl each
        years = args.year
        base_output = args.output
        for i, year in enumerate(years, 1):
            index_url = build_index_url_from_year(year, args.courts)
            year_output = str(Path(base_output) / str(year))
            print(f"\n{'='*60}")
            print(f"Year {i}/{len(years)}: {year}")
            print(f"Constructed URL: {index_url}")
            print(f"Output folder: {year_output}")
            print(f"{'='*60}\n")
            crawl_cases(index_url, args.max_pages, year_output)
    else:
        # Custom URL: single crawl, no year subfolder
        index_url = args.index_url
        crawl_cases(index_url, args.max_pages, args.output)
