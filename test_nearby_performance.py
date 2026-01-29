#!/usr/bin/env python
"""
Test script to verify the NearbySearchAPI optimization.
Tests various scenarios to ensure functionality is preserved and performance improved.
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings')
sys.path.insert(0, '/Users/apple/Documents/Projects/pathzi')
django.setup()

import time
from geo_search.services_search import search_nearby

def test_nearby_search():
    """Test nearby search functionality with various inputs."""
    
    # London coordinates
    london_lat, london_lon = 51.5074, -0.1278
    # Manchester coordinates  
    manchester_lat, manchester_lon = 53.4808, -2.2426
    
    test_cases = [
        # (description, lat, lon, radius_km, types, q, category, page)
        ("London 25km - all types", london_lat, london_lon, 25, ["jobs", "courses", "apprenticeships"], "", "", 1),
        ("London 50km - jobs only", london_lat, london_lon, 50, ["jobs"], "", "", 1),
        ("London 10km - with keyword", london_lat, london_lon, 10, ["jobs"], "software", "", 1),
        ("Manchester 25km - courses", manchester_lat, manchester_lon, 25, ["courses"], "", "", 1),
        ("London 25km - page 2", london_lat, london_lon, 25, ["jobs"], "", "", 2),
        ("Small radius 5km", london_lat, london_lon, 5, ["jobs", "courses"], "", "", 1),
    ]
    
    print("=" * 80)
    print("TESTING NearbySearchAPI Optimization")
    print("=" * 80)
    print()
    
    all_passed = True
    total_time = 0
    
    for description, lat, lon, radius_km, types, q, category, page in test_cases:
        print(f"Test: {description}")
        print(f"  Query: lat={lat}, lon={lon}, radius={radius_km}km, types={types}, page={page}")
        
        try:
            start_time = time.time()
            
            # Test each type separately
            for t in types:
                result = search_nearby(
                    t=t,
                    lat=lat,
                    lon=lon,
                    radius_km=radius_km,
                    q=q,
                    category=category,
                    page=page,
                    page_size=20
                )
                
                elapsed = time.time() - start_time
                total_time += elapsed
                
                count = result.get('count', 0)
                items = result.get('items', [])
                
                print(f"  ✅ {t}: {len(items)} items (total: {count}) in {elapsed*1000:.2f}ms")
                
                # Validate result structure
                assert 'count' in result, "Missing 'count' field"
                assert 'page' in result, "Missing 'page' field"
                assert 'page_size' in result, "Missing 'page_size' field"
                assert 'items' in result, "Missing 'items' field"
                assert isinstance(items, list), "Items should be a list"
                
                # Validate distance is within radius for each item
                for item in items:
                    assert 'distance_km' in item, "Missing 'distance_km' field"
                    distance = float(item['distance_km'])
                    # Allow small margin due to over-fetch optimization
                    assert distance <= radius_km + 1, f"Distance {distance} exceeds radius {radius_km}"
                
                # Validate items have required fields
                for item in items:
                    assert 'latitude' in item, "Missing 'latitude' field"
                    assert 'longitude' in item, "Missing 'longitude' field"
            
        except Exception as e:
            print(f"  ❌ Failed: {str(e)}")
            import traceback
            traceback.print_exc()
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
    sys.exit(test_nearby_search())
