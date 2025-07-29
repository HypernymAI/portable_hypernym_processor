# Hypernym Processor Examples

This directory contains example scripts demonstrating how to use the Hypernym processor.

## Files

### api_integration.py
Shows how to use the Hypernym processor with v2 API features:
- Basic usage with default settings
- Advanced v2 features (analysis modes, detail counts, filters)
- Integration with existing databases
- Uses the standard test strings from API documentation

Run it:
```bash
cd portable_hypernym_processor
python examples/api_integration.py
```

### data_converter.py
Demonstrates how to convert data from various sources into the samples table format:
- Converting from JSON files
- Converting from CSV files
- Converting from existing SQLite databases with different schemas
- Text preprocessing and cleaning
- Adding metadata to preserve source information

Run it:
```bash
cd portable_hypernym_processor
python examples/data_converter.py
```

## Note

These examples use test data and will create/remove temporary databases during execution. They're designed to show patterns you can adapt for your own use cases.

For questions about chunking strategies or advanced usage, contact: hi@hypernym.ai