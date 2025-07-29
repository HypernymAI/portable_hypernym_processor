#!/usr/bin/env python3
"""
Queue Worker - Connects ProcessingQueue to HypernymProcessor

This shows how the queue and processor work together:
1. Queue holds work items (SQL queries)
2. Worker pulls from queue
3. Processor does the Hypernym API calls
4. Results go back to queue
"""

import sys
import time
from processing_queue import ProcessingQueue
from hypernym_processor import HypernymProcessor

def run_worker(db_path: str, max_batches: int = None):
    """
    Worker that continuously processes batches from queue
    
    Args:
        db_path: Path to SQLite database
        max_batches: Stop after N batches (None = run forever)
    """
    queue = ProcessingQueue(db_path)
    processor = HypernymProcessor(db_path)
    
    batches_processed = 0
    
    while max_batches is None or batches_processed < max_batches:
        # Get next work item
        batch = queue.get_next_pending()
        
        if not batch:
            print("No pending batches, waiting...")
            time.sleep(5)
            continue
        
        print(f"\n{'='*60}")
        print(f"Processing batch {batch['id']}: {batch['name']}")
        print(f"Query: {batch['query'][:100]}...")
        
        try:
            # Execute the query to get samples
            samples = processor.get_samples_by_query(batch['query'])
            print(f"Found {len(samples)} samples to process")
            
            if not samples:
                queue.mark_complete(batch['id'], 0, 0)
                print("No samples found, marking complete")
                continue
            
            # Process through Hypernym API
            results = processor.process_batch(
                samples,
                batch_size=5,
                cooldown=0.5,
                batch_cooldown=2.0
            )
            
            # Count results
            success_count = sum(1 for r in results if r['success'])
            error_count = len(results) - success_count
            
            # Update queue
            queue.mark_complete(batch['id'], success_count, error_count)
            
            print(f"\n✓ Batch complete: {success_count} success, {error_count} errors")
            
            # Generate report for this batch
            report = processor.generate_report(results)
            print("\nBatch Report:")
            print(report)
            
        except Exception as e:
            print(f"\n✗ Batch failed: {e}")
            queue.mark_failed(batch['id'], str(e))
        
        batches_processed += 1
        print(f"{'='*60}\n")


def add_sample_batches(db_path: str):
    """Add some example batches to the queue"""
    queue = ProcessingQueue(db_path)
    
    # Add different types of work
    batches = [
        ("Literature samples", "SELECT * FROM samples WHERE category='literature' LIMIT 10"),
        ("Recent samples", "SELECT * FROM samples WHERE id > 100 ORDER BY id DESC LIMIT 5"),
        ("Unprocessed samples", """
            SELECT s.* FROM samples s 
            LEFT JOIN hypernym_responses h ON s.id = h.sample_id 
            WHERE h.id IS NULL 
            LIMIT 20
        """),
        ("Large samples", "SELECT * FROM samples WHERE word_count > 500 LIMIT 10"),
    ]
    
    for name, query in batches:
        batch_id = queue.add_batch(name, query)
        print(f"Added batch {batch_id}: {name}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python queue_worker.py run [db_path]      # Run worker")
        print("  python queue_worker.py add [db_path]      # Add sample batches")
        print("  python queue_worker.py status [db_path]   # Show queue status")
        sys.exit(1)
    
    command = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else 'test.sqlite'
    
    if command == 'run':
        print("Starting queue worker...")
        print(f"Database: {db_path}")
        print("Press Ctrl+C to stop\n")
        
        try:
            run_worker(db_path)
        except KeyboardInterrupt:
            print("\nWorker stopped")
    
    elif command == 'add':
        add_sample_batches(db_path)
        
    elif command == 'status':
        queue = ProcessingQueue(db_path)
        
        # Overall status
        status = queue.get_status()
        print("\nQueue Status:")
        for state, count in sorted(status.items()):
            print(f"  {state:12} {count:4}")
        
        # Recent batches
        print("\nRecent Batches:")
        for batch in queue.get_recent(10):
            status_icon = {
                'pending': '⏳',
                'processing': '🔄',
                'completed': '✓',
                'failed': '✗'
            }.get(batch['status'], '?')
            
            print(f"  {status_icon} [{batch['id']:3}] {batch['name'][:40]:40} {batch['status']}")
            if batch['processed_count'] or batch['error_count']:
                print(f"         Processed: {batch['processed_count']}, Errors: {batch['error_count']}")