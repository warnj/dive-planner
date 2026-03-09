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
    TIMEFMT,
    TIME_FILTER_ALL,
    CANADA_API_BASE_URL,
    passes_time_filter,
    date_str,
    time_str,
    get_canada_station_id_local,
    DiveWindow,
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


class TideDiveWindow(DiveWindow):
    """
    A dive window derived from tide height predictions.

    Maps tide concepts onto the DiveWindow interface:
    - slackBeforeEbb = isHighTide (high tide → water ebbs/drops next)
    - magnitude = height change between this tide and its neighbors
    - max_flood/max_ebb in site config = max allowed height change (feet)
    - max_total_height in site config = max allowed sum of rise + fall height change
    """

    def __init__(self, tide: 'Tide', prev_tide: Optional['Tide'] = None,
                 next_tide: Optional['Tide'] = None) -> None:
        super().__init__()
        self.tide = tide
        self.time = tide.time
        self.sunriseTime = tide.sunriseTime
        self.sunsetTime = tide.sunsetTime
        self.moonPhase = tide.moonPhase
        # High tide = slack before ebb (water will drop); Low tide = slack before flood (water will rise)
        self.slackBeforeEbb = tide.isHighTide

        # Height changes to neighboring tides
        self.prevTide: Optional['Tide'] = prev_tide
        self.nextTide: Optional['Tide'] = next_tide

        # Compute height changes
        # "rise" = height change on the flood (rising) side
        # "fall" = height change on the ebb (falling) side
        if tide.isHighTide:
            # High tide: prior was rising (flood side), next is falling (ebb side)
            self.riseHeight: float = abs(tide.height - prev_tide.height) if prev_tide else 0.0
            self.fallHeight: float = abs(tide.height - next_tide.height) if next_tide else 0.0
        else:
            # Low tide: prior was falling (ebb side), next is rising (flood side)
            self.fallHeight = abs(prev_tide.height - tide.height) if prev_tide else 0.0
            self.riseHeight = abs(next_tide.height - tide.height) if next_tide else 0.0

    def __str__(self) -> str:
        if self.slackBeforeEbb:
            # High tide: show rise → HIGH → fall
            return '{:.1f}ft rise -> {} -> {:.1f}ft fall'.format(
                self.riseHeight, date_str(self.time), self.fallHeight)
        else:
            # Low tide: show fall → LOW → rise
            return '{:.1f}ft fall -> {} -> {:.1f}ft rise'.format(
                self.fallHeight, date_str(self.time), self.riseHeight)

    def logString(self) -> str:
        """Compact string with tide type and height."""
        tide_type = 'High' if self.slackBeforeEbb else 'Low'
        return '{} {} ({:.1f} ft)'.format(tide_type, time_str(self.time), self.tide.height)

    def logStringWithSpeed(self) -> str:
        """Show height changes with neighboring tide times."""
        parts = []
        if self.prevTide:
            prev_type = 'H' if self.prevTide.isHighTide else 'L'
            parts.append('{}{:.1f}ft({})'.format(prev_type, self.prevTide.height, time_str(self.prevTide.time)))
        parts.append('{:.1f}ft({})'.format(self.tide.height, time_str(self.time)))
        if self.nextTide:
            next_type = 'H' if self.nextTide.isHighTide else 'L'
            parts.append('{}{:.1f}ft({})'.format(next_type, self.nextTide.height, time_str(self.nextTide.time)))
        return ' > '.join(parts)

    def magnitude(self) -> float:
        """Total height change (rise + fall) around this tide event."""
        return self.riseHeight + self.fallHeight

    def isDiveable(self, site: dict, ignoreMaxMagnitude: bool) -> tuple[bool, str]:
        """
        Check if this tide window is diveable at the given tide-based site.

        For tide sites:
        - slackBeforeEbb (high tide): diveable_before_ebb check
        - not slackBeforeEbb (low tide): diveable_before_flood check
        - max_flood = max allowed rise height (low→high change in feet)
        - max_ebb = max allowed fall height (high→low change in feet)
        - max_total_height = max allowed total height change
        """
        if self.slackBeforeEbb and not site['diveable_before_ebb']:
            return False, 'Not diveable at high tide'
        elif not self.slackBeforeEbb and not site['diveable_before_flood']:
            return False, 'Not diveable at low tide'
        elif not ignoreMaxMagnitude:
            if self.riseHeight > site['max_flood']:
                return False, 'Rise too large ({:.1f}ft > {:.1f}ft max)'.format(
                    self.riseHeight, site['max_flood'])
            if self.fallHeight > site['max_ebb']:
                return False, 'Fall too large ({:.1f}ft > {:.1f}ft max)'.format(
                    self.fallHeight, site['max_ebb'])
            max_total = site.get('max_total_height', site.get('max_total_speed', float('inf')))
            if self.riseHeight + self.fallHeight > max_total:
                return False, 'Total height change too large ({:.1f}ft > {:.1f}ft max)'.format(
                    self.riseHeight + self.fallHeight, max_total)
        return True, 'Diveable'

    def printDive(self, site: dict, titleMessage: str, Color) -> None:
        """Print detailed dive plan for this tide window."""
        from interpreter import _getEntryTimes
        times = _getEntryTimes(self, site)
        if not times:
            print('ERROR: a json key was expected that was not found')
        else:
            minCurrentTime, clubEntryTime, entryTime, exitTime = times
            if self.sunriseTime:
                warning = ''
                if entryTime < self.sunriseTime:
                    warning = 'BEFORE'
                elif entryTime - datetime.timedelta(minutes=30) < self.sunriseTime:
                    warning = 'near'
                if warning:
                    print('\t\tWARNING: entry time of {} is {} sunrise at {}'.format(date_str(entryTime),
                        warning, date_str(self.sunriseTime)))

            tide_label = 'High Tide' if self.slackBeforeEbb else 'Low Tide'
            print('\t\t{}: {}'.format(titleMessage, self))
            print('\t\t\t{} at {}, Height = {:.1f} ft, Duration = {}, SurfaceSwim = {}'
                  .format(tide_label, date_str(minCurrentTime), self.tide.height,
                          site['dive_duration'], site['surface_swim_time']))
            print('\t\t\t{}Entry Time: {}{}\t(Exit time: {})'
                  .format(Color.UNDERLINE, date_str(entryTime), Color.END, dt.strftime(exitTime, TIMEFMT)))
            print('\t\t\t{}'.format(self.logString()))
            print('\t\t\t{}'.format(self.logStringWithSpeed()))
            print('\t\t\tHeight change = {:.1f} ft (rise={:.1f}, fall={:.1f})'.format(
                self.magnitude(), self.riseHeight, self.fallHeight))


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

    def getSlacks(self, day: dt, time_filter: str = TIME_FILTER_ALL) -> list[TideDiveWindow]:
        """
        Get dive windows for a single day, matching the Interpreter.getSlacks() signature.

        Fetches tides for the day (plus neighbors for height-change calculation),
        then wraps each tide into a TideDiveWindow.

        Args:
            day: datetime for the day to get dive windows for
            time_filter: One of TIME_FILTER_DAY, TIME_FILTER_NIGHT, TIME_FILTER_ALL

        Returns:
            List of TideDiveWindow objects for the given day
        """
        # Fetch a wider range so we have neighboring tides for height change calculation
        # We need at least the day before and after for accurate prev/next tide references
        all_tides = self.getTides(day - datetime.timedelta(days=1), days_in_future=3, time_filter=TIME_FILTER_ALL)
        if not all_tides:
            return []

        day_str = dt.strftime(day, DATEFMT)

        # Build TideDiveWindows for tides on the requested day
        windows: list[TideDiveWindow] = []
        for i, tide in enumerate(all_tides):
            tide_date_str = dt.strftime(tide.time, DATEFMT)
            if tide_date_str != day_str:
                continue

            # Apply time filter
            if not passes_time_filter(tide.time, tide.sunriseTime, tide.sunsetTime, time_filter):
                continue

            prev_tide = all_tides[i - 1] if i > 0 else None
            next_tide = all_tides[i + 1] if i < len(all_tides) - 1 else None
            windows.append(TideDiveWindow(tide, prev_tide, next_tide))

        return windows

    @staticmethod
    def getDayUrl(baseUrl, day) -> Optional[str]:
        """TideInterpreters don't have per-day URLs; return None."""
        return None


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
    Interpreter for Canadian tide predictions from Canadian Hydrographic Service (CHS) IWLS API.

    Uses the official Canadian tide prediction API at api-sine.dfo-mpo.gc.ca.
    API documentation: https://api-sine.dfo-mpo.gc.ca/swagger-ui/index.html

    Station codes can be found at https://tides.gc.ca/en/stations
    """

    METERS_TO_FEET = 3.28084

    def __init__(self, base_url: str, station: StationConfig) -> None:
        """
        Initialize the Canadian tide interpreter.

        Args:
            base_url: Not used for Canada API (we use the standard base URL)
            station: Station config dict from dive_sites.json (tide_stations array)
                     Must contain 'ca_code' with the station code (e.g., "08426")
        """
        # Pass the Canada API base URL to parent so base class getTides check passes
        super().__init__(CANADA_API_BASE_URL, station)
        self.station_code = station.get('ca_code', '')
        self._internal_station_id: Optional[str] = None
        self._astral_city = LocationInfo("Vancouver", "BC", "America/Vancouver", 49.28, -123.12)

    def _get_station_id(self) -> Optional[str]:
        """Look up the internal station ID from the station code."""
        if not self._internal_station_id:
            result = get_canada_station_id_local(self.station)
            self._internal_station_id = result
        return self._internal_station_id


    def _fetchTides(self, start_day: dt, days_in_future: int) -> list[Tide]:
        """
        Fetch tides from Canadian Hydrographic Service API.

        Uses the wlp-hilo time series code to get high/low tide predictions.

        Args:
            start_day: datetime for the start of the range
            days_in_future: Number of days to fetch

        Returns:
            List of Tide objects
        """
        if not self.station_code:
            station_name = self.station.get('name', 'unknown')
            print(f"Warning: No ca_code configured for Canadian station '{station_name}'")
            return []

        # Get the internal station ID
        internal_id = self._get_station_id()
        if not internal_id:
            return []

        # Build the API URL for tide predictions
        # Format dates as ISO 8601 for the API
        start_str = start_day.strftime("%Y-%m-%dT00:00:00Z")
        end_day = start_day + datetime.timedelta(days=days_in_future+1)
        end_str = end_day.strftime("%Y-%m-%dT23:59:59Z")

        url = (
            f"{CANADA_API_BASE_URL}/stations/{internal_id}/data"
            f"?time-series-code=wlp-hilo"
            f"&from={start_str}"
            f"&to={end_str}"
        )

        try:
            response = requests.get(url)
            if response.status_code != 200:
                raise Exception(f'Canada Tide API request failed: {response.status_code} - {response.text}')

            json_data = response.json()

            # Parse the response into Tide objects
            tides: list[Tide] = []
            for entry in json_data:
                tide = Tide()
                # Parse the timestamp - API returns ISO 8601 format
                # Example: "2026-03-04T05:30:00Z"
                time_str_raw = entry.get('eventDate', '')
                if not time_str_raw:
                    continue

                # Parse as UTC then convert to Pacific time
                utc_time = dt.strptime(time_str_raw, "%Y-%m-%dT%H:%M:%SZ")
                utc_tz = timezone('UTC')
                pacific_tz = timezone('US/Pacific')
                utc_time = utc_tz.localize(utc_time)
                local_time = utc_time.astimezone(pacific_tz)
                tide.time = local_time.replace(tzinfo=None)

                # Height is in meters, convert to feet
                height_meters = float(entry.get('value', 0))
                tide.height = height_meters * self.METERS_TO_FEET

                # The wlp-hilo API doesn't provide explicit H/L markers,
                # so we'll determine high/low from heights after collecting all tides
                tide.isHighTide = False  # Will be set by _infer_high_low_tides
                tides.append(tide)

            # If we couldn't determine high/low from qcFlagCode, infer from heights
            self._infer_high_low_tides(tides)
            return tides

        except requests.RequestException as e:
            station_name = self.station.get('name', 'unknown')
            print(f"Error fetching Canadian tide data for '{station_name}': {e}")
            return []
        except Exception as e:
            station_name = self.station.get('name', 'unknown')
            print(f"Error parsing Canadian tide data for '{station_name}': {e}")
            return []

    def _infer_high_low_tides(self, tides: list[Tide]) -> None:
        """
        Infer high/low tide status from height values if not provided by API.

        For a series of tide events, alternating high/low, we compare each
        tide to its neighbors to determine if it's a local max or min.
        """
        if len(tides) < 2:
            return

        for i, tide in enumerate(tides):
            if i == 0:
                tide.isHighTide = tide.height > tides[i + 1].height
            elif i == len(tides) - 1:
                tide.isHighTide = tide.height > tides[i - 1].height
            else:
                # Compare to both neighbors
                tide.isHighTide = tide.height > tides[i - 1].height and tide.height > tides[i + 1].height


def get_tide_interpreter(station_config: StationConfig) -> TideInterpreter:
    """
    Factory function to create the appropriate TideInterpreter for a station.

    Args:
        station_config: Station configuration dict from dive_sites.json (tide_stations array)

    Returns:
        TideInterpreter subclass instance appropriate for the station's data source
    """

    if 'ca_code' in station_config:
        return CanadaTideInterpreter(station_config.get('url_canada_tide', ''), station_config)
    else:
        return NoaaTideInterpreter(station_config.get('url_noaa', ''), station_config)
