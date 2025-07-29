#!/bin/bash

# Benchmark Standard Tier Test - Tests all features available to standard tier
# Compares performance and capabilities vs Northstar tier

echo "Standard Tier Benchmark Test"
echo "============================"
echo "Testing standard tier features:"
echo "- Partial analysis mode (single pass)"
echo "- 60-second timeout limit"
echo "- Detail count limited to 3-9"
echo "- No embeddings"
echo "- Basic filtering"
echo ""

# Define API endpoint and standard API key
API_ENDPOINT="http://localhost:5000/analyze_sync"
API_KEY="j38f74hf83h4f834"  # Standard tier key

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test content - same as Northstar test for comparison
CONTENT="Quantum computing represents a paradigm shift in computational capabilities. Unlike classical computers that use bits representing either 0 or 1, quantum computers utilize qubits that can exist in superposition states. This fundamental difference enables quantum computers to process vast amounts of information simultaneously.

The implications for cryptography are profound. Current encryption methods rely on the computational difficulty of factoring large prime numbers. Quantum computers could break these encryptions in minutes rather than millennia. This has led to the development of quantum-resistant cryptographic algorithms.

In drug discovery, quantum simulations can model molecular interactions at unprecedented scales. Pharmaceutical companies are investing billions in quantum research to accelerate drug development. The ability to simulate protein folding could revolutionize treatment for diseases like Alzheimer's and cancer.

Financial modeling presents another frontier. Portfolio optimization, risk analysis, and derivative pricing could benefit from quantum speedups. Major banks are establishing quantum computing divisions to maintain competitive advantages in high-frequency trading and risk management.

However, significant challenges remain. Quantum decoherence limits computation time, requiring extreme cooling to near absolute zero. Error rates are still too high for practical applications. The engineering challenges of scaling from dozens to millions of qubits remain formidable."

echo -e "${YELLOW}Running standard tier benchmark tests...${NC}"
echo ""

# Test 1: Basic analysis with standard parameters
echo -e "${BLUE}Test 1: Basic partial analysis${NC}"
START_TIME=$(date +%s)

RESPONSE_BASIC=$(curl -s -X POST $API_ENDPOINT \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --max-time 60 \
  -d '{
    "essay_text": "'"$(echo "$CONTENT" | sed 's/"/\\"/g' | tr '\n' ' ')"'",
    "params": {
      "min_compression_ratio": 0.5,
      "min_semantic_similarity": 0.8,
      "analysis_mode": "partial"
    }
  }')

END_TIME=$(date +%s)
ELAPSED_BASIC=$((END_TIME - START_TIME))

echo -e "Completed in ${ELAPSED_BASIC} seconds"

# Test 2: Maximum allowed detail count for standard tier
echo ""
echo -e "${BLUE}Test 2: Maximum detail extraction (9 elements)${NC}"
START_TIME=$(date +%s)

RESPONSE_MAX_DETAILS=$(curl -s -X POST $API_ENDPOINT \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --max-time 60 \
  -d '{
    "essay_text": "'"$(echo "$CONTENT" | sed 's/"/\\"/g' | tr '\n' ' ')"'",
    "params": {
      "min_compression_ratio": 0.3,
      "min_semantic_similarity": 0.7,
      "force_detail_count": 9,
      "analysis_mode": "partial"
    }
  }')

END_TIME=$(date +%s)
ELAPSED_DETAILS=$((END_TIME - START_TIME))

echo -e "Completed in ${ELAPSED_DETAILS} seconds"

# Test 3: With filtering
echo ""
echo -e "${BLUE}Test 3: Semantic filtering${NC}"
START_TIME=$(date +%s)

RESPONSE_FILTERED=$(curl -s -X POST $API_ENDPOINT \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --max-time 60 \
  -d '{
    "essay_text": "'"$(echo "$CONTENT" | sed 's/"/\\"/g' | tr '\n' ' ')"'",
    "params": {
      "min_compression_ratio": 0.5,
      "min_semantic_similarity": 0.8,
      "force_detail_count": 5
    },
    "filters": {
      "purpose": {
        "exclude": [
          {"semantic_category": "financial", "min_semantic_similarity": 0.35},
          {"semantic_category": "investment", "min_semantic_similarity": 0.35}
        ]
      }
    }
  }')

END_TIME=$(date +%s)
ELAPSED_FILTERED=$((END_TIME - START_TIME))

echo -e "Completed in ${ELAPSED_FILTERED} seconds"

# Test 4: Attempt to use Northstar features (should fail or be ignored)
echo ""
echo -e "${BLUE}Test 4: Attempting Northstar features (expected to fail/ignore)${NC}"
START_TIME=$(date +%s)

RESPONSE_NORTHSTAR_ATTEMPT=$(curl -s -X POST $API_ENDPOINT \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --max-time 60 \
  -d '{
    "essay_text": "'"$(echo "$CONTENT" | sed 's/"/\\"/g' | tr '\n' ' ')"'",
    "params": {
      "min_compression_ratio": 0.5,
      "min_semantic_similarity": 0.8,
      "analysis_mode": "comprehensive",
      "timeout": 900,
      "force_detail_count": 15,
      "include_embeddings": true
    }
  }')

END_TIME=$(date +%s)
ELAPSED_ATTEMPT=$((END_TIME - START_TIME))

echo -e "Completed in ${ELAPSED_ATTEMPT} seconds"

# Save responses
mkdir -p benchmark_results
echo "$RESPONSE_BASIC" > benchmark_results/standard_basic.json
echo "$RESPONSE_MAX_DETAILS" > benchmark_results/standard_max_details.json
echo "$RESPONSE_FILTERED" > benchmark_results/standard_filtered.json
echo "$RESPONSE_NORTHSTAR_ATTEMPT" > benchmark_results/standard_northstar_attempt.json

# Analysis and comparison
echo ""
echo -e "${GREEN}=== Benchmark Results Summary ===${NC}"
echo ""

# Function to safely extract values
extract_value() {
    local json=$1
    local path=$2
    local default=$3
    echo "$json" | jq -r "$path // \"$default\"" 2>/dev/null || echo "$default"
}

# Analyze each test
echo -e "${YELLOW}Test 1 - Basic Analysis:${NC}"
if echo "$RESPONSE_BASIC" | jq '.' >/dev/null 2>&1; then
    SEGMENTS=$(extract_value "$RESPONSE_BASIC" ".results.response.segments | length" "0")
    TOKENS=$(extract_value "$RESPONSE_BASIC" ".results.metadata.tokens.total" "N/A")
    echo "  Segments processed: $SEGMENTS"
    echo "  Tokens used: $TOKENS"
    echo "  Processing time: ${ELAPSED_BASIC}s"
else
    echo "  ${RED}Failed to get valid response${NC}"
fi

echo ""
echo -e "${YELLOW}Test 2 - Maximum Details (9):${NC}"
if echo "$RESPONSE_MAX_DETAILS" | jq '.' >/dev/null 2>&1; then
    DETAIL_COUNT=$(extract_value "$RESPONSE_MAX_DETAILS" ".results.response.segments[0].covariant_details | length" "0")
    echo "  Details extracted: $DETAIL_COUNT (limit: 9)"
    echo "  Processing time: ${ELAPSED_DETAILS}s"
else
    echo "  ${RED}Failed to get valid response${NC}"
fi

echo ""
echo -e "${YELLOW}Test 3 - Filtering:${NC}"
if echo "$RESPONSE_FILTERED" | jq '.' >/dev/null 2>&1; then
    EXCLUDED=$(extract_value "$RESPONSE_FILTERED" ".results.metadata.excluded_segments_count" "0")
    FILTERS_APPLIED=$(extract_value "$RESPONSE_FILTERED" ".results.metadata.filters_applied" "false")
    echo "  Filters applied: $FILTERS_APPLIED"
    echo "  Segments excluded: $EXCLUDED"
    echo "  Processing time: ${ELAPSED_FILTERED}s"
else
    echo "  ${RED}Failed to get valid response${NC}"
fi

echo ""
echo -e "${YELLOW}Test 4 - Northstar Feature Attempt:${NC}"
if echo "$RESPONSE_NORTHSTAR_ATTEMPT" | jq '.' >/dev/null 2>&1; then
    MODE=$(extract_value "$RESPONSE_NORTHSTAR_ATTEMPT" ".results.metadata.analysis_mode" "unknown")
    EMBEDDINGS=$(extract_value "$RESPONSE_NORTHSTAR_ATTEMPT" ".results.response.segments[0].original.embedding" "null")
    DETAIL_COUNT=$(extract_value "$RESPONSE_NORTHSTAR_ATTEMPT" ".results.response.segments[0].covariant_details | length" "0")
    
    echo "  Analysis mode: $MODE (requested: comprehensive)"
    echo "  Embeddings included: $([ "$EMBEDDINGS" != "null" ] && echo "Yes" || echo "No")"
    echo "  Details extracted: $DETAIL_COUNT (requested: 15)"
    echo "  Processing time: ${ELAPSED_ATTEMPT}s"
    
    if [ "$MODE" = "partial" ]; then
        echo "  ${YELLOW}✓ Correctly limited to partial mode${NC}"
    fi
    if [ "$EMBEDDINGS" = "null" ]; then
        echo "  ${YELLOW}✓ Embeddings correctly not included${NC}"
    fi
    if [ "$DETAIL_COUNT" -le 9 ]; then
        echo "  ${YELLOW}✓ Detail count correctly limited${NC}"
    fi
else
    echo "  ${RED}Failed to get valid response${NC}"
fi

# Performance comparison
echo ""
echo -e "${GREEN}=== Performance Comparison ===${NC}"
echo "Standard Tier Performance:"
echo "  Basic analysis: ${ELAPSED_BASIC}s"
echo "  With max details: ${ELAPSED_DETAILS}s"
echo "  With filtering: ${ELAPSED_FILTERED}s"
echo ""
echo "Compare with Northstar tier by running:"
echo "  ./curl_test_northstar_full_features.sh"
echo ""
echo -e "${BLUE}Key Limitations vs Northstar:${NC}"
echo "  ❌ No comprehensive mode (60 trials)"
echo "  ❌ Maximum 60-second timeout"
echo "  ❌ Detail count limited to 9"
echo "  ❌ No embedding vectors"
echo "  ❌ No caching benefits"
echo "  ✓ Basic filtering works"
echo "  ✓ Partial analysis mode"
echo ""
echo "All responses saved in: benchmark_results/"