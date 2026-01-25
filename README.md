# Massachusetts General Laws Downloader

This Python script downloads all Massachusetts General Laws from the [Massachusetts Legislature API](https://malegislature.gov/api/swagger/index.html?url=/api/swagger/v1/swagger.json#/).

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
