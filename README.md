# Portable Hypernym Processor

A high-performance, standalone tool for processing text samples from any SQLite database through the Hypernym compression API. Features massive parallel processing capabilities with an elegant, scrollable terminal interface that can handle hundreds of concurrent workers.

## Key Features

### 🚀 Performance & Scalability
- **Massive parallel processing**: Handle 256+ concurrent workers efficiently
- **Adaptive concurrency**: Automatically adjusts workers based on API rate limits
- **Smart caching**: Skip already-processed samples automatically
- **Batch processing**: Process entire books or databases in one command
- **Rate limit handling**: Automatic backoff and retry with visual feedback

### 🎨 Beautiful Terminal Interface
- **Scrollable worker display**: Monitor unlimited workers with keyboard navigation
- **Real-time statistics**: Live compression ratios, similarity scores, and processing rates
- **Visual progress tracking**: Individual progress bars for each worker
- **Performance meters**: Animated compression and similarity score displays
- **High score tracking**: Best compression and similarity achievements

### 🔧 Flexible Processing
- **Multiple selection modes**: Process by ID, book, custom query, or entire database
- **SQL query support**: Use any SQL query to select samples
- **Multi-segment support**: Handles documents split into semantic segments
- **Semantic similarity tracking**: Monitor meaning preservation (0-100%)
- **Error resilience**: Comprehensive error handling with detailed logging

## How It Works: Complete Workflow Example

### General Workflow

The Hypernym processor is designed to work with existing SQLite databases in a non-destructive, additive way:

1. **Initial Database Creation** (your responsibility):
   - Create SQLite with your text data
   - Must have columns: `id` (unique) and `content`/`text` 
   - Can include any additional metadata columns
   - No minimum text length required with v2 API

2. **Hypernym Processing** (this tool):
   - Reads text from your database
   - Sends to Hypernym API for semantic compression
   - **Adds new tables** to store results (never modifies originals)
   - Creates `hypernym_responses` table with API responses
   - Caches results to avoid reprocessing

3. **Result Structure**:
   - Original data remains untouched
   - New data is added in separate tables
   - Everything is traceable and reversible

### Real Example: LongBench Case Study

LongBench is a benchmark for testing language models on extremely long documents (8k-2M words). It's a perfect use case for Hypernym compression because:
- Documents are too long for most models to process
- Need to preserve meaning for question-answering tasks
- Contains diverse content: code repositories, legal documents, literature, scientific papers

Here's how we used this processor for LongBench:

#### 1. Initial SQLite Creation
```bash
# LongBench is a dataset of massive documents paired with questions
# Someone created an SQLite database from it with this structure:
# 
# Original: "Here's a 500-page novel. Question: Who killed the butler?"
# ↓
# In this example, text was pre-chunked into paragraphs
# With v2 API, chunking is optional - you can process entire documents
# For custom chunking strategies, contact: hi@hypernym.ai
#
# Resulting SQLite tables:
# - samples: id, content (the paragraph), word_count, is_valid
# - sample_metadata: question, answer choices, domain (like "Code Repository Understanding")
```

#### 2. Run Hypernym Processor
```bash
cd portable_hypernym_processor
python hypernym_processor.py --db-path ../longbench.sqlite --all --max-samples 100
```

#### 3. What Gets Added to SQLite
The processor adds:
- `hypernym_responses`: Raw API responses (JSON)
- Compression results for each chunk
- Never touches original `samples` or `sample_metadata` tables

#### 4. Actual Hypernym Output Example

Here's a real hypernym string from a code documentation sample:

```
[SEGMENT 1 | similarity: 0.42] Evolution of financial trading systems.::0=evolved significantly over the past century;1=revolutionized buying and selling of securities;2=introduced by Harry Markowitz for risk management;3=dominates markets with high-frequency transactions
```

Breaking this down:
- **Semantic Category**: "Evolution of financial trading systems." 
- **Covariant Details** (in hyperstring format):
  - 0=evolved significantly over the past century
  - 1=revolutionized buying and selling of securities
  - 2=introduced by Harry Markowitz for risk management
  - 3=dominates markets with high-frequency transactions
- **Similarity**: 0.42 (42% of original meaning preserved)

### Complete Data Flow Example

Example: Processing a code repository from LongBench (sample `66fa208bbb02136c067c5fc1`):

```
1. WHAT THE PROCESSOR SEES IN THE DATABASE:
   samples table:
   - id: "66fa208bbb02136c067c5fc1_100"
   - content: "def hypsum(ctx, p, q, types, coeffs..."
   - word_count: 287
   - is_valid: 1

2. PROCESSOR SENDS TO HYPERNYM API:
   {
     "essay_text": "def hypsum(ctx, p, q, types, coeffs...",
     "params": {
       "min_compression_ratio": 0.6,
       "min_semantic_similarity": 0.75
     }
   }

3. API RETURNS:
   {
     "results": {
       "response": {
         "segments": [{
           "semantic_category": "Numerical series convergence calculation function.",
           "covariant_details": [
             {"n": 0, "text": "hypsum identifies the convergence calculation method"},
             {"n": 1, "text": "ctx, p, q, types, coeffs, z, maxterms, kwargs"},
             {"n": 2, "text": "abs(t) < tol defines when to stop the loop"},
             {"n": 3, "text": "ctx.NoConvergence raised if maxterms exceeded"}
           ],
           "semantic_similarity": 0.42,
           "compression_ratio": 0.43
         }]
       }
     }
   }

4. PROCESSOR STORES IN hypernym_responses TABLE:
   - sample_id: "66fa208bbb02136c067c5fc1_100"
   - response_data: [full JSON above]
   - compression_ratio: 0.43
   - processing_time: 1.23

5. WHEN YOU CALL processor.get_hypernym_string():
   Returns: "[SEGMENT 1 | similarity: 0.42] Numerical series convergence calculation function.::0=hypsum identifies the convergence calculation method;1=ctx, p, q, types, coeffs, z, maxterms, kwargs;2=abs(t) < tol defines when to stop the loop;3=ctx.NoConvergence raised if maxterms exceeded"
```

### Key Points

1. **Non-destructive**: Original data never modified
2. **Traceable**: Can always map: original → chunks → compressed
3. **Flexible**: Works with any SQLite schema
4. **Cached**: Rerun without hitting API again

## Installation

### Requirements

```bash
pip install -r requirements.txt
```

This installs:
- `requests` - HTTP client for API calls
- `tqdm` - Progress bars (legacy, kept for compatibility)
- `python-dotenv` - Environment variable management
- `rich` - Beautiful terminal UI with parallel progress display
- `aiohttp` - Async HTTP for concurrent API requests
- `asyncio-throttle` - Rate limiting support
- `aiosqlite` - Async SQLite operations

### Environment Variables

Copy `.env.example` to `.env` and fill in your API credentials:

```bash
cp .env.example .env
# Edit .env with your actual API key
```

The `.env` file should contain:
```bash
HYPERNYM_API_KEY=your_api_key_here
HYPERNYM_API_URL=https://fc-api-development.hypernym.ai/analyze_sync
```

**⚠️ CRITICAL: Working Directory Requirement**

**YOU MUST RUN ALL COMMANDS FROM INSIDE THE `portable_hypernym_processor` DIRECTORY!**

```bash
# CORRECT - CD into the directory first:
cd portable_hypernym_processor
python hypernym_processor.py --db-path data.sqlite --sample-ids 1,2,3

# WRONG - Running from parent directory WILL NOT WORK:
python portable_hypernym_processor/hypernym_processor.py ...
```

The `.env` file MUST be in the same directory where you run the command. The script loads environment variables from `.env` in the current working directory only.

## Visual Interface

When you run the processor, you'll see a stunning real-time display that scales to any number of workers:

```
╭────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│                                                          HYPERNYM Parallel Processor                                                           │
│                                                            2025-08-05 15:42:37                                                                 │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭───────────────────────────────────────────────────────────────────────────────────────────────────────────╮╭──── 📊 Performance Meters 📊 ─────╮
│ ⠙ Overall Progress ████████████████████████████████████████████████████░░░░░░░░░░░░  78% • 0:12:34 • 0:03:21 ││                                   │
╰───────────────────────────────────────────────────────────────────────────────────────────────────────────╯│   ╔═══════════════════════════╗   │
╭─────────────────────────────────────────── Workers [21-40/256] ───────────────────────────────────────────╮│   ║ ⚡ COMPRESSION POWER ⚡   ║   │
│  Worker 21 ⠋ ████████████████████████████ 100% Sample #1234 [green](done)[/green]                          ││   ╠═══════════════════════════╣   │
│  Worker 22 ⠋ ████████████████░░░░░░░░░░░  67% Sample #5678                                                ││   ║ [████████               ] ║   │
│  Worker 23 ⠙ ██████████░░░░░░░░░░░░░░░░░  42% Sample #9012                                                ││   ║            40.2%          ║   │
│  Worker 24 ⠹ ████████████████████░░░░░░░  83% Sample #3456                                                ││   ╚═══════════════════════════╝   │
│  Worker 25 ⠸ ░░░░░░░░░░░░░░░░░░░░░░░░░░░   0% Starting...                                                 ││                                   │
│  Worker 26 ⠼ ████████████████████████████ 100% Sample #7890 [yellow](cached)[/yellow]                      ││   ╔═══════════════════════════╗   │
│  Worker 27 ⠴ ██████░░░░░░░░░░░░░░░░░░░░░  25% Sample #2468                                                ││   ║ 💎 SIMILARITY SHIELD 💎   ║   │
│  Worker 28 ⠦ ████████████████████████░░░  92% Sample #1357                                                ││   ╠═══════════════════════════╣   │
│  Worker 29 ⠧ ████████████░░░░░░░░░░░░░░░  50% Sample #8642                                                ││   ║ [██████████             ] ║   │
│  Worker 30 ⠇ ████████████████████████████ 100% Sample #9753 [green](done)[/green]                          ││   ║            54.2%          ║   │
│  Worker 31 ⠏ ░░░░░░░░░░░░░░░░░░░░░░░░░░░   8% Sample #1593                                                ││   ╚═══════════════════════════╝   │
│  Worker 32 ⠋ ████████████████████░░░░░░░  75% Sample #7531                                                ││                                   │
│  Worker 33 ⠙ ██████████████░░░░░░░░░░░░░  58% Sample #2846                                                ││   Historical samples: 125,847     │
│  Worker 34 ⠹ ████████████████████████████ 100% Sample #9517 [magenta](rate limited)[/magenta]            ││                                   │
│  Worker 35 ⠸ ██████████████████░░░░░░░░░  71% Sample #3579                                                ││                                   │
│  Worker 36 ⠼ ████░░░░░░░░░░░░░░░░░░░░░░░  17% Sample #6284                                                ││   ★ MEGA COMBO ACTIVE ★           │
│  Worker 37 ⠴ ████████████████████████████ 100% Sample #1628 [green](done)[/green]                          ││                                   │
│  Worker 38 ⠦ ████████████████████░░░░░░░  79% Sample #7395                                                ││                                   │
│  Worker 39 ⠧ ██████████████████████████░░  96% Sample #8527                                                ││                                   │
│  Worker 40 ⠇ ████████░░░░░░░░░░░░░░░░░░░  33% Sample #4826                                                ││                                   │
╰────────────────────────────────── ↑/↓: scroll 1 | PgUp/PgDn: scroll 18 ───────────────────────────────────╯╰───────────────────────────────────╯
╭───────────────────────────── Statistics ──────────────────────────────╮╭────────────────────────── 🏆 High Scores 🏆 ──────────────────────────╮
│                                                                       ││             🏆 COMPRESSION            🏆 SIMILARITY                    │
│                       ✓ Processed       98,432                        ││             Best: 99.7%               Best: 100.0%                    │
│                       ⚡ Cache Hits     45,218                        ││             ║----====▓▓▓▓▓====----    ----====▓▓▓▓▓▓▓===----         │
│                       ✗ Errors          126                           ││             0%        50%      100%   0%        50%       100%        │
│                       ⏱ Rate Limited    43                            ││             [Min: 12%  Avg: 40%  Max: 99%]  [Min: 15%  Avg: 54%  Max: 100%] │
│                       ⚡ Rate           186.3/sec                      ││                                                                       │
│                       👷 Workers        192/192                        ││             Total samples: 125,847                                    │
│                                                                       ││                                                                       │
╰───────────────────────────────────────────────────────────────────────╯╰───────────────────────────────────────────────────────────────────────╯
```

### Interface Features

#### 🎮 Keyboard Controls
- **↑/↓ arrows**: Scroll through workers one at a time
- **PgUp/PgDn**: Scroll by 18 workers (full page)
- **Position indicator**: Shows current view range `[21-40/256]`
- **Auto-adjusting**: Window size adapts to terminal height

#### 📊 Live Performance Meters
- **Compression Power**: Animated gauge showing average compression ratio
- **Similarity Shield**: Animated gauge showing semantic preservation
- **Mega Combo**: Activates when both metrics exceed thresholds
- **Historical tracking**: Running statistics from all processed samples

#### 🏆 High Scores Display
- **Distribution visualization**: ASCII art violin plots of compression/similarity
- **Min/Avg/Max indicators**: Statistical summary of performance
- **Best achievements**: Track record compression and similarity scores
- **Total samples**: Running count of all processed samples

### Adaptive Concurrency

The processor automatically:
1. **Queries your API rate limits** at startup
2. **Starts conservatively** with 50% of recommended workers
3. **Scales up** when performance is good
4. **Scales down** immediately on rate limits or errors
5. **Shows current/max workers** in the statistics panel

## Usage

**Remember: ALL commands must be run from inside the `portable_hypernym_processor` directory!**

### Basic Examples

1. **Process specific samples by ID:**
```bash
cd portable_hypernym_processor  # ALWAYS CD INTO THE DIRECTORY FIRST
python hypernym_processor.py --db-path data.sqlite --sample-ids 1,2,3,4,5
```

2. **Process an entire book by ID:**
```bash
python hypernym_processor.py --db-path gutenberg_books.db --book-id 120
```

3. **Process samples using custom SQL query:**
```bash
python hypernym_processor.py --db-path data.sqlite \
  --query "SELECT id, content FROM samples WHERE category='literature' LIMIT 10"
```

4. **Process all samples with massive parallelism:**
```bash
python hypernym_processor.py --db-path data.sqlite --all --max-workers 256
```

### Scrollable Interface Examples

```bash
# Process with 50 workers (scrollable display)
python hypernym_processor.py --db-path data.sqlite --all --max-workers 50

# Process with 256 workers, show 30 at a time
python hypernym_processor.py --db-path data.sqlite --all --max-workers 256 --max-display-workers 30

# Process specific book with maximum parallelism
python hypernym_processor.py --db-path gutenberg_books.db --book-id 1342 --max-workers 192
```

### Advanced Options

```bash
python hypernym_processor.py \
  --db-path /path/to/database.sqlite \
  --query "SELECT * FROM documents WHERE word_count > 500" \
  --compression 0.7 \
  --similarity 0.8 \
  --batch-size 10 \
  --cooldown 1.0 \
  --batch-cooldown 5.0 \
  --timeout 60 \
  --max-retries 5 \
  --no-cache \
  --report processing_report.txt
```

### Parameters

#### Required (one of):
- `--sample-ids`: Comma-separated list of sample IDs to process
- `--book-id`: Process all samples from a specific book ID
- `--query`: Custom SQL query (must return 'id' and 'content' columns)
- `--all`: Process all samples in the table

#### Database Options:
- `--db-path`: Path to SQLite database (required)
- `--table`: Table name containing samples (default: 'samples')

#### Parallel Processing:
- `--max-workers`: Maximum concurrent workers (default: 4, auto-adjusts based on API limits)
- `--max-display-workers`: Maximum workers to show in scrollable display (default: 20)

#### Processing Parameters:
- `--compression`: Target compression ratio (default: 0.6)
- `--similarity`: Target semantic similarity (default: 0.75)
- `--batch-size`: Number of samples per batch (default: 5)
- `--cooldown`: Seconds to wait between samples (default: 0.5)
- `--batch-cooldown`: Seconds to wait between batches (default: 2.0)
- `--timeout`: API timeout in seconds (default: 30)
- `--max-retries`: Maximum retry attempts (default: 3)
- `--max-samples`: Maximum samples to process

#### V2 API Parameters:
- `--analysis-mode`: Analysis depth - `partial` (default) or `comprehensive` (Northstar only)
- `--force-detail-count`: Force specific number of details (3-9 standard, unlimited Northstar)
- `--no-single-segment`: Process paragraphs separately instead of as single segment
- `--include-embeddings`: Include 768D embedding vectors (Northstar only)
- `--filters`: JSON string with semantic filters to exclude content

#### Other Options:
- `--no-cache`: Disable cache lookup
- `--report`: Save processing report to file
- `--api-key`: Override environment variable
- `--api-url`: Override environment variable

## Database Schema

The tool expects a table with at least these columns:
- `id`: Unique identifier (INTEGER)
- `content` or `text`: The text to process (TEXT)

Additional columns are preserved as metadata.

### Results Table

The tool creates a `hypernym_responses` table to cache results:

```sql
CREATE TABLE hypernym_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id INTEGER NOT NULL,
    request_hash TEXT NOT NULL,
    response_data TEXT NOT NULL,
    compression_ratio REAL,
    processing_time REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sample_id, request_hash)
)
```

## Examples

### Project Structure

```
portable_hypernym_processor/
├── README.md                      # This file
├── requirements.txt               # Python dependencies
├── .env.example                   # Example environment variables
│
├── hypernym_processor.py          # Main processor module
├── processing_queue.py            # Queue management for batch processing
├── queue_worker.py               # Worker for processing queues
│
├── examples/                      # Example scripts
│   ├── api_integration.py        # v2 API features demonstration
│   ├── data_converter.py         # Data conversion patterns
│   └── README.md                 # Examples documentation
│
├── tests/                         # Test files
│   ├── test_*.py                 # Unit and integration tests
│   └── reference_calls/          # API reference implementations
│
├── docs/                          # Additional documentation
│   └── flow_diagram.txt          # System architecture diagram
│
└── __production_steps/            # Development history
```

### Example Files

The `examples/` directory contains scripts to help you get started:

- **`api_integration.py`** - Shows how to use the processor with v2 API features, including the standard test strings
- **`data_converter.py`** - Demonstrates how to convert data from various sources (JSON, CSV, existing SQLite) into the samples table format

Run these examples to see the processor in action:
```bash
cd portable_hypernym_processor
python examples/api_integration.py  # See v2 API features
python examples/data_converter.py   # Learn data conversion patterns
```

### Working with Different Table Structures

If your table has different column names:

```bash
cd portable_hypernym_processor  # CD INTO DIRECTORY FIRST!
# For a table with 'document_id' and 'full_text' columns
python hypernym_processor.py --db-path corpus.sqlite \
  --query "SELECT document_id as id, full_text as content FROM documents LIMIT 50"
```

### Filtering and Processing

```bash
# Process only unprocessed samples
python hypernym_processor.py --db-path data.sqlite \
  --query "SELECT s.* FROM samples s LEFT JOIN hypernym_responses h ON s.id = h.sample_id WHERE h.id IS NULL"

# Process samples from specific date range
python hypernym_processor.py --db-path data.sqlite \
  --query "SELECT * FROM samples WHERE created_at >= '2025-01-01' AND created_at < '2025-02-01'"
```

### Integration with Existing Workflows

```python
import subprocess
import json
import os

# CRITICAL: Change to the correct directory first!
os.chdir('portable_hypernym_processor')

# Run processor and capture output
result = subprocess.run([
    'python', 'hypernym_processor.py',
    '--db-path', 'my_data.sqlite',
    '--sample-ids', '1,2,3',
    '--report', 'results.txt'
], capture_output=True, text=True)

# Check results in database
import sqlite3
conn = sqlite3.connect('my_data.sqlite')
responses = conn.execute(
    "SELECT * FROM hypernym_responses WHERE sample_id IN (1,2,3)"
).fetchall()
```

## Processing Queue System

The queue system (`processing_queue.py`) enables batch job management and multi-worker processing:

### Queue Basics

```python
from processing_queue import ProcessingQueue

# Initialize queue
queue = ProcessingQueue('data.sqlite')

# Add work
batch_id = queue.add_batch(
    "Literature samples", 
    "SELECT * FROM samples WHERE category='literature'"
)

# Get next work item
batch = queue.get_next_pending()

# Mark complete
queue.mark_complete(batch_id, processed_count=10, error_count=0)
```

### Using the Queue Worker

```bash
# Add sample batches to queue
python queue_worker.py add data.sqlite

# Run worker (processes queue continuously)
python queue_worker.py run data.sqlite

# Check queue status
python queue_worker.py status data.sqlite
```

### Queue Features

- **Atomic work assignment** - Multiple workers won't process same batch
- **Status tracking** - pending → processing → completed/failed
- **Resume on failure** - Restart workers anytime
- **Progress visibility** - See what's done and what's pending

### Important: Metadata for Processing Control

When using the queue system, **metadata must be written to the database WITH the sample** before the queue worker picks it up. The metadata controls how each sample is processed (sync/async, timeout, analysis mode, etc.).

```sql
-- Example: Insert sample with processing metadata
INSERT INTO samples (id, content, processing_mode, timeout, analysis_mode, compression_ratio) 
VALUES (
    1, 
    'Your text content here...', 
    'async',         -- Process asynchronously
    120,             -- 2 minute timeout
    'comprehensive', -- Use comprehensive mode (Northstar only)
    0.5              -- Target 50% compression
);
```

Any columns beyond `id` and `content` automatically become metadata on the Sample object. If you add metadata after insertion, the queue worker may already be processing the sample with default settings.

### Example Workflow

```bash
# 1. Add batches to process
python processing_queue.py add "Recent docs" "SELECT * FROM documents WHERE date > '2025-01-01'"
python processing_queue.py add "Unprocessed" "SELECT d.* FROM documents d LEFT JOIN hypernym_responses h ON d.id = h.sample_id WHERE h.id IS NULL"

# 2. Run workers (can run multiple)
python queue_worker.py run &  # Worker 1
python queue_worker.py run &  # Worker 2

# 3. Monitor progress
python queue_worker.py status
```

## Performance Considerations

### 🚀 Parallel Processing at Scale

The processor is designed for massive parallelism:

1. **Auto-scaling Workers**: 
   - Queries your API rate limits at startup
   - Starts conservatively (50% of max)
   - Scales up when performance is good
   - Scales down on errors or rate limits

2. **Optimal Worker Counts**:
   - **Standard tier**: 4-16 workers typical
   - **Northstar tier**: 96-192 workers recommended
   - **Testing**: We've successfully run 256+ workers

3. **Scrollable Display**: 
   - Shows 20 workers by default
   - Use keyboard to navigate through all workers
   - Minimal performance impact even with 256+ workers

### ⚡ Performance Tips

1. **Start Big**: Don't be afraid to use many workers - the system self-regulates
   ```bash
   python hypernym_processor.py --db-path data.sqlite --all --max-workers 192
   ```

2. **Cache Strategy**: First run caches results, subsequent runs are lightning fast
   ```bash
   # First run: processes everything
   python hypernym_processor.py --db-path data.sqlite --all --max-workers 96
   
   # Second run: skips cached results, only processes new/failed
   python hypernym_processor.py --db-path data.sqlite --all --max-workers 96
   ```

3. **Timeout Tuning**: 
   - Default 30s works for most content
   - Use 60-120s for very long documents
   - Server returns 408 for problematic content (not real timeouts)

4. **Display Performance**:
   - Scrolling is smooth even with 256 workers
   - Only visible workers update (performance optimization)
   - Keyboard input handled in separate thread

## Error Handling

### Robust Error Management

The processor handles errors gracefully without stopping:

1. **Automatic Retries**: Exponential backoff with jitter for transient failures
2. **Error Tracking**: All errors saved to `error_entries` table with details
3. **Visual Feedback**: Color-coded status in worker display
   - 🟢 `[green](done)[/green]` - Successfully processed
   - 🟡 `[yellow](cached)[/yellow]` - Retrieved from cache
   - 🟣 `[magenta](rate limited)[/magenta]` - Hit rate limit, will retry
   - 🔴 `[red](failed: reason)[/red]` - Processing failed

4. **Common Error Types**:
   - **408 Timeout**: Usually content moderation blocks (not real timeouts)
   - **429 Rate Limit**: Automatic backoff and retry
   - **500 Server Error**: Logged and skipped
   - **Connection Error**: Retried with exponential backoff

### Error Analysis

Check errors after processing:
```sql
-- View recent errors
SELECT sample_id, error_type, error_message, created_at 
FROM error_entries 
ORDER BY created_at DESC 
LIMIT 20;

-- Count errors by type
SELECT error_type, COUNT(*) as count 
FROM error_entries 
GROUP BY error_type 
ORDER BY count DESC;

-- Find samples that consistently fail
SELECT sample_id, COUNT(*) as attempts 
FROM error_entries 
GROUP BY sample_id 
HAVING attempts > 3;
```

## Understanding Hypernym Compression

### What is Hypernym?

Hypernym is a semantic compression API that reduces text while preserving meaning. It works by:
1. Breaking text into semantic segments
2. Extracting the core meaning (semantic category/hypernym)
3. Preserving key details (covariant details)
4. Measuring how well the compressed version preserves the original meaning

### Compression Parameters

- **min_compression_ratio** (0.0-1.0): Target compression level
  - 0.6 = Keep 60% of original size (40% reduction)
  - Lower values = more compression
  
- **min_semantic_similarity** (0.0-1.0): Meaning preservation threshold
  - 0.75 = Preserve at least 75% of original meaning
  - Higher values = better fidelity but less compression

### Complete Python API Example

Here's how to process new text programmatically:

```python
from hypernym_processor import HypernymProcessor, Sample
import sqlite3

# Initialize processor
processor = HypernymProcessor('my_data.db')

# Add text to the samples table
text = "Your long document text here..."
with sqlite3.connect('my_data.db') as conn:
    cursor = conn.execute(
        "INSERT INTO samples (content) VALUES (?)",
        (text,)
    )
    sample_id = cursor.lastrowid

# Process the sample
sample = Sample(id=sample_id, content=text)
result = processor.process_sample(sample)

if result['success']:
    # Get the hypernym string representation
    hypernym = processor.get_hypernym_string(sample_id)
    print(f"Hypernym: {hypernym}")
    
    # Get the suggested text (API's recommendation)
    suggested = processor.get_suggested_text(sample_id)
    print(f"Suggested: {suggested}")
    
    # Get the compressed text (all hyperstrings)
    compressed = processor.get_compressed_text(sample_id)
    print(f"Compressed: {compressed}")
```

### Understanding the Hypernym String Format

The processor returns a display format that shows:
```
[SEGMENT N | similarity: X.XX] Semantic category.: detail 1; detail 2; detail 3; detail 4
```

Breaking it down:
- **[SEGMENT N]** - Segment number (1, 2, 3, etc.)
- **similarity: X.XX** - How much meaning was preserved (0.00 to 1.00)
- **Semantic category.** - The 6-word hypernym ending with period
- **detail 1; detail 2; ...** - Covariant details separated by semicolons

Real example:
```
[SEGMENT 1 | similarity: 0.83] Evolution of financial trading systems.: evolved significantly over the past century; revolutionized buying and selling of securities; introduced by Harry Markowitz for risk management; dominates markets with high-frequency transactions
```

Note: This is the display format. The actual hyperstring format returned by the API is:
```
Semantic Category::1=element one;2=element two;3=element three;4=element four
```

Example:
```
Financial markets and theory evolution::1=complex systems;2=mathematical models;3=behavioral insights;4=technological innovation
```

### Why Short Text Returns Only Semantic Category

When text is very short (like "Test text to process"), the API:
1. Can't compress it further without losing meaning
2. Returns `was_compressed: false`
3. Provides only a semantic category with no covariant details
4. Shows `compression_ratio: 1.0` (no compression)

Example with short text:
```
Input: "Test text to process"
Output: [SEGMENT 1 | similarity: 1.00] Text processing task
```

For meaningful compression, text should be at least a paragraph (50+ words). The API needs enough content to extract patterns and create useful compressions.

### Retrieving Results After Processing

```python
# Get the suggested text (what to actually use - API's recommendation)
suggested = processor.get_suggested_text(sample_id)

# Get the compressed text (all hyperstrings - shows everything attempted)
compressed = processor.get_compressed_text(sample_id)

# Get the hypernym representation (semantic structure)
hypernym = processor.get_hypernym_string(sample_id)
# Real example outputs:
# [SEGMENT 1 | similarity: 0.42] Numerical series convergence calculation function.: hypsum identifies the convergence calculation method; ctx, p, q, types, coeffs, z, maxterms, kwargs; abs(t) < tol defines when to stop the loop; ctx.NoConvergence raised if maxterms exceeded
# [SEGMENT 2 | similarity: 0.79] Literary narrative with character development.: protagonist enters mysterious library; ancient books contain forgotten knowledge; discovers hidden magical abilities; transforms understanding of reality

# Get segment details
segments = processor.get_segment_details(sample_id)
# Returns: [{'semantic_category': 'INTRO', 'compression_ratio': 0.34, 'semantic_similarity': 0.82, ...}]

# Get average semantic similarity
avg_similarity = processor.get_average_semantic_similarity(sample_id)
# Returns: 0.805 (80.5% meaning preserved)
```

### Multi-Segment Handling

By default, the processor now uses `force_single_segment=True` to process entire documents as one unit. This gives you full control over how your text is chunked - you can pre-process and segment your data according to your specific needs before sending to the API.

When `force_single_segment=False`, the API will automatically split long documents into semantic segments. Each segment:
- Has its own semantic category (the hypernym)
- Contains ordered covariant details
- Includes compression ratio and semantic similarity scores
- Preserves document structure (intro → main points → conclusion)

For guidance on optimal chunking strategies for your use case, contact: hi@hypernym.ai

### When Compression Fails

If the API cannot achieve the requested compression while maintaining the similarity threshold:
- The `texts.suggested` field contains the ORIGINAL text unchanged
- Check the actual compression_ratio to know if compression occurred
- Lower the similarity threshold or increase the compression ratio to allow more aggressive compression

## What We've Built

The Portable Hypernym Processor represents a significant evolution in text processing tools:

### 🏗️ Architecture Highlights
- **Massively Parallel**: Successfully tested with 256+ concurrent workers
- **Scrollable Interface**: iOS-style smooth scrolling through unlimited workers
- **Real-time Monitoring**: Live statistics, performance gauges, and progress tracking
- **Intelligent Scaling**: Auto-adjusts concurrency based on API limits and performance
- **Production Ready**: Comprehensive error handling, caching, and retry logic

### 🎯 Use Cases
- **Large Dataset Processing**: Process millions of samples efficiently
- **Book Analysis**: Compress entire books with `--book-id` parameter
- **Research Workflows**: Flexible SQL queries for custom sample selection
- **Benchmark Creation**: Build compression benchmarks across different text types
- **API Testing**: Stress test with massive parallelism while monitoring performance

### 🔮 Future Directions
- **Distributed Processing**: Multi-machine coordination for even larger datasets
- **Real-time Streaming**: Process live text streams as they arrive
- **Advanced Analytics**: Deeper compression pattern analysis and visualization
- **Plugin System**: Extensible architecture for custom processors

### 📞 Contact & Support
- **Technical Issues**: Create an issue in the repository
- **API Access**: Contact hi@hypernym.ai
- **Feature Requests**: Open a discussion with your use case

---

*Built with ❤️ for the semantic compression community*