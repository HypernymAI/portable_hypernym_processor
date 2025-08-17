"""Data models for the Hypernym Processor."""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List


@dataclass
class Sample:
    """
    A text sample to be processed through Hypernym API.
    
    This represents a single unit of text that needs compression. The processor
    will send the content to Hypernym API and store the compressed result.
    
    Attributes:
        id: Unique identifier, typically from your database primary key
        content: The actual text to compress (any length, but 200+ words works best)
        metadata: Optional dict of extra fields from your database row
        
    Example:
        sample = Sample(
            id=42,
            content="The sun was setting over the mountains...",
            metadata={'category': 'literature', 'author': 'Unknown'}
        )
    """
    id: int
    content: str
    metadata: Dict[str, Any] = None


@dataclass
class HypernymResponse:
    """Hypernym API response structure"""
    sample_id: int
    original_text: str
    compressed_text: str
    compression_ratio: float
    segments: List[Dict[str, Any]]
    processing_time: float
    timestamp: str


__all__ = ['Sample', 'HypernymResponse']