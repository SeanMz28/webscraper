"""
Vehicle Parser Module
=====================
Parses the trim catalogue CSV and extracts unique vehicle entries
with Make, Model, Year Range, and associated SKUs.
"""

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VehicleEntry:
    """Represents a unique vehicle for dashboard image scraping."""
    make: str
    model: str
    year_range: str
    skus: list = field(default_factory=list)
    description: str = ""

    @property
    def folder_name(self) -> str:
        """Generate a filesystem-safe folder name."""
        safe_model = re.sub(r'[^\w\s-]', '', self.model).strip()
        safe_model = re.sub(r'\s+', '_', safe_model)
        safe_year = self.year_range.replace(' ', '').replace('+', '-present')
        return f"{safe_model}_{safe_year}"

    @property
    def search_query(self) -> str:
        """Generate an optimized Google Images search query."""
        # Pick a representative year from the range for better results
        year = self._representative_year()
        query = f"{year} {self.make} {self.model} dashboard interior OEM"
        return query

    @property
    def alt_search_queries(self) -> list:
        """Generate alternative search queries for fallback."""
        year = self._representative_year()
        return [
            f"{year} {self.make} {self.model} interior center console",
            f"{self.make} {self.model} {self.year_range} dashboard",
            f"{self.make} {self.model} {year} cockpit interior view",
            f"{self.make} {self.model} radio dashboard center stack",
        ]

    def _representative_year(self) -> str:
        """Extract a representative year from a year range."""
        years = re.findall(r'((?:19|20)\d{2})', self.year_range)
        if years:
            # Use the first year in the range
            return years[0]
        return ""

    def __hash__(self):
        return hash((self.make, self.model, self.year_range))

    def __eq__(self, other):
        if not isinstance(other, VehicleEntry):
            return False
        return (self.make == other.make and
                self.model == other.model and
                self.year_range == other.year_range)


# Known vehicle makes for detection
KNOWN_MAKES = [
    "ALFA", "AUDI", "BMW", "CHEVROLET", "CHRYSLER", "DAEWOO", "DAIHATSU",
    "FIAT", "FORD", "FOTON", "GWM", "HAVAL", "HONDA", "HYUNDAI", "ISUZU",
    "IVECO", "JEEP", "KIA", "LANDROVER", "LAND ROVER", "LEXUS", "MAHINDRA",
    "MAZDA", "MERCEDES", "MITSUBISHI", "NISSAN", "OPEL", "PEUGEOT",
    "PORSCHE", "RENAULT", "SUBARU", "SUZUKI", "SUSUKI", "TOYOTA", "VW",
    "VOLKSWAGEN",
]


def _extract_make(description: str) -> Optional[str]:
    """Extract the vehicle make from a description string."""
    desc_upper = description.upper()
    for make in sorted(KNOWN_MAKES, key=len, reverse=True):
        if make in desc_upper:
            # Normalise some make names
            if make in ("SUSUKI",):
                return "SUZUKI"
            if make in ("VOLKSWAGEN",):
                return "VW"
            if make in ("LAND ROVER",):
                return "LANDROVER"
            return make
    return None


def _extract_model_and_year(description: str, make: str) -> tuple:
    """Extract model name and year range from description."""
    # Remove the make from the description to isolate model
    desc = description.upper()
    make_idx = desc.find(make.upper())
    if make_idx != -1:
        after_make = description[make_idx + len(make):].strip()
    else:
        after_make = description.strip()

    # Clean up common suffixes
    for suffix in [
        "& HARNESS", "& CANBUS HARNESS", "NO HARNESS",
        "S/DIN", "D/DIN", "S/D-DIN",
        "WITH POCKET", "WITH DISPLAY", "NO DISPLAY",
        "WITH SWITCHES", "NO CD", "WITH CD MECH",
        "MANUAL AIRCON", "AUTO AIRCON", "MANUEL ACC",
        "AUTO/MANUAL AIRCON", "MANUAL /AUTO AIRCON",
        "WITH ELEC BUTTONS", "WITH HAZZARD SWITCH",
        "WITH HAZZARD SWITCH/DOOR LOCK BUTTONS",
        "UV BLACK", "RHD", "BLACK", "SILVER", "SILVER GREY",
        "CURVE", "FLAT",
    ]:
        after_make = re.sub(re.escape(suffix), '', after_make, flags=re.IGNORECASE)

    # Remove screen size references like 9"", 10.1"", 7""
    after_make = re.sub(r'\d+\.?\d*\s*[""\']+\s*/?\s*\d*\.?\d*\s*[""\']*', '', after_make)
    after_make = re.sub(r'\(\w+\)', '', after_make)  # Remove (RIGHT), (SILVER) etc.

    # Extract years
    year_pattern = r'((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2})'
    year_range_match = re.search(year_pattern, after_make)

    single_year_pattern = r'((?:19|20)\d{2})\+?'
    single_year_match = re.search(single_year_pattern, after_make)

    year_range = ""
    if year_range_match:
        year_range = f"{year_range_match.group(1)}-{year_range_match.group(2)}"
        # Remove year from model string
        after_make = after_make[:year_range_match.start()] + after_make[year_range_match.end():]
    elif single_year_match:
        year_str = single_year_match.group(0)
        if year_str.endswith('+'):
            year_range = f"{single_year_match.group(1)}+"
        else:
            year_range = single_year_match.group(1)
        after_make = after_make[:single_year_match.start()] + after_make[single_year_match.end():]

    # Clean model name
    model = after_make.strip()
    model = re.sub(r'\s+', ' ', model)
    model = model.strip(' /-&,')

    # Remove leftover artifacts
    model = re.sub(r'\s*TRIM\b', '', model, flags=re.IGNORECASE)
    model = re.sub(r'\s+', ' ', model).strip()

    return model, year_range


def parse_csv(csv_path: str) -> list:
    """
    Parse the trim catalogue CSV and return a deduplicated list of VehicleEntry objects.

    The CSV has columns: TRIMPLATE, CARAV, Description, A/SUPERB qty, OTHER qty
    We use column C (Description) to extract vehicle information.
    """
    vehicles_dict = {}  # Key: (make, model, year_range) -> VehicleEntry
    skipped = []

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        rows = list(reader)

    # Skip header rows (first 5 rows are headers/contact info)
    data_rows = rows[5:]  # Skip: name, email, 2 blank, header

    for row_idx, row in enumerate(data_rows):
        if len(row) < 3:
            continue

        sku = row[0].strip() if row[0] else ""
        description = row[2].strip() if row[2] else ""

        if not description or not sku:
            continue

        # Skip non-vehicle entries (adapters, brackets, bezels, pockets)
        skip_patterns = [
            r'ADAPTER',
            r'BEZZLE',
            r'BRACKET',
            r'^POCKET',
            r'UNIVERSAL POCKET',
            r'UNIVERSAL.*SIDE PLATE',
            r'CITI GOLF S/DIN',  # Too generic
        ]
        if any(re.search(p, description, re.IGNORECASE) for p in skip_patterns):
            continue

        make = _extract_make(description)
        if not make:
            skipped.append((sku, description, "Could not identify make"))
            continue

        model, year_range = _extract_model_and_year(description, make)

        if not model:
            skipped.append((sku, description, "Could not identify model"))
            continue

        key = (make, model, year_range)
        if key in vehicles_dict:
            vehicles_dict[key].skus.append(sku)
        else:
            vehicles_dict[key] = VehicleEntry(
                make=make,
                model=model,
                year_range=year_range,
                skus=[sku],
                description=description,
            )

    vehicles = sorted(vehicles_dict.values(), key=lambda v: (v.make, v.model, v.year_range))

    print(f"\n{'='*60}")
    print(f"CSV Parsing Summary")
    print(f"{'='*60}")
    print(f"Total data rows processed: {len(data_rows)}")
    print(f"Unique vehicles extracted:  {len(vehicles)}")
    print(f"Entries skipped:            {len(skipped)}")
    print(f"{'='*60}")

    if skipped:
        print(f"\nSkipped entries (first 10):")
        for sku, desc, reason in skipped[:10]:
            print(f"  [{sku}] {desc} -> {reason}")

    return vehicles


def generate_vehicle_list_csv(vehicles: list, output_path: str):
    """Write the parsed vehicle list to a clean CSV for review."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Make', 'Model', 'Year Range', 'Search Query',
            'Folder Name', 'SKU Count', 'SKUs'
        ])
        for v in vehicles:
            writer.writerow([
                v.make, v.model, v.year_range, v.search_query,
                v.folder_name, len(v.skus), '; '.join(v.skus[:5])
            ])
    print(f"\nVehicle list saved to: {output_path}")


if __name__ == "__main__":
    import sys
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "list of trims to scrape 2026.02.04.csv"
    vehicles = parse_csv(csv_file)

    print(f"\nFirst 20 vehicles:")
    print(f"{'-'*80}")
    for v in vehicles[:20]:
        print(f"  {v.make:12s} | {v.model:35s} | {v.year_range:12s} | SKUs: {len(v.skus)}")

    generate_vehicle_list_csv(vehicles, "parsed_vehicles.csv")
