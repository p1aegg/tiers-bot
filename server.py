"""
Name Tiers server with local JSON file storage.

Usage:
  pip install flask
  python server.py
Then open http://localhost:8000

Uses local JSON files for all data:
  - website_data.json (consolidated data for website - PRIMARY ENDPOINT)
  - users.json (user data - legacy)
  - tiers.json (tier data - legacy)
  - stats.json (statistics - legacy)

Endpoints:
  GET /                 -> serves index.html
  GET /vanilla, /uhc... -> ALSO serves index.html (SPA fallback)
  GET /website_data.json -> serves consolidated website data (RECOMMENDED)
  GET /data/website_data.json -> same endpoint (compatibility alias)
  GET /users.json       -> serves users.json (legacy)
  GET /tiers.json       -> serves tiers.json (legacy)
  GET /stats.json       -> serves stats.json (legacy)
  GET /data/<file>      -> same endpoints (compatibility alias)

Website Data Structure:
{
  "players": {
    "user_id": {
      "username": "PlayerName",
      "uuid": "minecraft-uuid",
      "tier": "LT3",
      "peak_tier": "HT2",
      "region": "NA",
      "pref_server": "crystalranked.org",
      "verified": true,
      "cooldown": { ... }
    }
  },
  "stats": { ... },
  "config": {
    "regions": ["NA", "EU", "AS", "AU"],
    "tiers": ["LT5", "HT5", ...],
    "rank_names": { ... }
  }
}
"""
import os
import json
from flask import Flask, send_from_directory, jsonify, abort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWED_JSON = {"users.json", "tiers.json", "stats.json", "website_data.json"}
HTML_FILE = "index.html"

# Valid SPA routes the front-end script understands.
VALID_MODES = {"vanilla", "uhc", "pot", "nethop", "smp", "sword", "axe", "mace"}

# Local JSON file paths
TIERS_FILE = os.path.join(BASE_DIR, "tiers.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")
STATS_FILE = os.path.join(BASE_DIR, "stats.json")

app = Flask(__name__)

def load_json_from_file(filename):
    """Load JSON from local file"""
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_json_to_file(filename, data):
    """Save JSON to local file"""
    path = os.path.join(BASE_DIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _serve_html():
    return send_from_directory(BASE_DIR, HTML_FILE)


def _serve_json(name):
    if name not in ALLOWED_JSON:
        abort(404)
    
    # Load all JSON files locally
    path = os.path.join(BASE_DIR, name)
    if not os.path.exists(path):
        # Return empty object so the page still renders.
        return jsonify({})
    return send_from_directory(BASE_DIR, name, mimetype="application/json")


@app.route("/")
def index():
    return _serve_html()


@app.route("/website_data.json")
def website_data():
    """Primary endpoint for website data - consolidated all data in one place"""
    return _serve_json("website_data.json")


@app.route("/data/<path:name>")
def data_file(name):
    return _serve_json(name)


# Catch-all: serve JSON when asked, the HTML itself by name,
# the SPA fallback for known gamemode routes, and 404 for anything else.
@app.route("/<path:name>")
def catch_all(name):
    if name in ALLOWED_JSON:
        return _serve_json(name)
    if name in (HTML_FILE, "mctiers.html"):
        return _serve_html()
    # SPA fallback for the gamemode tabs (/vanilla, /uhc, ...).
    if name.strip("/").lower() in VALID_MODES:
        return _serve_html()
    abort(404)


if __name__ == "__main__":
    print("Using local JSON files for all data storage")
    
    print(f"Serving from: {BASE_DIR}")
    print("Open http://localhost:8000")
    app.run(host="0.0.0.0", port=8000, debug=False)
