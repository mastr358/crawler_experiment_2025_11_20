import os
import time
import json
import hashlib
import argparse
import re
import random
from urllib.parse import urlparse, urljoin
from datetime import datetime

# Try to import dependencies, if missing, warn user
try:
    import requests
    from bs4 import BeautifulSoup, Comment
    import html2text
except ImportError as e:
    print("!" * 60)
    print(f"MISSING DEPENDENCY: {e.name}")
    print("Please run: pip install requests beautifulsoup4 html2text")
    print("!" * 60)
    exit(1)

# --- CONFIGURATION ---
class Config:
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
    ]
    
    CACHE_DIR = "scraper_data/raw_html"
    OUTPUT_DIR = "scraper_data/markdown"
    INDEX_FILE = "scraper_data/index.json"
    
    # Politeness settings
    MIN_DELAY = 0.5
    MAX_DELAY = 1.5

class Utils:
    @staticmethod
    def get_url_hash(url):
        """Generates a safe filename from a URL."""
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    @staticmethod
    def ensure_dirs():
        os.makedirs(Config.CACHE_DIR, exist_ok=True)
        os.makedirs(Config.OUTPUT_DIR, exist_ok=True)

    @staticmethod
    def log(msg, type="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "\033[94m",    # Blue
            "SUCCESS": "\033[92m", # Green
            "WARN": "\033[93m",    # Yellow
            "ERROR": "\033[91m",   # Red
            "RESET": "\033[0m"
        }
        color = colors.get(type, colors["RESET"])
        print(f"{colors['RESET']}[{timestamp}] {color}{type:<7}{colors['RESET']} : {msg}")

    @staticmethod
    def normalize_url(url):
        """Removes fragments and cleans URL."""
        parsed = urlparse(url)
        return parsed.scheme + "://" + parsed.netloc + parsed.path + parsed.params + parsed.query

class CacheManager:
    """
    Manages the 'Database' of downloaded pages.
    Stores metadata in a JSON index and raw HTML in files.
    """
    def __init__(self):
        self.index = {}
        if os.path.exists(Config.INDEX_FILE):
            with open(Config.INDEX_FILE, 'r', encoding='utf-8') as f:
                self.index = json.load(f)

    def is_cached(self, url):
        # Check normalized URL
        url_hash = Utils.get_url_hash(url)
        return url_hash in self.index and os.path.exists(os.path.join(Config.CACHE_DIR, f"{url_hash}.html"))

    def save(self, url, html_content, status_code=200):
        url_hash = Utils.get_url_hash(url)
        filename = f"{url_hash}.html"
        filepath = os.path.join(Config.CACHE_DIR, filename)
        
        # Save Raw HTML
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
            
        # Update Index
        self.index[url_hash] = {
            "url": url,
            "file": filename,
            "timestamp": datetime.now().isoformat(),
            "status": status_code
        }
        self._save_index()
        return filename

    def get_html(self, url):
        url_hash = Utils.get_url_hash(url)
        if url_hash not in self.index:
            return None
        
        filepath = os.path.join(Config.CACHE_DIR, self.index[url_hash]['file'])
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return None

    def get_all_cached_urls(self):
        return [data['url'] for data in self.index.values()]

    def _save_index(self):
        with open(Config.INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=2)

class Fetcher:
    """
    Handles network requests.
    """
    def __init__(self):
        self.session = requests.Session()

    def fetch(self, url):
        headers = {'User-Agent': random.choice(Config.USER_AGENTS)}
        
        # Politeness delay
        time.sleep(random.uniform(Config.MIN_DELAY, Config.MAX_DELAY))
        
        try:
            response = self.session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.text, response.status_code
            return None, response.status_code
        except requests.exceptions.RequestException as e:
            Utils.log(f"Failed to fetch {url}: {e}", "ERROR")
            return None, 0

class Parser:
    """
    Handles the 'Elegant' parsing logic.
    Converts HTML to clean Markdown.
    """
    def __init__(self):
        self.converter = html2text.HTML2Text()
        self.converter.ignore_links = False
        self.converter.ignore_images = False
        self.converter.ignore_tables = False
        self.converter.body_width = 0  # No wrapping
        self.converter.skip_internal_links = True
        
    def clean_soup(self, soup):
        """
        Heuristic-based cleaning to remove non-content elements.
        """
        # 1. Remove standard clutter tags
        for tag in soup(['script', 'style', 'iframe', 'noscript', 'svg', 'form']):
            tag.decompose()

        # 2. Remove structural clutter (Navs, Footers, Sidebars)
        for tag in soup(['header', 'footer', 'nav', 'aside']):
            tag.decompose()

        # 3. Remove by class/id names that are typically clutter
        clutter_terms = ['sidebar', 'menu', 'navigation', 'ad-container', 'popup', 'cookie', 'social-share', 'banner']
        
        # DEFENSIVE FIX: iterate safely
        for tag in soup.find_all(attrs={"class": True}):
            try:
                # Ensure attributes exist
                if not hasattr(tag, 'attrs') or tag.attrs is None:
                    continue
                
                cls_list = tag.get("class")
                if not cls_list:
                    continue
                
                # Handle both list (standard) and string (edge case) class formats
                classes = " ".join(cls_list) if isinstance(cls_list, list) else str(cls_list)
                
                if any(term in classes.lower() for term in clutter_terms):
                    tag.decompose()
            except Exception:
                # If any tag structure is corrupted, skip it rather than crashing
                continue
                
        # 4. Remove invisible content (display: none)
        for tag in soup.find_all(style=re.compile(r'display:\s*none', re.I)):
            tag.decompose()
            
        # 5. Remove Comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        return soup

    def extract_main_content(self, soup):
        """
        Tries to find the 'meat' of the page.
        """
        # Priority 1: <main> tag
        main = soup.find('main')
        if main:
            return main
            
        # Priority 2: <article> tag
        article = soup.find('article')
        if article:
            return article
            
        # Priority 3: Div with id="content" or class="content"
        content_div = soup.find('div', {'id': re.compile('content|main|article', re.I)})
        if content_div:
            return content_div
            
        # Fallback: Return body or whole soup
        return soup.find('body') or soup

    def to_markdown(self, html_content, url):
        if not html_content:
            return ""
            
        soup = BeautifulSoup(html_content, 'html.parser')
        title = soup.title.string if soup.title else "Untitled"
        
        # Clean the DOM
        soup = self.clean_soup(soup)
        
        # Focus on main content
        main_content = self.extract_main_content(soup)
        
        # Convert to markdown
        md = self.converter.handle(str(main_content))
        
        # Add a clean meta-header to the markdown (for file identification)
        meta = f"---\nTitle: {title}\nSource: {url}\nDate: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
        
        return meta + md

class ScraperApp:
    def __init__(self):
        Utils.ensure_dirs()
        self.cache = CacheManager()
        self.fetcher = Fetcher()
        self.parser = Parser()

    def _extract_links(self, html, base_url, pattern_regex=None):
        """
        Extracts all valid links from HTML that match the scope/pattern.
        """
        if not html: return []
        
        soup = BeautifulSoup(html, 'html.parser')
        found_links = set()
        
        base_parsed = urlparse(base_url)
        base_domain = base_parsed.netloc

        for a in soup.find_all('a', href=True):
            href = a['href']
            full_url = urljoin(base_url, href)
            normalized = Utils.normalize_url(full_url)
            
            parsed_new = urlparse(normalized)
            
            # Basic Security: Only http(s)
            if parsed_new.scheme not in ['http', 'https']:
                continue

            # Filter Logic:
            # 1. If pattern provided, match regex
            if pattern_regex:
                if not pattern_regex.search(normalized):
                    continue
            # 2. Default: Restrict to same domain
            else:
                if parsed_new.netloc != base_domain:
                    continue
            
            found_links.add(normalized)
            
        return list(found_links)

    def run_fetch_phase(self, start_urls, force=False, crawl=False, pattern=None):
        """
        Phase 1: Download URLs to cache. Supports recursive crawling.
        """
        # Setup Queue
        queue = [Utils.normalize_url(u) for u in start_urls]
        visited = set() # Tracks URLs processed in this session
        
        # Load existing cache index into visited to avoid re-crawling old stuff if not forced
        # (Optional optimization: if you want to resume a huge crawl)
        # For now, we just track session visited to avoid infinite loops in queue.
        
        # Compile regex if provided
        regex_obj = None
        if pattern:
            try:
                regex_obj = re.compile(pattern)
                Utils.log(f"Crawler constrained by pattern: {pattern}", "INFO")
            except re.error:
                Utils.log(f"Invalid regex pattern: {pattern}", "ERROR")
                return

        print(f"\n=== PHASE 1: FETCHING (Crawl Mode: {crawl}) ===")
        
        count = 0
        while queue:
            url = queue.pop(0)
            
            if url in visited:
                continue
            visited.add(url)
            count += 1
            
            progress = f"[{count}] (Q:{len(queue)})"
            
            # Check Cache First
            html = None
            from_cache = False
            
            if not force and self.cache.is_cached(url):
                Utils.log(f"{progress} Cached: {url}", "INFO")
                html = self.cache.get_html(url)
                from_cache = True
            else:
                Utils.log(f"{progress} Fetching: {url}", "INFO")
                html, status = self.fetcher.fetch(url)
                if html:
                    self.cache.save(url, html, status)
                else:
                    Utils.log(f"Failed: {url}", "ERROR")

            # If Crawling is enabled, extract links and add to queue
            if crawl and html:
                new_links = self._extract_links(html, url, regex_obj)
                added_count = 0
                for link in new_links:
                    if link not in visited and link not in queue:
                        # Also check if it's already cached to avoid queue bloat? 
                        # No, we need to process cached pages to find THEIR links (BFS)
                        queue.append(link)
                        added_count += 1
                
                # If we added links, logging helps visualize expansion
                if added_count > 0:
                    pass # verbose: print(f"   Found {added_count} new links")

    def run_parse_phase(self, start_urls=None, merge=False):
        """
        Phase 2: Process cached files into Markdown.
        """
        # If start_urls given, only parse those. 
        # BUT, if we just crawled, we might want to parse EVERYTHING in the cache that matches our domain?
        # Simplify: If start_urls is None, parse ALL cached files.
        
        target_urls = []
        if start_urls:
            # If user provided specific URLs, use them
            target_urls = [Utils.normalize_url(u) for u in start_urls]
        else:
            # Otherwise parse everything in the index
            target_urls = self.cache.get_all_cached_urls()
        
        print(f"\n=== PHASE 2: PARSING ({len(target_urls)} URLs) ===")
        
        generated_files = []
        
        for url in target_urls:
            html = self.cache.get_html(url)
            if not html:
                # It might be in the cache but under a slightly different string (slash issues)
                # But we normalized inputs, so should be okay.
                continue
                
            md_content = self.parser.to_markdown(html, url)
            
            # Generate filename
            parsed = urlparse(url)
            path_clean = re.sub(r'[^a-zA-Z0-9]', '_', parsed.path)
            if not path_clean or path_clean == "_":
                path_clean = "index"
            
            # Limit filename length
            if len(path_clean) > 50:
                path_clean = path_clean[:50]
                
            filename = f"{parsed.netloc}_{path_clean}.md"
            filepath = os.path.join(Config.OUTPUT_DIR, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(md_content)
            
            generated_files.append(filepath)
            Utils.log(f"Converted: {filename}", "SUCCESS")

        if merge and generated_files:
            self.merge_markdowns(generated_files)

    def merge_markdowns(self, file_paths):
        """
        Merges all markdown files into one.
        """
        print(f"\n=== PHASE 3: MERGING ===")
        merged_path = os.path.join(Config.OUTPUT_DIR, "full_export.md")
        
        with open(merged_path, 'w', encoding='utf-8') as outfile:
            outfile.write(f"# Web Scrape Export\nGenerated: {datetime.now()}\n\n")
            
            for fp in file_paths:
                with open(fp, 'r', encoding='utf-8') as infile:
                    content = infile.read()
                    outfile.write("\n\n" + ("="*40) + "\n\n")
                    outfile.write(content)
                    
        Utils.log(f"Merged {len(file_paths)} files into: {merged_path}", "SUCCESS")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Elegant Web Scraper with Crawling")
    parser.add_argument("urls", nargs="*", help="Start URLs")
    parser.add_argument("--file", "-f", help="File containing list of URLs")
    parser.add_argument("--crawl", "-c", action="store_true", help="Enable recursive crawling")
    parser.add_argument("--pattern", "-p", help="Regex pattern for crawling (e.g. 'example.com/blog/.*')")
    parser.add_argument("--refresh", "-r", action="store_true", help="Force re-download")
    parser.add_argument("--merge", "-m", action="store_true", help="Merge output to single file")
    parser.add_argument("--parse-only", action="store_true", help="Skip fetch, only parse cache")
    
    args = parser.parse_args()
    
    # Collect URLs
    target_urls = []
    if args.urls:
        target_urls.extend(args.urls)
    if args.file and os.path.exists(args.file):
        with open(args.file, 'r') as f:
            target_urls.extend([line.strip() for line in f if line.strip()])
            
    if not target_urls and not args.parse_only:
        print("Error: No URLs provided.")
        exit(1)

    app = ScraperApp()
    
    # 1. Fetch / Crawl Phase
    if not args.parse_only:
        app.run_fetch_phase(target_urls, force=args.refresh, crawl=args.crawl, pattern=args.pattern)
    
    # 2. Parse Phase
    # If we crawled, we likely want to parse everything in the cache, not just the start URL.
    # If parse_only is specified with specific URLs, we restrict to those.
    parse_targets = target_urls if (args.parse_only and target_urls) else None
    
    app.run_parse_phase(parse_targets, merge=args.merge)

    print("\nDone!")