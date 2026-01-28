#!/usr/bin/env python3
"""
Filter Law Case JSON Files by Content Length

Reads law case JSON files from an input folder (recursively, including subfolders),
and copies each file to an output folder only when the "content" string length
is greater than a minimum length threshold.
"""

import argparse
import json
import shutil
from pathlib import Path
from typing import Optional, Tuple


def get_content_length(json_path: Path) -> Optional[int]:
    """
    Load a JSON file and return the length of the "content" field if present.
    
    Args:
        json_path: Path to the JSON file
        
    Returns:
        Length of content string, or None if no content field or invalid JSON
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        content = data.get('content')
        if content is None:
            return None
        
        if isinstance(content, str):
            return len(content)
        
        # If content is not a string (e.g. list), treat as empty
        return 0
    except (json.JSONDecodeError, OSError):
        return None


def filter_and_copy(
    input_dir: Path,
    output_dir: Path,
    min_length: int = 400,
) -> Tuple[int, int]:
    """
    Walk input directory recursively, and copy JSON files to output directory
    when content length exceeds min_length.
    
    Args:
        input_dir: Input directory (searched recursively)
        output_dir: Output directory (relative structure preserved)
        min_length: Minimum content length to copy (default 400)
        
    Returns:
        Tuple of (files_copied, files_skipped)
    """
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    
    files_copied = 0
    files_skipped = 0
    
    # Find all JSON files recursively
    for json_path in input_dir.rglob('*.json'):
        if not json_path.is_file():
            continue
        
        content_len = get_content_length(json_path)
        
        if content_len is None:
            files_skipped += 1
            print(f"  Skip (no content or invalid): {json_path.relative_to(input_dir)}")
            continue
        
        if content_len <= min_length:
            files_skipped += 1
            print(f"  Skip (content length {content_len} <= {min_length}): {json_path.relative_to(input_dir)}")
            continue
        
        # Preserve relative path under output dir
        rel_path = json_path.relative_to(input_dir)
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(json_path, out_path)
        files_copied += 1
        print(f"  Copy (content length {content_len}): {rel_path} -> {out_path}")
    
    return files_copied, files_skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Filter law case JSON files by content length and copy to output folder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Copy only cases with content length > 400 (default)
  python filter_cases_by_content.py -i ma_cases -o filtered_cases

  # Use minimum content length of 1000
  python filter_cases_by_content.py -i ma_cases -o filtered_cases -m 1000

  # Absolute paths
  python filter_cases_by_content.py -i /path/to/ma_cases -o /path/to/filtered
        """,
    )
    
    parser.add_argument(
        "-i", "--input",
        type=Path,
        required=True,
        help="Input folder containing law case JSON files (searched recursively including subfolders)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        required=True,
        help="Output folder where filtered files will be copied",
    )
    parser.add_argument(
        "-m", "--min-length",
        type=int,
        default=400,
        help="Minimum content string length to copy (default: 400)",
    )
    
    args = parser.parse_args()
    
    input_dir = args.input.resolve()
    output_dir = args.output.resolve()
    
    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        return
    
    if not input_dir.is_dir():
        print(f"Error: Input path is not a directory: {input_dir}")
        return
    
    print(f"Input folder:  {input_dir}")
    print(f"Output folder: {output_dir}")
    print(f"Min content length: {args.min_length}")
    print()
    
    files_copied, files_skipped = filter_and_copy(
        input_dir,
        output_dir,
        min_length=args.min_length,
    )
    
    print()
    print(f"Done. Copied {files_copied} file(s), skipped {files_skipped} file(s).")


if __name__ == "__main__":
    main()
