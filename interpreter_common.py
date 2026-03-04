"""
Common constants and utilities shared between interpreter.py and interpreter_tides.py.
"""

from datetime import datetime as dt
from datetime import timedelta as td

# https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior
TIMEPARSEFMT = '%Y-%m-%d %I:%M%p'  # example: 2019-01-18 09:36AM
TIMEPARSEFMT_TBONE = '%Y-%m-%d %H:%M'  # example: 2019-01-18 22:36
TIMEPARSEFMT_CA = '%Y-%m-%dT%H:%M:%SZ'  # example: 2024-03-13T23:29:00Z
TIMEPRINTFMT = '%a %Y-%m-%d %I:%M%p'  # example: Fri 2019-01-18 09:36AM
DATEFMT = '%Y-%m-%d'  # example 2019-01-18
TIMEFMT = '%I:%M%p'  # example 09:36AM

# Time filter constants for getSlacks/getTides
TIME_FILTER_DAY = 'day'              # Only daytime (between sunrise and sunset)
TIME_FILTER_NIGHT = 'night'          # Only nighttime (between sunset and sunrise)
TIME_FILTER_EARLY_NIGHT = 'early_night'  # Only early night (45min after sunset to 11pm)
TIME_FILTER_ALL = 'all'              # All times


def passes_time_filter(event_time, sunrise_time, sunset_time, time_filter):
    """
    Returns True if the event passes the given time filter.

    Args:
        event_time: datetime of the event
        sunrise_time: datetime of sunrise on this day
        sunset_time: datetime of sunset on this day
        time_filter: One of TIME_FILTER_DAY, TIME_FILTER_NIGHT, TIME_FILTER_EARLY_NIGHT, or TIME_FILTER_ALL

    Returns:
        True if the event should be included based on the time filter
    """
    if time_filter == TIME_FILTER_ALL:
        return True
    # If we don't have sunrise/sunset times, we can't filter properly
    if not sunrise_time or not sunset_time:
        return True

    is_daytime = sunrise_time <= event_time <= sunset_time

    if time_filter == TIME_FILTER_DAY:
        return is_daytime
    elif time_filter == TIME_FILTER_NIGHT:
        return not is_daytime
    elif time_filter == TIME_FILTER_EARLY_NIGHT:
        # Between 45 minutes after sunset and 11pm on the same day
        early_night_start = sunset_time + td(minutes=45)
        eleven_pm = event_time.replace(hour=23, minute=0, second=0, microsecond=0)
        return event_time >= early_night_start and event_time <= eleven_pm
    return True


def date_str(date):
    """Format datetime as full date/time string."""
    return dt.strftime(date, TIMEPRINTFMT)


def time_str(date):
    """Format datetime as time-only string, without leading zero."""
    result = dt.strftime(date, TIMEFMT)
    if result.startswith('0'):
        return result[1:]  # remove leading 0 (i.e. 9:02AM instead of 09:02AM)
    return result

