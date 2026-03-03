"""
Image Scraper Engine
====================
Scrapes dashboard interior images from multiple sources:
  1. Google Images (via SerpAPI or direct scraping)
  2. Bing Images
  3. DuckDuckGo Images (via duckduckgo_search library)

Implements rate limiting, retry logic, and polite scraping practices.
"""

import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

logger = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# Rate limiting (seconds between requests)
MIN_DELAY = 2.0
MAX_DELAY = 5.0
RETRY_DELAYS = [5, 15, 30]  # Escalating retry delays


@dataclass
class ImageResult:
    """Represents a found image with metadata."""
    url: str
    source_page: str = ""
    title: str = ""
    width: int = 0
    height: int = 0
    search_engine: str = ""
    search_query: str = ""
    file_size: int = 0


@dataclass
class ScraperConfig:
    """Configuration for the scraper."""
    images_per_vehicle: int = 5
    min_width: int = 800
    min_height: int = 600
    max_file_size_mb: int = 15
    request_timeout: int = 30
    max_retries: int = 3
    serpapi_key: str = ""  # Optional SerpAPI key for Google Images
    prefer_landscape: bool = True
    output_dir: str = "dashboards"


class RateLimiter:
    """Simple rate limiter to be polite to search engines."""

    def __init__(self, min_delay: float = MIN_DELAY, max_delay: float = MAX_DELAY):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request_time = 0.0
        self._domain_times: dict = {}

    def wait(self, domain: str = "default"):
        """Wait an appropriate amount of time before the next request."""
        now = time.time()
        last = self._domain_times.get(domain, 0.0)
        elapsed = now - last
        delay = random.uniform(self.min_delay, self.max_delay)

        if elapsed < delay:
            sleep_time = delay - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.1f}s for {domain}")
            time.sleep(sleep_time)

        self._domain_times[domain] = time.time()


class ImageScraper:
    """Multi-source image scraper for vehicle dashboard photos."""

    def __init__(self, config: Optional[ScraperConfig] = None):
        self.config = config or ScraperConfig()
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.rate_limiter = RateLimiter()
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        )

    def _make_request(self, url: str, stream: bool = False, domain: str = "default") -> Optional[requests.Response]:
        """Make an HTTP request with retry logic and rate limiting."""
        self.rate_limiter.wait(domain)

        for attempt in range(self.config.max_retries):
            try:
                resp = self.session.get(
                    url,
                    timeout=self.config.request_timeout,
                    stream=stream,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    return resp
                elif resp.status_code == 429:
                    delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
                    logger.warning(f"Rate limited (429). Waiting {delay}s before retry...")
                    time.sleep(delay)
                elif resp.status_code in (403, 451):
                    logger.warning(f"Blocked ({resp.status_code}) for {url}")
                    return None
                else:
                    logger.warning(f"HTTP {resp.status_code} for {url}")

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout for {url} (attempt {attempt + 1})")
            except requests.exceptions.ConnectionError:
                logger.warning(f"Connection error for {url} (attempt {attempt + 1})")
                time.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
            except Exception as e:
                logger.error(f"Unexpected error for {url}: {e}")
                return None

        return None

    # ─── Source 1: DuckDuckGo Images ────────────────────────────────────
    def search_duckduckgo(self, query: str, max_results: int = 20) -> list:
        """Search DuckDuckGo Images using the duckduckgo_search library."""
        results = []
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                ddg_results = list(ddgs.images(
                    keywords=query,
                    region="wt-wt",
                    safesearch="moderate",
                    size="Large",
                    type_image="photo",
                    layout="Wide",
                    max_results=max_results,
                ))
                for item in ddg_results:
                    results.append(ImageResult(
                        url=item.get("image", ""),
                        source_page=item.get("url", ""),
                        title=item.get("title", ""),
                        width=item.get("width", 0),
                        height=item.get("height", 0),
                        search_engine="duckduckgo",
                        search_query=query,
                    ))
        except ImportError:
            logger.warning("duckduckgo_search not installed. Skipping DDG source.")
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")

        return results

    # ─── Source 2: Bing Images ──────────────────────────────────────────
    def search_bing(self, query: str, max_results: int = 20) -> list:
        """Search Bing Images by scraping the results page."""
        results = []
        encoded_query = quote_plus(query)
        url = (
            f"https://www.bing.com/images/search?"
            f"q={encoded_query}&qft=+filterui:imagesize-large"
            f"+filterui:photo-photo+filterui:aspect-wide&form=IRFLTR"
        )

        resp = self._make_request(url, domain="bing.com")
        if not resp:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")

        # Bing stores image data in 'm' attribute of anchor tags
        for item in soup.select("a.iusc"):
            try:
                m_data = item.get("m")
                if m_data:
                    data = json.loads(m_data)
                    img_url = data.get("murl", "")
                    if img_url and self._is_valid_image_url(img_url):
                        results.append(ImageResult(
                            url=img_url,
                            source_page=data.get("purl", ""),
                            title=data.get("t", ""),
                            width=data.get("mw", 0),
                            height=data.get("mh", 0),
                            search_engine="bing",
                            search_query=query,
                        ))
            except (json.JSONDecodeError, AttributeError):
                continue

            if len(results) >= max_results:
                break

        logger.info(f"Bing: found {len(results)} results for '{query}'")
        return results

    # ─── Source 3: Google Images via SerpAPI ─────────────────────────────
    def search_google_serpapi(self, query: str, max_results: int = 20) -> list:
        """Search Google Images using SerpAPI (requires API key)."""
        if not self.config.serpapi_key:
            return []

        results = []
        params = {
            "engine": "google_images",
            "q": query,
            "api_key": self.config.serpapi_key,
            "num": max_results,
            "imgsz": "l",    # Large images
            "imgtype": "photo",
        }

        try:
            resp = self.session.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=self.config.request_timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("images_results", []):
                    results.append(ImageResult(
                        url=item.get("original", ""),
                        source_page=item.get("link", ""),
                        title=item.get("title", ""),
                        width=item.get("original_width", 0),
                        height=item.get("original_height", 0),
                        search_engine="google_serpapi",
                        search_query=query,
                    ))
        except Exception as e:
            logger.error(f"SerpAPI search failed: {e}")

        return results

    # ─── Source 4: Direct Google Images scraping ────────────────────────
    def search_google_direct(self, query: str, max_results: int = 20) -> list:
        """
        Scrape Google Images directly (fallback if no SerpAPI key).
        Note: This may be less reliable due to Google's anti-scraping measures.
        """
        results = []
        encoded_query = quote_plus(query)
        url = f"https://www.google.com/search?q={encoded_query}&tbm=isch&tbs=isz:l,itp:photo"

        resp = self._make_request(url, domain="google.com")
        if not resp:
            return results

        # Google embeds image URLs in script tags
        # Look for patterns like ["https://example.com/image.jpg",width,height]
        img_pattern = re.compile(
            r'\["(https?://[^"]+\.(?:jpg|jpeg|png|webp)(?:\?[^"]*)?)"'
            r',\s*(\d+)\s*,\s*(\d+)\s*\]',
            re.IGNORECASE
        )

        for match in img_pattern.finditer(resp.text):
            img_url = match.group(1).replace("\\u003d", "=").replace("\\u0026", "&")
            width = int(match.group(2))
            height = int(match.group(3))

            if self._is_valid_image_url(img_url) and width >= 200:
                results.append(ImageResult(
                    url=img_url,
                    source_page="",
                    title="",
                    width=width,
                    height=height,
                    search_engine="google_direct",
                    search_query=query,
                ))

            if len(results) >= max_results:
                break

        logger.info(f"Google Direct: found {len(results)} results for '{query}'")
        return results

    # ─── Combined search ────────────────────────────────────────────────
    def search_all_sources(self, query: str, max_per_source: int = 15) -> list:
        """
        Search all available sources and combine results.
        Deduplicates by image URL.
        """
        all_results = []
        seen_urls = set()

        # Try sources in order of reliability
        sources = [
            ("DuckDuckGo", self.search_duckduckgo),
            ("Bing", self.search_bing),
        ]

        # Add Google sources
        if self.config.serpapi_key:
            sources.insert(0, ("Google SerpAPI", self.search_google_serpapi))
        else:
            sources.append(("Google Direct", self.search_google_direct))

        for source_name, search_fn in sources:
            try:
                logger.info(f"Searching {source_name} for: '{query}'")
                results = search_fn(query, max_results=max_per_source)

                for r in results:
                    if r.url and r.url not in seen_urls:
                        seen_urls.add(r.url)
                        all_results.append(r)

                if len(all_results) >= max_per_source * 2:
                    break  # We have enough candidates

            except Exception as e:
                logger.error(f"{source_name} failed: {e}")
                continue

        logger.info(f"Total unique image URLs found: {len(all_results)}")
        return all_results

    # ─── Image downloading & validation ─────────────────────────────────
    def download_and_validate(self, image_result: ImageResult) -> Optional[bytes]:
        """
        Download an image and validate it meets quality standards.
        Returns the image bytes if valid, None otherwise.
        """
        url = image_result.url
        domain = urlparse(url).netloc

        try:
            resp = self._make_request(url, stream=True, domain=domain)
            if not resp:
                return None

            # Check content type
            content_type = resp.headers.get("Content-Type", "")
            if not any(ct in content_type.lower() for ct in ["image/", "octet-stream"]):
                logger.debug(f"Not an image content-type: {content_type}")
                return None

            # Check content length
            content_length = resp.headers.get("Content-Length")
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > self.config.max_file_size_mb:
                    logger.debug(f"Image too large: {size_mb:.1f}MB")
                    return None

            # Download image data
            image_data = resp.content

            # Validate with PIL
            try:
                img = Image.open(BytesIO(image_data))
                width, height = img.size

                # Check minimum dimensions
                if width < self.config.min_width or height < self.config.min_height:
                    logger.debug(f"Image too small: {width}x{height}")
                    return None

                # Update the result with actual dimensions
                image_result.width = width
                image_result.height = height
                image_result.file_size = len(image_data)

                # Prefer landscape orientation
                if self.config.prefer_landscape and height > width * 1.3:
                    logger.debug(f"Portrait image skipped: {width}x{height}")
                    return None

                # Convert to JPEG if needed (standardize format)
                if img.format not in ('JPEG', 'PNG'):
                    buffer = BytesIO()
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    img.save(buffer, format='JPEG', quality=90)
                    image_data = buffer.getvalue()

                return image_data

            except Exception as e:
                logger.debug(f"Invalid image data from {url}: {e}")
                return None

        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            return None

    def _is_valid_image_url(self, url: str) -> bool:
        """Check if a URL looks like a valid image URL."""
        if not url or len(url) > 2000:
            return False

        # Skip known bad patterns
        bad_patterns = [
            "gstatic.com/images",
            "google.com/images",
            "bing.com/th",
            "favicon",
            "logo",
            "icon",
            "pixel",
            "spacer",
            "blank",
            "1x1",
            "tracker",
            "analytics",
            "advertisement",
        ]
        url_lower = url.lower()
        if any(p in url_lower for p in bad_patterns):
            return False

        # Must have an image-like extension or be from a known image host
        image_exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
        parsed = urlparse(url)
        path_lower = parsed.path.lower()

        has_image_ext = any(path_lower.endswith(ext) for ext in image_exts)
        is_image_host = any(h in parsed.netloc for h in [
            'imgur', 'cloudinary', 'wp.com', 'amazonaws',
            'googleusercontent', 'ggpht', 'cdninstagram',
        ])

        return has_image_ext or is_image_host or '/image' in path_lower

    def generate_filename(self, image_result: ImageResult, index: int) -> str:
        """Generate a descriptive filename for a downloaded image."""
        # Create a short hash of the URL for uniqueness
        url_hash = hashlib.md5(image_result.url.encode()).hexdigest()[:8]

        # Determine extension from URL
        parsed = urlparse(image_result.url)
        path = parsed.path.lower()
        if '.png' in path:
            ext = '.png'
        elif '.webp' in path:
            ext = '.jpg'  # We convert webp to jpg
        else:
            ext = '.jpg'

        return f"dashboard_{index + 1:02d}_{url_hash}{ext}"
