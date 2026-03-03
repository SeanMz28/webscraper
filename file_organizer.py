"""
File Organizer & Catalogue Generator
======================================
Manages the output folder structure, saves images with metadata,
and generates the master catalogue CSV + quality control report.
"""

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from vehicle_parser import VehicleEntry
from image_scraper import ImageResult

logger = logging.getLogger(__name__)


class FileOrganizer:
    """Manages the output folder structure and image storage."""

    def __init__(self, base_dir: str = "dashboards"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._catalogue_entries = []
        self._qc_records = []

    def get_vehicle_dir(self, vehicle: VehicleEntry) -> Path:
        """Create and return the directory path for a vehicle."""
        vehicle_dir = self.base_dir / vehicle.make / vehicle.folder_name
        vehicle_dir.mkdir(parents=True, exist_ok=True)
        return vehicle_dir

    def save_image(
        self,
        vehicle: VehicleEntry,
        image_data: bytes,
        image_result: ImageResult,
        filename: str,
    ) -> Optional[str]:
        """Save an image to the vehicle's directory and return the full path."""
        vehicle_dir = self.get_vehicle_dir(vehicle)
        filepath = vehicle_dir / filename

        try:
            with open(filepath, 'wb') as f:
                f.write(image_data)

            logger.info(f"  Saved: {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"  Failed to save {filepath}: {e}")
            return None

    def save_metadata(
        self,
        vehicle: VehicleEntry,
        downloaded_images: list,
    ):
        """Save metadata JSON file for a vehicle's images."""
        vehicle_dir = self.get_vehicle_dir(vehicle)
        metadata_file = vehicle_dir / "metadata.json"

        metadata = {
            "vehicle": {
                "make": vehicle.make,
                "model": vehicle.model,
                "year_range": vehicle.year_range,
                "skus": vehicle.skus,
                "description": vehicle.description,
            },
            "search_queries_used": list(set(
                img["search_query"] for img in downloaded_images
            )),
            "download_date": datetime.now().isoformat(),
            "images": downloaded_images,
            "total_images": len(downloaded_images),
        }

        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info(f"  Metadata saved: {metadata_file}")

    def record_catalogue_entry(
        self,
        vehicle: VehicleEntry,
        images_saved: int,
        image_files: list,
        status: str,
    ):
        """Record a catalogue entry for the master CSV."""
        self._catalogue_entries.append({
            "make": vehicle.make,
            "model": vehicle.model,
            "year_range": vehicle.year_range,
            "skus": "; ".join(vehicle.skus[:5]),
            "search_query": vehicle.search_query,
            "images_saved": images_saved,
            "image_files": "; ".join(image_files),
            "status": status,
            "folder": str(self.get_vehicle_dir(vehicle)),
        })

    def record_qc(
        self,
        vehicle: VehicleEntry,
        images_found: int,
        images_validated: int,
        images_saved: int,
        queries_tried: int,
        errors: list,
    ):
        """Record a quality control entry."""
        self._qc_records.append({
            "make": vehicle.make,
            "model": vehicle.model,
            "year_range": vehicle.year_range,
            "images_found": images_found,
            "images_validated": images_validated,
            "images_saved": images_saved,
            "queries_tried": queries_tried,
            "errors": "; ".join(errors) if errors else "",
            "status": "SUCCESS" if images_saved >= 3 else (
                "PARTIAL" if images_saved > 0 else "FAILED"
            ),
        })

    def generate_master_catalogue(self, output_file: str = "master_catalogue.csv"):
        """Generate the master catalogue CSV mapping vehicles to images."""
        filepath = self.base_dir / output_file

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'make', 'model', 'year_range', 'skus', 'search_query',
                'images_saved', 'image_files', 'status', 'folder',
            ])
            writer.writeheader()
            for entry in sorted(
                self._catalogue_entries,
                key=lambda x: (x['make'], x['model'])
            ):
                writer.writerow(entry)

        logger.info(f"\nMaster catalogue saved: {filepath}")
        return str(filepath)

    def generate_qc_report(self, output_file: str = "quality_control_report.csv"):
        """Generate the quality control report."""
        filepath = self.base_dir / output_file

        # Summary stats
        total = len(self._qc_records)
        success = sum(1 for r in self._qc_records if r['status'] == 'SUCCESS')
        partial = sum(1 for r in self._qc_records if r['status'] == 'PARTIAL')
        failed = sum(1 for r in self._qc_records if r['status'] == 'FAILED')
        total_images = sum(r['images_saved'] for r in self._qc_records)

        # Write CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'make', 'model', 'year_range', 'images_found',
                'images_validated', 'images_saved', 'queries_tried',
                'status', 'errors',
            ])
            writer.writeheader()
            for record in sorted(
                self._qc_records,
                key=lambda x: (x['status'], x['make'], x['model'])
            ):
                writer.writerow(record)

        # Write summary report
        summary_file = self.base_dir / "qc_summary.txt"
        with open(summary_file, 'w') as f:
            f.write("=" * 60 + "\n")
            f.write("QUALITY CONTROL SUMMARY REPORT\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Total vehicles processed:  {total}\n")
            f.write(f"Successful (3+ images):    {success} ({success/max(total,1)*100:.1f}%)\n")
            f.write(f"Partial (1-2 images):      {partial} ({partial/max(total,1)*100:.1f}%)\n")
            f.write(f"Failed (0 images):         {failed} ({failed/max(total,1)*100:.1f}%)\n")
            f.write(f"Total images downloaded:   {total_images}\n")
            f.write(f"Avg images per vehicle:    {total_images/max(total,1):.1f}\n\n")

            if failed > 0:
                f.write("FAILED VEHICLES:\n")
                f.write("-" * 40 + "\n")
                for r in self._qc_records:
                    if r['status'] == 'FAILED':
                        f.write(f"  {r['make']} {r['model']} {r['year_range']}\n")
                        if r['errors']:
                            f.write(f"    Errors: {r['errors']}\n")

        logger.info(f"QC report saved: {filepath}")
        logger.info(f"QC summary saved: {summary_file}")

        # Print summary to console
        print(f"\n{'='*60}")
        print(f"QUALITY CONTROL SUMMARY")
        print(f"{'='*60}")
        print(f"Total vehicles:         {total}")
        print(f"  ✓ Success (3+ imgs):  {success}")
        print(f"  ~ Partial (1-2 imgs): {partial}")
        print(f"  ✗ Failed  (0 imgs):   {failed}")
        print(f"Total images saved:     {total_images}")
        print(f"Success rate:           {(success + partial) / max(total, 1) * 100:.1f}%")
        print(f"{'='*60}")

        return str(filepath)
