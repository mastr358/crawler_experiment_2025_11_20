Elegant Web Scraper

An intelligent, two-phase web scraper designed to convert websites into clean, readable Markdown. It separates the downloading (fetching) process from the processing (parsing) process, allowing you to tweak your parsing logic instantly without re-downloading thousands of pages.

Features

Two-Phase Architecture:

Fetch Phase: Downloads raw HTML to a local cache (scraper_data/raw_html). Skips already downloaded files to save bandwidth.

Parse Phase: Reads from the local cache and converts content to Markdown (scraper_data/markdown). Runs instantly.

Smart Cleaning: Aggressively strips navbars, footers, sidebars, ads, and hidden elements (display: none) to capture only the actual article content.

Recursive Crawling: Can crawl entire domains, subdomains, or specific path patterns.

One-Header-Logic: When merging multiple pages into a single document, it ensures site headers/footers don't clutter the text between sections.

Politeness: Includes random delays and User-Agent rotation to avoid getting blocked.

Installation

Clone this repository or save the script as elegant_scraper.py.

Install the required Python dependencies:

pip install requests beautifulsoup4 html2text


Usage

1. Basic Single Page Scrape

Download a single page and convert it to Markdown.

python elegant_scraper.py [https://example.com/article](https://example.com/article)


2. Crawl an Entire Domain

Crawl example.com and all internal links found, then merge the results into one file.

python elegant_scraper.py [https://example.com](https://example.com) --crawl --merge


3. Crawl Specific Paths (Regex Pattern)

Only scrape pages that match a specific pattern (e.g., only blog posts).

python elegant_scraper.py [https://example.com/blog/](https://example.com/blog/) --crawl --pattern "[example.com/blog/](https://example.com/blog/).*" --merge


4. Batch Scrape from File

If you have a list of specific URLs you want to scrape:

Create a file links.txt with one URL per line.

Run:

python elegant_scraper.py --file links.txt --merge


5. The "Dev Loop": Update Parser Without Re-downloading

This is the scraper's most powerful feature. If you don't like how the Markdown looks (e.g., you want to remove specific CSS classes or change formatting), you don't need to re-crawl the internet.

Fetch data once: python elegant_scraper.py https://example.com --crawl

Edit the code: Modify the Parser class in elegant_scraper.py.

Re-run parsing only:

python elegant_scraper.py --parse-only --merge


Configuration

You can modify the Config class at the top of elegant_scraper.py to change:

Delays: MIN_DELAY and MAX_DELAY (default 0.5s - 1.5s).

Directories: Change where raw HTML and Markdown files are saved.

User Agents: Add or remove user agent strings.

Output Structure

The script creates a scraper_data/ folder:

scraper_data/
├── raw_html/       # Cache of raw downloaded files (do not edit these)
├── markdown/       # The cleaned Markdown output files
└── index.json      # Database mapping URLs to filenames


License

MIT