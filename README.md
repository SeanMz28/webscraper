# Vehicle Dashboard Image Scraper

**Audio Superb CC — Trim Kit Visual Catalogue Builder**

Automated web scraper that collects high-quality dashboard interior images for ~200 vehicle make/model/year combinations to support creation of a visual trim kit catalogue.

---

## Project Structure

```
webscraper/
├── scrape_dashboards.py      # Main orchestrator — run this
├── vehicle_parser.py         # Parses the trim CSV → unique vehicle list
├── image_scraper.py          # Multi-source image search & download engine
├── file_organizer.py         # Folder structure, metadata, catalogue & QC reports
├── requirements.txt          # Python dependencies
├── list of trims to scrape 2026.02.04.csv   # Input data
└── dashboards/               # Output directory (created at runtime)
    ├── BMW/
    │   ├── E46_1998-2005/
    │   │   ├── dashboard_01_a1b2c3d4.jpg
    │   │   ├── dashboard_02_e5f6g7h8.jpg
    │   │   └── metadata.json
    │   └── E90_2004-2012/
    │       └── ...
    ├── TOYOTA/
    │   └── ...
    ├── master_catalogue.csv
    ├── quality_control_report.csv
    ├── qc_summary.txt
    └── parsed_vehicles.csv
```

## Setup

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt
```

## Usage

### Basic — scrape all vehicles
```bash
python scrape_dashboards.py
```

### Test run — scrape first 5 vehicles only
```bash
python scrape_dashboards.py --limit 5
```

### Dry run — parse CSV and preview vehicle list (no scraping)
```bash
python scrape_dashboards.py --dry-run
```

### Filter by make
```bash
python scrape_dashboards.py --make TOYOTA
python scrape_dashboards.py --make BMW --limit 3
```

### Resume interrupted session
```bash
python scrape_dashboards.py --resume
```

### Customise image count and resolution
```bash
python scrape_dashboards.py --images 3 --min-width 1024 --min-height 768
```

### Use Google Images via SerpAPI (better results)
```bash
python scrape_dashboards.py --serpapi-key YOUR_API_KEY
# or set as environment variable:
export SERPAPI_KEY=YOUR_API_KEY
python scrape_dashboards.py
```

### All options
```bash
python scrape_dashboards.py --help
```

## Image Sources

The scraper searches multiple sources and combines/deduplicates results:

| Source | Method | Quality | Rate Limit Risk |
|--------|--------|---------|-----------------|
| DuckDuckGo Images | `duckduckgo_search` library | Good | Low |
| Bing Images | HTML scraping | Good | Medium |
| Google Images (SerpAPI) | API (requires key) | Best | None (paid) |
| Google Images (direct) | HTML scraping (fallback) | Variable | High |

## Image Quality Standards

- **Minimum resolution:** 800×600 px (configurable)
- **Preferred orientation:** Landscape
- **Format:** JPEG/PNG (WebP auto-converted to JPEG)
- **Content:** OEM/stock dashboard views preferred over aftermarket
- **Max file size:** 15 MB per image

## Output Files

| File | Description |
|------|-------------|
| `dashboards/master_catalogue.csv` | Maps every vehicle to its downloaded images |
| `dashboards/quality_control_report.csv` | Per-vehicle scraping statistics |
| `dashboards/qc_summary.txt` | Human-readable success/failure summary |
| `dashboards/parsed_vehicles.csv` | Clean list of all vehicles extracted from CSV |
| `dashboards/{Make}/{Model_Year}/metadata.json` | Per-vehicle image metadata & source URLs |

## Graceful Shutdown

Press `Ctrl+C` once to finish the current vehicle and save progress.  
Press `Ctrl+C` twice to force quit immediately.

Use `--resume` on the next run to skip vehicles that already completed.

## Rate Limiting

The scraper includes built-in rate limiting:
- 2–5 second random delay between requests
- Escalating retry delays (5s → 15s → 30s) on errors/blocks
- Per-domain tracking to avoid hammering any single site

## Troubleshooting

**"duckduckgo_search not installed"**  
Run: `pip install duckduckgo_search`

**Low image counts / many failures**  
- Try adding a SerpAPI key (`--serpapi-key`)
- Check your internet connection
- Some niche vehicles simply have few dashboard photos online

**Script blocked by search engines**  
- The scraper will automatically retry with delays
- Use `--resume` to continue after waiting
- Consider using SerpAPI to avoid blocks entirely
