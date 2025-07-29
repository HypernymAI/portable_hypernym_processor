#!/usr/bin/env python3
"""
Simple Processing Queue for Hypernym Processor

A minimal sequential read/write system that tracks what needs processing
and what's been done. No complex catalog - just a queue.

Usage:
    # Add work
    queue = ProcessingQueue('data.sqlite')
    queue.add_batch("literature_samples", "SELECT * FROM samples WHERE category='literature'")
    
    # Get next work
    batch = queue.get_next_pending()
    
    # Mark complete
    queue.mark_complete(batch['id'], processed_count=10)
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List

class ProcessingQueue:
    """
    A work queue for batch processing with SQLite.
    
    This queue enables multiple workers to process batches of samples without
    collision. Each batch is a SQL query that defines what samples to process.
    
    The queue tracks status progression:
        pending → processing → completed/failed
        
    This allows you to:
    - Add work items (SQL queries) to process later
    - Have multiple workers pull from the same queue
    - Resume processing after crashes
    - Track what's done and what's pending
    
    Table schema (created automatically):
        processing_queue:
            id              - Unique batch identifier
            name            - Human-readable batch name
            query           - SQL query to get samples
            status          - pending|processing|completed|failed
            created_at      - When batch was added
            started_at      - When processing began
            completed_at    - When processing finished
            processed_count - How many samples succeeded
            error_count     - How many samples failed
            metadata        - JSON field for extra data
            
    Example:
        queue = ProcessingQueue('data.sqlite')
        
        # Producer adds work
        queue.add_batch("Recent docs", "SELECT * FROM docs WHERE date > '2025-01-01'")
        
        # Worker processes it
        batch = queue.get_next_pending()  # Atomically claims work
        # ... do processing ...
        queue.mark_complete(batch['id'], processed_count=10)
    """
    
    def __init__(self, db_path: str):
        """
        Initialize queue and create table if needed.
        
        Args:
            db_path: Path to SQLite database (will be created if doesn't exist)
        """
        self.db_path = db_path
        self._init_table()
    
    def _init_table(self):
        """Create queue table if not exists"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processing_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    processed_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_status 
                ON processing_queue(status)
            """)
    
    def add_batch(self, name: str, query: str, metadata: Dict = None) -> int:
        """Add a batch to process"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO processing_queue (name, query, metadata)
                VALUES (?, ?, ?)
            """, (name, query, json.dumps(metadata or {})))
            return cursor.lastrowid
    
    def get_next_pending(self) -> Optional[Dict]:
        """
        Atomically claim the next pending batch for processing.
        
        This method finds the oldest pending batch and atomically updates its
        status to 'processing' in a single transaction. This prevents multiple
        workers from claiming the same batch (no race conditions).
        
        The batch is marked with started_at timestamp when claimed.
        
        Returns:
            Dict with batch data if found:
                {
                    'id': 123,                    # Batch ID
                    'name': 'Literature samples', # Batch name
                    'query': 'SELECT * FROM...',  # SQL to get samples
                    'status': 'processing',       # Now processing
                    'created_at': '2025-01-01...', # When added
                    'started_at': '2025-01-01...', # Just now
                    'processed_count': 0,         # Not done yet
                    'error_count': 0,            # No errors yet
                    'metadata': '{}'             # Any extra data
                }
            
            None if no pending batches available
            
        Example:
            # Worker loop
            while True:
                batch = queue.get_next_pending()
                if not batch:
                    time.sleep(5)  # No work available
                    continue
                    
                # Process the batch
                samples = db.execute(batch['query'])
                # ... process samples ...
                
        Side effects:
            Updates the claimed batch's status to 'processing' and sets started_at
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # Get and lock next pending atomically using RETURNING clause
            cursor = conn.execute("""
                UPDATE processing_queue
                SET status = 'processing', started_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM processing_queue 
                    WHERE status = 'pending' 
                    ORDER BY created_at 
                    LIMIT 1
                )
                RETURNING *
            """)
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def mark_complete(self, batch_id: int, processed_count: int = 0, error_count: int = 0):
        """Mark batch as complete"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE processing_queue
                SET status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    processed_count = ?,
                    error_count = ?
                WHERE id = ?
            """, (processed_count, error_count, batch_id))
    
    def mark_failed(self, batch_id: int, error: str):
        """Mark batch as failed"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE processing_queue
                SET status = 'failed',
                    completed_at = CURRENT_TIMESTAMP,
                    metadata = json_set(metadata, '$.error', ?)
                WHERE id = ?
            """, (error, batch_id))
    
    def get_status(self) -> Dict[str, int]:
        """Get queue status summary"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM processing_queue
                GROUP BY status
            """)
            return {row[0]: row[1] for row in cursor.fetchall()}
    
    def get_recent(self, limit: int = 10) -> List[Dict]:
        """Get recent batches"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM processing_queue
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]


# Example worker that uses the queue
def process_with_queue(db_path: str):
    """Example of reading from queue and writing results"""
    from hypernym_processor import HypernymProcessor
    
    queue = ProcessingQueue(db_path)
    processor = HypernymProcessor(db_path)
    
    # Get next batch
    batch = queue.get_next_pending()
    if not batch:
        print("No pending batches")
        return
    
    print(f"Processing batch: {batch['name']}")
    
    try:
        # Get samples using the query
        samples = processor.get_samples_by_query(batch['query'])
        
        # Process them
        results = processor.process_batch(samples)
        
        # Count successes/failures
        success_count = sum(1 for r in results if r['success'])
        error_count = len(results) - success_count
        
        # Mark complete
        queue.mark_complete(batch['id'], success_count, error_count)
        print(f"✓ Completed: {success_count} success, {error_count} errors")
        
    except Exception as e:
        queue.mark_failed(batch['id'], str(e))
        print(f"✗ Failed: {e}")


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Add batch:    python processing_queue.py add <name> <query>")
        print("  Process next: python processing_queue.py process")
        print("  Show status:  python processing_queue.py status")
        sys.exit(1)
    
    db_path = 'benchmark_data.sqlite'
    queue = ProcessingQueue(db_path)
    
    command = sys.argv[1]
    
    if command == 'add':
        name = sys.argv[2]
        query = sys.argv[3]
        batch_id = queue.add_batch(name, query)
        print(f"Added batch {batch_id}: {name}")
    
    elif command == 'process':
        process_with_queue(db_path)
    
    elif command == 'status':
        status = queue.get_status()
        print("\nQueue Status:")
        for state, count in status.items():
            print(f"  {state}: {count}")
        
        print("\nRecent batches:")
        for batch in queue.get_recent(5):
            print(f"  [{batch['id']}] {batch['name']} - {batch['status']}")
    
    else:
        print(f"Unknown command: {command}")