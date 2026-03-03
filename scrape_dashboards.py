#!/usr/bin/env python3
"""
Vehicle Dashboard Image Scraper
================================
Main orchestrator script that:
  1. Reads the trim catalogue CSV
  2. Extracts unique vehicle entries
  3. Scrapes dashboard images from multiple sources
  4. Validates image quality
  5. Saves images in an organized folder structure
  6. Generates master catalogue and QC reports

Usage:
    python scrape_dashboards.py                           # Process all vehicles
    python scrape_dashboards.py --limit 10                # Process first 10 only
    python scrape_dashboards.py --make BMW                # Only process BMWs
    python scrape_dashboards.py --resume                  # Skip already-scraped
    python scrape_dashboards.py --serpapi-key YOUR_KEY     # Use SerpAPI for Google
    python scrape_dashboards.py --dry-run                 # Parse CSV only, no scraping
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from vehicle_parser import parse_csv, generate_vehicle_list_csv, VehicleEntry
from image_scraper import ImageScraper, ScraperConfig
from file_organizer import FileOrganizer

logger = logging.getLogger(__name__)

# ─── Graceful shutdown handling ────────────────────────────────────────
_shutdown_requested = False


def _signal_handler(signum, frame):
    global _shutdown_requested
    if _shutdown_requested:
        print("\nForced shutdown!")
        sys.exit(1)
    _shutdown_requested = True
    print("\n⚠ Graceful shutdown requested. Finishing current vehicle...")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ─── Progress tracking ────────────────────────────────────────────────
class ProgressTracker:
    """Tracks scraping progress for resume capability."""

    def __init__(self, progress_file: str = "dashboards/.scrape_progress.json"):
        self.progress_file = Path(progress_file)
        self.data = self._load()

    def _load(self) -> dict:
        if self.progress_file.exists():
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return {"completed": {}, "started": None}
        return {"completed": {}, "started": None}

    def save(self):
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def is_completed(self, vehicle: VehicleEntry) -> bool:
        key = f"{vehicle.make}|{vehicle.model}|{vehicle.year_range}"
        return key in self.data.get("completed", {})

    def mark_completed(self, vehicle: VehicleEntry, images_saved: int):
        key = f"{vehicle.make}|{vehicle.model}|{vehicle.year_range}"
        self.data.setdefault("completed", {})[key] = {
            "images_saved": images_saved,
            "timestamp": datetime.now().isoformat(),
        }
        self.save()

    @property
    def completed_count(self) -> int:
        return len(self.data.get("completed", {}))


# ─── Main scraping logic ──────────────────────────────────────────────
def scrape_vehicle(
    vehicle: VehicleEntry,
    scraper: ImageScraper,
    organizer: FileOrganizer,
    target_images: int = 5,
) -> tuple:
    """
    Scrape dashboard images for a single vehicle.
    Returns (images_saved, images_found, images_validated, errors).
    """
    images_saved = 0
    images_found = 0
    images_validated = 0
    downloaded_metadata = []
    saved_filenames = []
    errors = []
    queries_tried = 0

    # Build list of queries to try
    queries = [vehicle.search_query] + vehicle.alt_search_queries

    for query in queries:
        if images_saved >= target_images:
            break

        queries_tried += 1
        logger.info(f"  Query: '{query}'")

        try:
            results = scraper.search_all_sources(
                query,
                max_per_source=15,
            )
            images_found += len(results)

            # Score and sort results by relevance
            scored = _score_results(results, vehicle)
            scored.sort(key=lambda x: x[0], reverse=True)

            for score, result in scored:
                if images_saved >= target_images:
                    break

                # Download and validate
                image_data = scraper.download_and_validate(result)
                if image_data:
                    images_validated += 1

                    # Generate filename and save
                    filename = scraper.generate_filename(result, images_saved)
                    saved_path = organizer.save_image(
                        vehicle, image_data, result, filename
                    )

                    if saved_path:
                        images_saved += 1
                        saved_filenames.append(filename)
                        downloaded_metadata.append({
                            "filename": filename,
                            "source_url": result.url,
                            "source_page": result.source_page,
                            "search_engine": result.search_engine,
                            "search_query": result.search_query,
                            "width": result.width,
                            "height": result.height,
                            "file_size_bytes": result.file_size,
                            "download_time": datetime.now().isoformat(),
                        })

        except Exception as e:
            error_msg = f"Query '{query}' failed: {str(e)}"
            logger.error(f"  {error_msg}")
            errors.append(error_msg)

    # Save metadata for this vehicle
    if downloaded_metadata:
        organizer.save_metadata(vehicle, downloaded_metadata)

    # Record for catalogue and QC
    status = "SUCCESS" if images_saved >= 3 else (
        "PARTIAL" if images_saved > 0 else "FAILED"
    )
    organizer.record_catalogue_entry(vehicle, images_saved, saved_filenames, status)
    organizer.record_qc(
        vehicle, images_found, images_validated, images_saved, queries_tried, errors
    )

    return images_saved, images_found, images_validated, errors


def _score_results(results: list, vehicle: VehicleEntry) -> list:
    """
    Score image results by relevance to the vehicle.
    Higher score = more likely a good dashboard image.
    """
    scored = []
    for result in results:
        score = 0.0

        # Prefer larger images
        if result.width >= 1200 and result.height >= 800:
            score += 3.0
        elif result.width >= 800 and result.height >= 600:
            score += 1.5

        # Prefer landscape orientation
        if result.width > result.height:
            score += 2.0

        # Check title/URL for relevant keywords
        text = (result.title + " " + result.url + " " + result.source_page).lower()

        relevance_keywords = [
            'dashboard', 'interior', 'cockpit', 'center console',
            'instrument panel', 'radio', 'infotainment', 'cabin',
        ]
        for kw in relevance_keywords:
            if kw in text:
                score += 1.5

        # Check for vehicle-specific terms
        make_lower = vehicle.make.lower()
        model_lower = vehicle.model.lower()
        if make_lower in text:
            score += 1.0
        if model_lower in text:
            score += 1.5

        # Penalize for aftermarket/modified
        bad_keywords = [
            'aftermarket', 'custom', 'modified', 'wrap', 'tune',
            'android', 'head unit', 'stereo replacement', 'installation',
            'aliexpress', 'alibaba', 'ebay',
        ]
        for kw in bad_keywords:
            if kw in text:
                score -= 2.0

        # Prefer automotive/editorial sources
        good_domains = [
            'caranddriver', 'motortrend', 'edmunds', 'autoblog',
            'kbb', 'cargurus', 'autotrader', 'topgear',
            'carwow', 'whatcar', 'parkers', 'media.ed.edmunds',
            'netcarshow', 'carpixel', 'cars.com',
        ]
        for domain in good_domains:
            if domain in result.source_page.lower() or domain in result.url.lower():
                score += 3.0
                break

        scored.append((score, result))

    return scored


# ─── CLI & Main ────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="Vehicle Dashboard Image Scraper for Audio Superb CC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scrape_dashboards.py                                # Process all vehicles
  python scrape_dashboards.py --limit 5                      # Test with 5 vehicles
  python scrape_dashboards.py --make TOYOTA                  # Only Toyota vehicles
  python scrape_dashboards.py --resume                       # Skip completed vehicles
  python scrape_dashboards.py --serpapi-key sk-xxxx           # Use Google via SerpAPI
  python scrape_dashboards.py --dry-run                      # Parse CSV only
  python scrape_dashboards.py --images 3                     # 3 images per vehicle
        """
    )
    parser.add_argument(
        "--csv", default="list of trims to scrape 2026.02.04.csv",
        help="Path to the input CSV file (default: list of trims to scrape 2026.02.04.csv)"
    )
    parser.add_argument(
        "--output", default="dashboards",
        help="Output directory for images (default: dashboards/)"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit to first N vehicles (0 = no limit)"
    )
    parser.add_argument(
        "--make", type=str, default="",3
        help="Filter to a specific make (e.g., BMW, TOYOTA)"
    )
    parser.add_argument(
        "--images", type=int, default=5,
        help="Target number of images per vehicle (default: 5)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip vehicles that were already successfully scraped"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse CSV and show vehicles without scraping"
    )
    parser.add_argument(
        "--serpapi-key", type=str, default="",
        help="SerpAPI key for Google Images search (optional)"
    )
    parser.add_argument(
        "--min-width", type=int, default=800,
        help="Minimum image width in pixels (default: 800)"
    )
    parser.add_argument(
        "--min-height", type=int, default=600,
        help="Minimum image height in pixels (default: 600)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose/debug logging"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(args.output, "scraper.log") if not args.dry_run else "scraper.log",
                mode='a'
            ),
        ]
    )

    print(r"""
    ╔══════════════════════════════════════════════════════╗
    ║   Vehicle Dashboard Image Scraper                   ║
    ║   Audio Superb CC - Trim Kit Catalogue Builder      ║
    ╚══════════════════════════════════════════════════════╝
    """)

    # Step 1: Parse CSV
    print("Step 1: Parsing vehicle catalogue CSV...")
    vehicles = parse_csv(args.csv)

    if not vehicles:
        print("ERROR: No vehicles found in CSV!")
        sys.exit(1)

    # Apply filters
    if args.make:
        vehicles = [v for v in vehicles if v.make.upper() == args.make.upper()]
        print(f"Filtered to {len(vehicles)} {args.make.upper()} vehicles")

    if args.limit > 0:
        vehicles = vehicles[:args.limit]
        print(f"Limited to first {len(vehicles)} vehicles")

    # Export clean vehicle list
    os.makedirs(args.output, exist_ok=True)
    generate_vehicle_list_csv(vehicles, os.path.join(args.output, "parsed_vehicles.csv"))

    if args.dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN - Vehicle list ({len(vehicles)} entries):")
        print(f"{'='*60}")
        for i, v in enumerate(vehicles, 1):
            print(f"  {i:3d}. {v.make:12s} {v.model:30s} {v.year_range:12s} (SKUs: {len(v.skus)})")
            print(f"       Query: {v.search_query}")
        print(f"\nTotal: {len(vehicles)} unique vehicles to scrape")
        return

    # Step 2: Initialize components
    print("\nStep 2: Initializing scraper...")
    config = ScraperConfig(
        images_per_vehicle=args.images,
        min_width=args.min_width,
        min_height=args.min_height,
        serpapi_key=args.serpapi_key or os.environ.get("SERPAPI_KEY", ""),
        output_dir=args.output,
    )
    scraper = ImageScraper(config)
    organizer = FileOrganizer(args.output)
    progress = ProgressTracker(os.path.join(args.output, ".scrape_progress.json"))

    # Step 3: Process vehicles
    print(f"\nStep 3: Scraping images for {len(vehicles)} vehicles...")
    print(f"         Target: {args.images} images per vehicle")
    print(f"         Min resolution: {args.min_width}x{args.min_height}")
    if config.serpapi_key:
        print(f"         Using SerpAPI for Google Images ✓")
    print(f"{'='*60}\n")

    start_time = time.time()
    total_images = 0
    processed = 0
    skipped_resume = 0

    for idx, vehicle in enumerate(vehicles):
        if _shutdown_requested:
            print(f"\n⚠ Shutdown requested. Processed {processed} vehicles.")
            break

        # Resume: skip already completed
        if args.resume and progress.is_completed(vehicle):
            skipped_resume += 1
            continue

        processed += 1
        elapsed = time.time() - start_time
        rate = processed / max(elapsed, 1) * 60  # vehicles per minute

        print(f"\n[{idx + 1}/{len(vehicles)}] {vehicle.make} {vehicle.model} ({vehicle.year_range})")
        print(f"  Search: {vehicle.search_query}")
        if processed > 1:
            remaining = (len(vehicles) - idx) / max(rate, 0.1)
            print(f"  Progress: {processed} done | {rate:.1f} vehicles/min | ~{remaining:.0f} min remaining")

        # Scrape
        images_saved, images_found, images_validated, errors = scrape_vehicle(
            vehicle, scraper, organizer, target_images=args.images
        )

        total_images += images_saved
        progress.mark_completed(vehicle, images_saved)

        # Status indicator
        if images_saved >= 3:
            status_icon = "✓"
        elif images_saved > 0:
            status_icon = "~"
        else:
            status_icon = "✗"

        print(f"  {status_icon} Result: {images_saved}/{args.images} images saved "
              f"(found: {images_found}, valid: {images_validated})")

        if errors:
            for err in errors[:2]:
                print(f"    ⚠ {err}")

    # Close scraper session
    scraper.session.close()

    # Step 4: Generate reports
    print(f"\n\nStep 4: Generating reports...")
    catalogue_path = organizer.generate_master_catalogue()
    qc_path = organizer.generate_qc_report()

    # Final summary
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"SCRAPING COMPLETE")
    print(f"{'='*60}")
    print(f"Time elapsed:        {elapsed/60:.1f} minutes")
    print(f"Vehicles processed:  {processed}")
    if skipped_resume:
        print(f"Vehicles resumed:    {skipped_resume}")
    print(f"Total images saved:  {total_images}")
    print(f"Output directory:    {args.output}/")
    print(f"Master catalogue:    {catalogue_path}")
    print(f"QC report:           {qc_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
