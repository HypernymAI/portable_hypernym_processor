"""Adaptive concurrency management for API rate limiting."""

import time
from typing import Dict, Any, Optional
import aiohttp


class AdaptiveConcurrencyManager:
    """Manages concurrent workers based on API rate limits and performance"""
    
    def __init__(self, processor, initial_workers: int = 4):
        self.processor = processor
        self.initial_workers = initial_workers
        self.current_workers = initial_workers
        self.min_workers = 1
        self.max_workers = initial_workers  # Will be updated from API
        self.recommended_workers = initial_workers
        
        # Performance tracking
        self.success_count = 0
        self.error_count = 0
        self.rate_limit_count = 0
        self.total_response_time = 0.0
        self.last_adjustment = time.time()
        self.adjustment_interval = 30  # seconds
        
        # Rate limit info
        self.api_limits = None
        self.last_limit_check = 0
        self.limit_check_interval = 300  # 5 minutes
        
    async def get_rate_limits(self, session: aiohttp.ClientSession) -> Dict[str, Any]:
        """Query the API for current rate limits"""
        try:
            headers = {
                'X-API-Key': self.processor.api_key,
                'Content-Type': 'application/json'
            }
            
            # Extract base URL
            base_url = self.processor.api_url.rsplit('/', 1)[0]
            limits_url = f"{base_url}/user/rate-limits"
            
            async with session.get(limits_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()
                    self.api_limits = data
                    
                    # Update max workers based on API recommendation
                    if 'recommended' in data:
                        self.max_workers = data['recommended'].get('max_workers', self.initial_workers)
                        self.recommended_workers = self.max_workers
                    
                    # Be conservative - start at 50% of max
                    self.current_workers = max(1, self.max_workers // 2)
                    
                    return data
        except Exception as e:
            print(f"⚠️  Could not fetch rate limits: {e}")
        
        return None
    
    def should_check_limits(self) -> bool:
        """Check if we should refresh rate limit info"""
        return time.time() - self.last_limit_check > self.limit_check_interval
    
    def record_success(self, response_time: float):
        """Record a successful request"""
        self.success_count += 1
        self.total_response_time += response_time
    
    def record_error(self):
        """Record an error"""
        self.error_count += 1
    
    def record_rate_limit(self):
        """Record a rate limit event"""
        self.rate_limit_count += 1
        # Immediately reduce workers on rate limit
        self.current_workers = max(self.min_workers, self.current_workers // 2)
    
    def get_avg_response_time(self) -> float:
        """Get average response time"""
        if self.success_count == 0:
            return 0.0
        return self.total_response_time / self.success_count
    
    def should_adjust(self) -> bool:
        """Check if we should adjust worker count"""
        return time.time() - self.last_adjustment > self.adjustment_interval
    
    def adjust_workers(self) -> int:
        """Adjust worker count based on performance"""
        if not self.should_adjust():
            return self.current_workers
        
        self.last_adjustment = time.time()
        
        # If we hit rate limits, stay conservative
        if self.rate_limit_count > 0:
            self.rate_limit_count = 0  # Reset counter
            return self.current_workers  # Keep reduced count
        
        # If high error rate, reduce workers
        error_rate = self.error_count / max(1, self.success_count + self.error_count)
        if error_rate > 0.1:  # More than 10% errors
            self.current_workers = max(self.min_workers, self.current_workers - 1)
            self.error_count = 0
            self.success_count = 0
            return self.current_workers
        
        # If good performance and low response times, try increasing
        avg_response_time = self.get_avg_response_time()
        if self.success_count > 50 and avg_response_time < 2.0 and error_rate < 0.02:
            # Increase by 1 worker at a time, up to recommended
            if self.current_workers < self.recommended_workers:
                self.current_workers += 1
        
        # Reset counters
        self.error_count = 0
        self.success_count = 0
        self.total_response_time = 0.0
        
        return self.current_workers