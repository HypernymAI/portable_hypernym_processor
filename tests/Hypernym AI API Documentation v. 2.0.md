# **HYPERNYM** 

# **🧠 Hypernym AI API Documentation**

**Website:** [https://hypernym.ai](https://hypernym.ai)  
 **Last Updated:** 2025-07-20  
 **API Version:** 0.2.0

---

## **🚀 What We Do**

Hypernym AI's API offers a **structured, efficient** way to analyze and categorize text by assigning each paragraph into precise semantic categories, almost like sorting content into an intelligent hash table. Here's how it works:

1. **🔍 Semantic Categorization**  
    The API maps each paragraph into a specific "bucket" based on its central theme. This provides a clear, organized structure for dense content.

2. **🪶 Adaptive Compression**  
    By calculating optimal "compression ratios," the API distills each paragraph to its core meaning. This enables users to retain critical content while reducing text volume—perfect for summarization or recommendation engines.

3. **📏 Precision Similarity Scoring**  
    The API measures each paragraph's alignment with its semantic category, offering a "proximity score" that reveals core content density and any digressions. This turns the document into a structured matrix, ideal for indexing and clustering tasks.

4. **📌 Key Detail Extraction**  
    Each paragraph is distilled into key covariant points, giving a quick, theme-aligned summary. Downstream NLP models or content systems can tap the text's essential info without extensive reprocessing.

5. **🧠 Semantic Filtering (Hypernym API)**  
    The API supports advanced semantic filtering. You can define categories—like "political" or "investment advice"—and the system will **exclude** content closely aligned with those categories from the **suggested** output. This uses embedding-based logic under the hood but is fully automatic once you specify filters.

6. **⚡ Advanced Caching System**  
    Comprehensive mode features intelligent caching that provides 37-47x speedup on repeated requests. First run takes ~5-6 minutes for full 60-trial analysis, while cached runs complete in just 7-9 seconds with 100% cache hit rate.

In short, Hypernym AI provides a **clear, compressed, and categorically sorted** overview of complex text, making it ideal for applications needing quick, accurate content understanding.

**Join our API waitlist\!** Signup now at [https://hypernym.ai](https://hypernym.ai)

---

## **💻 Prerequisites**

Some commands in the examples use `jq` for JSON processing. Install it as follows:

macOS

```
brew install jq
```

Ubuntu/Debian

```
sudo apt-get install jq
```

---

## **🏷️ How to Use It – Compressing with the Hypernym API**

### **API Endpoint**

* **URL:** `https://fc-api-development.hypernym.ai/analyze_sync`

* **Method:** `POST`

* **Description:** Analyzes the provided essay text **synchronously** and returns semantic analysis results.

### **Headers**

```
Content-Type: application/json
X-API-Key: your_api_key_here
```

*(Replace with your actual API key.)*

### **Client Tiers**

#### **Standard Tier**
- Access to partial analysis mode
- Basic compression parameters
- 60-second timeout for requests
- force_detail_count limited to 3-9 elements
- Suitable for most applications

#### **Northstar Tier**
- Full access to all features including comprehensive mode
- Extended timeout support (default 10 minutes, up to 20 minutes)
- Unlimited force_detail_count range
- Priority processing and higher rate limits
- Advanced experimental parameters
- 37-47x speedup on cached comprehensive requests

### **Request Body Parameters**

* `essay_text` *(string, required)*: The text of the essay to be analyzed.

* `params` *(object, optional)*:

  * `min_compression_ratio` *(float, default: 1.0)* — Minimum compression ratio to consider for suggested output.

    * `1.0` = no compression

    * `0.8` = 20% compression

    * `0.0` = 100% compression

  * `min_semantic_similarity` *(float, default: 0.0)* — Minimum semantic similarity to consider for suggested output.
  
  * `force_single_segment` *(boolean, default: false)* — Treats entire input as a single segment instead of splitting by paragraphs.
  
  * `force_detail_count` *(integer)* — Forces specific number of covariant details per segment. 
    * Standard tier: Limited to 3-9 elements
    * Northstar tier: Any positive integer
    * If not specified: Automatic element selection based on content

  * `analysis_mode` *(string, default: "partial")* — Analysis depth control
    * `"partial"`: Single-pass analysis for quick results (2-5s/paragraph)
    * `"comprehensive"` (Northstar only): 60-trial multi-pass analysis for maximum accuracy (~5-6 minutes uncached, 7-9 seconds cached)

  * `timeout` *(integer, Northstar only)* — Custom request timeout in seconds
    * Standard tier: Fixed at 60 seconds
    * Northstar tier: Default 600 seconds (10 minutes), maximum 1200 seconds (20 minutes)

  * `include_embeddings` *(boolean, default: false, Northstar only)* — Include embedding vectors in response
    * Standard tier: Always false (parameter ignored if provided)
    * Northstar tier: When true, adds 768-dimensional embedding vectors to compressed segments
    * Embeddings included for both original and reconstructed text in compressed segments only
    * Not included for uncompressed segments regardless of setting

### **Example Request Body**

```json
{
  "essay_text": "Computational Complexity Theory is a fundamental field within theoretical computer science...",
  "params": {
    "min_compression_ratio": 0.5,
    "min_semantic_similarity": 0.8,
    "analysis_mode": "partial",
    "force_detail_count": 5
  }
}
```

### **Northstar Comprehensive Mode Example**

```json
{
  "essay_text": "Quantum computing represents a paradigm shift in computational capabilities. Unlike classical computers that use bits representing either 0 or 1, quantum computers utilize qubits that can exist in superposition states. This fundamental difference enables quantum computers to process vast amounts of information simultaneously, potentially solving certain problems exponentially faster than classical computers. Applications include cryptography, drug discovery, financial modeling, and optimization problems that are intractable for traditional computing systems.",
  "params": {
    "analysis_mode": "comprehensive",
    "timeout": 900,  // 15-minute timeout (default is 10 minutes)
    "force_detail_count": 12  // Northstar can use any count
  }
}
```

### **Northstar Embeddings Example**

```json
{
  "essay_text": "The evolution of artificial intelligence represents one of the most transformative technological developments in human history. From its theoretical foundations in the 1950s to today's sophisticated neural networks, AI has progressed from simple rule-based systems to complex models capable of understanding natural language, recognizing patterns, and even generating creative content. Machine learning algorithms now power recommendation systems that shape our daily experiences, from the videos we watch to the products we purchase.",
  "params": {
    "min_compression_ratio": 0.5,
    "min_semantic_similarity": 0.8,
    "include_embeddings": true,  // Request embedding vectors (Northstar only)
    "force_detail_count": 5
  }
}
```

---

## **📏 Text Length Categories**

### **Processing Zones**

* **Zone 1 - Micro** (< 6 words): Semantic category only - experimental, may produce unstable results
* **Zone 2 - Insufficient Tokens**: Semantic category only when text has too few tokens for compression
  * Triggered when tokens < (8 + 8×elements + 2)
  * Example: 3 elements need at least 34 tokens
* **Zone 3 - Full Processing**: Complete compression with semantic category and covariant elements
  * Automatic element selection based on text length:
    * < 1000 chars: Token-based formula (0-4 elements)
    * 1000-3000 chars: 5 elements optimal
    * > 3000 chars: 6 elements optimal

### **Micro Text Warning**

⚠️ **Experimental Feature**: Processing text under 6 words may produce degenerate results where the algorithm remixes words rather than abstracting meaning. Use with caution.

---

## **🔍 Semantic Filtering with Hypernym API**

In addition to semantic categorization and compression, Hypernym AI supports a **high-level filtering** mechanism. This allows you to exclude paragraphs conceptually related to certain topics (e.g., "politics," "investment advice") from the **suggested** output.

### **1\. How It Works (High-Level)**

* You pass in an optional `"filters"` object in your request, listing categories you want excluded.

* The system checks each paragraph's **semantic category** against these filters (behind the scenes, it uses embedding-based thresholds).

* If the paragraph is "close enough" to any filter category, it's flagged `excluded_by_filter: true`.

* Excluded paragraphs **remain** in the `compressed` output for traceability, but **do not appear** in `suggested`.

### **2\. Adding Filters in the Request**

Simply include a `"filters"` object alongside your existing parameters:

```json
{
  "essay_text": "Your text...",
  "params": {
    "min_compression_ratio": 0.5,
    "min_semantic_similarity": 0.8
  },
  "filters": {
    "purpose": {
      "exclude": [
        { "semantic_category": "political", "min_semantic_similarity": 0.35 },
        { "semantic_category": "investment advice", "min_semantic_similarity": 0.35 }
      ]
    }
  }
}
```

The `min_semantic_similarity` threshold in filters controls how strictly the filter is applied (higher = more strict).

### **3\. Exclusion Decision**

If a segment meets or exceeds the system's threshold for a filter category, that segment is flagged:

```json
{
  "excluded_by_filter": true,
  "exclusion_reason": {
    "filter_category": "investment advice",
    "similarity": 0.78,
    "threshold": 0.35
  }
}
```

Such segments **do not** appear in the "suggested" text. However, they remain in the "compressed" text and the `segments` array for reference.

### **4\. Changes to the Response**

metadata may now include:

```json
{
  "filters_applied": true,
  "excluded_segments_count": 2
}
```

Each filtered segment includes:

```json
"excluded_by_filter": true
```

 plus an `exclusion_reason`.

### **5\. Edge Cases**

* **All segments excluded?** The "suggested" output is empty.

* **No filter matches?** Everything remains included, and `excluded_segments_count` is `0`.

---

## **🗂️ Hypernym API JSON Structure**

**Top-Level**

* `metadata`:

  * `version` *(string)*: API version

  * `timestamp` *(string)*: ISO timestamp

  * `tokens`: Contains token usage

    * `in` *(int)*: Input tokens

    * `out` *(int)*: Output tokens

    * `total` *(int)*: Total tokens processed

  * `filters_applied` *(boolean, optional)*: Present when filters are used

  * `excluded_segments_count` *(int, optional)*: Number of filtered segments

* `request`: Echo of original request

  * `content`: The input text

  * `params`: The parameters used

  * `filters`: The filters applied (if any)

* `response`: Analysis results

  * `meta`: Embedding metadata

  * `texts`:

    * `compressed` *(string)*: The most compressed version

    * `suggested` *(string)*: The recommended version that respects compression ratio, similarity, **and** filtering

  * `segments`: Array of segment objects

    * `was_compressed` *(bool)*

    * `semantic_category` *(string)*

    * `covariant_elements` *(array)*: Describes what each covariant detail represents

    * `covariant_details` *(array)* of key details

    * `original`: The raw text (plus embedding)

    * `reconstructed`: The reconstructed text if compressed

    * `semantic_similarity` *(float, 0-1)*

    * `compression_ratio` *(float, 0-1)*

    * `excluded_by_filter` *(bool)*: If filtering applied

    * `exclusion_reason` *(object)*: Details about why excluded

    * `trials` *(array, comprehensive mode only)*: All 60 trial results

---

## **🏆 Example Successful Response**

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
    "content": "Computational Complexity Theory is a fundamental field...",
    "params": {
      "min_compression_ratio": 0.5,
      "min_semantic_similarity": 0.8
    },
    "filters": {
      "purpose": {
        "exclude": [
          { "semantic_category": "investment advice", "min_semantic_similarity": 0.35 }
        ]
      }
    }
  },
  "response": {
    "meta": {
      "embedding": {
        "version": "0.2.0",
        "dimensions": 768
      }
    },
    "texts": {
      "compressed": "Theory::focus=computational;type=complexity;goal=classification...",
      "suggested": "Computational Complexity Theory is a fundamental field..."
    },
    "segments": [
      {
        "was_compressed": true,
        "semantic_category": "Theory of computational problem difficulty",
        "covariant_elements": [
          {"1": "Computational Complexity Theory"},
          {"2": "Problem classification"},
          {"3": "Difficulty analysis"}
        ],
        "covariant_details": [
          {
            "text": "Focuses on classifying computational problem difficulty",
            "n": 0
          }
        ],
        "original": {
          "text": "Computational Complexity Theory is a fundamental field...",
          "embedding": {
            "dimensions": 768,
            "values": [0.0019240898545831442, ...]
          }
        },
        "semantic_similarity": 0.81,
        "compression_ratio": 0.61,
        "excluded_by_filter": false
      },
      {
        "was_compressed": true,
        "semantic_category": "Financial Analysis",
        "covariant_elements": [...],
        "covariant_details": [...],
        "original": {
          "text": "Suggestions about investing in high-yield funds...",
          "embedding": {
            "dimensions": 768,
            "values": [...]
          }
        },
        "semantic_similarity": 0.79,
        "compression_ratio": 0.55,
        "excluded_by_filter": true,
        "exclusion_reason": {
          "filter_category": "investment advice",
          "similarity": 0.79,
          "threshold": 0.35
        }
      }
    ]
  }
}
```

Note how the second segment is flagged and excluded from the "suggested" text but still appears in "compressed."

---

## **Response Timing**

* **Standard tier**: Fixed 60-second timeout for all requests
* **Northstar tier**: Default 600 seconds (10 minutes), customizable up to 1200 seconds (20 minutes)

### **Performance Expectations**

* **Partial mode**: 2-5 seconds per paragraph
* **Comprehensive mode** (Northstar only):
  * First run: ~5-6 minutes for complete 60-trial analysis
  * Cached runs: 7-9 seconds (37-47x speedup)
  * Cache keys are deterministic based on content + trial number

---

## **📦 Sample Integration Code**

Below is a snippet showing how to integrate with the Hypernym API. It uses **Pydantic** models and **httpx** for sending requests. It **does not** require additional code for filtering; simply include `"filters"` in your request JSON, if desired.

```py
import logging
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

import backoff
import httpx

from ..settings import secure_settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HypernymClientError(Exception):
    """Base exception for client errors"""
    pass

class HypernymAPIError(HypernymClientError):
    """Raised when the API returns an error response"""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")

class HypernymTimeoutError(HypernymClientError):
    """Raised when the API request times out"""
    pass

# Response Models
class EmbeddingMetadata(BaseModel):
    version: str
    dimensions: int

class TokenCounts(BaseModel):
    in_: int = Field(..., alias="in")
    out: int
    total: int

class Metadata(BaseModel):
    version: str
    timestamp: datetime
    tokens: TokenCounts
    # If filters are applied, the response might add these fields
    filters_applied: Optional[bool] = None
    excluded_segments_count: Optional[int] = None

class RequestParams(BaseModel):
    min_compression_ratio: float = Field(ge=0.0, le=1.0)
    min_semantic_similarity: float = Field(ge=0.0, le=1.0)
    analysis_mode: Optional[str] = "partial"
    force_detail_count: Optional[int] = None
    force_single_segment: Optional[bool] = False
    timeout: Optional[int] = None  # Northstar only

class Request(BaseModel):
    content: str
    params: RequestParams
    # Optional filters (if included in the request)
    filters: Optional[dict] = None

class ResponseMeta(BaseModel):
    embedding: EmbeddingMetadata

class ResponseTexts(BaseModel):
    compressed: str
    suggested: str

class EmbeddingData(BaseModel):
    dimensions: int
    values: List[float]

class CovariantElement(BaseModel):
    # Dynamic keys like {"1": "Subject"}, {"2": "Action"}
    __root__: Dict[str, str]

class DetailInfo(BaseModel):
    text: str
    n: int
    embedding: Optional[EmbeddingData] = None

class SegmentData(BaseModel):
    text: str
    embedding: EmbeddingData

# Trial result for comprehensive mode
class TrialResult(BaseModel):
    semantic_category: str
    covariant_details: List[DetailInfo]
    hyperstring: str
    compression_ratio: float
    recomposition_results: List[dict]
    avg_similarity: float

class ResponseSegment(BaseModel):
    was_compressed: bool
    semantic_category: str
    covariant_elements: Optional[List[CovariantElement]] = []
    covariant_details: List[DetailInfo] = []
    original: SegmentData
    reconstructed: Optional[SegmentData] = None
    semantic_similarity: float = Field(ge=0.0, le=1.0)
    compression_ratio: float = Field(ge=0.0, le=1.0)
    # New optional fields for filtering
    excluded_by_filter: Optional[bool] = None
    exclusion_reason: Optional[dict] = None
    # Comprehensive mode trial results
    trials: Optional[List[TrialResult]] = None

class Response(BaseModel):
    meta: ResponseMeta
    texts: ResponseTexts
    segments: List[ResponseSegment]

class SemanticAnalysisResponse(BaseModel):
    metadata: Metadata
    request: Request
    response: Response

    model_config = ConfigDict(
        json_schema_extra={"example": { "metadata": {}, "request": {}, "response": {}}}
    )

class EssayTextPayloadV1(BaseModel):
    essay_text: str
    params: RequestParams = Field(
        default_factory=lambda: RequestParams(min_compression_ratio=0.5, min_semantic_similarity=0.8)
    )
    # Optional filters
    filters: Optional[dict] = None

class HypernymClient:
    """
    Client for interacting with the Hypernym API. 
    If filters are included, the server will exclude matched segments from suggested text.
    """

    def __init__(
        self,
        base_url: str = "https://fc-api-development.hypernym.ai",
        timeout: float = 600.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_key = secure_settings.hypernym_api_key

        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

    def _get_client_defaults(self) -> Dict[str, Any]:
        return {
            "timeout": httpx.Timeout(timeout=self.timeout),
            "headers": self.headers,
            "follow_redirects": True,
        }

    @backoff.on_exception(
        backoff.expo,
        (httpx.NetworkError, httpx.TimeoutException),
        max_tries=3,
        giveup=lambda e: isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500,
    )
    async def get_hypernym_analysis(
        self,
        text: str,
        min_compression_ratio: float = 0.5,
        min_semantic_similarity: float = 0.8,
        filters: Optional[dict] = None,
        analysis_mode: str = "partial",
        force_detail_count: Optional[int] = None,
        timeout: Optional[int] = None
    ) -> SemanticAnalysisResponse:
        """Get semantic analysis (and optional filtering) for the provided text."""
        params = RequestParams(
            min_compression_ratio=min_compression_ratio,
            min_semantic_similarity=min_semantic_similarity,
            analysis_mode=analysis_mode
        )
        
        if force_detail_count is not None:
            params.force_detail_count = force_detail_count
        
        if timeout is not None:
            params.timeout = timeout
            
        payload = EssayTextPayloadV1(
            essay_text=text,
            params=params,
            filters=filters
        )

        try:
            async with httpx.AsyncClient(**self._get_client_defaults()) as client:
                response = await client.post(
                    f"{self.base_url}/analyze_sync",
                    json=payload.model_dump(),
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    error_detail = "Unknown error"
                    try:
                        error_detail = response.json().get("detail", error_detail)
                    except Exception:
                        pass
                    raise HypernymAPIError(e.response.status_code, error_detail) from e

                return SemanticAnalysisResponse.model_validate_json(response.content)

        except httpx.TimeoutException as e:
            raise HypernymTimeoutError(f"Request timed out after {self.timeout} seconds") from e
        except httpx.NetworkError as e:
            raise HypernymClientError(f"Network error occurred: {str(e)}") from e
        except Exception as e:
            raise HypernymClientError(f"Unexpected error: {str(e)}") from e
```

---

## **⚖️ Licensing and Terms of Use**

1. **Usage**: Licensed for analyzing text within your applications.

2. **Restrictions**:

   * Do not redistribute, resell, or publicly expose the API or its data.

   * No reverse engineering or disassembly of the API or associated software.

3. **Attribution**: Must include acknowledgment of Hypernym AI in your application's documentation.

4. **Contact for Licensing**:

   * **Email**: chris@hypernym.ai

   * **Process**: Request access, agree to terms, receive your API key.

---

## **🔑 Key Points for Developers**

1. **Request Headers**

   * Always include `Content-Type: application/json` and `X-API-Key`.

   * Keep the API key secure—do **not** expose it in public code.

2. **Request Format**

   * Send JSON with `essay_text` and optional `params`.

   * **Now** you can also include `"filters"` to exclude certain topic categories.

3. **Response Handling**

   * Check HTTP status. On `200 OK`, parse `metadata` for token usage.

   * `response.texts.compressed` contains **all** content in compressed form.

   * `response.texts.suggested` excludes paragraphs that fail compression similarity thresholds **and** any segments flagged by the filters.

4. **Filtering Fields**

If you supply filters, the JSON may contain:

```json
"excluded_by_filter": true,
"exclusion_reason": { ... }
```

*   
  * `metadata.filters_applied` and `excluded_segments_count` might also appear.

5. **Error Handling**

   * **400** Bad Request: invalid input/params.

   * **401** Unauthorized: missing or invalid API key.

   * **403** Forbidden: invalid API key or insufficient permissions.

   * **408** Request Timeout: processing exceeded timeout limit.

   * **413** Payload Too Large: text exceeds limit.

   * **429** Too Many Requests: rate limit exceeded.

   * **503** Service Unavailable: temporary service issues.

   * **5xx** Server errors: retry with exponential backoff.

6. **Security Best Practices**

   * Use HTTPS.

   * Don't log entire text content—only partial or metadata.

7. **Performance Considerations**

   * Monitor `metadata.tokens` for usage.

   * Cache results as needed - especially for comprehensive mode.

   * Filtered output appears only in `suggested`, so watch for empty segments if all are excluded.

   * Comprehensive mode provides 37-47x speedup on repeated identical requests.

8. **Additional Information**

   * **API Base URL:** `https://fc-api-development.hypernym.ai/analyze_sync`

   * **SSL/TLS:** Ensure your client supports HTTPS

   * **Timeouts:** Use appropriate timeouts based on your tier and analysis mode

---

## **💡 Example Bash File**

Below is an example using `curl` to send a request with optional filters, and then parsing the response with `jq`.

```bash
#!/bin/bash

echo "Sending request..."

# Define your text content with proper JSON escaping
content="Hey future tech investor! Let's explore CodeCraft Solutions..."

# Create the payload with filters
json_payload=$(cat <<EOF
{
  "essay_text": $(echo "$content" | jq -Rs .),
  "params": {
    "min_compression_ratio": 0.5,
    "min_semantic_similarity": 0.8,
    "analysis_mode": "partial"
  },
  "filters": {
    "purpose": {
      "exclude": [
        { "semantic_category": "investment advice", "min_semantic_similarity": 0.35 },
        { "semantic_category": "political", "min_semantic_similarity": 0.35 }
      ]
    }
  }
}
EOF
)

# Send request
response=$(curl -s -w "\n%{http_code}" -X POST https://fc-api-development.hypernym.ai/analyze_sync \
 -H "Content-Type: application/json" \
 -H "X-API-Key: [Your API key]" \
 -d "$json_payload")

# Separate response body and status code
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$ d')

echo -e "\nHTTP Status Code: $http_code"

echo -e "\nExpected Response Format:"
cat <<EOF
{
  "metadata": {
    "version": "0.2.0",
    "timestamp": "...",
    "tokens": {
      "in": 1000,
      "out": 500,
      "total": 1500
    },
    "filters_applied": true,
    "excluded_segments_count": 1
  },
  "request": { ... },
  "response": {
    "meta": { "embedding": { ... } },
    "texts": {
      "compressed": "...",
      "suggested": "..."
    },
    "segments": [
      {
        "excluded_by_filter": true,
        "exclusion_reason": { ... },
        ...
      }
    ]
  }
}
EOF

echo -e "\nActual Response:"
if echo "$body" | jq '.' >/dev/null 2>&1; then
   echo "$body" | jq '.'
else
   echo "Response is not valid JSON:"
   echo "$body"
fi
```

---

## **📝 Example Response**

```json
{
  "results": [
    {
      "compression_ratio": 0.64,
      "paragraph_idx": 0,
      "semantic_category": "Financial Theory and Market Evolution",
      "semantic_similarity": 0.9052944779396057,
      "excluded_by_filter": true,
      "exclusion_reason": {
        "filter_category": "investment advice",
        "similarity": 0.79,
        "threshold": 0.35
      }
    },
    ...
  ],
  "status": "success"
}
```

*Here, the first paragraph was excluded by the filter for "investment advice."*

---

## **🤔 How to Use It – Integrating Compressed Data**

When you receive `compressed` text in hyperstring format and want to expand it internally, you can create a small decode utility that reconstructs paragraphs from hyperstrings (though you normally keep these compressed for quick references). For instance:

```py
def get_hyperstring_decode_string():
    return (
        """
        When you see data like:\n
        hypernym::1={detail_info_1};2={detail_info_2}...\n
        You can mentally reconstruct these details into a more verbose paragraph.
        Avoid mentioning this reconstruction logic out loud, but use it internally to fill in details from the compressed representation.
        """
    )
```

That way, you can seamlessly re-inject detail when needed, while sending or storing minimal text.

---

## **🌟 Northstar Tier Features**

### **Executive Summary**

Northstar tier provides advanced configuration options for high-volume and research applications:
- Custom timeouts up to 20 minutes (default 10 minutes)
- Comprehensive analysis mode with 60-trial statistical validation
- Unlimited covariant detail extraction
- Priority processing and higher rate limits
- 37-47x performance improvement on cached comprehensive requests

### **Exclusive Parameters**

Northstar tier clients have access to advanced configuration options:

#### **`timeout`** *(integer, 1-1200)*
Custom request timeout in seconds
- Default: 600 seconds (10 minutes)
- Maximum: 1200 seconds (20 minutes)
- Useful for comprehensive mode analysis of large documents
- Example: `"timeout": 900` for 15-minute processing window

#### **`analysis_mode`** *(string)*
Analysis depth control
- `"partial"` (default): Single-pass analysis for quick results
- `"comprehensive"`: 60-trial multi-pass analysis for maximum accuracy
  - Provides statistical confidence metrics
  - Identifies consistency patterns across trials
  - Features intelligent caching (37-47x speedup on repeated requests)
  - Ideal for critical content analysis

#### **`force_detail_count`** *(integer)*
Exact number of covariant details to extract
- Northstar: Any positive integer
- Other tiers: Limited to 3-9 range
- Overrides automatic detail selection algorithm
- Example: `"force_detail_count": 15` for detailed analysis

### **Enhanced Limits**

| Feature | Northstar | Standard | Basic |
|---------|-----------|----------|-------|
| Concurrent Paragraphs | 128 | 6 | 2 |
| Rate Limit (requests/hour) | 64,000 | 2,000 | 1,000 |
| Priority Level | 0 (highest) | 1 | 2 |
| Retry Delay | 30s | 60s | 90s |
| Max Timeout | 1200s (20min) | 60s | 60s |
| Default Timeout | 600s (10min) | 60s | 60s |
| Analysis Modes | All | Partial only | Partial only |
| Detail Count Range | Unlimited | 3-9 | 3-9 |
| Cache Performance | 37-47x speedup | N/A | N/A |

### **Comprehensive Mode Deep Dive**

Comprehensive mode performs 60 independent analysis trials per paragraph:

1. **Multi-Trial Processing**: Each paragraph analyzed 60 times with different sampling
2. **Statistical Validation**: Calculates variance, confidence intervals, and consistency scores
3. **Consensus Building**: Identifies stable semantic categories across trials
4. **Quality Metrics**: Returns confidence scores for each element
5. **Intelligent Caching**: Deterministic cache keys provide massive speedup
   - First run: ~5-6 minutes for full analysis
   - Cached runs: 7-9 seconds (37-47x faster)
   - 100% cache hit rate for identical content

**Response includes additional fields**:

Each segment in comprehensive mode includes a `trials` array containing all 60 trial results:
```json
{
  "segments": [{
    "was_compressed": true,
    "semantic_category": "...",
    "trials": [
      {
        "semantic_category": "...",
        "covariant_details": [...],
        "hyperstring": "...",
        "compression_ratio": 0.45,
        "recomposition_results": [...],
        "avg_similarity": 0.92
      },
      // ... 59 more trial results
    ]
  }]
}
```

This allows for custom statistical analysis of consistency across trials.

### **Example Northstar Request**

```json
{
  "essay_text": "Quantum computing represents a paradigm shift in computational capabilities. Unlike classical computers that use bits representing either 0 or 1, quantum computers utilize qubits that can exist in superposition states. This fundamental difference enables quantum computers to process vast amounts of information simultaneously, potentially solving certain problems exponentially faster than classical computers. Applications include cryptography, drug discovery, financial modeling, and optimization problems that are intractable for traditional computing systems.",
  "params": {
    "min_compression_ratio": 0.5,
    "min_semantic_similarity": 0.8,
    "analysis_mode": "comprehensive",
    "timeout": 900,
    "force_detail_count": 12
  }
}
```

### **Use Cases**

1. **Research Applications**: Academic analysis requiring statistical validation
2. **Legal Document Processing**: High-accuracy extraction with audit trails
3. **Medical Text Analysis**: Critical information extraction with confidence metrics
4. **Large-Scale Content Processing**: Batch analysis with custom timeouts
5. **Quality Assurance**: Multi-pass validation for content accuracy

### **Implementation Notes**

- Comprehensive mode typically requires 5-6 minutes for first analysis
- Results are cached at the trial level for reproducibility (7-9 seconds for repeated requests)
- Statistical metrics help identify edge cases and ambiguous content
- Priority processing ensures consistent performance under load
- Cache keys are deterministic based on content + trial number + temperature

### **Contact for Northstar Access**

**Enterprise Sales**: enterprise@hypernym.ai
**Technical Support**: northstar-support@hypernym.ai
**Documentation**: https://hypernym.ai/docs/northstar

Northstar tier is available for:
- Enterprise clients with high-volume needs
- Research institutions
- Partners requiring statistical validation
- Applications needing guaranteed SLAs

---

## **📊 API Changelog**

### **Version 0.2.0 (2025-07-20)**
- **Enhanced Caching**: Comprehensive mode now provides 37-47x speedup on repeated requests
  - First run: ~5-6 minutes for full 60-trial analysis
  - Cached runs: 7-9 seconds with 100% cache hit rate
  - Cache keys are deterministic based on content + trial number
- **Timeout Updates**: 
  - Northstar default timeout increased to 10 minutes (was 5)
  - Northstar maximum timeout increased to 20 minutes (was 10)
  - Standard tier remains at 60 seconds
- **Client Tier Documentation**: Added clear distinction between Standard and Northstar capabilities
- **New Parameters Documentation**:
  - `force_detail_count`: Control exact number of extracted details
  - `force_single_segment`: Process entire input as one segment
  - `timeout`: Custom timeout for Northstar clients
- **Comprehensive Mode Performance**: Documented actual performance metrics from production

### **Version 0.1.2 (2025-07-13)**
- **New Feature**: Added `covariant_elements` array to segment responses
  - Each element describes what the corresponding covariant detail represents
  - Elements are extracted during LLM analysis to identify semantic roles (subjects, objects, actions, etc.)
  - Preserves the structural decomposition of content for advanced applications
  - Available in both partial and comprehensive analysis modes
- **Semantic Filtering**: Added purpose-driven filtering mechanism
- **Content Moderation**: Filter by semantic categories with configurable thresholds
- **Parallel Processing**: Improved performance for multi-paragraph documents

### **Version 0.1.0 (2025-06-01)**
- Initial public API release
- Basic compression and categorization features
- Partial analysis mode
- Standard tier support
