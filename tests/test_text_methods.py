#!/usr/bin/env python3
"""
Test the get_suggested_text() and get_compressed_text() methods
to ensure they return the correct fields from the API response.
"""

import os
import sys
import json
import sqlite3
import tempfile
from unittest.mock import patch, MagicMock

# Add parent directory to path so we can import hypernym_processor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hypernym_processor import HypernymProcessor, Sample


def create_mock_response():
    """Create a mock API response with both compressed and suggested text"""
    return {
        "results": {
            "response": {
                "texts": {
                    "compressed": "Evolution of financial trading systems.::0=evolved significantly;1=revolutionized securities;2=Harry Markowitz frameworks;3=algorithmic trading dominance",
                    "suggested": "Financial markets have evolved significantly over the past century. Electronic trading revolutionized securities. Modern portfolio theory by Harry Markowitz introduced mathematical frameworks. Algorithmic trading now dominates."
                },
                "segments": [{
                    "semantic_category": "Evolution of financial trading systems.",
                    "semantic_similarity": 0.83,
                    "compression_ratio": 0.77,
                    "was_compressed": True,
                    "covariant_details": [
                        {"n": 0, "text": "evolved significantly"},
                        {"n": 1, "text": "revolutionized securities"},
                        {"n": 2, "text": "Harry Markowitz frameworks"},
                        {"n": 3, "text": "algorithmic trading dominance"}
                    ]
                }]
            }
        }
    }


def test_text_methods():
    """Test that get_suggested_text and get_compressed_text return correct fields"""
    
    print("=== Testing Text Retrieval Methods ===\n")
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Initialize processor
        processor = HypernymProcessor(
            db_path=db_path,
            api_key="test_key",
            api_url="http://test.api"
        )
        
        # Insert test sample
        test_text = "Financial markets have evolved significantly..."
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO samples (content) VALUES (?)",
                (test_text,)
            )
            sample_id = cursor.lastrowid
        
        # Manually insert mock response
        mock_response = create_mock_response()
        request_hash = processor._get_request_hash(test_text, 0.6, 0.75)
        
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                INSERT INTO hypernym_responses 
                (sample_id, request_hash, response_data, compression_ratio, processing_time)
                VALUES (?, ?, ?, ?, ?)
            """, (sample_id, request_hash, json.dumps(mock_response), 0.77, 1.0))
        
        # Test get_suggested_text()
        print("1. Testing get_suggested_text()...")
        suggested = processor.get_suggested_text(sample_id)
        expected_suggested = mock_response["results"]["response"]["texts"]["suggested"]
        
        if suggested == expected_suggested:
            print(f"✓ PASS: Returns suggested text correctly")
            print(f"  Got: '{suggested[:50]}...'")
        else:
            print(f"✗ FAIL: Wrong text returned")
            print(f"  Expected: {expected_suggested}")
            print(f"  Got: {suggested}")
        
        # Test get_compressed_text()
        print("\n2. Testing get_compressed_text()...")
        compressed = processor.get_compressed_text(sample_id)
        expected_compressed = mock_response["results"]["response"]["texts"]["compressed"]
        
        if compressed == expected_compressed:
            print(f"✓ PASS: Returns compressed text correctly")
            print(f"  Got: '{compressed}'")
        else:
            print(f"✗ FAIL: Wrong text returned")
            print(f"  Expected: {expected_compressed}")
            print(f"  Got: {compressed}")
        
        # Test get_hypernym_string()
        print("\n3. Testing get_hypernym_string()...")
        hypernym = processor.get_hypernym_string(sample_id)
        print(f"  Hypernym format: {hypernym}")
        
        # Verify the format includes segment wrapper and compressed text
        if hypernym and "[SEGMENT 1" in hypernym and "::" in hypernym:
            print("✓ PASS: Hypernym string includes segment wrapper and proper format")
        else:
            print("✗ FAIL: Hypernym string format incorrect")
        
        # Show the difference
        print("\n4. Comparing outputs:")
        print(f"  Suggested (for actual use): '{suggested[:60]}...'")
        print(f"  Compressed (all hyperstrings): '{compressed[:60]}...'")
        print(f"  Hypernym (display format): '{hypernym[:60]}...'")
        
    finally:
        # Cleanup
        os.unlink(db_path)
    
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    test_text_methods()