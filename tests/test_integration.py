#!/usr/bin/env python3
"""
Integration test for portable Hypernym processor
Real API calls, real database, no mocks
"""

import os
import sys
import sqlite3
import tempfile
import subprocess
import json
from dotenv import load_dotenv

# Import local modules for direct testing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypernym_processor import HypernymProcessor, Sample

# Load environment variables from .env file
load_dotenv()

# Test data - each sample must be 200+ tokens for Hypernym to work properly
SAMPLES = [
    (1, """The sun was setting over the mountains, casting long shadows across the valley below. Birds circled overhead in the fading light, their silhouettes dancing against the orange and purple sky. The air grew cooler as evening approached, carrying with it the scent of pine trees and wildflowers. In the distance, a lone wolf howled, its mournful cry echoing through the wilderness. The landscape transformed before my eyes, as darkness slowly crept across the terrain, replacing the vibrant colors of day with the mysterious blues and blacks of night. Stars began to appear, one by one, like diamonds scattered across velvet. The moon rose majestically, bathing everything in its silvery glow. Nature's transition from day to night never ceased to amaze me, this daily ritual that had been occurring for millions of years. I sat in quiet contemplation, feeling incredibly small yet profoundly connected to the universe around me. The mountain peaks stood as silent sentinels, witnesses to countless sunsets throughout the ages. This moment of tranquility filled me with a deep sense of peace and wonder at the natural world's eternal rhythms."""),
    
    (2, """In the depths of the ocean, strange creatures lurk in perpetual darkness, adapted to extreme pressure and cold. These fascinating organisms have evolved unique characteristics that allow them to survive in one of Earth's most hostile environments. Bioluminescent fish create their own light through chemical reactions, using this ability to attract prey, communicate with potential mates, or confuse predators. Giant squid with eyes the size of dinner plates patrol the midnight zone, their tentacles equipped with powerful suckers that can grasp prey in the absolute darkness. The pressure at these depths would crush most surface-dwelling creatures instantly, yet these deep-sea inhabitants thrive under conditions that would be fatal to humans. Their bodies have adapted with special pressure-resistant proteins and gas-filled swim bladders that help them maintain neutral buoyancy. Some species have transparent bodies, making them nearly invisible to both predators and prey. Others have developed enormous mouths and expandable stomachs, allowing them to consume prey larger than themselves - a crucial adaptation when meals are scarce in the deep ocean. The deep sea remains one of the least explored regions on our planet, with scientists estimating that countless species remain undiscovered in these mysterious depths."""),
    
    (3, """The old library smelled of leather and dust, its shelves groaning under the weight of countless forgotten stories. Ancient tomes lined the walls from floor to ceiling, their spines bearing titles in languages both familiar and foreign. Sunlight filtered through stained glass windows, casting colorful patterns across the worn wooden floors that creaked with every step. In the corners, cobwebs draped like delicate lace curtains, undisturbed for years. The librarian, a elderly woman with silver hair pulled back in a severe bun, moved through the stacks with practiced ease, her fingers trailing along the books as if greeting old friends. Each volume held within its pages entire worlds waiting to be discovered - tales of adventure, romance, mystery, and wisdom accumulated over centuries. The card catalogs, relics from a pre-digital age, stood like sentinels near the entrance, their tiny drawers filled with handwritten index cards yellowed with age. Comfortable reading chairs were scattered throughout, their leather cracked but still inviting, perfect spots for losing oneself in literature. The atmosphere was one of reverent silence, broken only by the occasional whisper of turning pages or the soft footsteps of another patron seeking knowledge or escape within these hallowed halls."""),
]

def main():
    # Create temp database
    temp_dir = tempfile.mkdtemp()
    temp_db = os.path.join(temp_dir, 'test.sqlite')
    
    print(f"Creating test database at: {temp_db}")
    
    # Setup database
    conn = sqlite3.connect(temp_db)
    conn.execute("""
        CREATE TABLE samples (
            id INTEGER PRIMARY KEY,
            content TEXT
        )
    """)
    conn.executemany("INSERT INTO samples VALUES (?, ?)", SAMPLES)
    conn.commit()
    conn.close()
    
    # Initialize processor
    processor = HypernymProcessor(temp_db)
    
    # Get samples
    samples = processor.get_samples_by_ids([1, 2, 3])
    
    # Test 1: Process samples
    print("\n1. Processing samples 1,2,3...")
    results = processor.process_batch(samples)
    
    # Check results
    success_count = sum(1 for r in results if r['success'])
    print(f"Exit code: {0 if success_count == len(results) else 1}")
    
    # Verify responses saved
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        cursor = conn.execute("SELECT COUNT(*) FROM hypernym_responses")
        response_count = cursor.fetchone()[0]
    
    print(f"Tables in database: {tables}")
    print(f"Responses in database: {response_count}")
    
    # Test 2: Run again - should use cache
    print("\n2. Running again (should use cache)...")
    results2 = processor.process_batch(samples, use_cache=True)
    
    # Check if all used cache
    cached_count = sum(1 for r in results2 if r.get('cached', False))
    if cached_count == len(results2):
        print("✓ Cache working")
    else:
        print("✗ Cache not working")
    
    # Test 3: Different parameters
    print("\n3. Running with different compression...")
    results3 = processor.process_batch(samples, compression_ratio=0.7, similarity=0.8)
    
    # Check total responses
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM hypernym_responses")
        final_count = cursor.fetchone()[0]
    
    print(f"Total responses after compression change: {final_count}")
    
    # Show example hypernym for first sample
    print("\n3a. Example hypernym string for sample 1:")
    hypernym = processor.get_hypernym_string(1)
    if hypernym:
        print(hypernym)
        avg_sim = processor.get_average_semantic_similarity(1)
        print(f"\nAverage similarity: {avg_sim:.1%}")
    
    # Test 4: Verify multi-segment handling
    print("\n4. Testing multi-segment extraction...")
    # Create a longer sample that will likely generate multiple segments
    long_sample = Sample(
        id=99,
        content="The history of artificial intelligence begins in antiquity, with myths and stories of artificial beings endowed with intelligence. " * 20  # ~400 words
    )
    
    # Insert long sample
    with sqlite3.connect(temp_db) as conn:
        conn.execute("INSERT INTO samples (id, content) VALUES (?, ?)", 
                    (long_sample.id, long_sample.content))
    
    # Process it
    result = processor.process_sample(long_sample)
    
    if result['success']:
        # Get hypernym string
        hypernym = processor.get_hypernym_string(long_sample.id)
        if hypernym:
            print("✓ Hypernym extracted successfully")
            # Count segments
            segment_count = hypernym.count('[SEGMENT')
            print(f"  Found {segment_count} segments")
            if segment_count > 1:
                print("  ✓ Multi-segment handling working")
                print("\n  First 200 chars of hypernym string:")
                print(f"  {hypernym[:200]}...")
            else:
                print("  ⚠️ Only one segment found (expected multiple for long text)")
        
        # Get segment details
        segments = processor.get_segment_details(long_sample.id)
        if segments:
            print(f"\n  Segment details:")
            for seg in segments:
                print(f"    Segment {seg['index']+1}: {seg['semantic_category']} "
                      f"({seg['detail_count']} details, {seg['compression_ratio']:.1%} compression, "
                      f"{seg['semantic_similarity']:.1%} similarity)")
        
        # Get average semantic similarity
        avg_similarity = processor.get_average_semantic_similarity(long_sample.id)
        if avg_similarity:
            print(f"\n  Average semantic similarity: {avg_similarity:.1%}")
    
    print(f"\nTest database at: {temp_db}")
    print("Integration test complete")

if __name__ == '__main__':
    main()