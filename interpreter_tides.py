"""
Tide prediction interpreter classes for abstracting tide data sources.

This module provides a clean abstraction for fetching tide (high/low water) predictions
from various data sources.

Supported data sources:
- NOAA API (NoaaTideInterpreter) - US tide stations
- Canadian API (CanadaTideInterpreter) - Placeholder for future BC tide stations

Usage:
    interpreter = get_tide_interpreter(station_config)
    tides = interpreter.getTides(start_day, days_in_future=7, time_filter=TIME_FILTER_DAY)
"""

from __future__ import annotations

import datetime
from datetime import datetime as dt, date
from typing import Optional, Any
import requests
from astral.sun import sun
from astral import LocationInfo
from astral import moon
from pytz import timezone

from interpreter_common import (
    TIMEPARSEFMT_TBONE,
    DATEFMT,
    TIME_FILTER_ALL,
    passes_time_filter,
    date_str,
    time_str,
)

# Re-export time filter constants for consumers of this module
from interpreter_common import TIME_FILTER_DAY, TIME_FILTER_NIGHT, TIME_FILTER_EARLY_NIGHT  # noqa: F401

# Type alias for station config dict
StationConfig = dict[str, Any]


def print_tides_dive_fmt(tides: list['Tide']) -> None:
    """
    Print tides of each day in the format "time (height) > time (height)".
    Groups tides by day for compact display.

    Args:
        tides: List of Tide objects to print
    """
    prev_tide: Optional['Tide'] = None
    for tide in tides:
        if prev_tide and dt.strftime(prev_tide.time, DATEFMT) == dt.strftime(tide.time, DATEFMT):
            # Same day - continue on same line
            print(' > {}'.format(tide.shortString()), end='')
        else:
            if prev_tide:
                print()  # End previous day
            # Start new day
            print('\t{}: '.format(dt.strftime(tide.time, DATEFMT)), end='')
            print('{}'.format(tide.shortString()), end='')
        prev_tide = tide
    if prev_tide:
        print()  # End final day


class Tide:
    """
    Represents a single tide event (high or low tide).

    Heights are stored in feet.
    """

    def __init__(self) -> None:
        self.time: Optional[dt] = None           # datetime of the tide event
        self.height: float = 0.0                 # tide height in feet
        self.isHighTide: bool = False            # True for high tide, False for low tide
        self.sunriseTime: Optional[dt] = None    # datetime of sunrise on this day
        self.sunsetTime: Optional[dt] = None     # datetime of sunset on this day
        self.moonPhase: float = -1               # moon phase 0-27, -1 if not set

    def __str__(self) -> str:
        tide_type = 'High' if self.isHighTide else 'Low'
        return '{}: {} tide {:.1f} ft'.format(date_str(self.time), tide_type, self.height)

    def logString(self) -> str:
        """String without date info (only time) for compact display."""
        tide_type = 'High' if self.isHighTide else 'Low'
        return '{} {} ({:.1f} ft)'.format(tide_type, time_str(self.time), self.height)

    def shortString(self) -> str:
        """Very compact format: time and height only."""
        return '{} ({:.1f} ft)'.format(time_str(self.time), self.height)

    def __repr__(self) -> str:
        return self.__str__()


class TideInterpreter:
    """
    Base class for tide data interpreters.

    Child classes must implement _fetchTides() to handle their specific data source.
    """

    def __init__(self, base_url: str, station: StationConfig) -> None:
        """
        Initialize the interpreter.

        Args:
            base_url: Base URL for the tide data source
            station: Station config dict from dive_sites.json (tide_stations array)
        """
        self.base_url: str = base_url
        self.station: StationConfig = station
        self._cached_tides: list[Tide] = []
        self._cache_start: Optional[date] = None
        self._cache_end: Optional[date] = None
        # For sunrise/sunset calculations
        self._astral_city: LocationInfo = LocationInfo("Seattle", "Washington", "America/Los_Angeles", 47.6, -122.3)

    def _add_sun_moon_data(self, tide: Tide) -> None:
        """Add sunrise, sunset, and moon phase data to a Tide object."""
        sun_data = sun(self._astral_city.observer, date=tide.time, tzinfo=timezone('US/Pacific'))
        tide.sunriseTime = sun_data['sunrise'].replace(tzinfo=None)
        tide.sunsetTime = sun_data['sunset'].replace(tzinfo=None)
        tide.moonPhase = moon.phase(tide.time)

    def _fetchTides(self, start_day: dt, days_in_future: int) -> list[Tide]:
        """
        Fetch tide predictions from the data source.

        Child classes must implement this method.

        Args:
            start_day: datetime for the start of the range
            days_in_future: Number of days to fetch

        Returns:
            List of Tide objects (without sun/moon data - that's added by the base class)
        """
        raise NotImplementedError("Child classes must implement _fetchTides()")

    def _cache_covers_range(self, start_day: dt, end_day: dt) -> bool:
        """Check if the cache covers the requested date range."""
        if not self._cached_tides or not self._cache_start or not self._cache_end:
            return False
        start_date = start_day.date() if hasattr(start_day, 'date') else start_day
        end_date = end_day.date() if hasattr(end_day, 'date') else end_day
        return self._cache_start <= start_date and end_date <= self._cache_end

    def getTides(self, start_day: dt, days_in_future: int = 7, time_filter: str = TIME_FILTER_ALL) -> list[Tide]:
        """
        Get tide predictions for the specified date range.

        This is the single public method for fetching tides.

        Args:
            start_day: datetime for the start of the range
            days_in_future: Number of days to fetch (default 7)
            time_filter: One of TIME_FILTER_DAY, TIME_FILTER_NIGHT, TIME_FILTER_ALL (default ALL)

        Returns:
            List of Tide objects matching the criteria
        """
        if not self.base_url:
            return []

        end_day = start_day + datetime.timedelta(days=days_in_future)

        # Fetch new data if cache doesn't cover the range
        if not self._cache_covers_range(start_day, end_day):
            raw_tides = self._fetchTides(start_day, days_in_future)

            # Add sun/moon data to each tide
            for tide in raw_tides:
                self._add_sun_moon_data(tide)

            self._cached_tides = raw_tides
            if raw_tides:
                self._cache_start = raw_tides[0].time.date()
                self._cache_end = raw_tides[-1].time.date()

        # Filter cached tides by date range and time filter
        start_str = dt.strftime(start_day, DATEFMT)
        end_str = dt.strftime(end_day, DATEFMT)

        result: list[Tide] = []
        for tide in self._cached_tides:
            tide_date_str = dt.strftime(tide.time, DATEFMT)

            # Check date range
            if tide_date_str < start_str or tide_date_str > end_str:
                continue

            # Check time filter
            if not passes_time_filter(tide.time, tide.sunriseTime, tide.sunsetTime, time_filter):
                continue

            result.append(tide)

        return result


class NoaaTideInterpreter(TideInterpreter):
    """
    Interpreter for NOAA tide prediction API.

    Uses the NOAA CO-OPS API to fetch tide predictions.
    API documentation: https://api.tidesandcurrents.noaa.gov/api/prod/
    """

    def _fetchTides(self, start_day: dt, days_in_future: int) -> list[Tide]:
        """
        Fetch tides from NOAA API and return list of Tide objects.
        """
        # Build URL with date range
        start_str = start_day.strftime(DATEFMT).replace("-", "")
        end_day = start_day + datetime.timedelta(days=days_in_future)
        end_str = end_day.strftime(DATEFMT).replace("-", "")
        url = f"{self.base_url}&begin_date={start_str}&end_date={end_str}"

        # Fetch from API
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(f'NOAA Tide API request failed: {response.status_code}')

        json_data = response.json()
        if 'predictions' not in json_data:
            raise Exception(f'NOAA Tide API unexpected response: {json_data}')

        # Parse predictions into Tide objects
        tides: list[Tide] = []
        for pred in json_data['predictions']:
            tide = Tide()
            tide.time = dt.strptime(pred['t'], TIMEPARSEFMT_TBONE)
            tide.height = float(pred['v'])
            tide.isHighTide = pred['type'] == 'H'
            tides.append(tide)

        return tides


class CanadaTideInterpreter(TideInterpreter):
    """
    Placeholder interpreter for Canadian tide predictions from tides.gc.ca.

    This class is a placeholder for future implementation of Canadian tide data.
    Potential data sources:
    - Canadian Hydrographic Service REST API
    - PDF predictions from tides.gc.ca
    """

    def _fetchTides(self, start_day: dt, days_in_future: int) -> list[Tide]:
        """Placeholder - not yet implemented."""
        station_name = self.station.get('name', 'unknown')
        print(f"Warning: Canadian tide data not yet implemented for station '{station_name}'")
        return []


def get_tide_interpreter(station_config: StationConfig) -> TideInterpreter:
    """
    Factory function to create the appropriate TideInterpreter for a station.

    Args:
        station_config: Station configuration dict from dive_sites.json (tide_stations array)

    Returns:
        TideInterpreter subclass instance appropriate for the station's data source
    """
    source_type = station_config.get('source_type', 'noaa')

    if source_type == 'canada_api' or 'ca_tide_id' in station_config:
        return CanadaTideInterpreter(station_config.get('url_canada_tide', ''), station_config)
    else:
        # Default to NOAA
        return NoaaTideInterpreter(station_config.get('url_noaa', ''), station_config)
