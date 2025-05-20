#!/usr/bin/env python3
"""
Advanced example: Web scraper with sophisticated middleware patterns.

This example demonstrates how to build a production-grade web scraper
using mware's middleware patterns for rate limiting, caching, retries,
circuit breaking, and monitoring.
"""

import asyncio
import aiohttp
import time
import hashlib
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
import random

from mware import middleware, Context


# Data Classes
@dataclass
class ScraperConfig:
    """Configuration for the web scraper."""
    max_retries: int = 3
    retry_delay: float = 1.0
    cache_ttl: int = 3600  # 1 hour
    rate_limit: int = 10  # requests per minute
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60


@dataclass
class ScrapeResult:
    """Result of a scraping operation."""
    url: str
    content: str
    status_code: int
    headers: Dict[str, str]
    scraped_at: datetime
    cached: bool = False


# Caching Middleware
class CacheStore:
    """Simple in-memory cache with TTL support."""
    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self.store: Dict[str, tuple] = {}
    
    def get(self, key: str) -> Optional[Any]:
        if key in self.store:
            value, timestamp = self.store[key]
            if time.time() - timestamp < self.ttl:
                return value
            del self.store[key]
        return None
    
    def set(self, key: str, value: Any):
        self.store[key] = (value, time.time())
    
    def clear_expired(self):
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self.store.items()
            if current_time - timestamp >= self.ttl
        ]
        for key in expired_keys:
            del self.store[key]


cache = CacheStore(ttl=3600)


@middleware
async def cache_middleware(ctx: Context, next) -> Any:
    """Cache scraping results to avoid duplicate requests."""
    cache_key = hashlib.md5(f"{ctx.url}:{ctx.get('params', {})}".encode()).hexdigest()
    
    # Check cache
    cached_result = cache.get(cache_key)
    if cached_result:
        print(f"Cache hit for {ctx.url}")
        cached_result.cached = True
        return cached_result
    
    # Execute request
    print(f"Cache miss for {ctx.url}")
    result = await next(ctx)
    
    # Cache successful results
    if isinstance(result, ScrapeResult) and result.status_code == 200:
        cache.set(cache_key, result)
    
    return result


# Rate Limiting Middleware
class RateLimiter:
    """Token bucket rate limiter."""
    def __init__(self, rate: int, per: int = 60):
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last_check = time.time()
    
    async def acquire(self):
        current = time.time()
        time_passed = current - self.last_check
        self.last_check = current
        
        # Replenish tokens
        self.allowance += time_passed * (self.rate / self.per)
        if self.allowance > self.rate:
            self.allowance = self.rate
        
        if self.allowance < 1.0:
            sleep_time = (1.0 - self.allowance) * (self.per / self.rate)
            print(f"Rate limit reached, sleeping for {sleep_time:.2f}s")
            await asyncio.sleep(sleep_time)
            self.allowance = 0.0
        else:
            self.allowance -= 1.0


@middleware
async def rate_limit_middleware(ctx: Context, next) -> Any:
    """Limit the rate of requests."""
    rate_limiter = ctx.get('rate_limiter') or RateLimiter(10, 60)
    await rate_limiter.acquire()
    return await next(ctx)


# Retry Middleware
@middleware
async def retry_middleware(ctx: Context, next) -> Any:
    """Retry failed requests with exponential backoff."""
    max_retries = ctx.get('max_retries', 3)
    retry_delay = ctx.get('retry_delay', 1.0)
    
    last_exception = None
    for attempt in range(max_retries + 1):
        try:
            result = await next(ctx)
            if isinstance(result, ScrapeResult) and result.status_code >= 500:
                # Retry on server errors
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"Server error {result.status_code}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
                    continue
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_exception = e
            if attempt < max_retries:
                delay = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"Request failed: {e}, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
            else:
                print(f"Max retries reached for {ctx.url}")
                raise
    
    if last_exception:
        raise last_exception


# Circuit Breaker Middleware
class CircuitBreaker:
    """Circuit breaker to prevent cascading failures."""
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    def record_success(self):
        self.failures = 0
        self.state = "closed"
    
    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.failure_threshold:
            self.state = "open"
            print(f"Circuit breaker opened after {self.failures} failures")
    
    def can_proceed(self) -> bool:
        if self.state == "closed":
            return True
        
        if self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half-open"
                print("Circuit breaker entering half-open state")
                return True
            return False
        
        return True  # half-open


@middleware
async def circuit_breaker_middleware(ctx: Context, next) -> Any:
    """Prevent cascading failures with circuit breaker pattern."""
    breaker = ctx.get('circuit_breaker') or CircuitBreaker()
    
    if not breaker.can_proceed():
        raise Exception("Circuit breaker is open")
    
    try:
        result = await next(ctx)
        breaker.record_success()
        return result
    except Exception as e:
        breaker.record_failure()
        raise


# Monitoring Middleware
class ScrapeMetrics:
    """Collect metrics about scraping operations."""
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.cache_hits = 0
        self.total_time = 0.0
        self.status_codes = defaultdict(int)
    
    def record_request(self, result: ScrapeResult, duration: float):
        self.total_requests += 1
        self.total_time += duration
        
        if result.cached:
            self.cache_hits += 1
        
        if result.status_code == 200:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        
        self.status_codes[result.status_code] += 1
    
    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "cache_hit_rate": self.cache_hits / self.total_requests if self.total_requests > 0 else 0,
            "avg_response_time": self.total_time / self.total_requests if self.total_requests > 0 else 0,
            "status_codes": dict(self.status_codes)
        }


@middleware
async def monitoring_middleware(ctx: Context, next) -> Any:
    """Monitor scraping operations and collect metrics."""
    metrics = ctx.get('metrics') or ScrapeMetrics()
    start_time = time.time()
    
    try:
        result = await next(ctx)
        duration = time.time() - start_time
        
        if isinstance(result, ScrapeResult):
            metrics.record_request(result, duration)
            print(f"Scraped {ctx.url} in {duration:.3f}s (status: {result.status_code})")
        
        return result
    except Exception as e:
        duration = time.time() - start_time
        print(f"Failed to scrape {ctx.url} after {duration:.3f}s: {e}")
        raise


# Header Management Middleware
@middleware
async def headers_middleware(ctx: Context, next) -> Any:
    """Add common headers to requests."""
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Mware Scraper) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    ctx.headers = {**default_headers, **ctx.get('headers', {})}
    return await next(ctx)


# The actual scraper function
@monitoring_middleware
@circuit_breaker_middleware
@retry_middleware
@rate_limit_middleware
@cache_middleware
@headers_middleware
async def scrape_url(ctx: Context) -> ScrapeResult:
    """Scrape a URL with all middleware protections."""
    url = ctx.url
    headers = ctx.headers
    timeout = ctx.get('timeout', 30)
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=timeout) as response:
                content = await response.text()
                return ScrapeResult(
                    url=url,
                    content=content,
                    status_code=response.status,
                    headers=dict(response.headers),
                    scraped_at=datetime.now(),
                    cached=False
                )
        except aiohttp.ClientError as e:
            # Return error result
            return ScrapeResult(
                url=url,
                content=str(e),
                status_code=0,
                headers={},
                scraped_at=datetime.now(),
                cached=False
            )


# Batch scraping with concurrent execution
async def scrape_urls(urls: List[str], config: ScraperConfig = None) -> List[ScrapeResult]:
    """Scrape multiple URLs concurrently."""
    config = config or ScraperConfig()
    
    # Create shared context
    ctx = Context()
    ctx.config = config
    ctx.metrics = ScrapeMetrics()
    ctx.rate_limiter = RateLimiter(config.rate_limit, 60)
    ctx.circuit_breaker = CircuitBreaker(
        config.circuit_breaker_threshold,
        config.circuit_breaker_timeout
    )
    
    # Create tasks for all URLs
    tasks = []
    for url in urls:
        url_ctx = Context()
        url_ctx.update(ctx.__dict__)
        url_ctx.url = url
        tasks.append(scrape_url(url_ctx))
    
    # Execute concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Print metrics summary
    print("\nScraping Summary:")
    print(json.dumps(ctx.metrics.get_summary(), indent=2))
    
    # Filter out exceptions
    return [r for r in results if isinstance(r, ScrapeResult)]


# Example usage
async def main():
    """Demonstrate the web scraper with middleware."""
    print("=== Mware Web Scraper Example ===\n")
    
    # URLs to scrape
    urls = [
        "https://httpbin.org/delay/1",
        "https://httpbin.org/status/200",
        "https://httpbin.org/status/500",  # Will trigger retry
        "https://httpbin.org/delay/2",
        "https://httpbin.org/status/200",  # Will hit cache on second run
        "https://httpbin.org/status/404",
        "https://httpbin.org/delay/1",
        "https://httpbin.org/status/200",
    ]
    
    # Configure scraper
    config = ScraperConfig(
        max_retries=2,
        retry_delay=0.5,
        cache_ttl=300,
        rate_limit=5,  # 5 requests per minute (for demo)
        circuit_breaker_threshold=3,
        circuit_breaker_timeout=30
    )
    
    # First run
    print("First run - all requests will be fresh:\n")
    results1 = await scrape_urls(urls, config)
    
    print("\n" + "="*50 + "\n")
    
    # Second run - some requests will hit cache
    print("Second run - some requests will hit cache:\n")
    results2 = await scrape_urls(urls[:5], config)  # Subset of URLs
    
    # Print results
    print("\n=== Results ===")
    for result in results2:
        print(f"URL: {result.url}")
        print(f"  Status: {result.status_code}")
        print(f"  Cached: {result.cached}")
        print(f"  Content length: {len(result.content)}")
        print()


if __name__ == "__main__":
    asyncio.run(main())