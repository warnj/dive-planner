#!/usr/bin/env python3
"""
Parse Canadian Hydrographic Service (CHS) current prediction PDFs into Slack objects.

Usage:
    python canada_pdf_parser.py <url>

Example:
    python canada_pdf_parser.py "https://tides.gc.ca/sites/tides/files/2025-11/08450_2026.pdf"

This module now uses canada_pdf_lib.py for the core parsing logic.
"""

import sys
from datetime import datetime
from dataclasses import dataclass

# Import the shared library
import canada_pdf_lib as pdf_lib

# Import the Slack class from interpreter module if available
try:
    from interpreter import Slack
except ImportError:
    # Define a compatible Slack class if interpreter module not available
    @dataclass
    class Slack:
        time: datetime = None
        sunriseTime: datetime = None
        sunsetTime: datetime = None
        moonPhase: float = -1
        slackBeforeEbb: bool = False
        ebbSpeed: float = 0.0  # negative number
        floodSpeed: float = 0.0  # positive number
        maxEbbTime: datetime = None
        maxFloodTime: datetime = None

        def __str__(self):
            fmt = '%a %Y-%m-%d %I:%M%p'
            time_str = self.time.strftime(fmt) if self.time else 'None'
            if self.slackBeforeEbb:
                return f'{self.floodSpeed} -> {time_str} -> {self.ebbSpeed}'
            else:
                return f'{self.ebbSpeed} -> {time_str} -> {self.floodSpeed}'

        def speedSum(self):
            return abs(self.floodSpeed) + abs(self.ebbSpeed)


def parse_current_pdf(url: str):
    """
    Main function to download and parse a CHS current predictions PDF.
    Uses the common library from canada_pdf_lib.py.

    Args:
        url: URL to the PDF (e.g., "https://tides.gc.ca/sites/tides/files/2025-11/08450_2026.pdf")

    Returns:
        List of Slack objects representing all slack currents in the PDF
    """
    return pdf_lib.parse_current_pdf(url, Slack)


def main():
    # Parse arguments
    url = None
    # Default date range (set to None for no filtering, or use strings like "2026-09-28")
    start_date = "2026-09-28"
    end_date = "2026-10-05"

    # Convert string dates to datetime objects
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    for arg in sys.argv[1:]:
        if arg.startswith("--start="):
            start_date = datetime.strptime(arg.split("=")[1], "%Y-%m-%d")
        elif arg.startswith("--end="):
            end_date = datetime.strptime(arg.split("=")[1], "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        elif not arg.startswith("--"):
            url = arg

    if url is None:
        # Default to example URL if no args provided
        # parent url:  https://tides.gc.ca/en/current-predictions-station
        url = "https://tides.gc.ca/sites/tides/files/2025-11/08450_2026.pdf" # Nakwakto
        # url = "https://tides.gc.ca/sites/tides/files/2025-11/08108_2026.pdf" # Seymour
        # url = "https://tides.gc.ca/sites/tides/files/2025-11/07545_2026.pdf" # Gabriola
        # url = "https://tides.gc.ca/sites/tides/files/2025-11/08277_2026.pdf" # Weynton Pass
        # print(f"No URL provided, using default: {url}")

    print(f"Parsing PDF from: {url}")

    slacks = parse_current_pdf(url)

    print(f"\nFound {len(slacks)} slack currents total")

    # Sort all slacks by combined speed (least to most)
    slacks.sort(key=lambda x: abs(x.ebbSpeed) + abs(x.floodSpeed))

    # Build a map of slack -> rank (1-based)
    slack_ranks = {id(slack): rank for rank, slack in enumerate(slacks, 1)}

    # Filter by date range if provided
    if start_date or end_date:
        filtered_slacks = []
        for slack in slacks:
            if start_date and slack.time < start_date:
                continue
            if end_date and slack.time > end_date:
                continue
            filtered_slacks.append(slack)

        # Sort filtered slacks by time for display
        filtered_slacks.sort(key=lambda x: x.time)

        date_range_str = ""
        if start_date:
            date_range_str += f" from {start_date.strftime('%Y-%m-%d')}"
        if end_date:
            date_range_str += f" to {end_date.strftime('%Y-%m-%d')}"

        print(f"Showing {len(filtered_slacks)} slacks{date_range_str}:\n")

        for slack in filtered_slacks:
            rank = slack_ranks[id(slack)]
            speed_sum = abs(slack.ebbSpeed) + abs(slack.floodSpeed)
            print(f"Rank {rank}/{len(slacks)} (speed sum: {speed_sum:.1f}): {slack}")
    else:
        print("Sorted by combined speed (least to most):\n")
        for i, slack in enumerate(slacks, 1):
            print(f"{i}. {slack}")


if __name__ == "__main__":
    main()
