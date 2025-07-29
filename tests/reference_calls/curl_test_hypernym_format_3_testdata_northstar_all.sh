#!/bin/bash

# Northstar Full Features Test - Demonstrates ALL Northstar tier capabilities
# This test exercises every Northstar-exclusive feature

echo "Northstar Tier Full Feature Test"
echo "================================"
echo "Testing ALL Northstar features including:"
echo "- Comprehensive mode (60 trials)"
echo "- Extended timeout (15 minutes)"
echo "- Embeddings inclusion"
echo "- High detail count (15 elements)"
echo "- Semantic filtering"
echo ""

# Define API endpoint and Northstar API key
API_ENDPOINT="http://localhost:5000/analyze_sync"
API_KEY="fkd8493jg7392bduw"  # Replace with your Northstar API key

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
PURPLE='\033[0;35m'
NC='\033[0m'

# Test content - substantial enough to showcase all features
CONTENT="Quantum computing represents a paradigm shift in computational capabilities. Unlike classical computers that use bits representing either 0 or 1, quantum computers utilize qubits that can exist in superposition states. This fundamental difference enables quantum computers to process vast amounts of information simultaneously.

The implications for cryptography are profound. Current encryption methods rely on the computational difficulty of factoring large prime numbers. Quantum computers could break these encryptions in minutes rather than millennia. This has led to the development of quantum-resistant cryptographic algorithms.

In drug discovery, quantum simulations can model molecular interactions at unprecedented scales. Pharmaceutical companies are investing billions in quantum research to accelerate drug development. The ability to simulate protein folding could revolutionize treatment for diseases like Alzheimer's and cancer.

Financial modeling presents another frontier. Portfolio optimization, risk analysis, and derivative pricing could benefit from quantum speedups. Major banks are establishing quantum computing divisions to maintain competitive advantages in high-frequency trading and risk management.

However, significant challenges remain. Quantum decoherence limits computation time, requiring extreme cooling to near absolute zero. Error rates are still too high for practical applications. The engineering challenges of scaling from dozens to millions of qubits remain formidable."

echo -e "${YELLOW}Sending Northstar comprehensive analysis request...${NC}"
echo "Expected processing time: 5-6 minutes (first run) or 7-9 seconds (cached)"
echo ""

# Create comprehensive Northstar request with ALL features
START_TIME=$(date +%s)

RESPONSE=$(curl -s -X POST $API_ENDPOINT \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Client-Tier: northstar" \
  -d '{
    "essay_text": "'"$(echo "$CONTENT" | sed 's/"/\\"/g' | tr '\n' ' ')"'",
    "params": {
      "min_compression_ratio": 0.3,
      "min_semantic_similarity": 0.7,
      "analysis_mode": "comprehensive",
      "timeout": 900,
      "force_detail_count": 15,
      "include_embeddings": true,
      "force_single_segment": true
    },
    "filters": {
      "purpose": {
        "exclude": [
          {"semantic_category": "investment advice", "min_semantic_similarity": 0.35},
          {"semantic_category": "political", "min_semantic_similarity": 0.35}
        ]
      }
    }
  }')

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo -e "${GREEN}Request completed in ${ELAPSED} seconds${NC}"
echo ""

# Save full response
mkdir -p northstar_results
echo "$RESPONSE" > northstar_results/comprehensive_full_response.json

# Parse and display results
if echo "$RESPONSE" | jq '.' >/dev/null 2>&1; then
    echo -e "${BLUE}=== Analysis Summary ===${NC}"
    
    # Check if it's the new async format or direct response
    if echo "$RESPONSE" | jq -e '.results' >/dev/null 2>&1; then
        # Direct response format
        RESULTS_PATH=".results"
    else
        # Check for error
        ERROR=$(echo "$RESPONSE" | jq -r '.error // empty')
        if [ -n "$ERROR" ]; then
            echo -e "${RED}Error: $ERROR${NC}"
            exit 1
        fi
        RESULTS_PATH="."
    fi
    
    # Extract key metrics
    echo "$RESPONSE" | jq -r "$RESULTS_PATH | 
        \"Mode: \\(.metadata.analysis_mode // \"unknown\")
Cache Hit: \\(.metadata.cache_hit // false)
Processing Time: \\(.metadata.processing_time // \"N/A\")s
Total Segments: \\(.response.segments | length)
Compressed Segments: \\(.response.segments | map(select(.was_compressed)) | length)
Excluded by Filter: \\(.metadata.excluded_segments_count // 0)
Tokens Used: \\(.metadata.tokens.total // \"N/A\")
Embeddings Included: \\(.response.segments[0].original.embedding // null | if . then \"Yes\" else \"No\" end)\""
    
    echo ""
    echo -e "${BLUE}=== Segment Details ===${NC}"
    
    # Show each segment with Northstar-specific details
    echo "$RESPONSE" | jq -r "$RESULTS_PATH.response.segments[] | 
        \"\\nSegment \\(.paragraph_idx // \"N/A\"):
  Semantic Category: \\(.semantic_category)
  Compression Ratio: \\(.compression_ratio)
  Semantic Similarity: \\(.semantic_similarity)
  Covariant Details Count: \\(.covariant_details | length)
  Has Embeddings: \\(if .original.embedding then \"Yes (\\(.original.embedding.dimensions)D)\" else \"No\" end)
  Trial Count: \\(if .trials then (.trials | length) else \"N/A\" end)
  Excluded: \\(.excluded_by_filter // false)\\(if .exclusion_reason then \" (\\(.exclusion_reason.filter_category))\" else \"\" end)\""
    
    # If comprehensive mode, show trial statistics
    TRIALS=$(echo "$RESPONSE" | jq -r "$RESULTS_PATH.response.segments[0].trials // empty")
    if [ -n "$TRIALS" ]; then
        echo ""
        echo -e "${PURPLE}=== Comprehensive Mode Trial Statistics ===${NC}"
        echo "$RESPONSE" | jq -r "$RESULTS_PATH.response.segments[0] | 
            \"First Segment Trial Analysis:
  Total Trials: \\(.trials | length)
  Unique Categories: \\(.trials | map(.semantic_category) | unique | length)
  Avg Compression Ratio: \\(.trials | map(.compression_ratio) | add / length)
  Avg Similarity: \\(.trials | map(.avg_similarity) | add / length)
  Most Common Category: \\(.trials | group_by(.semantic_category) | max_by(length) | .[0].semantic_category)\""
    fi
    
    # Show sample covariant details with forced count of 15
    echo ""
    echo -e "${BLUE}=== Sample Covariant Details (15 forced) ===${NC}"
    echo "$RESPONSE" | jq -r "$RESULTS_PATH.response.segments[0].covariant_details[:5][] | \"  - \\(.text)\""
    echo "  ... (showing 5 of 15 details)"
    
    # Show embedding sample if included
    EMBEDDING=$(echo "$RESPONSE" | jq -r "$RESULTS_PATH.response.segments[0].original.embedding.values[:5] // empty")
    if [ -n "$EMBEDDING" ]; then
        echo ""
        echo -e "${GREEN}=== Embedding Vector Sample ===${NC}"
        echo "First 5 dimensions of 768D embedding:"
        echo "$RESPONSE" | jq -r "$RESULTS_PATH.response.segments[0].original.embedding.values[:5][] | \"  \\(.)\""
    fi
    
    # Performance comparison note
    echo ""
    echo -e "${YELLOW}=== Performance Notes ===${NC}"
    if [ $ELAPSED -lt 20 ]; then
        echo -e "${GREEN}✓ Fast response (${ELAPSED}s) - likely served from cache${NC}"
        echo "  Cache provides 37-47x speedup for comprehensive mode"
    else
        echo -e "${YELLOW}⚠ Initial comprehensive analysis (${ELAPSED}s)${NC}"
        echo "  Subsequent identical requests will be ~7-9 seconds"
    fi
    
else
    echo -e "${RED}Error: Invalid JSON response${NC}"
    echo "$RESPONSE"
fi

echo ""
echo -e "${GREEN}Full response saved to: northstar_results/comprehensive_full_response.json${NC}"
echo ""
echo "To run performance comparison:"
echo "1. Run this script again (should hit cache)"
echo "2. Compare with standard tier: ./curl_test_benchmark_standard.sh"