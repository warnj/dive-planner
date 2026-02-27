#!/usr/bin/env python3
"""
NOTE:  for really good current days, the pdf may have a * for weak current instead of max/turn - then no ouput is provided!

Common library for parsing Canadian Hydrographic Service (CHS) current prediction PDFs.

This module contains the shared logic used by both canada_pdf_parser.py and
the CanadaPDFInterpreter class in interpreter.py.
"""

import os
import re
import requests
import pdfplumber
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Tuple, Optional
import pytz


# Mapping of month names to numbers (English and French)
MONTH_MAP = {
    'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4,
    'MAY': 5, 'JUNE': 6, 'JULY': 7, 'AUGUST': 8,
    'SEPTEMBER': 9, 'OCTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12,
    'JANVIER': 1, 'FÉVRIER': 2, 'FEVRIER': 2, 'MARS': 3, 'AVRIL': 4,
    'MAI': 5, 'JUIN': 6, 'JUILLET': 7, 'AOÛT': 8, 'AOUT': 8,
    'SEPTEMBRE': 9, 'OCTOBRE': 10, 'NOVEMBRE': 11, 'DÉCEMBRE': 12, 'DECEMBRE': 12
}


@dataclass
class CurrentEvent:
    """Represents either a slack or maximum current event."""
    time: datetime
    speed: float  # 0 for slack, positive for flood, negative for ebb
    is_slack: bool
    is_ebb: bool  # True for ebb, False for flood


def download_pdf(url: str, cache_dir: str = "bc-current-pdfs") -> str:
    """Download PDF from URL and return the local file path.

    Files are cached in the cache_dir directory. If the file already exists
    locally, it will be used instead of downloading again.
    """
    # Create cache directory if it doesn't exist
    os.makedirs(cache_dir, exist_ok=True)

    # Extract filename from URL (e.g., "08450_2026.pdf")
    filename = url.split('/')[-1]
    local_path = os.path.join(cache_dir, filename)

    # Check if file already exists locally
    if os.path.exists(local_path):
        return local_path

    # Download the file
    print(f"Downloading PDF to: {local_path}")
    response = requests.get(url)
    response.raise_for_status()

    with open(local_path, 'wb') as f:
        f.write(response.content)

    return local_path


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
    """Parse time string like '0154', '0409', '1:54', '14:09' into (hour, minute).

    Handles various formats:
    - 4-digit: '0154', '1409'
    - 3-digit: '154' (interpreted as 01:54)
    - Colon-separated: '1:54', '14:09'
    - Space-separated: '1 54', '14 09'
    """
    time_str = time_str.strip()

    # Handle colon-separated format: "1:54" or "14:09"
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        raise ValueError(f"Invalid time format: {time_str}")

    # Handle space-separated format: "1 54" (sometimes seen in parsed PDFs)
    if ' ' in time_str:
        parts = time_str.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])

    # Handle 3-4 digit format: "0154" or "154"
    if len(time_str) == 3:
        time_str = '0' + time_str
    if len(time_str) != 4:
        raise ValueError(f"Invalid time format: {time_str}")

    hour = int(time_str[:2])
    minute = int(time_str[2:])
    return hour, minute


def parse_speed(speed_str: str) -> float:
    """Parse speed string like '+9.5', '-13.2', '0.7F', '0.7E', etc. into float.

    Handles various formats:
    - Signed: '+9.5', '-13.2', '+0.7', '-0.1'
    - With direction suffix: '9.5F' (flood, positive), '13.2E' (ebb, negative)
    - Plain numbers: '9.5', '0.7' (treated as positive)
    """
    speed_str = speed_str.strip().upper()

    # Check for F (flood) or E (ebb) suffix
    if speed_str.endswith('F'):
        # Flood - positive
        return abs(float(speed_str[:-1]))
    elif speed_str.endswith('E'):
        # Ebb - negative
        return -abs(float(speed_str[:-1]))
    else:
        # Standard signed format or plain number
        return float(speed_str)


def is_day_indicator(token: str) -> bool:
    """Check if token is a day-of-week indicator like TH, FR, SA, etc."""
    day_codes = {'MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU',
                 'LU', 'MA', 'ME', 'JE', 'VE', 'DI'}  # English and French
    return token.upper() in day_codes


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

    Expected format for each day:
    "1 0154 0409 -5.2"  (day_num slack_time max_time speed)
    "0628 0945 +9.5"    (continuation: slack_time max_time speed)
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
        if not tokens:
            continue

        # Check if this line starts with a new day number
        first_token_idx = 0
        if is_day_indicator(tokens[0]):
            first_token_idx = 1

        # Look for a day number (1-31) at the start
        found_day = None
        if first_token_idx < len(tokens):
            token = tokens[first_token_idx]
            if token.isdigit() and 1 <= int(token) <= 31:
                found_day = int(token)

        if found_day is not None:
            # New day starting
            if current_day is not None and current_block:
                # Process previous day's data
                day_events = parse_day_data('\n'.join(current_block), year, month, current_day)
                all_events.extend(day_events)

            current_day = found_day
            current_block = [line]
        else:
            # Not a day boundary - could be:
            # 1. Continuation of current day
            # 2. Header/label line (if current_day is None)

            if current_day is not None:
                # Continuation of current day
                current_block.append(line)
            else:
                # Try to parse this line as standalone data
                # This handles cases where the day number might be on a separate line
                # or the cell structure is different

                # Check if this looks like time data (has 4-digit patterns)
                has_time_pattern = False
                for token in tokens:
                    if re.match(r'^\d{3,4}$', token):
                        has_time_pattern = True
                        break

                if has_time_pattern:
                    # This might be orphaned data - try to infer the day
                    # For now, skip it but log a warning in debug mode
                    pass

    # Don't forget the last day
    if current_day is not None and current_block:
        day_events = parse_day_data('\n'.join(current_block), year, month, current_day)
        all_events.extend(day_events)

    return all_events


def events_to_slacks(events: List[CurrentEvent], Slack) -> list:
    """
    Convert a list of CurrentEvents into Slack objects.

    A Slack object needs:
    - time: slack time
    - slackBeforeEbb: True if ebb follows the slack
    - ebbSpeed: max ebb speed (negative)
    - floodSpeed: max flood speed (positive)
    - maxEbbTime: time of max ebb
    - maxFloodTime: time of max flood

    The Slack class is passed as a parameter to allow usage from both
    canada_pdf_parser.py and interpreter.py.
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


def parse_text_fallback(text: str, year: int, months: List[int]) -> List[CurrentEvent]:
    """
    Parse current data directly from raw text when table extraction fails.

    Looks for patterns like:
    "1 0154 0409 -5.2" (day slack_time max_time speed)
    "0628 0945 +9.5" (continuation line)

    This is a fallback for PDFs where pdfplumber's table extraction doesn't work.
    """
    all_events = []

    # Pattern to match data lines:
    # Optional day indicator (TH, FR, etc) + Optional day number (1-31) + time + time + speed
    # Example: "TH 12 0845 1203 -2.5" or "12 0845 1203 -2.5" or "0845 1203 -2.5"

    lines = text.split('\n')
    current_day = None
    current_month_idx = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        tokens = line.split()
        if len(tokens) < 3:
            continue

        # Skip day indicators
        idx = 0
        while idx < len(tokens) and is_day_indicator(tokens[idx]):
            idx += 1

        if idx >= len(tokens):
            continue

        # Check for day number
        if tokens[idx].isdigit() and 1 <= int(tokens[idx]) <= 31:
            new_day = int(tokens[idx])
            # Detect month boundary (day goes back to 1 or lower)
            if current_day is not None and new_day < current_day - 15:
                current_month_idx += 1
            current_day = new_day
            idx += 1

        if current_day is None:
            continue

        if idx >= len(tokens):
            continue

        remaining = tokens[idx:]

        # Need at least 3 tokens: time, time, speed
        if len(remaining) >= 3:
            try:
                slack_h, slack_m = parse_time(remaining[0])
                max_h, max_m = parse_time(remaining[1])
                speed = parse_speed(remaining[2])

                # Get month from current position
                if current_month_idx < len(months):
                    month = months[current_month_idx]
                else:
                    month = months[-1] if months else 1

                # Create slack event
                slack_time = datetime(year, month, current_day, slack_h, slack_m)
                all_events.append(CurrentEvent(
                    time=slack_time,
                    speed=0.0,
                    is_slack=True,
                    is_ebb=speed < 0
                ))

                # Create max event
                max_time = datetime(year, month, current_day, max_h, max_m)
                if max_h < slack_h - 12:
                    max_time = max_time + timedelta(days=1)
                all_events.append(CurrentEvent(
                    time=max_time,
                    speed=speed,
                    is_slack=False,
                    is_ebb=speed < 0
                ))
            except (ValueError, IndexError):
                pass

    return all_events


def parse_pdf(pdf_path: str, year: int, Slack) -> list:
    """
    Parse the CHS current predictions PDF and return list of Slack objects.

    The Slack class is passed as a parameter to allow usage from both
    canada_pdf_parser.py and interpreter.py.

    CHS PDFs have a consistent structure:
    - 4 pages total (one per quarter)
    - Page 1: January, February, March
    - Page 2: April, May, June
    - Page 3: July, August, September
    - Page 4: October, November, December
    - Each month has 2 columns (days 1-15, days 16-31)
    """
    all_events = []

    # Define months per page based on CHS PDF structure
    MONTHS_PER_PAGE = {
        0: [1, 2, 3],    # Page 1: Jan, Feb, Mar
        1: [4, 5, 6],    # Page 2: Apr, May, Jun
        2: [7, 8, 9],    # Page 3: Jul, Aug, Sep
        3: [10, 11, 12], # Page 4: Oct, Nov, Dec
    }

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            # Use page position to determine months instead of text detection
            # This is more reliable as CHS PDFs have a consistent structure
            if page_num in MONTHS_PER_PAGE:
                months_on_page = MONTHS_PER_PAGE[page_num]
            else:
                # Fallback for unexpected page numbers - try to detect from text
                months_on_page = []
                first_lines = text.split('\n')[:10]
                header_text = ' '.join(first_lines).upper()

                for month_name, month_num in MONTH_MAP.items():
                    if month_name.upper() in header_text:
                        if month_num not in months_on_page:
                            months_on_page.append(month_num)
                months_on_page = sorted(set(months_on_page))[:3]

            # Extract tables
            tables = page.extract_tables()

            # Try different table extraction settings if default fails
            if not tables:
                tables = page.extract_tables(table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text"
                })

            if not tables:
                # Try text-based parsing as fallback
                text_events = parse_text_fallback(text, year, months_on_page)
                if text_events:
                    all_events.extend(text_events)
                continue

            # The main data is typically in the first (and often only) table
            for table in tables:
                # Skip first 2 header rows (standard CHS PDF format)
                first_data_row = min(2, len(table))

                for row in table[first_data_row:]:
                    if not row:
                        continue

                    data_col_idx = 0

                    for cell in row:
                        if cell is None:
                            continue

                        month_idx = data_col_idx // 2
                        if month_idx < len(months_on_page):
                            month = months_on_page[month_idx]
                            events = parse_cell_data(cell, year, month)
                            all_events.extend(events)

                        data_col_idx += 1

    # Convert events to slacks
    slacks = events_to_slacks(all_events, Slack)


    return slacks


def parse_current_pdf(url: str, Slack) -> list:
    """
    Main function to download and parse a CHS current predictions PDF.

    Args:
        url: URL to the PDF (e.g., "https://tides.gc.ca/sites/tides/files/2025-11/08450_2026.pdf")
        Slack: The Slack class to use for creating slack objects

    Returns:
        List of Slack objects representing all slack currents in the PDF
    """
    # Extract year from URL
    year = extract_year_from_url(url)

    # Download PDF (or use cached version)
    pdf_path = download_pdf(url)

    # Parse PDF (file is kept in cache for future use)
    slacks = parse_pdf(pdf_path, year, Slack)
    return slacks


def get_slacks_for_day(all_slacks: list, day: datetime, night: bool = False,
                       sunrise: Optional[datetime] = None, sunset: Optional[datetime] = None) -> list:
    """
    Filter slacks for a specific day.

    Args:
        all_slacks: List of all Slack objects from the PDF
        day: The day to filter for
        night: If True, include night slacks; if False, only return daytime slacks
        sunrise: Sunrise time for the day (required if night=False)
        sunset: Sunset time for the day (required if night=False)

    Returns:
        List of Slack objects for the specified day
    """
    day_start = datetime(day.year, day.month, day.day, 0, 0, 0)
    day_end = datetime(day.year, day.month, day.day, 23, 59, 59)

    result = []
    for slack in all_slacks:
        if day_start <= slack.time <= day_end:
            if night:
                result.append(slack)
            elif sunrise and sunset:
                if sunrise <= slack.time <= sunset:
                    result.append(slack)
            else:
                # No sunrise/sunset provided, include all
                result.append(slack)

    return result


def build_pdf_url(station_code: str, year: int) -> str:
    """
    Build the CHS PDF URL for a given station code and year.

    Args:
        station_code: The CHS station code (e.g., "08108" for Seymour Narrows)
        year: The year for predictions

    Returns:
        The URL to the PDF file
    """
    # The URL pattern is: https://tides.gc.ca/sites/tides/files/{year-1}-11/{station_code}_{year}.pdf
    # The files are typically uploaded in November of the previous year
    prev_year = year - 1
    return f"https://tides.gc.ca/sites/tides/files/{prev_year}-11/{station_code}_{year}.pdf"
