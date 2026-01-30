import requests
import json

try:
    print("Fetching summary...")
    r = requests.get("http://localhost:8000/api/analytics/summary")
    print(json.dumps(r.json(), indent=2))
    
    print("\nFetching leaderboard...")
    r = requests.get("http://localhost:8000/api/analytics/leaderboard")
    print(json.dumps(r.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
