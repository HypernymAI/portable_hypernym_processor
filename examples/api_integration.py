#!/usr/bin/env python3
"""
Example showing how to use the Hypernym processor with v2 API features
"""

import os
import sys
import json
import sqlite3

# Add parent directory to path so we can import hypernym_processor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hypernym_processor import HypernymProcessor, Sample

# Use the test API key from the reference scripts
os.environ["HYPERNYM_API_KEY"] = "j38f74hf83h4f834"  # Standard tier key
os.environ["HYPERNYM_API_URL"] = "https://fc-api-development.hypernym.ai/analyze_sync"

def basic_usage_example():
    """Show basic usage with v2 defaults"""
    
    print("=== Basic Usage Example ===\n")
    
    # Initialize processor (creates database if it doesn't exist)
    processor = HypernymProcessor("example.db")
    
    # Add some text to process - using the standard test content
    sample_text = """Quantum computing represents a paradigm shift in computational capabilities. Unlike classical computers that use bits representing either 0 or 1, quantum computers utilize qubits that can exist in superposition states. This fundamental difference enables quantum computers to process vast amounts of information simultaneously.

The implications for cryptography are profound. Current encryption methods rely on the computational difficulty of factoring large prime numbers. Quantum computers could break these encryptions in minutes rather than millennia. This has led to the development of quantum-resistant cryptographic algorithms.

In drug discovery, quantum simulations can model molecular interactions at unprecedented scales. Pharmaceutical companies are investing billions in quantum research to accelerate drug development. The ability to simulate protein folding could revolutionize treatment for diseases like Alzheimer's and cancer.

Financial modeling presents another frontier. Portfolio optimization, risk analysis, and derivative pricing could benefit from quantum speedups. Major banks are establishing quantum computing divisions to maintain competitive advantages in high-frequency trading and risk management.

However, significant challenges remain. Quantum decoherence limits computation time, requiring extreme cooling to near absolute zero. Error rates are still too high for practical applications. The engineering challenges of scaling from dozens to millions of qubits remain formidable."""
    
    # Insert into samples table
    with sqlite3.connect("example.db") as conn:
        cursor = conn.execute(
            "INSERT INTO samples (content) VALUES (?)",
            (sample_text.strip(),)
        )
        sample_id = cursor.lastrowid
    
    print(f"Created sample with ID: {sample_id}")
    
    # Process with default parameters
    # Note: force_single_segment=True by default now
    sample = Sample(id=sample_id, content=sample_text.strip())
    result = processor.process_sample(sample)
    
    if result["success"]:
        print(f"✓ Processing successful!\n")
        
        # Get the compressed text
        compressed = processor.get_compressed_text(sample_id)
        print(f"Compressed text:\n{compressed}\n")
        
        # Get the hypernym representation
        hypernym = processor.get_hypernym_string(sample_id)
        print(f"Hypernym structure:\n{hypernym}\n")
        
        # Get average similarity
        avg_sim = processor.get_average_semantic_similarity(sample_id)
        print(f"Average semantic similarity: {avg_sim:.2%}")
    else:
        print(f"✗ Processing failed: {result.get('error', 'Unknown error')}")
    
    # Cleanup
    os.remove("example.db")


def advanced_v2_features():
    """Demonstrate v2 API features"""
    
    print("\n=== Advanced v2 Features ===\n")
    
    processor = HypernymProcessor("example_v2.db")
    
    # Example: Financial Theory text - the standard test case for comprehensive mode
    financial_text = """Modern Financial Theory and Markets represent a complex intersection of mathematical models, behavioral economics, and technological innovation. The evolution of financial markets from simple exchange mechanisms to today's sophisticated electronic trading platforms demonstrates the field's remarkable transformation.

This comprehensive framework encompasses everything from fundamental concepts like the Time Value of Money and Modern Portfolio Theory to cutting-edge developments in quantitative trading and decentralized finance (DeFi).

The foundation of modern finance was laid in the mid-20th century with the development of key theories that continue to influence market behavior and investment strategies."""
    
    with sqlite3.connect("example_v2.db") as conn:
        cursor = conn.execute(
            "INSERT INTO samples (content) VALUES (?)",
            (financial_text.strip(),)
        )
        sample_id = cursor.lastrowid
    
    # Example 1: Force multiple segments for better granularity
    print("1. Processing with automatic segmentation:")
    sample = Sample(id=sample_id, content=financial_text.strip())
    result = processor.process_sample(
        sample,
        force_single_segment=False,  # Let API decide segmentation
        compression_ratio=0.5,       # More aggressive compression
        similarity=0.8               # Higher similarity requirement
    )
    
    if result["success"]:
        segments = processor.get_segment_details(sample_id)
        print(f"   Created {len(segments)} segments")
        for i, seg in enumerate(segments):
            print(f"   Segment {i+1}: {seg['semantic_category']}")
    
    # Example 2: Request specific number of details (Standard tier: 3-9)
    print("\n2. Processing with specific detail count:")
    result = processor.process_sample(
        sample,
        force_detail_count=6,  # Request exactly 6 covariant details
        use_cache=False        # Force new processing
    )
    
    if result["success"]:
        segments = processor.get_segment_details(sample_id)
        for seg in segments:
            print(f"   Details count: {seg['detail_count']}")
    
    # Example 3: Using filters (if available)
    print("\n3. Processing with content filters:")
    result = processor.process_sample(
        sample,
        filters={
            "exclude_categories": ["technical_jargon", "statistics"]
        },
        use_cache=False
    )
    
    if result["success"]:
        filtered = processor.get_filtered_segments(sample_id)
        if filtered:
            print(f"   Filtered out {len(filtered)} segments")
        else:
            print("   No segments were filtered")
    
    # Cleanup
    os.remove("example_v2.db")


def integration_with_existing_database():
    """Show how to integrate with an existing database"""
    
    print("\n=== Integration with Existing Database ===\n")
    
    # Simulate an existing database with different schema
    existing_db = "existing_data.db"
    with sqlite3.connect(existing_db) as conn:
        # Create a table with different column names
        conn.execute("""
            CREATE TABLE documents (
                doc_id INTEGER PRIMARY KEY,
                full_text TEXT,
                title TEXT,
                author TEXT,
                date_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert sample data
        conn.execute("""
            INSERT INTO documents (full_text, title, author) 
            VALUES (?, ?, ?)
        """, (
            "Machine learning has transformed how we process information...",
            "Introduction to ML",
            "Dr. Smith"
        ))
    
    # Process using custom query to map columns
    processor = HypernymProcessor(existing_db)
    
    # First, get samples using custom query to map your schema
    samples = processor.get_samples_by_query("""
        SELECT doc_id as id, full_text as content 
        FROM documents 
        WHERE full_text IS NOT NULL
    """)
    
    print(f"Found {len(samples)} documents to process")
    
    # Then process them in batches
    results = processor.process_batch(
        samples,
        batch_size=10
    )
    
    # Count results
    successful = sum(1 for r in results if r['success'])
    failed = sum(1 for r in results if not r['success'])
    cached = sum(1 for r in results if r.get('cached', False))
    
    print(f"Processed {successful} documents successfully")
    print(f"Failed: {failed}")
    print(f"Used cache: {cached}")
    
    # Results are stored in hypernym_responses table
    # Original documents table is untouched
    
    # Cleanup
    os.remove(existing_db)


def show_available_parameters():
    """List all available v2 parameters"""
    
    print("\n=== Available v2 Parameters ===\n")
    
    print("Standard Parameters:")
    print("  - compression_ratio: Target compression (0.0-1.0)")
    print("  - similarity: Minimum semantic similarity (0.0-1.0)")
    print("")
    
    print("V2 Parameters (all tiers):")
    print("  - force_single_segment: Process as one segment (default: True)")
    print("  - force_detail_count: Exact number of details (3-9 for Standard)")
    print("  - filters: Content filtering rules")
    print("")
    
    print("Northstar-only Parameters:")
    print("  - analysis_mode: 'comprehensive' for 60-trial analysis")
    print("  - include_embeddings: Get 768D vectors")
    print("  - timeout: Up to 1200 seconds")
    print("  - force_detail_count: Unlimited details")
    print("")
    
    print("For custom chunking strategies, contact: hi@hypernym.ai")


if __name__ == "__main__":
    # Run examples
    basic_usage_example()
    advanced_v2_features()
    integration_with_existing_database()
    show_available_parameters()
    
    print("\n=== Summary ===")
    print("The processor now supports all v2 API features!")
    print("By default, it processes entire documents as single segments.")
    print("For optimal chunking strategies for your use case, contact: hi@hypernym.ai")