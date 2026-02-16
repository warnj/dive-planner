#!/usr/bin/env python3
"""
Parse Canadian Hydrographic Service (CHS) current prediction PDFs into Slack objects.

Usage:
    python canada_pdf_parser.py <url>

Example:
    python canada_pdf_parser.py "https://tides.gc.ca/sites/tides/files/2025-11/08450_2026.pdf"
"""

import sys
import os
import re
import requests
import pdfplumber
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Tuple
import pytz

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


# Mapping of month names to numbers
MONTH_MAP = {
    'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4,
    'MAY': 5, 'JUNE': 6, 'JULY': 7, 'AUGUST': 8,
    'SEPTEMBER': 9, 'OCTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12,
    'JANVIER': 1, 'FÉVRIER': 2, 'FEVRIER': 2, 'MARS': 3, 'AVRIL': 4,
    'MAI': 5, 'JUIN': 6, 'JUILLET': 7, 'AOÛT': 8, 'AOUT': 8,
    'SEPTEMBRE': 9, 'OCTOBRE': 10, 'NOVEMBRE': 11, 'DÉCEMBRE': 12, 'DECEMBRE': 12
}


def download_pdf(url: str, output_path: str = None) -> str:
    """Download PDF from URL and return the local file path."""
    if output_path is None:
        output_path = "temp_current_predictions.pdf"

    response = requests.get(url)
    response.raise_for_status()

    with open(output_path, 'wb') as f:
        f.write(response.content)

    return output_path


def extract_year_from_url(url: str) -> int:
    """Extract the year from the PDF URL (e.g., 08450_2026.pdf -> 2026)."""
    match = re.search(r'_(\d{4})\.pdf', url)
    if match:
        return int(match.group(1))
    raise ValueError(f"Could not extract year from URL: {url}")


def apply_dst_correction(dt_naive: datetime, timezone_str: str = "America/Vancouver") -> datetime:
    """
    Apply DST correction to a naive datetime that's in Pacific Standard Time.

    The CHS PDFs use PST (UTC-8) throughout, so we need to:
    1. Treat the time as PST
    2. Check if DST was in effect on that date
    3. If DST was in effect, add 1 hour to convert PST to PDT

    Returns a naive datetime representing the correct local time.
    """
    tz = pytz.timezone(timezone_str)

    # First, localize as PST (standard time, not DST)
    # We create a datetime at the start of the day to check DST status
    day_start = datetime(dt_naive.year, dt_naive.month, dt_naive.day, 12, 0, 0)

    # Check if DST is in effect on this date
    # We use localize with is_dst=None and catch ambiguous times
    try:
        localized = tz.localize(day_start, is_dst=None)
    except pytz.exceptions.AmbiguousTimeError:
        # During fall-back, just use DST=False
        localized = tz.localize(day_start, is_dst=False)

    # Check DST offset
    dst_offset = localized.dst()

    if dst_offset and dst_offset.total_seconds() > 0:
        # DST is in effect, add 1 hour to the PST time to get correct local time
        return dt_naive + timedelta(hours=1)
    else:
        # Standard time, no correction needed
        return dt_naive


def parse_time(time_str: str) -> Tuple[int, int]:
    """Parse time string like '0154' or '0409' into (hour, minute)."""
    time_str = time_str.strip()
    if len(time_str) == 3:
        time_str = '0' + time_str
    if len(time_str) != 4:
        raise ValueError(f"Invalid time format: {time_str}")

    hour = int(time_str[:2])
    minute = int(time_str[2:])
    return hour, minute


def parse_speed(speed_str: str) -> float:
    """Parse speed string like '+9.5' or '-13.2' into float."""
    return float(speed_str)


def is_day_indicator(token: str) -> bool:
    """Check if token is a day-of-week indicator like TH, FR, SA, etc."""
    day_codes = {'MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU',
                 'LU', 'MA', 'ME', 'JE', 'VE', 'DI'}  # English and French
    return token.upper() in day_codes


@dataclass
class CurrentEvent:
    """Represents either a slack or maximum current event."""
    time: datetime
    speed: float  # 0 for slack, positive for flood, negative for ebb
    is_slack: bool
    is_ebb: bool  # True for ebb, False for flood


def parse_day_data(day_text: str, year: int, month: int, day: int) -> List[CurrentEvent]:
    """
    Parse a day's data block and return list of CurrentEvents.

    Example input for a day:
    "1 0154 0409 -5.2
     0628 0945 +9.5
     TH 1301 1702 -13.2
     JE 2103 2358 +8.4"

    The pattern is: [day#] slack_time max_time speed
    Day indicators (TH, JE, etc.) can appear at start of lines.
    """
    events = []
    lines = day_text.strip().split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        tokens = line.split()
        if not tokens:
            continue

        # Skip day-of-week indicators at start
        idx = 0
        while idx < len(tokens) and is_day_indicator(tokens[idx]):
            idx += 1

        # Skip day number if present at start
        if idx < len(tokens) and tokens[idx].isdigit() and len(tokens[idx]) <= 2:
            idx += 1

        remaining = tokens[idx:]

        # Parse patterns - could be:
        # 1. "slack_time max_time speed" (3 tokens: two times + speed)
        # 2. "time speed" (2 tokens: one time + speed, usually a lone slack/max)
        # 3. "time" (1 token: just a time, usually at end of day)

        if len(remaining) >= 3:
            # Pattern: slack_time max_time speed
            try:
                slack_h, slack_m = parse_time(remaining[0])
                max_h, max_m = parse_time(remaining[1])
                speed = parse_speed(remaining[2])

                # Create slack event (speed = 0)
                slack_time = datetime(year, month, day, slack_h, slack_m)
                events.append(CurrentEvent(
                    time=slack_time,
                    speed=0.0,
                    is_slack=True,
                    is_ebb=speed < 0  # The following maximum determines ebb/flood
                ))

                # Create max event
                max_time = datetime(year, month, day, max_h, max_m)
                # Handle day rollover
                if max_h < slack_h - 12:
                    max_time = datetime(year, month, day, max_h, max_m) + timedelta(days=1)
                events.append(CurrentEvent(
                    time=max_time,
                    speed=speed,
                    is_slack=False,
                    is_ebb=speed < 0
                ))
            except (ValueError, IndexError):
                pass

        elif len(remaining) == 2:
            # Pattern: time speed (standalone max)
            try:
                h, m = parse_time(remaining[0])
                speed = parse_speed(remaining[1])

                event_time = datetime(year, month, day, h, m)
                events.append(CurrentEvent(
                    time=event_time,
                    speed=speed,
                    is_slack=abs(speed) < 0.1,
                    is_ebb=speed < 0
                ))
            except (ValueError, IndexError):
                pass

        elif len(remaining) == 1:
            # Pattern: just a time (standalone, interpret as slack at end of day)
            try:
                h, m = parse_time(remaining[0])
                event_time = datetime(year, month, day, h, m)
                # This is typically a slack at end of day, direction unknown
                events.append(CurrentEvent(
                    time=event_time,
                    speed=0.0,
                    is_slack=True,
                    is_ebb=False  # Will be corrected based on surrounding events
                ))
            except (ValueError, IndexError):
                pass

    return events


def parse_cell_data(cell_text: str, year: int, month: int) -> List[CurrentEvent]:
    """
    Parse a table cell containing one or more days of data.
    Returns all CurrentEvents found in the cell.
    """
    if not cell_text:
        return []

    all_events = []

    # Split by day boundaries - look for lines that start with a day number
    lines = cell_text.strip().split('\n')
    current_day = None
    current_block = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        tokens = line.split()
        # Check if this line starts with a new day number
        first_token_idx = 0
        if is_day_indicator(tokens[0]):
            first_token_idx = 1

        if first_token_idx < len(tokens) and tokens[first_token_idx].isdigit() and len(tokens[first_token_idx]) <= 2:
            # New day starting
            if current_day is not None and current_block:
                # Process previous day's data
                day_events = parse_day_data('\n'.join(current_block), year, month, current_day)
                all_events.extend(day_events)

            current_day = int(tokens[first_token_idx])
            current_block = [line]
        else:
            # Continuation of current day
            if current_day is not None:
                current_block.append(line)

    # Don't forget the last day
    if current_day is not None and current_block:
        day_events = parse_day_data('\n'.join(current_block), year, month, current_day)
        all_events.extend(day_events)

    return all_events


def events_to_slacks(events: List[CurrentEvent]) -> List[Slack]:
    """
    Convert a list of CurrentEvents into Slack objects.

    A Slack object needs:
    - time: slack time
    - slackBeforeEbb: True if ebb follows the slack
    - ebbSpeed: max ebb speed (negative)
    - floodSpeed: max flood speed (positive)
    - maxEbbTime: time of max ebb
    - maxFloodTime: time of max flood
    """
    # Sort events by time
    events = sorted(events, key=lambda e: e.time)

    slacks = []
    slack_indices = [i for i, e in enumerate(events) if e.is_slack]

    for i, slack_idx in enumerate(slack_indices):
        slack_event = events[slack_idx]

        # Find previous and next max events
        prev_max = None
        next_max = None

        # Look backwards for previous max
        for j in range(slack_idx - 1, -1, -1):
            if not events[j].is_slack:
                prev_max = events[j]
                break

        # Look forwards for next max
        for j in range(slack_idx + 1, len(events)):
            if not events[j].is_slack:
                next_max = events[j]
                break

        if prev_max is None or next_max is None:
            # Skip slacks at boundaries where we can't determine surrounding maxes
            continue

        s = Slack()
        s.time = apply_dst_correction(slack_event.time)

        # Determine if this is slack before ebb based on what follows
        s.slackBeforeEbb = next_max.is_ebb

        # Assign ebb and flood speeds
        if next_max.is_ebb:
            # Next is ebb, so previous was flood
            s.floodSpeed = abs(prev_max.speed)
            s.maxFloodTime = apply_dst_correction(prev_max.time)
            s.ebbSpeed = -abs(next_max.speed)
            s.maxEbbTime = apply_dst_correction(next_max.time)
        else:
            # Next is flood, so previous was ebb
            s.ebbSpeed = -abs(prev_max.speed)
            s.maxEbbTime = apply_dst_correction(prev_max.time)
            s.floodSpeed = abs(next_max.speed)
            s.maxFloodTime = apply_dst_correction(next_max.time)

        slacks.append(s)

    return slacks


def parse_pdf(pdf_path: str, year: int) -> List[Slack]:
    """
    Parse the CHS current predictions PDF and return list of Slack objects.
    """
    all_events = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            # Extract months from the header
            # Format: "January-janvier February-fvrier March-mars"
            months_on_page = []
            for month_name, month_num in MONTH_MAP.items():
                if month_name.upper() in text.upper():
                    if month_num not in months_on_page:
                        months_on_page.append(month_num)

            # Sort months to get them in order
            months_on_page = sorted(set(months_on_page))[:3]  # Max 3 months per page

            # Extract tables
            tables = page.extract_tables()
            if not tables:
                continue

            # The main data is typically in the first (and often only) table
            for table in tables:
                # Skip header rows
                for row in table[2:]:  # Skip first 2 header rows
                    if not row:
                        continue

                    # The row contains data for multiple months
                    # Structure: for each month there are 2 columns (days 1-15, days 16-31)
                    # But there are also None columns interspersed
                    # Pattern: [Month1_col1, None, Month1_col2, None, Month2_col1, None, ...]
                    # So actual data is at indices 0, 2, 4, 6, 8, 10 (even indices, excluding Nones)
                    data_col_idx = 0  # Counter for non-None columns

                    for cell in row:
                        if cell is None:
                            continue

                        # Each month has 2 data columns (days 1-15, days 16-31)
                        # So month index = data_col_idx // 2
                        month_idx = data_col_idx // 2
                        if month_idx < len(months_on_page):
                            month = months_on_page[month_idx]
                            events = parse_cell_data(cell, year, month)
                            all_events.extend(events)

                        data_col_idx += 1

    # Convert events to slacks
    slacks = events_to_slacks(all_events)

    return slacks


def parse_current_pdf(url: str) -> List[Slack]:
    """
    Main function to download and parse a CHS current predictions PDF.

    Args:
        url: URL to the PDF (e.g., "https://tides.gc.ca/sites/tides/files/2025-11/08450_2026.pdf")

    Returns:
        List of Slack objects representing all slack currents in the PDF
    """
    # Extract year from URL
    year = extract_year_from_url(url)

    # Download PDF
    pdf_path = download_pdf(url)

    try:
        # Parse PDF
        slacks = parse_pdf(pdf_path, year)
        return slacks
    finally:
        # Clean up temporary file
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


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
        print(f"No URL provided, using default: {url}")

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
