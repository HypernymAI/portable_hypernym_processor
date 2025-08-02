# Hypernym Processor V2 API Features

This document covers the new features added to support Hypernym API v2.0, including semantic filtering, comprehensive analysis mode, embeddings, and async processing.

## Table of Contents

1. [Semantic Filtering](#semantic-filtering)
2. [Comprehensive Analysis Mode](#comprehensive-analysis-mode)
3. [Embedding Support](#embedding-support)
4. [Async Processing](#async-processing)
5. [Additional V2 Parameters](#additional-v2-parameters)
6. [Command Line Usage](#command-line-usage)
7. [Python API Examples](#python-api-examples)

## Semantic Filtering

Filter out content based on semantic categories to exclude unwanted topics from the suggested output.

### How It Works

- Define filter categories with similarity thresholds
- API checks each segment against filter categories
- Excluded segments remain in `compressed` output but not in `suggested`
- Filter metadata included in response

### Filter Structure

```python
filters = {
    "purpose": {
        "exclude": [
            {
                "semantic_category": "political",
                "min_semantic_similarity": 0.35
            },
            {
                "semantic_category": "investment advice",
                "min_semantic_similarity": 0.35
            }
        ]
    }
}
```

### Example Usage

```python
result = processor.process_sample(
    sample,
    filters=filters,
    force_single_segment=False  # Process multiple segments
)

# Check filtered segments
filtered = processor.get_filtered_segments(sample.id)
```

## Comprehensive Analysis Mode

**Northstar Tier Only**

Performs 60-trial multi-pass analysis for maximum accuracy and statistical validation.

### Features

- 60 independent analysis trials per paragraph
- Statistical validation with variance and confidence intervals
- Consensus building across trials
- Intelligent caching (37-47x speedup on repeated requests)

### Performance

- First run: ~5-6 minutes
- Cached runs: 7-9 seconds
- 100% cache hit rate for identical content

### Example Usage

```python
result = processor.process_sample(
    sample,
    analysis_mode="comprehensive",
    timeout=900  # 15 minutes
)

# Get trial statistics
stats = processor.get_trial_statistics(sample.id)
```

## Embedding Support

**Northstar Tier Only**

Include 768-dimensional embedding vectors in the response for both original and reconstructed text.

### Features

- 768D vectors for semantic similarity calculations
- Available for compressed segments only
- Includes embeddings for both original and reconstructed text

### Example Usage

```python
result = processor.process_sample(
    sample,
    include_embeddings=True
)

# Extract embeddings
embeddings = processor.get_embeddings(sample.id)
for seg_idx, data in embeddings.items():
    if 'original' in data:
        print(f"Original: {data['original']['dimensions']}D vector")
```

## Async Processing

Process large documents asynchronously with polling for status updates.

### Endpoints

- `/analyze_begin` - Start async analysis
- `/analyze_status/{task_id}` - Check progress

### Example Usage

```python
# Start async processing
async_result = processor.analyze_async(sample)
task_id = async_result['task_id']

# Poll for completion
status_result = processor.check_async_status(task_id)

# Or use the convenience method
result = processor.process_sample_async(
    sample,
    poll_interval=5.0,  # Check every 5 seconds
    max_wait=1200.0    # Wait up to 20 minutes
)
```

## Additional V2 Parameters

### force_detail_count

Control the exact number of covariant details extracted:

- Standard tier: 3-9 elements
- Northstar tier: Unlimited

```python
result = processor.process_sample(
    sample,
    force_detail_count=12  # Extract exactly 12 details
)
```

### force_single_segment

Process entire input as one segment (default: True):

```python
result = processor.process_sample(
    sample,
    force_single_segment=False  # Allow paragraph segmentation
)
```

### timeout

Custom request timeout (Northstar only):

- Standard tier: Fixed at 60 seconds
- Northstar tier: Default 600s, max 1200s

```python
result = processor.process_sample(
    sample,
    timeout=900  # 15 minutes
)
```

## Command Line Usage

### Basic V2 Features

```bash
# Use comprehensive mode
python hypernym_processor.py --db-path data.sqlite --all \
    --analysis-mode comprehensive

# Apply semantic filters
python hypernym_processor.py --db-path data.sqlite --all \
    --filters '{"purpose": {"exclude": [{"semantic_category": "political", "min_semantic_similarity": 0.35}]}}'

# Force detail count
python hypernym_processor.py --db-path data.sqlite --all \
    --force-detail-count 10

# Include embeddings (Northstar only)
python hypernym_processor.py --db-path data.sqlite --all \
    --include-embeddings

# Process paragraphs separately
python hypernym_processor.py --db-path data.sqlite --all \
    --no-single-segment
```

### Async Processing

```bash
# Use async endpoints
python hypernym_processor.py --db-path data.sqlite --all \
    --async --poll-interval 10 --max-wait 1800
```

### Combined Example

```bash
python hypernym_processor.py \
    --db-path production.sqlite \
    --query "SELECT * FROM documents WHERE length > 1000" \
    --analysis-mode comprehensive \
    --force-detail-count 15 \
    --include-embeddings \
    --filters '{"purpose": {"exclude": [{"semantic_category": "legal advice", "min_semantic_similarity": 0.3}]}}' \
    --timeout 1200 \
    --async \
    --report results_v2.txt
```

## Python API Examples

### Complete V2 Processing Pipeline

```python
from hypernym_processor import HypernymProcessor, Sample

# Initialize
processor = HypernymProcessor('data.sqlite')

# Define sample
sample = Sample(
    id=1,
    content="Your text content here..."
)

# Configure filters
filters = {
    "purpose": {
        "exclude": [
            {"semantic_category": "medical advice", "min_semantic_similarity": 0.3},
            {"semantic_category": "legal advice", "min_semantic_similarity": 0.3}
        ]
    }
}

# Process with all V2 features
result = processor.process_sample(
    sample,
    compression_ratio=0.5,
    similarity=0.8,
    analysis_mode="comprehensive",  # Northstar only
    force_detail_count=10,
    force_single_segment=False,
    include_embeddings=True,  # Northstar only
    filters=filters,
    timeout=900  # 15 minutes
)

if result['success']:
    # Get results
    suggested = processor.get_suggested_text(sample.id)
    compressed = processor.get_compressed_text(sample.id)
    
    # Analyze segments
    segments = processor.get_segment_details(sample.id)
    for seg in segments:
        print(f"Segment: {seg['semantic_category']}")
        print(f"  Details: {seg['detail_count']}")
        print(f"  Compression: {seg['compression_ratio']:.2%}")
        print(f"  Excluded: {seg['excluded_by_filter']}")
    
    # Check filtered content
    filtered = processor.get_filtered_segments(sample.id)
    if filtered:
        print(f"\nFiltered {len(filtered)} segments")
    
    # Get embeddings (Northstar only)
    embeddings = processor.get_embeddings(sample.id)
    
    # Get trial statistics (Northstar comprehensive mode)
    stats = processor.get_trial_statistics(sample.id)
```

### Batch Processing with V2

```python
# Process multiple samples with V2 features
results = processor.process_batch(
    samples,
    analysis_mode="partial",
    force_detail_count=7,
    filters=filters,
    include_embeddings=False,
    batch_size=5,
    cooldown=1.0
)

# Analyze results
successful = [r for r in results if r['success']]
avg_compression = sum(r['compression_ratio'] for r in successful) / len(successful)
```

## Client Tier Comparison

| Feature | Standard Tier | Northstar Tier |
|---------|--------------|----------------|
| Analysis Modes | Partial only | Partial + Comprehensive |
| Timeout | Fixed 60s | 600s default, 1200s max |
| Detail Count | 3-9 | Unlimited |
| Embeddings | No | Yes |
| Trial Statistics | No | Yes (60 trials) |
| Cache Performance | N/A | 37-47x speedup |
| Concurrent Paragraphs | 6 | 128 |
| Rate Limit | 2,000/hour | 64,000/hour |

## Response Structure Updates

The V2 API uses a new response structure:

```json
{
  "metadata": {
    "version": "0.2.0",
    "timestamp": "2024-03-21T00:00:00Z",
    "tokens": {
      "in": 1000,
      "out": 500,
      "total": 1500
    },
    "filters_applied": true,
    "excluded_segments_count": 1
  },
  "request": {
    "content": "...",
    "params": {...},
    "filters": {...}
  },
  "response": {
    "meta": {...},
    "texts": {
      "compressed": "...",
      "suggested": "..."
    },
    "segments": [
      {
        "was_compressed": true,
        "semantic_category": "...",
        "covariant_elements": [...],
        "covariant_details": [...],
        "excluded_by_filter": false,
        "trials": [...]  // Comprehensive mode only
      }
    ]
  }
}
```

The processor automatically detects and handles both V2 and legacy response formats.

## Error Handling

The processor includes comprehensive error handling for V2 features:

- Invalid filter formats
- Out-of-range parameters
- Tier-restricted features
- Async timeout handling
- API version compatibility

## Testing

Run the included test suite to verify V2 features:

```bash
python test_v2_features.py
```

This will test:
- V2 response structure handling
- Semantic filtering
- Force detail count
- Embeddings (Northstar only)
- Comprehensive mode (Northstar only)
- Async endpoints
- Edge cases and error handling

## Migration Notes

When upgrading from V1:

1. **Response Structure**: The processor automatically handles both formats
2. **New Parameters**: All V2 parameters are optional and backward compatible
3. **Database Schema**: No changes required to existing tables
4. **Caching**: Cache keys include V2 parameters for proper invalidation

## Support

For questions about V2 features:
- Standard tier: support@hypernym.ai
- Northstar tier: northstar-support@hypernym.ai
- Documentation: https://hypernym.ai/docs