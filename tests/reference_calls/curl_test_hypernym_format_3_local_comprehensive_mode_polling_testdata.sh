#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Base URL and API key - Local test server
BASE_URL="http://localhost:5000"
API_KEY="fkd8493jg7392bduw"  # Northstar test key from testdata script

echo -e "${YELLOW}=== Field Constrictor Comprehensive Mode Test ===${NC}"
echo -e "Testing async analysis with comprehensive mode\n"
echo -e "Using local test server with Northstar tier API key\n"

# Sample text for testing
PAYLOAD='{
    "essay_text": "Modern Financial Theory and Markets represent a complex intersection of mathematical models, behavioral economics, and technological innovation. The evolution of financial markets from simple exchange mechanisms to today'\''s sophisticated electronic trading platforms demonstrates the field'\''s remarkable transformation.\n\nThis comprehensive framework encompasses everything from fundamental concepts like the Time Value of Money and Modern Portfolio Theory to cutting-edge developments in quantitative trading and decentralized finance (DeFi).\n\nThe foundation of modern finance was laid in the mid-20th century with the development of key theories that continue to influence market behavior and investment strategies.",
    "params": {
        "min_compression_ratio": 1.0,
        "min_semantic_similarity": 0.0,
        "analysis_mode": "comprehensive"
    }
}'

# Step 1: Start the analysis
echo -e "${BLUE}Starting comprehensive analysis...${NC}"
START_TIME=$(date +%s)
RESPONSE=$(curl -s -X POST "${BASE_URL}/analyze_begin" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "${PAYLOAD}")

echo "Response:"
echo "$RESPONSE" | jq '.'

# Extract analysis_id and estimated time
ANALYSIS_ID=$(echo "$RESPONSE" | jq -r '.analysis_id')
ESTIMATED_TIME=$(echo "$RESPONSE" | jq -r '.estimated_time')
MODE=$(echo "$RESPONSE" | jq -r '.mode')

if [ "$ANALYSIS_ID" = "null" ] || [ -z "$ANALYSIS_ID" ]; then
    echo -e "${RED}Failed to start analysis. No analysis_id returned.${NC}"
    exit 1
fi

echo -e "${GREEN}Analysis started successfully!${NC}"
echo -e "Analysis ID: ${ANALYSIS_ID}"
echo -e "Mode: ${PURPLE}${MODE}${NC}"
echo -e "Estimated time: ${ESTIMATED_TIME}s\n"

# Step 2: Poll for status
echo -e "${BLUE}Monitoring analysis progress...${NC}"
echo -e "${YELLOW}Note: Comprehensive mode performs multiple trials per paragraph${NC}\n"

MAX_ATTEMPTS=300  # Max 300 attempts (about 10 minutes with 2-second intervals)
ATTEMPT=0
COMPLETED=false
LAST_PROGRESS=-1

while [ $ATTEMPT -lt $MAX_ATTEMPTS ] && [ "$COMPLETED" = false ]; do
    ATTEMPT=$((ATTEMPT + 1))
    
    # Check status
    STATUS_RESPONSE=$(curl -s -X GET "${BASE_URL}/analyze_status/${ANALYSIS_ID}" \
        -H "X-API-Key: ${API_KEY}")
    
    STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')
    
    if [ "$STATUS" = "completed" ]; then
        COMPLETED=true
        END_TIME=$(date +%s)
        TOTAL_TIME=$((END_TIME - START_TIME))
        
        echo -e "\n${GREEN}Analysis completed!${NC}"
        echo -e "Total time: ${TOTAL_TIME}s (estimated was ${ESTIMATED_TIME}s)"
        echo -e "\nFinal response:"
        echo "$STATUS_RESPONSE" | jq '.'
        
        # Extract key metrics
        echo -e "\n${YELLOW}Analysis Summary:${NC}"
        echo "$STATUS_RESPONSE" | jq -r '
            "Processing Time: \(.processing_time)s
Mode: comprehensive
Total Segments: \(.results.summary.total_segments)
Compressed Segments: \(.results.summary.compressed_segments)
Average Compression Ratio: \(.results.summary.average_compression_ratio)
Average Semantic Similarity: \(.results.summary.average_semantic_similarity)
Total Tokens Used: \(.results.metadata.tokens.total)"
        ' 2>/dev/null || echo "Could not parse summary"
        
        # Show a sample compressed segment
        echo -e "\n${YELLOW}Sample Compressed Segment:${NC}"
        echo "$STATUS_RESPONSE" | jq -r '.results.response.segments[0] | 
            if .was_compressed then
                "Semantic Category: \(.semantic_category)
Compression Ratio: \(.compression_ratio)
Covariant Details:"
            else
                "First segment was not compressed"
            end' 2>/dev/null
        
        echo "$STATUS_RESPONSE" | jq -r '.results.response.segments[0].covariant_details[]? | "  - \(.text)"' 2>/dev/null
        
    elif [ "$STATUS" = "failed" ]; then
        echo -e "\n${RED}Analysis failed!${NC}"
        echo "$STATUS_RESPONSE" | jq '.'
        exit 1
        
    else
        # Still processing
        PROGRESS=$(echo "$STATUS_RESPONSE" | jq -r '.progress.percent_complete // 0')
        COMPLETED_PARAGRAPHS=$(echo "$STATUS_RESPONSE" | jq -r '.progress.completed_paragraphs // 0')
        TOTAL_PARAGRAPHS=$(echo "$STATUS_RESPONSE" | jq -r '.progress.total_paragraphs // 0')
        
        # Only update display if progress changed
        if [ "$PROGRESS" != "$LAST_PROGRESS" ]; then
            CURRENT_TIME=$(date +%s)
            ELAPSED=$((CURRENT_TIME - START_TIME))
            echo -e "\rElapsed: ${ELAPSED}s | Status: $STATUS | Progress: ${PROGRESS}% (${COMPLETED_PARAGRAPHS}/${TOTAL_PARAGRAPHS} paragraphs)"
            LAST_PROGRESS=$PROGRESS
        else
            echo -ne "."
        fi
        
        # Wait before next check
        sleep 2
    fi
done

if [ "$COMPLETED" = false ]; then
    echo -e "\n${RED}Analysis timed out after $MAX_ATTEMPTS attempts${NC}"
    exit 1
fi

echo -e "\n\n${GREEN}=== Comprehensive mode test completed successfully ===${NC}"

# Compare with partial mode
echo -e "\n${YELLOW}Quick comparison - Starting partial mode analysis...${NC}"

PARTIAL_PAYLOAD='{
    "essay_text": "Modern Financial Theory and Markets represent a complex intersection of mathematical models, behavioral economics, and technological innovation. The evolution of financial markets from simple exchange mechanisms to today'\''s sophisticated electronic trading platforms demonstrates the field'\''s remarkable transformation.\n\nThis comprehensive framework encompasses everything from fundamental concepts like the Time Value of Money and Modern Portfolio Theory to cutting-edge developments in quantitative trading and decentralized finance (DeFi).\n\nThe foundation of modern finance was laid in the mid-20th century with the development of key theories that continue to influence market behavior and investment strategies.",
    "params": {
        "min_compression_ratio": 1.0,
        "min_semantic_similarity": 0.0,
        "analysis_mode": "partial"
    }
}'

PARTIAL_START=$(date +%s)
PARTIAL_RESPONSE=$(curl -s -X POST "${BASE_URL}/analyze_begin" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "${PARTIAL_PAYLOAD}")

PARTIAL_ID=$(echo "$PARTIAL_RESPONSE" | jq -r '.analysis_id')

# Wait for partial to complete
sleep 5

PARTIAL_STATUS=$(curl -s -X GET "${BASE_URL}/analyze_status/${PARTIAL_ID}" \
    -H "X-API-Key: ${API_KEY}")

PARTIAL_TIME=$(echo "$PARTIAL_STATUS" | jq -r '.processing_time // "pending"')

echo -e "\n${YELLOW}Mode Comparison:${NC}"
echo -e "Comprehensive mode: ${TOTAL_TIME}s"
echo -e "Partial mode: ${PARTIAL_TIME}s"

if [ "$PARTIAL_TIME" != "pending" ]; then
    RATIO=$(echo "scale=2; $TOTAL_TIME / $PARTIAL_TIME" | bc)
    echo -e "Comprehensive mode took ${RATIO}x longer than partial mode"
fi

echo -e "\n${GREEN}All tests completed!${NC}"