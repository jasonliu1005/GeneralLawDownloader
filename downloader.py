#!/usr/bin/env python3
"""
Massachusetts General Laws Downloader

This script traverses the Massachusetts Legislature API to download all
General Laws organized by Parts, Chapters, and Sections.
"""

import argparse
import requests
import time
from pathlib import Path
from typing import Dict, List, Optional


BASE_URL = "https://malegislature.gov/api"
OUTPUT_DIR = "ma_laws"
REQUEST_DELAY = 0.5  # Delay between requests to be respectful to the API


def fix_url(url: str) -> str:
    """
    Convert http to https in API response URLs.
    
    The API returns URLs with http:// but they need to be https:// to work.
    """
    if url and url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url


def make_request(url: str, max_retries: int = 3) -> Optional[Dict]:
    """
    Make an API request with retry logic and error handling.
    
    Args:
        url: The URL to request
        max_retries: Maximum number of retry attempts
        
    Returns:
        JSON response as dict, or None if request failed
    """
    url = fix_url(url)
    
    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers={"accept": "application/json"},
                timeout=30
            )
            response.raise_for_status()
            time.sleep(REQUEST_DELAY)  # Be respectful to the API
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                print(f"  Retry {attempt + 1}/{max_retries} for {url}")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f"  Error fetching {url}: {e}")
                return None
    
    return None


def get_parts() -> List[Dict]:
    """Fetch all Parts from the API."""
    print("Fetching all Parts...")
    url = f"{BASE_URL}/Parts"
    parts = make_request(url)
    if parts:
        print(f"Found {len(parts)} Parts")
        return parts
    return []


def get_part_details(part_code: str) -> Optional[Dict]:
    """
    Fetch detailed information for a Part, including its Chapters.
    
    Args:
        part_code: Part code (e.g., "I", "II")
        
    Returns:
        Part details dictionary with Chapters, or None if failed
    """
    url = f"{BASE_URL}/Parts/{part_code}"
    return make_request(url)


def get_chapter_details(chapter_code: str) -> Optional[Dict]:
    """
    Fetch detailed information for a Chapter, including its Sections.
    
    Args:
        chapter_code: Chapter code (e.g., "1", "2A")
        
    Returns:
        Chapter details dictionary with Sections, or None if failed
    """
    url = f"{BASE_URL}/Chapters/{chapter_code}"
    return make_request(url)


def get_section_text(section_url: str) -> Optional[Dict]:
    """
    Fetch the full details of a Section including its text.
    
    Args:
        section_url: URL to the Section endpoint
        
    Returns:
        Section details dictionary, or None if failed
    """
    return make_request(section_url)


def download_all_laws(output_dir: str = OUTPUT_DIR) -> None:
    """
    Main function to traverse all Parts, Chapters, Sections and create documents.
    
    Args:
        output_dir: Directory to save the downloaded documents
    """
    # Create output directory and any missing parent directories
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {output_path.absolute()}\n")
    
    # Fetch all Parts
    parts = get_parts()
    if not parts:
        print("Failed to fetch Parts. Exiting.")
        return
    
    total_parts = len(parts)
    print(f"\nProcessing {total_parts} Parts...\n")
    
    # Process each Part
    for part_idx, part in enumerate(parts, 1):
        part_code = part.get("Code", "Unknown")
        
        if not part_code or part_code == "Unknown":
            print(f"[{part_idx}/{total_parts}] Warning: Invalid Part code, skipping...")
            continue
        
        # Fetch Part details (includes Chapters list)
        part_details = get_part_details(part_code)
        if not part_details:
            print(f"[{part_idx}/{total_parts}] Warning: Failed to fetch details for Part {part_code}, skipping...")
            continue
        
        part_name = part_details.get("Name", "No Title")
        print(f"[{part_idx}/{total_parts}] Processing Part {part_code}: {part_name}")
        
        # Open file for this Part and write header
        filename = output_path / f"Part_{part_code}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# Part {part_code}: {part_name}\n\n")
        
        # Get Chapters from Part details
        chapters_list = part_details.get("Chapters", [])
        if not chapters_list:
            print(f"  Warning: No chapters found for Part {part_code}")
            with open(filename, "a", encoding="utf-8") as f:
                f.write("*No chapters available*\n\n")
            continue
        
        print(f"  Found {len(chapters_list)} chapters")
        
        # Process each Chapter
        for chapter_idx, chapter_ref in enumerate(chapters_list, 1):
            chapter_code = chapter_ref.get("Code", "Unknown")
            
            # Fetch Chapter details (includes Sections list)
            chapter_details = get_chapter_details(chapter_code)
            if not chapter_details:
                print(f"    [{chapter_idx}/{len(chapters_list)}] Warning: Failed to fetch Chapter {chapter_code}, skipping...")
                continue
            
            chapter_name = chapter_details.get("Name", "No Title")
            print(f"    [{chapter_idx}/{len(chapters_list)}] Chapter {chapter_code}: {chapter_name}")
            
            # Write chapter header to file with proper markdown and separation
            with open(filename, "a", encoding="utf-8") as f:
                f.write("\n---\n\n")
                f.write(f"## Chapter {chapter_code}: {chapter_name}\n\n")
            
            # Get Sections from Chapter details
            sections_list = chapter_details.get("Sections", [])
            if not sections_list:
                print(f"      Warning: No sections found for Chapter {chapter_code}")
                with open(filename, "a", encoding="utf-8") as f:
                    f.write("*No sections available*\n\n")
                continue
            
            print(f"      Found {len(sections_list)} sections")
            
            # Process each Section
            for section_idx, section_ref in enumerate(sections_list, 1):
                section_code = section_ref.get("Code", "Unknown")
                
                if section_idx % 10 == 0 or section_idx == len(sections_list):
                    print(f"        [{section_idx}/{len(sections_list)}] Section {section_code}")
                
                # Get Section URL
                section_url = section_ref.get("Details")
                if not section_url:
                    print(f"          ERROR: No Details URL for Section {section_code} in Chapter {chapter_code}, skipping...")
                    continue
                
                # Fetch Section details (includes Text)
                section_details = get_section_text(section_url)
                if not section_details:
                    print(f"          ERROR: Failed to fetch Section {section_code} in Chapter {chapter_code}, skipping...")
                    continue
                
                # Append section to file immediately
                section_name = section_details.get("Name", "No Title")
                section_text = section_details.get("Text", "No text available")
                
                with open(filename, "a", encoding="utf-8") as f:
                    f.write(f"### Section {section_details.get('Code', section_code)}: {section_name}\n\n")
                    f.write(f"{section_text}\n\n")
        
        print(f"  ✓ Saved: {filename.name}\n")
    
    print(f"\n✓ Download complete! All documents saved to: {output_path.absolute()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download Massachusetts General Laws from the Legislature API"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=OUTPUT_DIR,
        help=f"Output directory for downloaded documents (default: {OUTPUT_DIR})"
    )
    
    args = parser.parse_args()
    download_all_laws(output_dir=args.output)
