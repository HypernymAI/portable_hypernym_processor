#!/usr/bin/env python3
"""
Examples for using the Hypernym Processor with V2 API features

This file demonstrates:
1. Semantic filtering to exclude content
2. Force detail count and other V2 parameters  
3. Short vs long content handling
4. Filter effectiveness analysis
5. Batch processing

For Northstar features (comprehensive mode, embeddings), see test_northstar_features.py
"""

import os
import json
from hypernym_processor import HypernymProcessor, Sample

# Load test content
with open('test_content.json', 'r') as f:
    TEST_CONTENT = json.load(f)['samples']

# Initialize processor with unique test database
import tempfile
import os

# Create unique test database for examples
test_db = os.path.join(tempfile.gettempdir(), f'hypernym_examples_{os.getpid()}.db')
processor = HypernymProcessor(test_db)

# Check Northstar tier access
HAS_NORTHSTAR_ACCESS = processor.has_northstar_access()
print(f"Tier access: {'Northstar' if HAS_NORTHSTAR_ACCESS else 'Standard'}")

# Example 1: Basic filtering to exclude political content
def example_filtering():
    """Demonstrate semantic filtering"""
    
    # Define filters to exclude political content
    filters = {
        "purpose": {
            "exclude": [
                {"semantic_category": "political", "min_semantic_similarity": 0.35}
            ]
        }
    }
    
    # Use political content from test data
    sample_data = TEST_CONTENT['political_content']
    sample = Sample(
        id=sample_data['id'],
        content=sample_data['content'],
        metadata={'filters': filters}  # Filters in metadata
    )
    
    result = processor.process_sample(
        sample,
        compression_ratio=0.5,
        similarity=0.8,
        filters=filters
    )
    
    if result['success']:
        # Check which segments were filtered
        filtered = processor.get_filtered_segments(sample.id)
        if filtered:
            print(f"Filtered {len(filtered)} segments:")
            for seg in filtered:
                print(f"  - {seg['semantic_category']}: {seg['exclusion_reason']}")
        
        # Get suggested text (excludes filtered segments)
        suggested = processor.get_suggested_text(sample.id)
        if suggested:
            print(f"\nSuggested text: {suggested}")
        else:
            print(f"\nSuggested text: [All content was filtered out]")

# Example 2: Short content handling
def example_short_content():
    """Demonstrate short content that only returns semantic category"""
    
    # Use short technical content
    sample_data = TEST_CONTENT['short_technical']
    sample = Sample(
        id=sample_data['id'],
        content=sample_data['content']
    )
    
    print(f"Content: {sample.content}")
    print(f"Length: {len(sample.content)} chars")
    
    result = processor.process_sample(sample)
    
    if result['success']:
        segments = processor.get_segment_details(sample.id)
        if segments:
            seg = segments[0]
            print(f"\nSemantic category: {seg['semantic_category']}")
            print(f"Was compressed: {seg['was_compressed']}")
            print(f"Detail count: {seg['detail_count']}")

# Example 3: Medium content with proper compression
def example_medium_content():
    """Demonstrate proper compression with medium-length content"""
    
    # Use medium literature content
    sample_data = TEST_CONTENT['medium_literature']
    sample = Sample(
        id=sample_data['id'],
        content=sample_data['content']
    )
    
    print(f"Content length: {len(sample.content)} chars")
    
    result = processor.process_sample(
        sample,
        compression_ratio=0.5,  # Target 50% compression
        similarity=0.8,
        force_detail_count=8
    )
    
    if result['success']:
        print(f"\nCompression achieved: {result['compression_ratio']:.2%}")
        
        # Get compressed text
        compressed = processor.get_compressed_text(sample.id)
        suggested = processor.get_suggested_text(sample.id)
        
        if compressed and suggested:
            print(f"Compressed length: {len(compressed)} chars")
            print(f"Suggested length: {len(suggested)} chars")
            print(f"\nFirst 200 chars of compressed:")
            print(compressed[:200] + "...")
        
        # Show segment details
        segments = processor.get_segment_details(sample.id)
        if segments:
            for seg in segments:
                print(f"\nSegment {seg['index']}:")
                print(f"  Category: {seg['semantic_category']}")
                print(f"  Details: {seg['detail_count']}")
                print(f"  Compression: {seg['compression_ratio']:.2%}")

# Example 4: Force detail count variations
def example_force_detail_count():
    """Demonstrate different detail count settings"""
    
    # Use medium science content
    sample_data = TEST_CONTENT['medium_science']
    
    detail_counts = [3, 5, 9]
    
    for count in detail_counts:
        sample = Sample(
            id=10 + count,  # Unique ID for each test
            content=sample_data['content'],
            metadata={'force_detail_count': count}  # Detail count in metadata
        )
        
        print(f"\nTesting with force_detail_count={count}")
        
        result = processor.process_sample(
            sample,
            compression_ratio=0.6,
            use_cache=False
        )
        
        if result['success']:
            segments = processor.get_segment_details(sample.id)
            if segments:
                actual = segments[0]['detail_count']
                print(f"  Requested: {count}, Got: {actual}")
                print(f"  Compression: {result['compression_ratio']:.2%}")

# Example 5: Investment content filtering
def example_investment_filtering():
    """Demonstrate filtering investment advice"""
    
    # Filter for investment advice
    filters = {
        "purpose": {
            "exclude": [
                {"semantic_category": "investment advice", "min_semantic_similarity": 0.35}
            ]
        }
    }
    
    # Use investment content
    sample_data = TEST_CONTENT['investment_content']
    sample = Sample(
        id=sample_data['id'],
        content=sample_data['content']
    )
    
    result = processor.process_sample(
        sample,
        filters=filters,
        force_single_segment=False  # Process as multiple segments
    )
    
    if result['success']:
        # Check if content was filtered
        filtered = processor.get_filtered_segments(sample.id)
        suggested = processor.get_suggested_text(sample.id)
        
        if filtered:
            print(f"\nFiltered {len(filtered)} segments:")
            for seg in filtered:
                print(f"  - {seg['semantic_category']}")
                print(f"    Similarity: {seg['exclusion_reason']['similarity']:.2%}")
                print(f"    Threshold: {seg['exclusion_reason']['threshold']}")
        
        if suggested:
            print(f"\nSuggested text: {suggested}")
        else:
            print(f"\nSuggested text: [All content was filtered]")

# Example 6: Batch processing with mixed parameters
def example_batch_processing():
    """Demonstrate batch processing with metadata-driven parameters"""
    
    # Create samples with different processing needs via metadata
    samples = [
        Sample(id=10, content=TEST_CONTENT['short_technical']['content'], 
               metadata={'compression_ratio': 0.8}),  # Short content, won't compress
        Sample(id=11, content=TEST_CONTENT['medium_science']['content'], 
               metadata={'processing_mode': 'async', 'timeout': 120}),  # Async with longer timeout
        Sample(id=12, content=TEST_CONTENT['investment_content']['content'], 
               metadata={'filters': {'purpose': {'exclude': [{'semantic_category': 'investment advice', 'min_semantic_similarity': 0.35}]}}}),  # Should filter out
        Sample(id=13, content=TEST_CONTENT['medium_literature']['content'],
               metadata={'force_detail_count': 10, 'compression_ratio': 0.5}),  # More aggressive compression
    ]
    
    # Process batch - parameters come from metadata
    results = processor.process_batch(
        samples,
        batch_size=2,  # Process 2 at a time
        cooldown=1.0,
        batch_cooldown=3.0
    )
    
    # Analyze results
    successful = [r for r in results if r['success']]
    filtered_count = sum(
        1 for r in successful 
        if processor.get_filtered_segments(r['sample_id'])
    )
    
    print(f"\nBatch processing summary:")
    print(f"  Total: {len(results)}")
    print(f"  Successful: {len(successful)}")
    print(f"  With filtered content: {filtered_count}")
    
    # Show what each sample did
    for r in results:
        if r['success']:
            sample_id = r['sample_id']
            print(f"\n  Sample {sample_id}:")
            print(f"    Compression: {r['compression_ratio']:.2%}")
            if processor.get_filtered_segments(sample_id):
                print(f"    Had filtered content")

# Example 7: Analyzing filter effectiveness
def example_filter_analysis():
    """Analyze how filters affect compression"""
    
    content = """
        Investment opportunities in tech stocks are abundant. 
        The market analysis suggests buying now before prices rise.
        Historical data shows consistent returns in this sector.
        Diversification remains a key strategy for risk management.
        """
    
    # Use different IDs for each test
    sample_no_filter = Sample(id=21, content=content)
    sample_with_filter = Sample(id=22, content=content)
    
    # Process without filters
    result_no_filter = processor.process_sample(
        sample_no_filter,
        compression_ratio=0.5,
        similarity=0.8,
        use_cache=False
    )
    
    # Process with filters
    filters = {
        "purpose": {
            "exclude": [
                {"semantic_category": "investment advice", "min_semantic_similarity": 0.35}
            ]
        }
    }
    
    result_filtered = processor.process_sample(
        sample_with_filter,
        compression_ratio=0.5,
        similarity=0.8,
        filters=filters,
        use_cache=False
    )
    
    # Compare results
    if result_no_filter['success'] and result_filtered['success']:
        text_no_filter = processor.get_suggested_text(sample_no_filter.id)
        text_filtered = processor.get_suggested_text(sample_with_filter.id)
        
        # Check what was filtered
        filtered_segments = processor.get_filtered_segments(sample_with_filter.id)
        
        print(f"\nFilter effectiveness analysis:")
        print(f"  Original length: {len(content.strip())}")
        print(f"  Without filter: {len(text_no_filter) if text_no_filter else 0} chars")
        print(f"  With filter: {len(text_filtered) if text_filtered else 0} chars")
        print(f"  Reduction: {len(text_no_filter) - len(text_filtered) if text_no_filter and text_filtered else 'N/A'} chars")
        
        if filtered_segments:
            print(f"\nFiltered {len(filtered_segments)} segments:")
            for seg in filtered_segments:
                print(f"  - {seg['semantic_category']}: {seg['exclusion_reason']['filter_category']}")

if __name__ == "__main__":
    print("Hypernym V2 API Examples")
    print("=" * 50)
    
    # Cleanup function
    def cleanup():
        if os.path.exists(test_db):
            os.remove(test_db)
            print(f"\nCleaned up test database: {test_db}")
    
    import atexit
    atexit.register(cleanup)
    
    # Run examples (comment out those requiring Northstar tier if not available)
    
    print("\n1. Semantic Filtering Example:")
    example_filtering()
    
    print("\n2. Short Content Example:")
    example_short_content()
    
    print("\n3. Medium Content Compression:")
    example_medium_content()
    
    print("\n4. Force Detail Count Example:")
    example_force_detail_count()
    
    print("\n5. Investment Filtering Example:")
    example_investment_filtering()
    
    print("\n6. Batch Processing Example:")
    example_batch_processing()
    
    print("\n7. Filter Analysis Example:")
    example_filter_analysis()