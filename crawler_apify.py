import os
import time
import json
import hashlib
import re
import random
from urllib.parse import urlparse, urljoin
from datetime import datetime
import asyncio

# Apify SDK
from apify import Actor

# Third-party dependencies
import requests
from bs4 import BeautifulSoup, Comment
import html2text

class Utils:
    @staticmethod
    def get_url_hash(url):
        """Generates a safe filename from a URL."""
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    @staticmethod
    def normalize_url(url):
        """Removes fragments and cleans URL."""
        parsed = urlparse(url)
        return parsed.scheme + "://" + parsed.netloc + parsed.path + parsed.params + parsed.query

class CacheManager:
    """
    Manages the 'Database' of downloaded pages using Apify Key-Value Store.
    """
    def __init__(self):
        self.store = None # Will be initialized async

    async def initialize(self):
        self.store = await Actor.open_key_value_store()

    async def is_cached(self, url):
        if not self.store: await self.initialize()
        url_hash = Utils.get_url_hash(url)
        # Check if record exists in KVS
        record = await self.store.get_value(url_hash)
        return record is not None

    async def save(self, url, html_content, status_code=200):
        if not self.store: await self.initialize()
        url_hash = Utils.get_url_hash(url)
        
        data = {
            "url": url,
            "html": html_content,
            "timestamp": datetime.now().isoformat(),
            "status": status_code
        }
        
        # Save to KVS
        await self.store.set_value(url_hash, data)
        return url_hash

    async def get_html(self, url):
        if not self.store: await self.initialize()
        url_hash = Utils.get_url_hash(url)
        data = await self.store.get_value(url_hash)
        if data and isinstance(data, dict):
            return data.get('html')
        return None

    async def get_all_cached_urls(self):
        if not self.store: await self.initialize()
        # In KVS, iterating keys is different. 
        # For simplicity in this port, we might skip "re-parsing all cache" feature 
        # or implement it by listing keys if needed. 
        # But for a standard Actor run, we usually process what we fetch.
        # We'll implement a basic list if possible, but KVS isn't designed for listing all keys efficiently in large stores.
        # We will skip this for now and focus on processing the current crawl.
        return []

class Fetcher:
    """
    Handles network requests.
    """
    def __init__(self):
        self.session = requests.Session()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
        ]

    def fetch(self, url):
        headers = {'User-Agent': random.choice(self.user_agents)}
        
        # Politeness delay (blocking, but acceptable for simple port)
        time.sleep(random.uniform(0.5, 1.5))
        
        try:
            response = self.session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.text, response.status_code
            return None, response.status_code
        except requests.exceptions.RequestException as e:
            Actor.log.error(f"Failed to fetch {url}: {e}")
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
        
        for tag in soup.find_all(attrs={"class": True}):
            try:
                if not hasattr(tag, 'attrs') or tag.attrs is None:
                    continue
                
                cls_list = tag.get("class")
                if not cls_list:
                    continue
                
                classes = " ".join(cls_list) if isinstance(cls_list, list) else str(cls_list)
                
                if any(term in classes.lower() for term in clutter_terms):
                    tag.decompose()
            except Exception:
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
        
        # Add a clean meta-header to the markdown
        meta = f"---\nTitle: {title}\nSource: {url}\nDate: {datetime.now().strftime('%Y-%m-%d')}\n---\n\n"
        
        return meta + md, title

class ScraperApp:
    def __init__(self, config):
        self.config = config
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

    async def run(self):
        await self.cache.initialize()
        
        # Support both camelCase (Apify standard) and snake_case
        start_urls = self.config.get('startUrls') or self.config.get('start_urls') or []
        
        if not start_urls:
            Actor.log.warning("No startUrls provided in input! Actor will exit without crawling.")
            Actor.log.info(f"Input keys received: {list(self.config.keys())}")
            return

        # Handle Apify startUrls format (list of objects or strings)
        urls_to_process = []
        for u in start_urls:
            if isinstance(u, dict):
                url = u.get('url')
                if url: urls_to_process.append(url)
            elif isinstance(u, str):
                urls_to_process.append(u)
        
        if not urls_to_process:
             Actor.log.warning("startUrls provided but no valid URLs found.")
             return

        crawl = self.config.get('crawl', False)
        pattern = self.config.get('pattern', None)
        force = self.config.get('refresh', False)
        
        # Compile regex if provided
        regex_obj = None
        if pattern:
            try:
                regex_obj = re.compile(pattern)
                Actor.log.info(f"Crawler constrained by pattern: {pattern}")
            except re.error:
                Actor.log.error(f"Invalid regex pattern: {pattern}")
                return

        queue = [Utils.normalize_url(u) for u in urls_to_process]
        visited = set()
        
        count = 0
        while queue:
            url = queue.pop(0)
            
            if url in visited:
                continue
            visited.add(url)
            count += 1
            
            Actor.log.info(f"Processing [{count}] (Q:{len(queue)}): {url}")
            
            html = None
            
            # Check Cache
            if not force and await self.cache.is_cached(url):
                Actor.log.info(f"Cached: {url}")
                html = await self.cache.get_html(url)
            else:
                Actor.log.info(f"Fetching: {url}")
                # Run blocking fetch in executor to avoid blocking async loop too much
                loop = asyncio.get_event_loop()
                html, status = await loop.run_in_executor(None, self.fetcher.fetch, url)
                
                if html:
                    await self.cache.save(url, html, status)
                else:
                    Actor.log.error(f"Failed to fetch: {url}")

            # Parse and Push Data
            if html:
                markdown, title = self.parser.to_markdown(html, url)
                
                # Push to Apify Dataset
                await Actor.push_data({
                    "url": url,
                    "title": title,
                    "markdown": markdown,
                    "crawledAt": datetime.now().isoformat()
                })
                
                # Crawl Logic
                if crawl:
                    new_links = self._extract_links(html, url, regex_obj)
                    for link in new_links:
                        if link not in visited and link not in queue:
                            queue.append(link)

async def main():
    async with Actor:
        Actor.log.info('Actor starting...')
        
        # Get input
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f'Received input: {json.dumps(actor_input, indent=2)}')
        
        # Validate startUrls
        start_urls = actor_input.get('startUrls', [])
        if not start_urls:
            Actor.log.warning('No startUrls provided in input!')
            Actor.log.info('Example input format: {"startUrls": [{"url": "https://example.com"}]}')
        
        # Run scraper
        app = ScraperApp(actor_input)
        await app.run()
        
        Actor.log.info('Actor finished.')

if __name__ == "__main__":
    asyncio.run(main())
