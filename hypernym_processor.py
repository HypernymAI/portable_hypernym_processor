#!/usr/bin/env python3
"""
Portable Hypernym Processor

A standalone tool for processing text samples from any SQLite database
through the Hypernym compression API. Works directly with database queries
without requiring catalog files or the benchmark framework.

Usage:
    python hypernym_processor.py --db-path /path/to/database.sqlite --query "SELECT * FROM samples WHERE category='literature' LIMIT 10"
    python hypernym_processor.py --db-path /path/to/database.sqlite --sample-ids 1,2,3,4,5
    python hypernym_processor.py --db-path /path/to/database.sqlite --all --max-samples 100
"""

import os
import sys
import json
import sqlite3
import argparse
import time
import hashlib
import random
import asyncio
import math
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import requests
from dataclasses import dataclass, asdict
from tqdm import tqdm
from dotenv import load_dotenv
import aiohttp
import aiosqlite
from asyncio_throttle import Throttler
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn
from rich.table import Table
from rich.align import Align


# Load environment variables from .env file
load_dotenv()

@dataclass
class Sample:
    """
    A text sample to be processed through Hypernym API.
    
    This represents a single unit of text that needs compression. The processor
    will send the content to Hypernym API and store the compressed result.
    
    Attributes:
        id: Unique identifier, typically from your database primary key
        content: The actual text to compress (any length, but 200+ words works best)
        metadata: Optional dict of extra fields from your database row
        
    Example:
        sample = Sample(
            id=42,
            content="The sun was setting over the mountains...",
            metadata={'category': 'literature', 'author': 'Unknown'}
        )
    """
    id: int
    content: str
    metadata: Dict[str, Any] = None

@dataclass
class HypernymResponse:
    """Hypernym API response structure"""
    sample_id: int
    original_text: str
    compressed_text: str
    compression_ratio: float
    segments: List[Dict[str, Any]]
    processing_time: float
    timestamp: str

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

class HypernymProcessor:
    """
    Processes text samples from SQLite through Hypernym compression API.
    
    This is the main class that connects your database to Hypernym's API. It:
    1. Reads text samples from your SQLite database
    2. Sends them to Hypernym API for compression
    3. Stores results back in the same database
    4. Caches results to avoid reprocessing
    
    The processor expects your database to have samples with at least:
    - An 'id' column (unique identifier)
    - A 'content' or 'text' column (the text to compress)
    
    Example usage:
        processor = HypernymProcessor('mydata.sqlite')
        samples = processor.get_samples_by_ids([1, 2, 3])
        results = processor.process_batch(samples)
        
    Environment variables:
        HYPERNYM_API_KEY: Your API key from Hypernym
        HYPERNYM_API_URL: API endpoint (usually http://127.0.0.1:5000/analyze_sync)
    """
    
    def __init__(self, db_path: str = "portable_hypernym_processor.db", api_key: str = None, api_url: str = None):
        self._tier_access = None  # Cache tier access level
        """
        Initialize the processor with database and API credentials.
        
        Creates a 'hypernym_responses' table in your database if it doesn't exist.
        This table stores all API responses for caching and analysis.
        
        Args:
            db_path: Path to SQLite database (must exist)
            api_key: Hypernym API key (defaults to env var HYPERNYM_API_KEY)
            api_url: Hypernym API URL (defaults to env var HYPERNYM_API_URL)
            
        Raises:
            FileNotFoundError: If database doesn't exist
            ValueError: If API credentials are missing
            
        Example:
            # Using environment variables (recommended)
            processor = HypernymProcessor('data.sqlite')
            
            # Or explicit credentials
            processor = HypernymProcessor(
                'data.sqlite',
                api_key='your-key-here',
                api_url='http://localhost:5000/analyze_sync'
            )
        """
        self.db_path = db_path
        self.api_key = api_key or os.environ.get("HYPERNYM_API_KEY")
        self.api_url = api_url or os.environ.get("HYPERNYM_API_URL")
        
        if not self.api_key:
            raise ValueError("HYPERNYM_API_KEY must be provided or set as environment variable")
        if not self.api_url:
            raise ValueError("HYPERNYM_API_URL must be provided or set as environment variable")
        
        # Database will be created if it doesn't exist
        
        # Initialize results storage
        self._init_results_table()
    
    def _init_results_table(self):
        """Create samples, hypernym_responses, and error_entries tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            # Create samples table - the standard input format
            conn.execute("""
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypernym_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id INTEGER NOT NULL,
                    request_hash TEXT NOT NULL,
                    response_data TEXT NOT NULL,
                    compression_ratio REAL,
                    processing_time REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(sample_id, request_hash)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id INTEGER NOT NULL,
                    error_type TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    status_code INTEGER,
                    request_params TEXT,
                    attempt_number INTEGER,
                    content_length INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hypernym_sample_id 
                ON hypernym_responses(sample_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_hypernym_request_hash 
                ON hypernym_responses(request_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_sample_id 
                ON error_entries(sample_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_type 
                ON error_entries(error_type)
            """)
            conn.commit()
    
    def get_samples_by_query(self, query: str) -> List[Sample]:
        """
        Get samples using a custom SQL query
        
        Args:
            query: SQL query that must return at least 'id' and 'content' columns
            
        Returns:
            List of Sample objects
        """
        samples = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            try:
                cursor.execute(query)
                rows = cursor.fetchall()
                
                for row in rows:
                    # Convert row to dict
                    row_dict = dict(row)
                    
                    # Extract required fields
                    if 'id' not in row_dict or 'content' not in row_dict:
                        print(f"⚠️ Warning: Query must return 'id' and 'content' columns")
                        continue
                    
                    # Create sample with all other fields as metadata
                    sample_id = row_dict.pop('id')
                    content = row_dict.pop('content')
                    
                    samples.append(Sample(
                        id=sample_id,
                        content=content,
                        metadata=row_dict  # Store remaining fields as metadata
                    ))
                    
            except sqlite3.Error as e:
                print(f"❌ Database error: {e}")
                raise
                
        return samples
    
    def get_samples_by_ids(self, sample_ids: List[int], table_name: str = "samples") -> List[Sample]:
        """
        Get samples by their IDs
        
        Args:
            sample_ids: List of sample IDs to fetch
            table_name: Name of the table containing samples
            
        Returns:
            List of Sample objects
        """
        if not sample_ids:
            return []
        
        # Build query with proper parameterization
        placeholders = ','.join('?' * len(sample_ids))
        query = f"SELECT * FROM {table_name} WHERE id IN ({placeholders})"
        
        samples = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(query, sample_ids)
            rows = cursor.fetchall()
            
            for row in rows:
                row_dict = dict(row)
                sample_id = row_dict.pop('id')
                content = row_dict.pop('content', row_dict.pop('text', ''))  # Try both common column names
                
                if not content:
                    print(f"⚠️ Warning: No content found for sample {sample_id}")
                    continue
                
                samples.append(Sample(
                    id=sample_id,
                    content=content,
                    metadata=row_dict
                ))
                
        return samples
    
    def get_all_samples(self, table_name: str = "samples", limit: int = None) -> List[Sample]:
        """
        Get all samples from a table
        
        Args:
            table_name: Name of the table containing samples
            limit: Maximum number of samples to fetch
            
        Returns:
            List of Sample objects
        """
        query = f"SELECT * FROM {table_name}"
        if limit:
            query += f" LIMIT {limit}"
        
        return self.get_samples_by_query(query)
    
    def _get_request_hash(self, text: str, compression_ratio: float, similarity: float,
                         analysis_mode: str = "partial", force_detail_count: Optional[int] = None,
                         force_single_segment: bool = True, filters: Optional[Dict] = None) -> str:
        """Generate hash for caching including v2 parameters"""
        # Include all parameters that affect the response
        cache_parts = [
            text, 
            str(compression_ratio), 
            str(similarity),
            analysis_mode
        ]
        
        if force_detail_count is not None:
            cache_parts.append(f"details:{force_detail_count}")
        if force_single_segment:
            cache_parts.append("single_segment")
        if filters:
            cache_parts.append(json.dumps(filters, sort_keys=True))
            
        content = ":".join(cache_parts)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _check_cache(self, sample_id: int, request_hash: str) -> Optional[Dict[str, Any]]:
        """Check if we have a cached response"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT response_data, compression_ratio, processing_time
                FROM hypernym_responses
                WHERE sample_id = ? AND request_hash = ?
            """, (sample_id, request_hash))
            
            row = cursor.fetchone()
            if row:
                return {
                    'response_data': json.loads(row['response_data']),
                    'compression_ratio': row['compression_ratio'],
                    'processing_time': row['processing_time'],
                    'cached': True
                }
        return None
    
    def _save_response(self, sample_id: int, request_hash: str, response_data: Dict[str, Any], 
                      compression_ratio: float, processing_time: float):
        """Save response to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO hypernym_responses
                (sample_id, request_hash, response_data, compression_ratio, processing_time)
                VALUES (?, ?, ?, ?, ?)
            """, (sample_id, request_hash, json.dumps(response_data), compression_ratio, processing_time))
            conn.commit()
    
    def _save_error(self, sample_id: int, error_type: str, error_message: str, 
                   status_code: Optional[int] = None, request_params: Optional[Dict] = None,
                   attempt_number: int = 1, content_length: Optional[int] = None):
        """Save error to error_entries table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO error_entries
                (sample_id, error_type, error_message, status_code, request_params, 
                 attempt_number, content_length)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (sample_id, error_type, error_message, status_code, 
                  json.dumps(request_params) if request_params else None,
                  attempt_number, content_length))
            conn.commit()
    
    def process_sample(self, sample: Sample, compression_ratio: float = 0.6, 
                      similarity: float = 0.75, timeout: int = 30,
                      max_retries: int = 3, use_cache: bool = True,
                      # New v2 API parameters:
                      analysis_mode: str = "partial",
                      force_detail_count: Optional[int] = None,
                      force_single_segment: bool = True,
                      include_embeddings: bool = False,
                      filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a single text sample through Hypernym compression API.
        
        This method handles the full lifecycle: cache check → API call → save result.
        Results are automatically saved to the hypernym_responses table.
        
        Args:
            sample: Sample object with id and content to process
            compression_ratio: Target compression (0.6 = reduce by 40%, keep 60%)
            similarity: Minimum semantic similarity to preserve (0.75 = 75% meaning preserved)
            timeout: Seconds to wait for API response before retry
            max_retries: How many times to retry on failure
            use_cache: If True, returns cached result if available
            analysis_mode: 'partial' (single-pass) or 'comprehensive' (60 trials, Northstar only)
            force_detail_count: Exact number of covariant details (3-9 standard, unlimited Northstar)
            force_single_segment: Treat entire input as one segment (default: False)
            include_embeddings: Include 768D vectors in response (Northstar only)
            filters: Semantic filters to exclude content types (e.g., {'purpose': {'exclude': [...]}})
            
        Returns:
            Dict with these keys:
                {
                    'success': bool,           # True if processed successfully
                    'sample_id': int,          # The sample's ID
                    'compression_ratio': float,# Actual compression achieved (0.0-1.0)
                    'processing_time': float,  # Seconds taken (excluding cache hits)
                    'cached': bool,            # True if result came from cache
                    'response': dict,          # Full API response (if successful)
                    'error': str              # Error message (if failed)
                }
                
        Example:
            result = processor.process_sample(
                Sample(id=1, content="Long text here..."),
                compression_ratio=0.5,  # Compress by 50%
                similarity=0.8,         # Keep 80% of meaning
                timeout=120             # 2 minutes for large content
            )
            
            if result['success']:
                print(f"Compressed to {result['compression_ratio']:.1%}")
            else:
                print(f"Failed: {result['error']}")
                
        Side effects:
            - Saves successful responses to hypernym_responses table
            - Prints progress messages (errors and cache hits)
        """
        # Check cache first
        request_hash = self._get_request_hash(
            sample.content, compression_ratio, similarity,
            analysis_mode, force_detail_count, force_single_segment, filters
        )
        
        if use_cache:
            cached = self._check_cache(sample.id, request_hash)
            if cached:
                print(f"✅ Using cached result for sample {sample.id}")
                return {
                    'success': True,
                    'sample_id': sample.id,
                    'compression_ratio': cached['compression_ratio'],
                    'processing_time': cached['processing_time'],
                    'cached': True,
                    'response': cached['response_data']
                }
        
        # Make API request with retries
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                
                # Prepare request
                headers = {
                    'X-API-Key': self.api_key,
                    'Content-Type': 'application/json'
                }
                
                # Build params with v2 API support
                params = {
                    'min_compression_ratio': compression_ratio,
                    'min_semantic_similarity': similarity
                }
                
                # Add optional v2 parameters
                if analysis_mode != "partial":
                    params['analysis_mode'] = analysis_mode
                    
                # Auto-adjust force_detail_count for large content if not specified
                if force_detail_count is None and len(sample.content) > 10000:
                    # For large content, auto-set higher detail count
                    # Roughly 10 details per 10k chars, max 50
                    auto_detail_count = min(10 * (len(sample.content) // 10000 + 1), 50)
                    params['force_detail_count'] = auto_detail_count
                    print(f"📊 Auto-setting force_detail_count={auto_detail_count} for large content ({len(sample.content):,} chars)")
                elif force_detail_count is not None:
                    params['force_detail_count'] = force_detail_count
                if force_single_segment:
                    params['force_single_segment'] = force_single_segment
                if timeout != 60:  # Only add if non-default (V2 default is 60s)
                    params['timeout'] = timeout
                if include_embeddings:
                    params['include_embeddings'] = include_embeddings
                
                payload = {
                    'essay_text': sample.content,
                    'params': params
                }
                
                # Add filters if provided
                if filters:
                    payload['filters'] = filters
                
                # Make request
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=timeout
                )
                
                response.raise_for_status()
                result = response.json()
                
                # Debug: log response structure
                if os.environ.get('DEBUG_HYPERNYM'):
                    print(f"DEBUG: Response keys: {list(result.keys())[:5]}")
                
                processing_time = time.time() - start_time
                
                # Extract the V2 response from the legacy wrapper
                # The actual V2 response is inside 'results'
                if 'results' in result:
                    v2_response = result['results']
                else:
                    v2_response = result
                
                # Extract compression ratio from segments
                # V2 API Response structure: metadata, request, response
                segments = v2_response.get('response', {}).get('segments', [])
                
                # Check for no_results flag (Zone 1/2 responses)
                no_results = result.get('metadata', {}).get('no_results', False)
                
                if segments:
                    # Segments have compression_ratio directly
                    segment_ratios = [s.get('compression_ratio', 0) for s in segments]
                    actual_ratio = sum(segment_ratios) / len(segment_ratios) if segment_ratios else 0.0
                elif no_results:
                    # This is a valid Zone 1/2 response - short text that can't be compressed
                    # Set ratio to 1.0 (no compression) to indicate it's processed but not compressed
                    actual_ratio = 1.0
                else:
                    actual_ratio = 0.0
                
                # Save to cache
                self._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                
                if no_results:
                    print(f"✅ Processed sample {sample.id}: short text (Zone 1/2) - no compression possible")
                else:
                    print(f"✅ Processed sample {sample.id}: compression={actual_ratio:.2f}")
                
                return {
                    'success': True,
                    'sample_id': sample.id,
                    'compression_ratio': actual_ratio,
                    'processing_time': processing_time,
                    'cached': False,
                    'response': result
                }
                
            except requests.exceptions.Timeout:
                error_msg = f"Request timed out after {timeout}s"
                print(f"❌ {error_msg} for sample {sample.id} (attempt {attempt+1}/{max_retries})")
                
                if attempt < max_retries - 1:
                    # Increase timeout for retry
                    timeout = min(timeout * 1.5, 300)  # Increase by 50%, max 5 minutes
                    sleep_time = (2 ** attempt) * (1 + random.random() * 0.2)
                    print(f"⏱️ Retrying in {sleep_time:.1f}s with timeout={timeout}s...")
                    time.sleep(sleep_time)
                else:
                    # Final attempt failed - save error
                    self._save_error(
                        sample.id, 
                        'TIMEOUT',
                        error_msg,
                        request_params=params,
                        attempt_number=attempt+1,
                        content_length=len(sample.content)
                    )
                    return {
                        'success': False,
                        'sample_id': sample.id,
                        'error': f'Request timed out after {max_retries} attempts'
                    }
                    
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                print(f"❌ Error processing sample {sample.id} (attempt {attempt+1}/{max_retries}): {e}")
                
                # Extract status code if it's an HTTP error
                status_code = None
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    status_code = e.response.status_code
                
                if attempt < max_retries - 1:
                    sleep_time = (2 ** attempt) * (1 + random.random() * 0.2)
                    print(f"⏱️ Retrying in {sleep_time:.1f}s...")
                    time.sleep(sleep_time)
                else:
                    # Final attempt failed - save error
                    self._save_error(
                        sample.id,
                        error_type,
                        error_msg,
                        status_code=status_code,
                        request_params=params if 'params' in locals() else None,
                        attempt_number=attempt+1,
                        content_length=len(sample.content)
                    )
                    return {
                        'success': False,
                        'sample_id': sample.id,
                        'error': f'Failed after {max_retries} attempts: {str(e)}'
                    }
        
        # This should never be reached due to early returns in exception handlers
        return {
            'success': False,
            'sample_id': sample.id,
            'error': f'Failed after {max_retries} attempts'
        }
    
    async def process_batch_parallel(self, samples: List[Sample], compression_ratio: float = 0.6,
                                    similarity: float = 0.75, batch_size: int = 5,
                                    cooldown: float = 0.5, batch_cooldown: float = 2.0,
                                    timeout: int = 30, max_retries: int = 3,
                                    use_cache: bool = True, max_workers: int = 4,
                                    analysis_mode: str = "partial",
                                    force_detail_count: Optional[int] = None,
                                    force_single_segment: bool = True,
                                    include_embeddings: bool = False,
                                    filters: Optional[Dict[str, Any]] = None,
                                    max_display_workers: int = 20) -> List[Dict[str, Any]]:
        """Process samples in parallel with beautiful progress display"""
        console = Console()
        
        # Create adaptive concurrency manager
        concurrency_mgr = AdaptiveConcurrencyManager(self, max_workers)
        
        # Create progress bars
        overall_progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Overall Progress"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=console,
            expand=False
        )
        
        worker_progress = Progress(
            TextColumn("[bold cyan]{task.fields[worker_name]:>10}"),
            SpinnerColumn(),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("[dim]{task.fields[current_sample]}"),
            console=console,
            expand=False
        )
        
        # Get historical data from database for accurate averages
        async def get_historical_stats():
            """Pull historical compression and similarity data from database"""
            historical = {
                'all_compressions': [],
                'all_similarities': [],
                'best_compression': 1.0,
                'best_similarity': 0.0
            }
            
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    # Get all compression ratios and similarities
                    cursor = await db.execute("""
                        SELECT response_data, compression_ratio 
                        FROM hypernym_responses 
                        WHERE compression_ratio > 0
                    """)
                    rows = await cursor.fetchall()
                    
                    for row in rows:
                        compression_ratio = row[1]
                        response_data = json.loads(row[0])
                        
                        # Track compression
                        if compression_ratio > 0:
                            historical['all_compressions'].append(compression_ratio)
                            if compression_ratio < historical['best_compression']:
                                historical['best_compression'] = compression_ratio
                        
                        # Extract similarity from response
                        try:
                            if 'results' in response_data:
                                segments = response_data['results'].get('response', {}).get('segments', [])
                            else:
                                segments = response_data.get('response', {}).get('segments', [])
                            
                            if segments:
                                similarities = [s.get('semantic_similarity', 0) for s in segments if 'semantic_similarity' in s]
                                if similarities:
                                    avg_sim = sum(similarities) / len(similarities)
                                    historical['all_similarities'].append(avg_sim)
                                    if avg_sim > historical['best_similarity']:
                                        historical['best_similarity'] = avg_sim
                        except:
                            pass
                            
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not load historical data: {e}[/yellow]")
            
            return historical
        
        # Stats tracking
        historical_data = await get_historical_stats()
        stats = {
            'processed': 0,
            'errors': 0,
            'cache_hits': 0,
            'rate_limited': 0,
            'start_time': time.time(),
            'recent_compressions': [],  # Track last 10 compression ratios
            'recent_similarities': [],  # Track last 10 similarity scores
            'all_compressions': historical_data['all_compressions'],  # ALL historical data
            'all_similarities': historical_data['all_similarities'],  # ALL historical data
            'best_compression': historical_data['best_compression'],
            'best_similarity': historical_data['best_similarity'],
            'animation_frame': 0
        }
        
        # Results storage
        results = {}
        
        def create_average_banners():
            """Create Megaman-style banners showing averages"""
            # Calculate averages from historical data
            avg_compression = sum(stats['all_compressions']) / len(stats['all_compressions']) if stats['all_compressions'] else 0.0
            avg_similarity = sum(stats['all_similarities']) / len(stats['all_similarities']) if stats['all_similarities'] else 0.0
            
            banner_lines = []
            
            # Compression banner
            comp_percent = (1 - avg_compression) * 100
            comp_bar = "█" * int(comp_percent / 5)  # 20 blocks max
            banner_lines.append(f"[bold yellow]╔═══════════════════════════╗[/bold yellow]")
            banner_lines.append(f"[bold yellow]║[/bold yellow] [bold red]⚡ COMPRESSION POWER ⚡[/bold red]   [bold yellow]║[/bold yellow]")
            banner_lines.append(f"[bold yellow]╠═══════════════════════════╣[/bold yellow]")
            banner_lines.append(f"[bold yellow]║[/bold yellow] [{comp_bar:<23}] [bold yellow]║[/bold yellow]")
            banner_lines.append(f"[bold yellow]║[/bold yellow]           [bold white]{comp_percent:>5.1f}%[/bold white]          [bold yellow]║[/bold yellow]")
            banner_lines.append(f"[bold yellow]╚═══════════════════════════╝[/bold yellow]")
            
            banner_lines.append("")  # Spacer
            
            # Similarity banner
            sim_percent = avg_similarity * 100
            sim_bar = "█" * int(sim_percent / 5)  # 20 blocks max
            banner_lines.append(f"[bold cyan]╔═══════════════════════════╗[/bold cyan]")
            banner_lines.append(f"[bold cyan]║[/bold cyan] [bold blue]💎 SIMILARITY SHIELD 💎[/bold blue]   [bold cyan]║[/bold cyan]")
            banner_lines.append(f"[bold cyan]╠═══════════════════════════╣[/bold cyan]")
            banner_lines.append(f"[bold cyan]║[/bold cyan] [{sim_bar:<23}] [bold cyan]║[/bold cyan]")
            banner_lines.append(f"[bold cyan]║[/bold cyan]           [bold white]{sim_percent:>5.1f}%[/bold white]          [bold cyan]║[/bold cyan]")
            banner_lines.append(f"[bold cyan]╚═══════════════════════════╝[/bold cyan]")
            
            banner_lines.append("")  # Spacer
            
            # Sample count
            banner_lines.append(f"[dim]Historical samples: {len(stats['all_compressions']):,}[/dim]")
            
            # Combo meter
            if comp_percent > 70 and sim_percent > 85:
                banner_lines.append("")
                banner_lines.append("[bold red on yellow blink]★ MEGA COMBO ACTIVE ★[/bold red on yellow blink]")
            
            return "\n".join(banner_lines)
        
        def create_best_scores_display():
            """Create display with 1D violin plots using exact style requested"""
            lines = []
            
            # Calculate statistics for all samples
            if stats['all_compressions']:
                comp_values = [(1-x)*100 for x in stats['all_compressions']]  # Convert to percentage
                comp_min = min(comp_values)
                comp_max = max(comp_values)
                comp_avg = sum(comp_values) / len(comp_values)
                comp_q1 = sorted(comp_values)[len(comp_values)//4]
                comp_q3 = sorted(comp_values)[3*len(comp_values)//4]
                
                # Calculate standard deviation
                comp_std = (sum((x - comp_avg) ** 2 for x in comp_values) / len(comp_values)) ** 0.5
                
                # Create violin plot for compression: ||---===|~~~~|===---||
                lines.append("[bold red]🏆 COMPRESSION[/bold red]")
                lines.append(f"Best: [bold yellow]{comp_max:.1f}%[/bold yellow]  Avg: {comp_avg:.1f}%")
                
                # Build violin plot: ||---------======|~~~~|==-----||
                graph_width = 40
                
                # Calculate standard error for error bars
                comp_se = comp_std / (len(comp_values) ** 0.5)
                
                # Map values to positions on the graph
                min_pos = int(comp_min / 100 * graph_width)
                max_pos = int(comp_max / 100 * graph_width)
                q1_pos = int(comp_q1 / 100 * graph_width)
                q3_pos = int(comp_q3 / 100 * graph_width)
                avg_pos = int(comp_avg / 100 * graph_width)
                error_left = int((comp_avg - comp_se) / 100 * graph_width)
                error_right = int((comp_avg + comp_se) / 100 * graph_width)
                
                # Build the violin character by character
                violin = ""
                i = 0
                while i < graph_width:
                    if i == min_pos:
                        violin += "||"
                        i += 2
                    elif i == max_pos and max_pos != min_pos + 1:
                        violin += "||"
                        i += 2
                    elif i == error_left:
                        violin += "|"
                        i += 1
                    elif i == error_right:
                        violin += "|"
                        i += 1
                    elif i > error_left and i < error_right:
                        violin += "~"
                        i += 1
                    elif i >= q1_pos and i <= q3_pos:
                        violin += "="
                        i += 1
                    elif i > min_pos and i < q1_pos:
                        violin += "-"
                        i += 1
                    elif i > q3_pos and i < max_pos:
                        violin += "-"
                        i += 1
                    else:
                        violin += " "
                        i += 1
                
                lines.append(violin)
                lines.append(f"0%{' ' * 18}50%{' ' * 17}100%")
                lines.append("")
            
            # Similar for similarity scores
            if stats['all_similarities']:
                sim_values = [x*100 for x in stats['all_similarities']]
                sim_min = min(sim_values)
                sim_max = max(sim_values)
                sim_avg = sum(sim_values) / len(sim_values)
                sim_q1 = sorted(sim_values)[len(sim_values)//4]
                sim_q3 = sorted(sim_values)[3*len(sim_values)//4]
                
                # Calculate standard deviation
                sim_std = (sum((x - sim_avg) ** 2 for x in sim_values) / len(sim_values)) ** 0.5
                
                lines.append("[bold cyan]🏆 SIMILARITY[/bold cyan]")
                lines.append(f"Best: [bold green]{sim_max:.1f}%[/bold green]  Avg: {sim_avg:.1f}%")
                
                # Build violin plot: ||---------======|~~~~|==-----||
                graph_width = 40
                
                # Calculate standard error for error bars
                sim_se = sim_std / (len(sim_values) ** 0.5)
                
                # Map values to positions on the graph
                min_pos = int(sim_min / 100 * graph_width)
                max_pos = int(sim_max / 100 * graph_width)
                q1_pos = int(sim_q1 / 100 * graph_width)
                q3_pos = int(sim_q3 / 100 * graph_width)
                avg_pos = int(sim_avg / 100 * graph_width)
                error_left = int((sim_avg - sim_se) / 100 * graph_width)
                error_right = int((sim_avg + sim_se) / 100 * graph_width)
                
                # Build the violin character by character
                violin = ""
                i = 0
                while i < graph_width:
                    if i == min_pos:
                        violin += "||"
                        i += 2
                    elif i == max_pos and max_pos != min_pos + 1:
                        violin += "||"
                        i += 2
                    elif i == error_left:
                        violin += "|"
                        i += 1
                    elif i == error_right:
                        violin += "|"
                        i += 1
                    elif i > error_left and i < error_right:
                        violin += "~"
                        i += 1
                    elif i >= q1_pos and i <= q3_pos:
                        violin += "="
                        i += 1
                    elif i > min_pos and i < q1_pos:
                        violin += "-"
                        i += 1
                    elif i > q3_pos and i < max_pos:
                        violin += "-"
                        i += 1
                    else:
                        violin += " "
                        i += 1
                
                lines.append(violin)
                lines.append(f"0%{' ' * 18}50%{' ' * 17}100%")
                lines.append("")
            
            lines.append(f"[dim]Total samples: {len(stats['all_compressions']):,}[/dim]")
            
            return "\n".join(lines)
        
        def create_pinball_animation():
            """Create display with two ASCII graphs"""
            # Get last 50 samples for graphs
            recent_comp = stats['all_compressions'][-50:] if len(stats['all_compressions']) > 50 else stats['all_compressions']
            recent_sim = stats['all_similarities'][-50:] if len(stats['all_similarities']) > 50 else stats['all_similarities']
            
            # Build display
            display = []
            display.append("╔" + "═" * 95 + "╗")
            display.append("║" + " " * 32 + "🎮 HYPERNYM PERFORMANCE 🎮" + " " * 33 + "║")
            display.append("╠" + "═" * 95 + "╣")
            display.append("║" + " " * 95 + "║")
            
            # Best scores boxes
            display.append("║ ┌─────────────────────────┐" + " " * 41 + "┌─────────────────────────┐ ║")
            display.append(f"║ │ 🏆 BEST COMPRESSION: {(1-stats['best_compression'])*100:>3.0f}% │" + " " * 41 + f"│ 🏆 BEST SIMILARITY: {stats['best_similarity']*100:>3.0f}% │ ║")
            display.append("║ └─────────────────────────┘" + " " * 41 + "└─────────────────────────┘ ║")
            display.append("║" + " " * 95 + "║")
            
            # Graph headers
            display.append("║ Compression History (last 50 samples)" + " " * 18 + "Similarity History (last 50 samples)   ║")
            
            # Create ASCII graphs
            if recent_comp and recent_sim:
                # Calculate ranges
                comp_values = [(1-x)*100 for x in recent_comp]  # Convert to percentage
                sim_values = [x*100 for x in recent_sim]
                
                # Create line graph for compression
                comp_graph = []
                for y in range(100, 40, -10):  # 100% to 50% 
                    line = f"{y:>3}%┤"
                    for i, val in enumerate(comp_values[-30:]):  # Last 30 points
                        if i == 0:
                            line += " "
                        elif abs(val - y) < 5:
                            line += "═"
                        elif comp_values[i-1] < y < val or val < y < comp_values[i-1]:
                            line += "╱" if val > comp_values[i-1] else "╲"
                        else:
                            line += " "
                    comp_graph.append(line)
                
                # Create bar graph for similarity
                sim_graph = []
                sim_avg = sum(sim_values) / len(sim_values)
                sim_min = min(sim_values)
                sim_max = max(sim_values)
                
                for y in range(100, 40, -10):
                    line = f"{y:>3}%┤"
                    if sim_min <= y <= sim_max:
                        if abs(y - sim_avg) < 5:
                            line += "═" * 30
                        else:
                            line += "║" + " " * 28 + "║"
                    else:
                        line += " " * 30
                    sim_graph.append(line)
                
                # Display graphs side by side
                for i in range(len(comp_graph)):
                    display.append(f"║ {comp_graph[i]:<44} {sim_graph[i]:<45} ║")
                
                # Graph bottom line
                display.append("║    └" + "─" * 30 + " " * 14 + "└" + "─" * 30 + " ║")
                
                # Stats
                comp_avg = sum(comp_values) / len(comp_values)
                sim_avg = sum(sim_values) / len(sim_values)
                display.append(f"║    [Min: {min(comp_values):>2.0f}%  Avg: {comp_avg:>2.0f}%  Max: {max(comp_values):>2.0f}%]" + 
                             " " * 19 + 
                             f"[Min: {min(sim_values):>2.0f}%  Avg: {sim_avg:>2.0f}%  Max: {max(sim_values):>2.0f}%]   ║")
            else:
                # No data message
                for _ in range(8):
                    display.append("║" + " " * 95 + "║")
                display.append("║" + " " * 40 + "[No data yet]" + " " * 42 + "║")
            
            display.append("╚" + "═" * 95 + "╝")
            
            return "\n".join(display)
        
        def make_stats_table():
            """Create stats table"""
            table = Table(show_header=False, box=None, padding=(0, 2))
            
            elapsed = time.time() - stats['start_time']
            rate = stats['processed'] / elapsed if elapsed > 0 else 0
            
            table.add_row("[green]✓ Processed", f"[bold green]{stats['processed']:,}")
            table.add_row("[yellow]⚡ Cache Hits", f"[bold yellow]{stats['cache_hits']:,}")
            table.add_row("[red]✗ Errors", f"[bold red]{stats['errors']:,}")
            table.add_row("[magenta]⏱ Rate Limited", f"[bold magenta]{stats['rate_limited']:,}")
            table.add_row("[blue]⚡ Rate", f"[bold blue]{rate:.1f}/sec")
            table.add_row("[cyan]👷 Workers", f"[bold cyan]{concurrency_mgr.current_workers}/{concurrency_mgr.max_workers}")
            
            return table
        
        def make_layout(num_workers, max_display_workers=20):
            """Create the layout"""
            layout = Layout()
            
            # Calculate optimal progress panel size based on max_display_workers
            worker_panel_size = min(max(num_workers, 10), max_display_workers)
            progress_panel_size = worker_panel_size + 3  # +3 for overall progress bar
            
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="progress", size=progress_panel_size),
                Layout(name="bottom")
            )
            
            # Split bottom section into stats and best scores
            layout["bottom"].split_row(
                Layout(name="stats", ratio=1),
                Layout(name="best_scores", ratio=1)
            )
            
            layout["header"].update(
                Panel(
                    Align.center(
                        f"[bold][rgb(164,27,27)]H[/rgb(164,27,27)][rgb(247,185,121)]Y[/rgb(247,185,121)][rgb(196,153,21)]P[/rgb(196,153,21)][rgb(68,126,42)]E[/rgb(68,126,42)][rgb(85,140,152)]R[/rgb(85,140,152)][rgb(81,135,220)]N[/rgb(81,135,220)][rgb(167,202,234)]Y[/rgb(167,202,234)][rgb(59,46,98)]M[/rgb(59,46,98)] Parallel Processor[/bold]\n"
                        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
                        vertical="middle"
                    ),
                    border_style="blue"
                )
            )
            
            
            # Create progress panels layout
            progress_left = Layout()
            
            # When many workers, create scrollable panel
            if num_workers > max_display_workers:
                # Note: Rich doesn't support true scrolling in live displays,
                # but we can show first N workers with indication of total
                worker_panel_content = Panel(
                    worker_progress, 
                    border_style="cyan",
                    title=f"[bold cyan]Workers (showing {max_display_workers} of {num_workers})[/bold cyan]",
                    subtitle="[dim]Use --max-display-workers to show more[/dim]"
                )
            else:
                worker_panel_content = Panel(worker_progress, border_style="cyan")
            
            progress_left.split_column(
                Layout(Panel(overall_progress, border_style="green"), size=3),
                Layout(worker_panel_content)
            )
            
            # Split progress into left (bars) and right (banners)
            progress_content = Layout()
            progress_content.split_row(
                Layout(progress_left, ratio=3),
                Layout(
                    Panel(
                        Align.center(create_average_banners(), vertical="middle"),
                        title="[bold magenta]📊 Performance Meters 📊[/bold magenta]",
                        border_style="magenta"
                    ),
                    ratio=1
                )
            )
            layout["progress"].update(progress_content)
            
            layout["stats"].update(
                Panel(
                    Align.center(make_stats_table(), vertical="middle"),
                    title="[bold]Statistics[/bold]",
                    border_style="yellow"
                )
            )
            
            layout["best_scores"].update(
                Panel(
                    Align.center(create_best_scores_display(), vertical="middle"),
                    title="[bold]🏆 High Scores 🏆[/bold]",
                    border_style="green"
                )
            )
            
            return layout
        
        async def process_sample_async(self, session, sample, worker_id, worker_task):
            """Process a single sample asynchronously"""
            worker_progress.update(
                worker_task,
                current_sample=f"Sample #{sample.id:04d}"
            )
            
            # Generate request hash for caching
            request_hash = self._get_request_hash(
                sample.content, compression_ratio, similarity,
                analysis_mode, force_detail_count, force_single_segment, filters
            )
            
            # Check cache
            if use_cache:
                cached = self._check_cache(sample.id, request_hash)
                if cached:
                    stats['processed'] += 1
                    stats['cache_hits'] += 1
                    worker_progress.update(
                        worker_task,
                        current_sample=f"Sample #{sample.id:04d} [yellow](cached)[/yellow]"
                    )
                    return {
                        'success': True,
                        'sample_id': sample.id,
                        'compression_ratio': cached['compression_ratio'],
                        'processing_time': cached['processing_time'],
                        'cached': True,
                        'response': cached['response_data']
                    }
            
            # Make API request
            try:
                headers = {
                    'X-API-Key': self.api_key,
                    'Content-Type': 'application/json'
                }
                
                params = {
                    'min_compression_ratio': compression_ratio,
                    'min_semantic_similarity': similarity
                }
                
                if analysis_mode != "partial":
                    params['analysis_mode'] = analysis_mode
                if force_detail_count is not None:
                    params['force_detail_count'] = force_detail_count
                if force_single_segment:
                    params['force_single_segment'] = force_single_segment
                if timeout != 60:
                    params['timeout'] = timeout
                if include_embeddings:
                    params['include_embeddings'] = include_embeddings
                
                payload = {
                    'essay_text': sample.content,
                    'params': params
                }
                
                if filters:
                    payload['filters'] = filters
                
                start_time = time.time()
                
                async with session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status == 429:
                        stats['rate_limited'] += 1
                        concurrency_mgr.record_rate_limit()
                        worker_progress.update(
                            worker_task,
                            current_sample=f"Sample #{sample.id:04d} [magenta](rate limited)[/magenta]"
                        )
                        # Exponential backoff with jitter
                        backoff = min(60, 2 ** stats.get('rate_limit_retries', 0) + random.random())
                        await asyncio.sleep(backoff)
                        stats['rate_limit_retries'] = stats.get('rate_limit_retries', 0) + 1
                        raise Exception("Rate limited")
                    
                    response.raise_for_status()
                    result = await response.json()
                
                processing_time = time.time() - start_time
                
                # Extract compression ratio
                if 'results' in result:
                    v2_response = result['results']
                else:
                    v2_response = result
                
                segments = v2_response.get('response', {}).get('segments', [])
                
                # Check for no_results flag (Zone 1/2 responses)
                no_results = result.get('metadata', {}).get('no_results', False)
                
                if segments:
                    segment_ratios = [s.get('compression_ratio', 0) for s in segments]
                    actual_ratio = sum(segment_ratios) / len(segment_ratios) if segment_ratios else 0.0
                elif no_results:
                    # This is a valid Zone 1/2 response - short text that can't be compressed
                    # Set ratio to 1.0 (no compression) to indicate it's processed but not compressed
                    actual_ratio = 1.0
                else:
                    actual_ratio = 0.0
                
                # Extract similarity scores from segments
                avg_similarity = 0.75  # default
                if segments:
                    similarities = [s.get('semantic_similarity', 0.75) for s in segments if 'semantic_similarity' in s]
                    if similarities:
                        avg_similarity = sum(similarities) / len(similarities)
                
                # Track recent metrics for animation
                stats['recent_compressions'].append(actual_ratio)
                stats['recent_similarities'].append(avg_similarity)
                # Keep only last 10
                if len(stats['recent_compressions']) > 10:
                    stats['recent_compressions'].pop(0)
                if len(stats['recent_similarities']) > 10:
                    stats['recent_similarities'].pop(0)
                
                # Track ALL metrics for high scores
                stats['all_compressions'].append(actual_ratio)
                stats['all_similarities'].append(avg_similarity)
                
                # Update high scores
                if actual_ratio < stats['best_compression']:
                    stats['best_compression'] = actual_ratio
                if avg_similarity > stats['best_similarity']:
                    stats['best_similarity'] = avg_similarity
                
                # Save to cache
                self._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                
                stats['processed'] += 1
                concurrency_mgr.record_success(processing_time)
                
                return {
                    'success': True,
                    'sample_id': sample.id,
                    'compression_ratio': actual_ratio,
                    'processing_time': processing_time,
                    'cached': False,
                    'response': result
                }
                
            except Exception as e:
                stats['errors'] += 1
                concurrency_mgr.record_error()
                error_type = type(e).__name__
                error_msg = str(e)
                
                # Extract status code if available
                status_code = None
                if hasattr(e, 'status'):
                    status_code = e.status
                
                # Enhanced error message for 408 timeouts
                if status_code == 408:
                    error_msg = f"Server timeout (408) at {self.api_url} - Server returned timeout status, not a client timeout. Content length: {len(sample.content)} bytes"
                    console.print(f"[yellow]⚠️  408 Timeout from server for sample {sample.id} ({len(sample.content)} bytes)[/yellow]")
                    console.print(f"[yellow]    URL: {self.api_url}[/yellow]")
                    console.print(f"[yellow]    This is a server-side timeout, not a client timeout[/yellow]")
                
                # Save error to database
                self._save_error(
                    sample.id,
                    error_type,
                    error_msg,
                    status_code=status_code,
                    request_params={
                        'min_compression_ratio': compression_ratio,
                        'min_semantic_similarity': similarity,
                        'analysis_mode': analysis_mode,
                        'force_detail_count': force_detail_count,
                        'force_single_segment': force_single_segment
                    },
                    attempt_number=1,  # Async version doesn't retry
                    content_length=len(sample.content)
                )
                
                worker_progress.update(
                    worker_task,
                    current_sample=f"Sample #{sample.id:04d} [red](failed: {str(e)})[/red]"
                )
                return {
                    'success': False,
                    'sample_id': sample.id,
                    'error': str(e)
                }
        
        async def worker(self, session, worker_id, queue, overall_task, samples_per_worker):
            """Worker coroutine"""
            worker_samples_processed = 0
            worker_task = worker_progress.add_task(
                f"Worker {worker_id}",
                total=samples_per_worker,  # Each worker gets approximately this many
                worker_name=f"Worker {worker_id}",
                current_sample="Starting...",
                samples_count=0
            )
            
            while True:
                try:
                    sample = await queue.get()
                    if sample is None:  # Stop signal
                        break
                    
                    # Process the sample
                    result = await process_sample_async(self, session, sample, worker_id, worker_task)
                    results[sample.id] = result
                    
                    # Update worker stats
                    worker_samples_processed += 1
                    worker_progress.update(
                        worker_task,
                        completed=worker_samples_processed,
                        current_sample=f"Sample #{sample.id:04d} [green](done)[/green]",
                        samples_count=worker_samples_processed
                    )
                    
                    # Update overall progress
                    overall_progress.advance(overall_task)
                    
                    queue.task_done()
                    
                except Exception as e:
                    worker_progress.update(
                        worker_task,
                        current_sample=f"[red]Error: {str(e)}[/red]"
                    )
            
            worker_progress.update(
                worker_task,
                current_sample="[green]Complete[/green]"
            )
        
        # Create overall task
        overall_task = overall_progress.add_task(
            "Processing samples",
            total=len(samples)
        )
        
        # Create work queue
        queue = asyncio.Queue()
        for sample in samples:
            await queue.put(sample)
        
        # Adjust worker count if we have fewer samples than workers
        actual_workers = min(max_workers, len(samples))
        
        # Create layout
        layout = make_layout(actual_workers, max_display_workers)
        
        # Create aiohttp session
        async with aiohttp.ClientSession() as session:
            # Query rate limits first
            console.print("🔍 Querying API rate limits...")
            limits = await concurrency_mgr.get_rate_limits(session)
            if limits:
                console.print(f"✅ Rate limits: {limits['limits']['requests_per_hour']:,}/hour, "
                            f"recommended {limits['recommended']['max_workers']} workers")
                console.print(f"🚀 Starting with {concurrency_mgr.current_workers} workers "
                            f"(will scale up to {concurrency_mgr.max_workers})")
            else:
                console.print(f"⚠️  Using default: {concurrency_mgr.current_workers} workers")
            
            await asyncio.sleep(1)  # Brief pause to read the info
            
            with Live(layout, console=console, refresh_per_second=10):
                # Start with adaptive number of workers
                active_workers = min(concurrency_mgr.current_workers, actual_workers)
                samples_per_worker = max(1, len(samples) // active_workers)
                
                workers = [
                    asyncio.create_task(worker(self, session, i+1, queue, overall_task, samples_per_worker))
                    for i in range(active_workers)
                ]
                
                # Add stop signals immediately after creating workers
                for _ in range(active_workers):
                    await queue.put(None)
                
                # Update stats while processing
                while any(not w.done() for w in workers):
                    stats['animation_frame'] += 1
                    
                    # Update progress section with banners
                    progress_left = Layout()
                    progress_left.split_column(
                        Layout(Panel(overall_progress, border_style="green"), size=3),
                        Layout(Panel(worker_progress, border_style="cyan"))
                    )
                    
                    progress_content = Layout()
                    progress_content.split_row(
                        Layout(progress_left, ratio=3),
                        Layout(
                            Panel(
                                Align.center(create_average_banners(), vertical="middle"),
                                title="[bold magenta]📊 Performance Meters 📊[/bold magenta]",
                                border_style="magenta"
                            ),
                            ratio=1
                        )
                    )
                    layout["progress"].update(progress_content)
                    
                    # Update stats panel
                    layout["stats"].update(
                        Panel(
                            Align.center(make_stats_table(), vertical="middle"),
                            title="[bold]Statistics[/bold]",
                            border_style="yellow"
                        )
                    )
                    
                    # Update best scores panel
                    layout["best_scores"].update(
                        Panel(
                            Align.center(create_best_scores_display(), vertical="middle"),
                            title="[bold]🏆 High Scores 🏆[/bold]",
                            border_style="green"
                        )
                    )
                    
                    await asyncio.sleep(0.1)
                
                # Wait for workers
                await asyncio.gather(*workers)
                
                # Final stats update
                layout["stats"].update(
                    Panel(
                        Align.center(make_stats_table(), vertical="middle"),
                        title="[bold]Statistics - Complete[/bold]",
                        border_style="green"
                    )
                )
                
                # Final best scores update
                layout["best_scores"].update(
                    Panel(
                        Align.center(create_best_scores_display(), vertical="middle"),
                        title="[bold]🏆 Final High Scores 🏆[/bold]",
                        border_style="green"
                    )
                )
                
                await asyncio.sleep(1)
        
        # Convert results dict to list in original order
        return [results.get(s.id) for s in samples if s.id in results]

    def process_batch(self, samples: List[Sample], compression_ratio: float = 0.6,
                     similarity: float = 0.75, batch_size: int = 5,
                     cooldown: float = 0.5, batch_cooldown: float = 2.0,
                     timeout: int = 30, max_retries: int = 3,
                     use_cache: bool = True, progress_bar: bool = True,
                     # New v2 API parameters:
                     analysis_mode: str = "partial",
                     force_detail_count: Optional[int] = None,
                     force_single_segment: bool = True,
                     include_embeddings: bool = False,
                     filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Process multiple samples in batches
        
        Args:
            samples: List of samples to process
            compression_ratio: Target compression ratio
            similarity: Target semantic similarity
            batch_size: Number of samples per batch
            cooldown: Seconds to wait between samples
            batch_cooldown: Seconds to wait between batches
            timeout: API timeout in seconds
            max_retries: Maximum retry attempts
            use_cache: Whether to use cached results
            progress_bar: Show progress bar
            analysis_mode: 'partial' or 'comprehensive' (Northstar only)
            force_detail_count: Exact number of details to extract
            force_single_segment: Process as single segment
            include_embeddings: Include embedding vectors (Northstar only)
            filters: Semantic filters for content exclusion
            
        Returns:
            List of processing results
        """
        results = []
        
        # Create batches
        batches = [samples[i:i + batch_size] for i in range(0, len(samples), batch_size)]
        
        # Process each batch
        for batch_idx, batch in enumerate(batches):
            print(f"\n📦 Processing batch {batch_idx + 1}/{len(batches)}")
            
            # Process samples in batch
            batch_samples = tqdm(batch, desc="Samples", disable=not progress_bar)
            for sample_idx, sample in enumerate(batch_samples):
                # Check metadata for per-sample processing parameters
                sample_meta = sample.metadata or {}
                
                # Determine processing mode (sync/async)
                processing_mode = sample_meta.get('processing_mode', 'sync')
                
                # Get parameters from metadata or use defaults
                sample_compression = sample_meta.get('compression_ratio', compression_ratio)
                sample_similarity = sample_meta.get('similarity', similarity)
                sample_analysis_mode = sample_meta.get('analysis_mode', analysis_mode)
                sample_filters = sample_meta.get('filters', filters)
                sample_embeddings = sample_meta.get('include_embeddings', include_embeddings)
                sample_single_segment = sample_meta.get('force_single_segment', force_single_segment)
                
                # Determine timeout based on content length if not in metadata
                sample_timeout = sample_meta.get('timeout')
                if sample_timeout is None:
                    content_length = len(sample.content)
                    if content_length > 10000:  # Large content
                        sample_timeout = 60  # 60s for large content
                        print(f"📊 Auto-setting timeout to {sample_timeout}s for large content ({content_length:,} chars)")
                    else:
                        sample_timeout = timeout  # Default 30s
                
                # Process based on mode
                if processing_mode == 'async':
                    print(f"🔄 Processing sample {sample.id} asynchronously")
                    result = self.process_sample_async(
                        sample, sample_compression, sample_similarity,
                        sample_timeout, poll_interval=5.0, max_wait=1200.0,
                        analysis_mode=sample_analysis_mode,
                        force_detail_count=force_detail_count,
                        force_single_segment=sample_single_segment,
                        include_embeddings=sample_embeddings,
                        filters=sample_filters,
                        use_cache=use_cache
                    )
                else:
                    # Synchronous processing
                    result = self.process_sample(
                        sample, sample_compression, sample_similarity,
                        sample_timeout, max_retries, use_cache,
                        sample_analysis_mode, force_detail_count, sample_single_segment,
                        sample_embeddings, sample_filters
                    )
                results.append(result)
                
                # Cooldown between samples
                if sample_idx < len(batch) - 1:
                    time.sleep(cooldown)
            
            # Batch cooldown
            if batch_idx < len(batches) - 1:
                print(f"⏱️ Batch cooldown: {batch_cooldown}s")
                time.sleep(batch_cooldown)
        
        return results
    
    def analyze_async(self, sample: Sample, compression_ratio: float = 0.6,
                      similarity: float = 0.75, timeout: int = 600,
                      analysis_mode: str = "partial",
                      force_detail_count: Optional[int] = None,
                      force_single_segment: bool = True,
                      include_embeddings: bool = False,
                      filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Start asynchronous analysis and return task ID.
        
        Args:
            sample: Sample object with content to process
            compression_ratio: Target compression ratio
            similarity: Target semantic similarity
            timeout: Maximum processing time in seconds
            analysis_mode: 'partial' or 'comprehensive'
            force_detail_count: Exact number of details to extract
            force_single_segment: Process as single segment
            include_embeddings: Include embedding vectors
            filters: Semantic filters for content exclusion
            
        Returns:
            Dict with task_id and status:
                {
                    'success': bool,
                    'task_id': str,
                    'status': str,
                    'error': str (if failed)
                }
        """
        try:
            # Prepare request
            headers = {
                'X-API-Key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            # Build params
            params = {
                'min_compression_ratio': compression_ratio,
                'min_semantic_similarity': similarity
            }
            
            if analysis_mode != "partial":
                params['analysis_mode'] = analysis_mode
            if force_detail_count is not None:
                params['force_detail_count'] = force_detail_count
            if force_single_segment:
                params['force_single_segment'] = force_single_segment
            if timeout != 600:
                params['timeout'] = timeout
            if include_embeddings:
                params['include_embeddings'] = include_embeddings
            
            payload = {
                'essay_text': sample.content,
                'params': params
            }
            
            if filters:
                payload['filters'] = filters
            
            # Make async request to analyze_begin endpoint
            api_url_base = self.api_url.rsplit('/', 1)[0]  # Remove analyze_sync
            async_url = f"{api_url_base}/analyze_begin"
            
            response = requests.post(
                async_url,
                headers=headers,
                json=payload,
                timeout=30  # Short timeout for async initiation
            )
            
            response.raise_for_status()
            result = response.json()
            
            return {
                'success': True,
                'task_id': result.get('task_id'),
                'status': result.get('status', 'pending')
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def check_async_status(self, task_id: str) -> Dict[str, Any]:
        """
        Check status of asynchronous analysis task.
        
        Args:
            task_id: Task ID returned by analyze_async
            
        Returns:
            Dict with status and results:
                {
                    'success': bool,
                    'status': str,  # 'pending', 'processing', 'completed', 'failed'
                    'progress': float,  # 0.0-1.0
                    'result': dict,  # Full result if completed
                    'error': str  # Error message if failed
                }
        """
        try:
            headers = {
                'X-API-Key': self.api_key,
                'Accept': 'application/json'
            }
            
            # Make request to analyze_status endpoint
            api_url_base = self.api_url.rsplit('/', 1)[0]
            status_url = f"{api_url_base}/analyze_status/{task_id}"
            
            response = requests.get(
                status_url,
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            return {
                'success': True,
                'status': result.get('status', 'unknown'),
                'progress': result.get('progress', 0.0),
                'result': result.get('result') if result.get('status') == 'completed' else None,
                'error': result.get('error') if result.get('status') == 'failed' else None
            }
            
        except Exception as e:
            return {
                'success': False,
                'status': 'error',
                'error': str(e)
            }
    
    def process_sample_async(self, sample: Sample, compression_ratio: float = 0.6,
                            similarity: float = 0.75, timeout: int = 600,
                            poll_interval: float = 5.0, max_wait: float = 1200.0,
                            analysis_mode: str = "partial",
                            force_detail_count: Optional[int] = None,
                            force_single_segment: bool = True,
                            include_embeddings: bool = False,
                            filters: Optional[Dict[str, Any]] = None,
                            use_cache: bool = True) -> Dict[str, Any]:
        """
        Process sample asynchronously with polling.
        
        Args:
            sample: Sample to process
            compression_ratio: Target compression ratio
            similarity: Target semantic similarity
            timeout: Processing timeout in seconds
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait for completion
            analysis_mode: 'partial' or 'comprehensive'
            force_detail_count: Exact number of details
            force_single_segment: Process as single segment
            include_embeddings: Include embeddings
            filters: Semantic filters
            use_cache: Check cache first
            
        Returns:
            Processing result dict
        """
        # Check cache first
        request_hash = self._get_request_hash(
            sample.content, compression_ratio, similarity,
            analysis_mode, force_detail_count, force_single_segment, filters
        )
        
        if use_cache:
            cached = self._check_cache(sample.id, request_hash)
            if cached:
                print(f"✅ Using cached result for sample {sample.id}")
                return {
                    'success': True,
                    'sample_id': sample.id,
                    'compression_ratio': cached['compression_ratio'],
                    'processing_time': cached['processing_time'],
                    'cached': True,
                    'response': cached['response_data']
                }
        
        # Start async analysis
        start_time = time.time()
        async_result = self.analyze_async(
            sample, compression_ratio, similarity, timeout,
            analysis_mode, force_detail_count, force_single_segment,
            include_embeddings, filters
        )
        
        if not async_result['success']:
            return {
                'success': False,
                'sample_id': sample.id,
                'error': async_result.get('error', 'Failed to start async analysis')
            }
        
        task_id = async_result['task_id']
        print(f"⏳ Started async analysis for sample {sample.id} (task: {task_id})")
        
        # Poll for completion
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed = time.time() - start_time
            
            status_result = self.check_async_status(task_id)
            
            if not status_result['success']:
                return {
                    'success': False,
                    'sample_id': sample.id,
                    'error': status_result.get('error', 'Failed to check status')
                }
            
            status = status_result['status']
            progress = status_result.get('progress', 0)
            
            print(f"⏳ Sample {sample.id}: {status} ({progress:.0%} complete)")
            
            if status == 'completed':
                result = status_result['result']
                processing_time = time.time() - start_time
                
                # Extract compression ratio
                if 'response' in result and 'segments' in result['response']:
                    segments = result['response']['segments']
                    segment_ratios = [s.get('compression_ratio', 0) for s in segments]
                    actual_ratio = sum(segment_ratios) / len(segment_ratios) if segment_ratios else 0.0
                else:
                    actual_ratio = 0.0
                
                # Save to cache
                self._save_response(sample.id, request_hash, result, actual_ratio, processing_time)
                
                print(f"✅ Completed async processing for sample {sample.id}")
                
                return {
                    'success': True,
                    'sample_id': sample.id,
                    'compression_ratio': actual_ratio,
                    'processing_time': processing_time,
                    'cached': False,
                    'response': result
                }
            
            elif status == 'failed':
                return {
                    'success': False,
                    'sample_id': sample.id,
                    'error': status_result.get('error', 'Processing failed')
                }
        
        # Timeout
        return {
            'success': False,
            'sample_id': sample.id,
            'error': f'Async processing timed out after {max_wait}s'
        }
    
    def get_suggested_text(self, sample_id: int) -> Optional[str]:
        """
        Retrieve the suggested text for a sample.
        
        The suggested text is the API's recommendation of what to actually use,
        based on quality thresholds. It uses hyperstrings only if they meet
        compression and similarity criteria, otherwise returns original text.
        
        Args:
            sample_id: ID of the sample to get suggested text for
            
        Returns:
            Suggested text string if found, None otherwise
            
        Example:
            suggested = processor.get_suggested_text(42)
            if suggested:
                print(f"Suggested: {suggested}")
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                # Navigate the response structure to get suggested text
                try:
                    # V2 API structure
                    suggested_text = response['response']['texts']['suggested']
                    return suggested_text
                except KeyError:
                    print(f"Warning: Could not find suggested text in response for sample {sample_id}")
                    return None
            return None
    
    def get_compressed_text(self, sample_id: int) -> Optional[str]:
        """
        Retrieve the compressed text (all hyperstrings) for a sample.
        
        The compressed text contains ALL segments as hyperstrings (if compressed)
        or original text (if not compressed). This shows everything the system
        attempted, regardless of quality thresholds.
        
        Args:
            sample_id: ID of the sample to get compressed text for
            
        Returns:
            Compressed text string if found, None otherwise
            
        Example:
            compressed = processor.get_compressed_text(42)
            if compressed:
                print(f"Compressed: {compressed}")
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                # Navigate the response structure to get compressed text
                try:
                    # V2 API structure
                    compressed_text = response['response']['texts']['compressed']
                    return compressed_text
                except KeyError:
                    print(f"Warning: Could not find compressed text in response for sample {sample_id}")
                    return None
            return None
    
    def get_hypernym_string(self, sample_id: int) -> Optional[str]:
        """
        Extract the full hypernym representation from ALL segments.
        
        For long documents, Hypernym breaks text into multiple semantic segments.
        Each segment has its own semantic_category and covariant_details that
        together form a hierarchical representation of meaning.
        
        Each segment also includes a semantic_similarity score showing how well
        the hypernym preserves that segment's meaning (0.0 to 1.0).
        
        Args:
            sample_id: ID of the sample to get hypernym string for
            
        Returns:
            Structured hypernym representation with similarity scores
            
        Example:
            hypernym = processor.get_hypernym_string(42)
            # For multi-segment document returns structured format:
            # "[SEGMENT 1 | similarity: 0.82] INTRO: detail1; detail2; detail3
            #  [SEGMENT 2 | similarity: 0.79] MAIN_ARGUMENT: detail4; detail5  
            #  [SEGMENT 3 | similarity: 0.85] CONCLUSION: detail6; detail7"
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                try:
                    # V2 API structure
                    segments = response['response']['segments']
                    
                    if not segments:
                        return None
                    
                    # Build structured representation preserving segment boundaries
                    hypernym_parts = []
                    
                    for idx, segment in enumerate(segments):
                        # Skip excluded segments
                        if segment.get('excluded_by_filter', False):
                            continue
                            
                        # Extract semantic category (the hypernym)
                        semantic_category = segment.get('semantic_category', 'UNKNOWN_CATEGORY')
                        
                        # Extract semantic similarity score
                        semantic_similarity = segment.get('semantic_similarity', 0)
                        
                        # Get the compressed hyperstring from the API response
                        compressed = response['response']['texts'].get('compressed', '')
                        
                        # Build segment representation with index marker and similarity score
                        segment_repr = f"[SEGMENT {idx+1} | similarity: {semantic_similarity:.2f}] {compressed}"
                            
                        hypernym_parts.append(segment_repr)
                    
                    # Join with newlines to preserve structure
                    return "\n".join(hypernym_parts)
                        
                except (KeyError, IndexError) as e:
                    print(f"Warning: Could not extract hypernym from response for sample {sample_id}: {e}")
                    return None
            return None
    
    def get_segment_details(self, sample_id: int) -> Optional[List[Dict[str, Any]]]:
        """
        Get detailed information about all segments for a sample.
        
        This is useful for understanding how Hypernym chunked the text and
        what compression was achieved per segment.
        
        Args:
            sample_id: ID of the sample
            
        Returns:
            List of segment details, each containing:
                {
                    'index': 0,
                    'semantic_category': 'INTRO',
                    'compression_ratio': 0.4,
                    'detail_count': 4,
                    'covariant_details': [...]
                }
                
        Example:
            segments = processor.get_segment_details(42)
            print(f"Document has {len(segments)} segments")
            for seg in segments:
                print(f"Segment {seg['index']}: {seg['semantic_category']} "
                      f"({seg['detail_count']} details, {seg['compression_ratio']:.1%} compression)")
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                try:
                    # V2 API structure
                    segments = response['response']['segments']
                    
                    if not segments:
                        return None
                    
                    segment_details = []
                    for idx, segment in enumerate(segments):
                        details = {
                            'index': idx,
                            'semantic_category': segment.get('semantic_category', 'UNKNOWN'),
                            'compression_ratio': segment.get('compression_ratio', 0),
                            'semantic_similarity': segment.get('semantic_similarity', 0),
                            'covariant_details': segment.get('covariant_details', []),
                            'detail_count': len(segment.get('covariant_details', [])),
                            # New v2 fields:
                            'covariant_elements': segment.get('covariant_elements', []),
                            'excluded_by_filter': segment.get('excluded_by_filter', False),
                            'exclusion_reason': segment.get('exclusion_reason'),
                            'was_compressed': segment.get('was_compressed', True),
                            'trial_count': len(segment.get('trials', [])) if 'trials' in segment else 0
                        }
                        segment_details.append(details)
                    
                    return segment_details
                    
                except (KeyError, IndexError) as e:
                    print(f"Warning: Could not extract segment details for sample {sample_id}: {e}")
                    return None
            return None
    
    def get_average_semantic_similarity(self, sample_id: int) -> Optional[float]:
        """
        Get the average semantic similarity across all segments.
        
        This tells you how well the hypernym representation preserves meaning.
        The API ensures each segment meets the minimum threshold, but the actual
        similarity is often higher.
        
        Args:
            sample_id: ID of the sample
            
        Returns:
            Average semantic similarity (0.0 to 1.0), None if not found
            
        Example:
            similarity = processor.get_average_semantic_similarity(42)
            print(f"Hypernym preserves {similarity:.1%} of original meaning")
        """
        segments = self.get_segment_details(sample_id)
        if not segments:
            return None
            
        similarities = [seg['semantic_similarity'] for seg in segments]
        return sum(similarities) / len(similarities) if similarities else 0.0
    
    def get_compression_comparison(self, sample_id: int) -> Dict[str, Any]:
        """
        Get original and compressed text with statistics.
        
        Args:
            sample_id: ID of the sample to compare
            
        Returns:
            Dict with comparison data:
                {
                    'original': str,
                    'compressed': str,
                    'original_length': int,
                    'compressed_length': int,
                    'reduction_percent': float,
                    'compression_ratio': float
                }
                
        Example:
            comparison = processor.get_compression_comparison(1)
            print(f"Original: {comparison['original'][:100]}...")
            print(f"Compressed: {comparison['compressed'][:100]}...")
            print(f"Reduced by {comparison['reduction_percent']:.1f}%")
        """
        # Get original text
        samples = self.get_samples_by_ids([sample_id])
        if not samples:
            return None
            
        original = samples[0].content
        
        # Get compressed text
        compressed = self.get_compressed_text(sample_id)
        if not compressed:
            return None
            
        # Get compression ratio from database
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT compression_ratio 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            row = cursor.fetchone()
            compression_ratio = row[0] if row else None
        
        return {
            'original': original,
            'compressed': compressed,
            'original_length': len(original),
            'compressed_length': len(compressed),
            'reduction_percent': (1 - len(compressed) / len(original)) * 100,
            'compression_ratio': compression_ratio
        }
    
    def generate_report(self, results: List[Dict[str, Any]], output_path: str = None) -> str:
        """
        Generate a summary report of processing results
        
        Args:
            results: List of processing results
            output_path: Optional path to save report
            
        Returns:
            Report content as string
        """
        successful = [r for r in results if r['success']]
        failed = [r for r in results if not r['success']]
        cached = [r for r in successful if r.get('cached', False)]
        
        avg_compression = sum(r['compression_ratio'] for r in successful) / len(successful) if successful else 0
        avg_time = sum(r['processing_time'] for r in successful if not r.get('cached', False)) / (len(successful) - len(cached)) if (len(successful) - len(cached)) > 0 else 0
        
        report = f"""
Hypernym Processing Report
==========================
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Database: {self.db_path}

Summary
-------
Total samples: {len(results)}
Successful: {len(successful)}
Failed: {len(failed)}
Cached: {len(cached)}

Performance
-----------
Average compression ratio: {avg_compression:.2%}
Average processing time: {avg_time:.2f}s (excluding cached)

Failed Samples
--------------
"""
        for r in failed:
            report += f"- Sample {r['sample_id']}: {r.get('error', 'Unknown error')}\n"
        
        if output_path:
            with open(output_path, 'w') as f:
                f.write(report)
            print(f"\n📄 Report saved to: {output_path}")
        
        return report
    
    def get_embeddings(self, sample_id: int) -> Optional[Dict[str, Any]]:
        """
        Extract embedding vectors from segments (Northstar tier only).
        
        Args:
            sample_id: ID of the sample
            
        Returns:
            Dict with embeddings for each segment, or None if not available
            
        Example:
            embeddings = processor.get_embeddings(42)
            if embeddings:
                for seg_idx, data in embeddings.items():
                    print(f"Segment {seg_idx}: {data['dimensions']}D vector")
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                try:
                    # V2 API structure
                    segments = response['response']['segments']
                    
                    embeddings = {}
                    
                    for idx, segment in enumerate(segments):
                        segment_embeddings = {}
                        
                        # Check for original text embedding
                        if 'original' in segment and 'embedding' in segment['original']:
                            segment_embeddings['original'] = {
                                'dimensions': segment['original']['embedding'].get('dimensions', 768),
                                'values': segment['original']['embedding'].get('values', [])
                            }
                        
                        # Check for reconstructed text embedding
                        if 'reconstructed' in segment and 'embedding' in segment.get('reconstructed', {}):
                            segment_embeddings['reconstructed'] = {
                                'dimensions': segment['reconstructed']['embedding'].get('dimensions', 768),
                                'values': segment['reconstructed']['embedding'].get('values', [])
                            }
                        
                        if segment_embeddings:
                            embeddings[idx] = segment_embeddings
                    
                    return embeddings if embeddings else None
                    
                except (KeyError, IndexError) as e:
                    print(f"Warning: Could not extract embeddings for sample {sample_id}: {e}")
                    return None
            return None
    
    def get_trial_statistics(self, sample_id: int) -> Optional[Dict[str, Any]]:
        """
        Extract trial statistics from comprehensive mode analysis (Northstar only).
        
        Args:
            sample_id: ID of the sample
            
        Returns:
            Dict with trial statistics for each segment, or None if not available
            
        Example:
            stats = processor.get_trial_statistics(42)
            if stats:
                for seg_idx, data in stats.items():
                    print(f"Segment {seg_idx}: {data['trial_count']} trials")
                    print(f"  Avg similarity: {data['avg_similarity']:.2%}")
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                try:
                    # V2 API structure
                    segments = response['response']['segments']
                    
                    trial_stats = {}
                    
                    for idx, segment in enumerate(segments):
                        if 'trials' in segment and segment['trials']:
                            trials = segment['trials']
                            
                            # Calculate statistics across trials
                            similarities = [t.get('avg_similarity', 0) for t in trials]
                            ratios = [t.get('compression_ratio', 0) for t in trials]
                            categories = [t.get('semantic_category', '') for t in trials]
                            
                            # Find most common category
                            from collections import Counter
                            category_counts = Counter(categories)
                            most_common_category = category_counts.most_common(1)[0][0] if category_counts else ''
                            
                            trial_stats[idx] = {
                                'trial_count': len(trials),
                                'avg_similarity': sum(similarities) / len(similarities) if similarities else 0,
                                'avg_compression_ratio': sum(ratios) / len(ratios) if ratios else 0,
                                'similarity_std': self._calculate_std(similarities),
                                'unique_categories': len(set(categories)),
                                'most_common_category': most_common_category,
                                'category_consensus': category_counts[most_common_category] / len(trials) if trials else 0
                            }
                    
                    return trial_stats if trial_stats else None
                    
                except (KeyError, IndexError) as e:
                    print(f"Warning: Could not extract trial statistics for sample {sample_id}: {e}")
                    return None
            return None
    
    def _calculate_std(self, values: List[float]) -> float:
        """Calculate standard deviation"""
        if not values or len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def check_tier_access(self) -> str:
        """
        Check API tier access level (Standard or Northstar).
        
        Returns:
            'northstar' or 'standard'
        """
        if self._tier_access is not None:
            return self._tier_access
            
        # TODO: Implement actual tier detection via API
        # For now, try a Northstar-only feature and see if it works
        # Future implementation:
        # - Try comprehensive mode with minimal input
        # - Check response for tier-specific error
        # - Cache result
        
        # Default to Northstar as requested
        self._tier_access = 'northstar'
        return self._tier_access
    
    def has_northstar_access(self) -> bool:
        """Check if user has Northstar tier access."""
        return self.check_tier_access() == 'northstar'
    
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of all errors in the database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Total errors
            cursor.execute("SELECT COUNT(*) FROM error_entries")
            total_errors = cursor.fetchone()[0]
            
            # Errors by type
            cursor.execute("""
                SELECT error_type, COUNT(*) as count 
                FROM error_entries 
                GROUP BY error_type 
                ORDER BY count DESC
            """)
            errors_by_type = dict(cursor.fetchall())
            
            # Recent errors
            cursor.execute("""
                SELECT sample_id, error_type, error_message, content_length, 
                       datetime(created_at, 'localtime') as error_time
                FROM error_entries 
                ORDER BY id DESC 
                LIMIT 10
            """)
            recent_errors = [dict(zip([col[0] for col in cursor.description], row)) 
                           for row in cursor.fetchall()]
            
            # Large content failures
            cursor.execute("""
                SELECT COUNT(*) 
                FROM error_entries 
                WHERE content_length > 10000
            """)
            large_content_failures = cursor.fetchone()[0]
            
            return {
                'total_errors': total_errors,
                'errors_by_type': errors_by_type,
                'recent_errors': recent_errors,
                'large_content_failures': large_content_failures
            }
    
    def get_sample_errors(self, sample_id: int) -> List[Dict[str, Any]]:
        """Get all errors for a specific sample"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT error_type, error_message, status_code, attempt_number,
                       content_length, datetime(created_at, 'localtime') as error_time
                FROM error_entries
                WHERE sample_id = ?
                ORDER BY id DESC
            """, (sample_id,))
            
            return [dict(zip([col[0] for col in cursor.description], row)) 
                   for row in cursor.fetchall()]
    
    def get_filtered_segments(self, sample_id: int) -> Optional[List[Dict[str, Any]]]:
        """
        Get segments that were excluded by filters.
        
        Args:
            sample_id: ID of the sample
            
        Returns:
            List of excluded segments with exclusion reasons
            
        Example:
            excluded = processor.get_filtered_segments(42)
            if excluded:
                for seg in excluded:
                    print(f"Excluded: {seg['semantic_category']}")
                    print(f"Reason: {seg['exclusion_reason']}")
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT response_data 
                FROM hypernym_responses 
                WHERE sample_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (sample_id,))
            
            row = cursor.fetchone()
            if row:
                response = json.loads(row[0])
                try:
                    # V2 API structure
                    segments = response['response']['segments']
                    
                    filtered = []
                    
                    for idx, segment in enumerate(segments):
                        if segment.get('excluded_by_filter', False):
                            filtered.append({
                                'index': idx,
                                'semantic_category': segment.get('semantic_category', 'UNKNOWN'),
                                'exclusion_reason': segment.get('exclusion_reason', {}),
                                'compression_ratio': segment.get('compression_ratio', 0),
                                'semantic_similarity': segment.get('semantic_similarity', 0)
                            })
                    
                    return filtered if filtered else None
                    
                except (KeyError, IndexError) as e:
                    print(f"Warning: Could not extract filtered segments for sample {sample_id}: {e}")
                    return None
            return None

def main():
    """
    Command-line interface for the Hypernym processor.
    
    This script processes text samples from SQLite through Hypernym API.
    Exit codes:
        0 - All samples processed successfully
        1 - Some or all samples failed
        
    Environment variables used:
        HYPERNYM_API_KEY - Your API key (required)
        HYPERNYM_API_URL - API endpoint (required)
        
    Example usage:
        # Process specific samples
        python hypernym_processor.py --db-path data.sqlite --sample-ids 1,2,3
        
        # Process with custom query
        python hypernym_processor.py --db-path data.sqlite \
            --query "SELECT * FROM samples WHERE word_count > 100"
            
        # Process all samples
        python hypernym_processor.py --db-path data.sqlite --all
        
    The script will:
    1. Connect to your database
    2. Fetch samples based on your selection
    3. Process each through Hypernym API (with caching)
    4. Save results to hypernym_responses table
    5. Generate a summary report
    """
    parser = argparse.ArgumentParser(
        description="Portable Hypernym processor for SQLite databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process specific samples by ID
  %(prog)s --db-path data.sqlite --sample-ids 1,2,3,4,5

  # Process samples using custom query
  %(prog)s --db-path data.sqlite --query "SELECT * FROM samples WHERE category='literature' LIMIT 10"

  # Process all samples with limit
  %(prog)s --db-path data.sqlite --all --max-samples 100

  # Process with custom parameters
  %(prog)s --db-path data.sqlite --all --compression 0.7 --similarity 0.8 --batch-size 10

  # Use comprehensive mode with embeddings (Northstar only)
  %(prog)s --db-path data.sqlite --all --analysis-mode comprehensive --include-embeddings

  # Apply semantic filters to exclude content
  %(prog)s --db-path data.sqlite --all --filters '{"purpose": {"exclude": [{"semantic_category": "political", "min_semantic_similarity": 0.35}]}}'

  # Use async processing with polling
  %(prog)s --db-path data.sqlite --all --async-mode --poll-interval 10 --max-wait 1800
        """
    )
    
    # Database options
    parser.add_argument('--db-path', required=True, help='Path to SQLite database')
    parser.add_argument('--table', default='samples', help='Table name containing samples (default: samples)')
    
    # Sample selection (mutually exclusive)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--sample-ids', help='Comma-separated list of sample IDs')
    selection.add_argument('--book-id', type=int, help='Process all samples from a specific book ID')
    selection.add_argument('--query', help='Custom SQL query (must return id and content columns)')
    selection.add_argument('--all', action='store_true', help='Process all samples in table')
    
    # Processing parameters
    parser.add_argument('--compression', type=float, default=0.6, help='Target compression ratio (default: 0.6)')
    parser.add_argument('--similarity', type=float, default=0.75, help='Target semantic similarity (default: 0.75)')
    parser.add_argument('--batch-size', type=int, default=5, help='Samples per batch (default: 5)')
    parser.add_argument('--cooldown', type=float, default=0.5, help='Seconds between samples (default: 0.5)')
    parser.add_argument('--batch-cooldown', type=float, default=2.0, help='Seconds between batches (default: 2.0)')
    parser.add_argument('--timeout', type=int, default=30, help='API timeout in seconds (default: 30)')
    parser.add_argument('--max-retries', type=int, default=3, help='Max retry attempts (default: 3)')
    parser.add_argument('--max-samples', type=int, help='Maximum samples to process')
    
    # V2 API parameters
    parser.add_argument('--analysis-mode', choices=['partial', 'comprehensive'], default='partial',
                       help='Analysis mode: partial (fast) or comprehensive (60 trials, Northstar only)')
    parser.add_argument('--force-detail-count', type=int, help='Force specific number of details (3-9 standard, unlimited Northstar)')
    parser.add_argument('--no-single-segment', action='store_true', help='Process paragraphs separately instead of as single segment')
    parser.add_argument('--include-embeddings', action='store_true', help='Include 768D embedding vectors (Northstar only)')
    parser.add_argument('--filters', type=str, help='JSON string with semantic filters to exclude content')
    
    # Async processing
    parser.add_argument('--async-mode', dest='async_mode', action='store_true', help='Use async API endpoints with polling')
    parser.add_argument('--poll-interval', type=float, default=5.0, help='Seconds between async status checks (default: 5.0)')
    parser.add_argument('--max-wait', type=float, default=1200.0, help='Maximum seconds to wait for async completion (default: 1200)')
    
    # Parallel processing
    parser.add_argument('--max-workers', type=int, default=4, help='Maximum concurrent workers (default: 4)')
    parser.add_argument('--max-display-workers', type=int, default=20, help='Maximum workers to display in UI (default: 20)')
    
    # Options
    parser.add_argument('--no-cache', action='store_true', help='Disable cache lookup')
    parser.add_argument('--report', help='Save processing report to file')
    parser.add_argument('--api-key', help='Hypernym API key (overrides env var)')
    parser.add_argument('--api-url', help='Hypernym API URL (overrides env var)')
    
    args = parser.parse_args()
    
    try:
        # Initialize processor
        processor = HypernymProcessor(
            db_path=args.db_path,
            api_key=args.api_key,
            api_url=args.api_url
        )
        
        # Get samples based on selection method
        if args.sample_ids:
            sample_ids = [int(sid.strip()) for sid in args.sample_ids.split(',')]
            samples = processor.get_samples_by_ids(sample_ids, args.table)
        elif args.book_id:
            # Build query to get all samples from the specified book
            book_query = f"SELECT * FROM {args.table} WHERE book_id = {args.book_id} ORDER BY id"
            samples = processor.get_samples_by_query(book_query)
        elif args.query:
            samples = processor.get_samples_by_query(args.query)
        else:  # --all
            samples = processor.get_all_samples(args.table, args.max_samples)
        
        if not samples:
            print("❌ No samples found")
            return 1
        
        print(f"\n📊 Found {len(samples)} samples to process")
        
        # Apply max samples limit if specified
        if args.max_samples and len(samples) > args.max_samples:
            samples = samples[:args.max_samples]
            print(f"📊 Limited to {len(samples)} samples")
        
        # Parse filters if provided
        filters = None
        if args.filters:
            try:
                filters = json.loads(args.filters)
            except json.JSONDecodeError:
                print(f"❌ Invalid JSON for filters: {args.filters}")
                return 1
        
        # Process samples - ALWAYS use parallel processing
        print("\n" * 2)  # Clear some space for the display
        
        # Run the async parallel processor
        results = asyncio.run(
            processor.process_batch_parallel(
                samples,
                compression_ratio=args.compression,
                similarity=args.similarity,
                batch_size=args.batch_size,
                cooldown=args.cooldown,
                batch_cooldown=args.batch_cooldown,
                timeout=args.timeout,
                max_retries=args.max_retries,
                use_cache=not args.no_cache,
                max_workers=args.max_workers,
                analysis_mode=args.analysis_mode,
                force_detail_count=args.force_detail_count,
                force_single_segment=not args.no_single_segment,
                include_embeddings=args.include_embeddings,
                filters=filters,
                max_display_workers=args.max_display_workers
            )
        )
        
        # Generate report
        print("\n" + "="*60)
        report = processor.generate_report(results, args.report)
        print(report)
        
        # Exit with error if any failures
        failed_count = sum(1 for r in results if not r['success'])
        return 1 if failed_count > 0 else 0
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())