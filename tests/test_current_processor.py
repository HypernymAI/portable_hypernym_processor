#!/usr/bin/env python3
"""
Test the current hypernym_processor.py with real API responses
"""

import json
import os
from hypernym_processor import HypernymProcessor

# Set up test environment
os.environ["HYPERNYM_API_KEY"] = "test_key"
os.environ["HYPERNYM_API_URL"] = "https://fc-api-development.hypernym.ai/analyze_sync"

# Create test database
test_db = "test_processor.db"
if os.path.exists(test_db):
    os.remove(test_db)

try:
    # Initialize processor
    print("1. Testing processor initialization...")
    processor = HypernymProcessor(test_db)
    print("✓ Processor initialized successfully")
    
    # Check if tables were created
    import sqlite3
    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"✓ Tables created: {tables}")
        
        # Check samples table schema
        cursor = conn.execute("PRAGMA table_info(samples)")
        columns = [(row[1], row[2]) for row in cursor]
        print(f"✓ Samples table columns: {columns}")
    
    # Test inserting a sample
    print("\n2. Testing sample insertion...")
    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute("INSERT INTO samples (content) VALUES (?)", 
                    ("Test content for processing",))
        sample_id = cursor.lastrowid
    print(f"✓ Sample inserted with ID: {sample_id}")
    
    # Test getting samples
    print("\n3. Testing sample retrieval...")
    samples = processor.get_samples_by_ids([sample_id])
    print(f"✓ Retrieved {len(samples)} samples")
    
    # Show what the processor expects vs what the API returns
    print("\n4. API Response Structure Analysis...")
    
    # This is what the processor expects (old format)
    expected_format = {
        "results": {
            "response": {
                "segments": [{
                    "semantic_category": "Category",
                    "covariant_details": [
                        {"n": 0, "text": "Detail 1"}
                    ],
                    "semantic_similarity": 0.8,
                    "compression_ratio": 0.5
                }]
            },
            "texts": {
                "suggested": "Compressed text"
            }
        }
    }
    
    # This is what the API actually returns (from the curl test)
    actual_format = {
        "results": {
            "metadata": {
                "version": "0.2.0",
                "tokens": {"in": 105, "out": 93, "total": 198}
            },
            "response": {
                "segments": [{
                    "semantic_category": "Financial markets and theory evolution.",
                    "covariant_elements": [  # NEW: Not handled by processor
                        {"1": "financial markets"}
                    ],
                    "covariant_details": [
                        {"n": 0, "text": "{'1': 'complex systems for trading assets'}"}
                    ],
                    "trials": [  # NEW: Comprehensive mode trials
                        # 60 trial results...
                    ],
                    "excluded_by_filter": False,  # NEW: Filtering
                    "original": {  # NEW: Different structure
                        "text": "Original text"
                    },
                    "reconstructed": {  # NEW: Different from old format
                        "text": "Reconstructed text"
                    }
                }],
                "texts": {  # This moved location
                    "compressed": "...",
                    "suggested": "..."
                }
            }
        }
    }
    
    print("Expected format keys:", list(expected_format["results"].keys()))
    print("Actual format keys:", list(actual_format["results"]["response"].keys()))
    
    print("\n5. Issues found:")
    print("❌ Processor expects 'texts' at results level, but it's at results.response level")
    print("❌ Processor doesn't handle 'covariant_elements' (new field)")
    print("❌ Processor doesn't handle 'trials' array (comprehensive mode)")
    print("❌ Processor doesn't handle 'excluded_by_filter' (filtering feature)")
    print("❌ Processor expects different structure for original/reconstructed text")
    
    # Test what would break
    print("\n6. Testing processor methods with mock response...")
    
    # Store a mock response
    with sqlite3.connect(test_db) as conn:
        mock_response = json.dumps(actual_format)
        conn.execute("""
            INSERT INTO hypernym_responses 
            (sample_id, request_hash, response_data, compression_ratio, processing_time)
            VALUES (?, ?, ?, ?, ?)
        """, (sample_id, "test_hash", mock_response, 0.5, 1.0))
    
    # Try to get hypernym string
    print("\nTrying processor.get_hypernym_string()...")
    try:
        result = processor.get_hypernym_string(sample_id)
        print(f"✓ Got result: {result[:100]}..." if result else "✗ Got None")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    # Try to get compressed text
    print("\nTrying processor.get_compressed_text()...")
    try:
        # This will fail because it looks for results["texts"]["suggested"]
        # but in new format it's results["response"]["texts"]["suggested"]
        result = processor.get_compressed_text(sample_id)
        print(f"Result: {result}")
    except KeyError as e:
        print(f"✗ KeyError as expected: {e}")
        print("  The path results['texts'] doesn't exist in new response format")
    
finally:
    # Cleanup
    if os.path.exists(test_db):
        os.remove(test_db)
        print(f"\nCleaned up {test_db}")