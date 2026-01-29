#!/usr/bin/env python
"""
Test script to verify the LocationAutocompleteAPI optimization.
Tests various scenarios to ensure functionality is preserved.
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings')
sys.path.insert(0, '/Users/apple/Documents/Projects/pathzi')
django.setup()

import time
from geo_search.services_db import db_suggest_distinct

def test_autocomplete():
    """Test autocomplete functionality with various inputs."""
    
    test_cases = [
        # (field, text, types, limit, description)
        ("city", "lon", ["jobs", "courses"], 8, "City prefix: 'lon'"),
        ("city", "man", ["jobs"], 5, "City prefix: 'man' (jobs only)"),
        ("city", "bir", ["courses"], 8, "City prefix: 'bir' (courses only)"),
        ("city", "edin", ["apprenticeships"], 8, "City prefix: 'edin' (apprenticeships only)"),
        ("zip_code", "SW", ["jobs", "courses", "apprenticeships"], 8, "Postcode prefix: 'SW'"),
        ("zip_code", "M1", ["jobs"], 8, "Postcode prefix: 'M1'"),
        ("city", "xx", ["jobs", "courses"], 8, "No results case"),
        ("city", "a", ["jobs"], 8, "Single character (should work)"),
    ]
    
    print("=" * 80)
    print("TESTING LocationAutocompleteAPI Optimization")
    print("=" * 80)
    print()
    
    all_passed = True
    total_time = 0
    
    for field, text, types, limit, description in test_cases:
        print(f"Test: {description}")
        print(f"  Query: field={field}, text='{text}', types={types}, limit={limit}")
        
        try:
            start_time = time.time()
            results = db_suggest_distinct(field, text, types, limit)
            elapsed = time.time() - start_time
            total_time += elapsed
            
            print(f"  ✅ Success: {len(results)} results in {elapsed*1000:.2f}ms")
            
            # Show first 3 results
            for i, result in enumerate(results[:3]):
                print(f"     {i+1}. {result['label']} ({result['kind']})")
            
            if len(results) > 3:
                print(f"     ... and {len(results) - 3} more")
            
            # Validate result structure
            for result in results:
                assert 'kind' in result, "Missing 'kind' field"
                assert 'label' in result, "Missing 'label' field"
                assert 'value' in result, "Missing 'value' field"
                assert result['kind'] in ['city', 'postcode'], f"Invalid kind: {result['kind']}"
            
            # Check limit is respected
            assert len(results) <= limit, f"Too many results: {len(results)} > {limit}"
            
        except Exception as e:
            print(f"  ❌ Failed: {str(e)}")
            all_passed = False
        
        print()
    
    print("=" * 80)
    print(f"SUMMARY")
    print("=" * 80)
    print(f"Total tests: {len(test_cases)}")
    print(f"Total time: {total_time*1000:.2f}ms")
    print(f"Average time per query: {(total_time/len(test_cases))*1000:.2f}ms")
    
    if all_passed:
        print("✅ All tests PASSED")
        return 0
    else:
        print("❌ Some tests FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(test_autocomplete())
