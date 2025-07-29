#!/usr/bin/env python3
"""
Minimal unit test to validate the segmentation approach.
Uses a tiny chunk with a known question/answer to verify both strategies work.
"""

import os
import json
import hashlib
import requests
from dotenv import load_dotenv

# Cache for API responses
CACHE = {}

def get_cache_key(api_name, text, **params):
    """Create cache key from API name, text, and parameters"""
    param_str = json.dumps(params, sort_keys=True)
    content = f"{api_name}:{text}:{param_str}"
    return hashlib.sha256(content.encode()).hexdigest()

def call_unstructured_api(text):
    """Call Unstructured API - simplified for test"""
    cache_key = get_cache_key("unstructured", text)
    if cache_key in CACHE:
        return CACHE[cache_key]
    
    api_key = os.getenv('UNSTRUCTURED_API_KEY')
    api_url = os.getenv('UNSTRUCTURED_API_URL')
    
    headers = {
        'accept': 'application/json',
        'unstructured-api-key': api_key
    }
    
    files = {
        'files': ('test.txt', text.encode('utf-8'), 'text/plain')
    }
    
    try:
        response = requests.post(api_url, headers=headers, files=files)
        response.raise_for_status()
        result = response.json()
        CACHE[cache_key] = result
        return result
    except Exception as e:
        print(f"Unstructured error: {e}")
        return None

def call_hypernym_api(text):
    """Call Hypernym API - simplified for test"""
    cache_key = get_cache_key("hypernym", text)
    if cache_key in CACHE:
        return CACHE[cache_key]
    
    api_key = os.getenv('HYPERNYM_API_KEY')
    api_url = os.getenv('HYPERNYM_API_URL', 'http://127.0.0.1:5000/analyze_sync')
    
    headers = {
        'X-API-Key': api_key,
        'Content-Type': 'application/json'
    }
    
    payload = {
        'essay_text': text,
        'params': {
            'min_compression_ratio': 0.6,
            'min_semantic_similarity': 0.75
        }
    }
    
    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        CACHE[cache_key] = result
        return result
    except Exception as e:
        print(f"Hypernym error: {e}")
        return None

def test_minimal():
    """Test with minimal text and known Q&A"""
    load_dotenv()
    
    # Tiny test chunk with clear facts (about 60 words)
    test_chunk = """The Eiffel Tower was completed in 1889. It stands 330 meters tall in Paris, France. 
    The tower was designed by Gustave Eiffel for the World's Fair. It was originally intended 
    to be temporary but became a permanent symbol of the city. The structure weighs approximately 
    10,100 tons and receives millions of visitors annually."""
    
    # Known question and answer
    test_question = "When was the Eiffel Tower completed?"
    correct_answer = "1889"
    
    print("=== Minimal Segmentation Test ===")
    print(f"Text: {len(test_chunk.split())} words")
    print(f"Question: {test_question}")
    print(f"Answer: {correct_answer}\n")
    
    # Strategy 1: Direct
    print("1. DIRECT: Chunk → Hypernym")
    hypernym_direct = call_hypernym_api(test_chunk)
    if hypernym_direct:
        segments = hypernym_direct.get('results', {}).get('response', {}).get('segments', [])
        print(f"   Got {len(segments)} segments")
        compressed_text = hypernym_direct.get('results', {}).get('response', {}).get('texts', {}).get('suggested', '')
        print(f"   Compressed text preview: {compressed_text[:100]}...")
        print(f"   Answer preserved: {'1889' in compressed_text}")
    
    # Strategy 2: Pre-segmented
    print("\n2. PRE-SEGMENTED: Chunk → Unstructured → Hypernym")
    unstructured_result = call_unstructured_api(test_chunk)
    if unstructured_result:
        elements = unstructured_result if isinstance(unstructured_result, list) else []
        print(f"   Unstructured found {len(elements)} elements")
        
        # Process first element through Hypernym (for minimal test)
        if elements and elements[0].get('text', ''):
            first_elem = elements[0]['text']
            if len(first_elem.split()) >= 50:
                hypernym_preseg = call_hypernym_api(first_elem)
                if hypernym_preseg:
                    compressed = hypernym_preseg.get('results', {}).get('response', {}).get('texts', {}).get('suggested', '')
                    print(f"   Compressed first element: {compressed[:100]}...")
                    print(f"   Answer preserved: {'1889' in compressed}")
            else:
                print(f"   First element too small ({len(first_elem.split())} words)")
    
    print("\nTest complete. Both strategies attempted.")
    print(f"Cache entries: {len(CACHE)}")

if __name__ == "__main__":
    test_minimal()