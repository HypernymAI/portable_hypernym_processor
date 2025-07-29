#!/usr/bin/env python3
"""
Example converter showing how to extract data from various sources
and prepare it for the Hypernym processor

This demonstrates basic patterns for converting your existing data
into the samples table format expected by the processor.
"""

import os
import sys
import sqlite3
import json
import csv
from typing import List, Dict, Any

# Add parent directory to path so we can import if needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SimpleConverter:
    """Base converter class with common functionality"""
    
    def __init__(self, target_db: str = "converted_data.db"):
        self.target_db = target_db
        self.conn = sqlite3.connect(target_db)
        self._ensure_samples_table()
    
    def _ensure_samples_table(self):
        """Create samples table if it doesn't exist"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
    
    def add_sample(self, content: str, metadata: Dict[str, Any] = None) -> int:
        """Add a single sample to the database"""
        metadata_json = json.dumps(metadata) if metadata else None
        cursor = self.conn.execute(
            "INSERT INTO samples (content, metadata) VALUES (?, ?)",
            (content, metadata_json)
        )
        self.conn.commit()
        return cursor.lastrowid
    
    def close(self):
        """Close database connection"""
        self.conn.close()


def convert_from_json_file():
    """Example: Convert from JSON file containing articles/documents"""
    
    print("=== Converting from JSON file ===")
    
    # Example JSON structure
    sample_data = [
        {
            "id": "doc1",
            "title": "Introduction to Machine Learning",
            "content": "Machine learning is a subset of artificial intelligence...",
            "author": "Dr. Smith",
            "category": "AI"
        },
        {
            "id": "doc2", 
            "title": "Climate Change Impact",
            "content": "Global warming has accelerated in recent decades...",
            "author": "Prof. Johnson",
            "category": "Environment"
        }
    ]
    
    # Write sample JSON file
    with open("sample_docs.json", "w") as f:
        json.dump(sample_data, f)
    
    # Convert to samples table
    converter = SimpleConverter("json_converted.db")
    
    with open("sample_docs.json", "r") as f:
        documents = json.load(f)
    
    for doc in documents:
        # Extract text content
        content = doc.get("content", "")
        
        # Preserve other fields as metadata
        metadata = {
            "original_id": doc.get("id"),
            "title": doc.get("title"),
            "author": doc.get("author"),
            "category": doc.get("category")
        }
        
        sample_id = converter.add_sample(content, metadata)
        print(f"  Added sample {sample_id}: {doc.get('title')}")
    
    converter.close()
    print(f"Converted {len(documents)} documents to json_converted.db\n")
    
    # Cleanup
    import os
    os.remove("sample_docs.json")
    os.remove("json_converted.db")


def convert_from_csv():
    """Example: Convert from CSV file with text data"""
    
    print("=== Converting from CSV file ===")
    
    # Create sample CSV
    csv_data = [
        ["id", "product_name", "description", "category"],
        ["1", "Smart Watch", "Advanced fitness tracking with heart rate monitoring and GPS capabilities", "Electronics"],
        ["2", "Organic Coffee", "Premium arabica beans sourced from sustainable farms in Colombia", "Food"],
        ["3", "Yoga Mat", "Extra thick non-slip surface perfect for all yoga styles", "Fitness"]
    ]
    
    with open("products.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(csv_data)
    
    # Convert to samples table
    converter = SimpleConverter("csv_converted.db")
    
    with open("products.csv", "r") as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # Combine relevant text fields
            content = f"{row['product_name']}: {row['description']}"
            
            # Store original data as metadata
            metadata = {
                "original_id": row["id"],
                "product_name": row["product_name"],
                "category": row["category"]
            }
            
            sample_id = converter.add_sample(content, metadata)
            print(f"  Added sample {sample_id}: {row['product_name']}")
    
    converter.close()
    print("Converted CSV data to csv_converted.db\n")
    
    # Cleanup
    import os
    os.remove("products.csv")
    os.remove("csv_converted.db")


def convert_from_existing_sqlite():
    """Example: Convert from existing SQLite with different schema"""
    
    print("=== Converting from existing SQLite ===")
    
    # Create example source database
    source_conn = sqlite3.connect("source_database.db")
    source_conn.execute("""
        CREATE TABLE blog_posts (
            post_id INTEGER PRIMARY KEY,
            title TEXT,
            body TEXT,
            author_name TEXT,
            published_date TEXT,
            tags TEXT
        )
    """)
    
    # Insert sample data
    posts = [
        ("Understanding Neural Networks", 
         "Neural networks are computing systems inspired by biological neural networks...",
         "Alice Chen", "2024-01-15", "AI,DeepLearning"),
        ("The Future of Renewable Energy",
         "Solar and wind power are becoming increasingly cost-effective...",
         "Bob Martinez", "2024-02-20", "Energy,Environment")
    ]
    
    for title, body, author, date, tags in posts:
        source_conn.execute(
            "INSERT INTO blog_posts (title, body, author_name, published_date, tags) VALUES (?, ?, ?, ?, ?)",
            (title, body, author, date, tags)
        )
    source_conn.commit()
    
    # Convert to samples format
    converter = SimpleConverter("blog_converted.db")
    
    # Query source database
    cursor = source_conn.execute("""
        SELECT post_id, title, body, author_name, published_date, tags
        FROM blog_posts
        WHERE body IS NOT NULL AND body != ''
    """)
    
    for row in cursor:
        post_id, title, body, author, date, tags = row
        
        # Main content is the body
        content = body
        
        # Preserve all other data as metadata
        metadata = {
            "original_id": post_id,
            "title": title,
            "author": author,
            "published_date": date,
            "tags": tags.split(",") if tags else []
        }
        
        sample_id = converter.add_sample(content, metadata)
        print(f"  Added sample {sample_id}: {title}")
    
    source_conn.close()
    converter.close()
    print("Converted blog posts to blog_converted.db\n")
    
    # Cleanup
    import os
    os.remove("source_database.db")
    os.remove("blog_converted.db")


def convert_with_text_preprocessing():
    """Example: Convert with text cleaning and preprocessing"""
    
    print("=== Converting with preprocessing ===")
    
    converter = SimpleConverter("preprocessed.db")
    
    # Example: messy text that needs cleaning
    messy_texts = [
        {
            "id": "email1",
            "content": """
            
            FW: RE: Important Update!!!
            
            
            Hi team,
            
                  Just wanted to share that we've completed the project...
            
            
            Best,
            John
            
            -------- Original Message --------
            [Quoted text removed]
            """
        },
        {
            "id": "scraped1",
            "content": "Breaking News: Scientists discover... Read more >> Click here! Subscribe to our newsletter..."
        }
    ]
    
    for item in messy_texts:
        # Basic text cleaning
        content = item["content"]
        
        # Remove excessive whitespace
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        content = ' '.join(lines)
        
        # Remove email artifacts
        if "-------- Original Message --------" in content:
            content = content.split("-------- Original Message --------")[0]
        
        # Remove common web artifacts
        for phrase in ["Read more >>", "Click here!", "Subscribe to"]:
            content = content.replace(phrase, "")
        
        # Only add if we have meaningful content left
        if len(content.split()) > 10:  # At least 10 words
            metadata = {"original_id": item["id"], "preprocessed": True}
            sample_id = converter.add_sample(content.strip(), metadata)
            print(f"  Added cleaned sample {sample_id}")
        else:
            print(f"  Skipped {item['id']} - too short after cleaning")
    
    converter.close()
    print("Converted with preprocessing to preprocessed.db\n")
    
    # Cleanup
    import os
    os.remove("preprocessed.db")


def main():
    """Run all converter examples"""
    
    print("CONVERTER EXAMPLES")
    print("==================")
    print("These examples show how to convert data from various sources")
    print("into the samples table format expected by the Hypernym processor.\n")
    print("Key points:")
    print("- The processor now uses force_single_segment=True by default")
    print("- No need to chunk text - send entire documents")
    print("- Preserve metadata for tracking original sources")
    print("- For custom chunking strategies, contact: hi@hypernym.ai")
    print("\n")
    
    # Run examples
    convert_from_json_file()
    convert_from_csv()
    convert_from_existing_sqlite()
    convert_with_text_preprocessing()
    
    print("SUMMARY")
    print("=======")
    print("After conversion, use the Hypernym processor on your new database:")
    print()
    print("  from hypernym_processor import HypernymProcessor")
    print("  processor = HypernymProcessor('converted_data.db')")
    print("  results = processor.process_batch(batch_size=10)")
    print()
    print("The processor will create hypernym_responses table with results.")
    print("Your original data remains in the samples table with metadata preserved.")


if __name__ == "__main__":
    main()