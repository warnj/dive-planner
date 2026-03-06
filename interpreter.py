import json
import urllib.request
from astral.sun import sun
from astral import LocationInfo
from astral import moon
from bs4 import BeautifulSoup
import datetime
from datetime import datetime as dt
from datetime import timedelta as td
from pytz import timezone
import requests
import re
from dateutil import parser
import pytz
import subprocess
import canada_pdf_lib
from interpreter_common import (
    TIMEPARSEFMT,
    TIMEPARSEFMT_TBONE,
    TIMEPARSEFMT_CA,
    TIMEPRINTFMT,
    DATEFMT,
    TIMEFMT,
    TIME_FILTER_DAY,
    TIME_FILTER_NIGHT,
    TIME_FILTER_EARLY_NIGHT,
    TIME_FILTER_ALL,
    CANADA_API_BASE_URL,
    passes_time_filter,
    date_str,
    time_str,
    get_canada_station_id_local,
)


def _passesTimeFilter(slack, time_filter):
    """
    Returns True if the slack passes the given time filter.

    Wrapper around passes_time_filter that extracts fields from Slack object.
    """
    return passes_time_filter(slack.time, slack.sunriseTime, slack.sunsetTime, time_filter)


# Legacy function names for backward compatibility
def dateStr(date):
    return date_str(date)

def timeStr(date):
    return time_str(date)

class Slack:
    time = None
    sunriseTime = None
    sunsetTime = None  # this is never used, but might be interesting to print it sometimes
    moonPhase = -1
    slackBeforeEbb = False
    ebbSpeed = 0.0  # negative number
    floodSpeed = 0.0  # positive number
    maxEbbTime = None
    maxFloodTime = None

    def __str__(self):
        if self.slackBeforeEbb:
            return '{} -> {} -> {}'.format(self.floodSpeed, dateStr(self.time), self.ebbSpeed)
        else:
            return '{} -> {} -> {}'.format(self.ebbSpeed, dateStr(self.time), self.floodSpeed)

    # string without date info (only time) for logbook entry
    def logString(self):
        if self.slackBeforeEbb:
            return '{} > {} > {}'.format(self.floodSpeed, timeStr(self.time), self.ebbSpeed)
        else:
            return '{} > {} > {}'.format(self.ebbSpeed, timeStr(self.time), self.floodSpeed)

    def logStringWithSpeed(self):
        if not self.maxEbbTime or not self.maxFloodTime:
            return self.logString()
        elif self.slackBeforeEbb:
            return '{}({}) > {} > {}({})'.format(self.floodSpeed, timeStr(self.maxFloodTime), timeStr(self.time), self.ebbSpeed, timeStr(self.maxEbbTime))
        else:
            return '{}({}) > {} > {}({})'.format(self.ebbSpeed, timeStr(self.maxEbbTime), timeStr(self.time), self.floodSpeed, timeStr(self.maxFloodTime))

    def speedSum(self):
        return abs(self.floodSpeed) + abs(self.ebbSpeed)

    def __repr__(self):
        return self.__str__()

# Base class to download and parse current data from various websites
class Interpreter:

    def __init__(self, baseUrl, station):
        self.baseUrl = baseUrl
        self.station = station
        self._webLines = None
        # https://astral.readthedocs.io/en/latest
        self._astralCity = LocationInfo("Seattle", "Washington", "America/Los_Angeles", 47.6, -122.3)

    # ----------------------- Stub functions child classes must implement ----------------------------------------------
    # Returns the datetime object parsed from the given data line
    def _parseTime(self, tokens):
        raise NotImplementedError

    # Returns the day-specific URL for the base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        raise NotImplementedError

    # Returns the current data from the given url
    def _getWebLines(self, url, day):
        raise NotImplementedError

    # Returns a list of Slack objects corresponding to the slack indexes within the list of data lines
    def _getSlackData(self, lines, indexes, sunrise, sunset, moonPhase):
        raise NotImplementedError
    # ----------------------- end stub functions -----------------------------------------------------------------------

    # Returns the line before index i in lines that contains an ebb or flood current speed prediction. Returns None if
    # no such prediction exists before index i.
    def _getCurrentBefore(self, i, lines):
        pre = i - 1
        if pre < 0:
            return None
        while 'ebb' not in lines[pre] and 'flood' not in lines[pre]:
            pre -= 1
            if pre < 0:
                return None
        return lines[pre]

    # Returns the line after index i in lines that contains an ebb or flood current speed prediction. Returns None if
    # no such prediction exists after index i.
    def _getCurrentAfter(self, i, lines):
        post = i + 1
        if post >= len(lines):
            return None
        while 'ebb' not in lines[post] and 'flood' not in lines[post]:
            post += 1
            if post >= len(lines):
                return None
        return lines[post]

    # Returns list with indexes of the slack currents in the given list of data lines.
    def _getAllSlacks(self, webLines):
        slacks = []
        for i, line in enumerate(webLines):
            if 'slack' in line or 'min ebb' in line or 'min flood' in line:
                slacks.append(i)
        return slacks

    # Returns list with indexes of the slack currents in the first 24hrs of the given list of data lines.
    def _getAllDaySlacks(self, webLines):
        day = webLines[0].split()[0]
        slacksIndexes = []
        leng = len(webLines)
        for i, line in enumerate(webLines):
            if line.split()[0] != day:
                return slacksIndexes
            # noaa doesn't have 'min ebb', only 3 ebbs in a row
            elif 'slack' in line or 'min ebb' in line or 'min flood' in line \
                    or ('ebb' in line and i>0 and 'ebb' in webLines[i-1] and i<(leng-1) and 'ebb' in webLines[i+1]) \
                    or ('flood' in line and i>0 and 'flood' in webLines[i-1] and i<(leng-1) and 'flood' in webLines[i+1]):
                slacksIndexes.append(i)
        return slacksIndexes

    # Returns list with indexes of the daytime (between given sunrise and sunset) slack currents in the given
    # list of data lines.
    def _getDaySlacks(self, webLines, sunrise, sunset):
        slacksIndexes = []
        leng = len(webLines)
        for i, line in enumerate(webLines):
            # noaa doesn't have 'min ebb', only 3 ebbs in a row
            if 'slack' in line or 'min ebb' in line or 'min flood' in line \
                    or ('ebb' in line and i>0 and 'ebb' in webLines[i-1] and i<(leng-1) and 'ebb' in webLines[i+1]) \
                    or ('flood' in line and i>0 and 'flood' in webLines[i-1] and i<(leng-1) and 'flood' in webLines[i+1]):
                time = self._parseTime(line.split())
                timeDate = dt.strftime(time, DATEFMT)  # sanity checks to surface errors with mismatched web dates early
                sunriseDate, sunsetDate = dt.strftime(sunrise, DATEFMT), dt.strftime(sunset, DATEFMT)
                if time > sunset:
                    return slacksIndexes
                elif time > sunrise:
                    slacksIndexes.append(i)
                elif sunriseDate != timeDate or sunriseDate != sunsetDate:
                    # note: mismatched dates may not be caught with this line, can hit (time > sunset) and trigger empty
                    print('ERROR: website date {} does not match requested date {}'.format(timeDate, sunriseDate))
                    return []
        return slacksIndexes

    # Returns true if self._webData contains the data for the given day, false otherwise
    def _canReuseWebData(self, day):
        if not self._webLines:
            return False
        dayStr = dt.strftime(day, DATEFMT)
        for i, line in enumerate(self._webLines):
            if dayStr in line:
                self._webLines = self._webLines[i:]
                return True
        return False

    # Returns all slacks retrieved from the web beginning with the startDay (7 days for NOAA and 4 days for MobileGeo)
    def allSlacks(self, startDay):
        url = self.getDayUrl(self.baseUrl, startDay)
        lines = self._getWebLines(url, startDay)
        slackIndexes = self._getAllSlacks(lines)
        return self._getSlackData(lines, slackIndexes, None, None, -1)

    # Returns a list of slacks for the given day, retrieves new web data if the current data doesn't have info for day.
    # time_filter: 'day' for daytime only, 'night' for nighttime only, 'all' for all times
    def getSlacks(self, day, time_filter):
        if not self._canReuseWebData(day):
            if not self.baseUrl:
                print('Base url empty')  # comment this out if it's annoying
                return []
            # print('making another API call')
            url = self.getDayUrl(self.baseUrl, day)
            self._webLines = self._getWebLines(url, day)
        if not self._webLines:
            print('Error getting web data')
            return []
        # Note: astral sunrise and sunset times do account for daylight savings
        sunData = sun(self._astralCity.observer, date=day, tzinfo=timezone('US/Pacific'))
        # remove time zone info to compare with other local times
        sunrise = sunData['sunrise'].replace(tzinfo=None)
        sunset = sunData['sunset'].replace(tzinfo=None)
        if time_filter == TIME_FILTER_ALL:
            slackIndexes = self._getAllDaySlacks(self._webLines)
        else:
            # For both DAY and NIGHT, we get day slacks first, then filter
            # For DAY_ONLY, we use the existing _getDaySlacks which filters to sunrise-sunset
            # For NIGHT_ONLY, we get all slacks and filter in _getSlackData
            slackIndexes = self._getDaySlacks(self._webLines, sunrise, sunset) if time_filter == TIME_FILTER_DAY else self._getAllDaySlacks(self._webLines)
        if not slackIndexes:
            print('ERROR: no slacks for {} found in webLines: {}'.format(day, self._webLines))
            return []
        slacks = self._getSlackData(self._webLines, slackIndexes, sunrise, sunset, moon.phase(day))
        # Apply time filter
        return [s for s in slacks if _passesTimeFilter(s, time_filter)]


# Class to retrieve and parse current data from mobilegeographics website
# NOTE: As of 11/2020, website down for weeks, deprecated and replaced by TBoneSCInterpreter
class MobilegeographicsInterpreter(Interpreter):

    # Returns the datetime object parsed from the given data line from MobileGeographics website
    def _parseTime(self, tokens):
        dayTimeStr = tokens[0] + ' ' + tokens[2] + tokens[3]  # ex: 2018-11-17 1:15PM
        return dt.strptime(dayTimeStr, TIMEPARSEFMT)

    # Returns the day-specific URL for the base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        return baseUrl + '?y={}&m={}&d={}'.format(day.year, day.month, day.day)

    # Returns the mobilegeographics current data from the given url
    def _getWebLines(self, url, day):
        with urllib.request.urlopen(url) as response:
            html = response.read()
            soup = BeautifulSoup(html, 'html.parser')
            predictions = soup.find('pre', {'class': 'predictions-table'})
            lines = predictions.text.lower().splitlines()
            # ignore the non-current speed data at the top, like current direction and gps coords
            start = 0
            for line in lines:
                if "knots" not in line:
                    start += 1
                else:
                    break
            return lines[start:]

    # Returns a list of Slack objects corresponding to the slack indexes within the list of data lines
    def _getSlackData(self, lines, indexes, sunrise, sunset, moonPhase):
        slacks = []
        for i in indexes:
            s = Slack()
            s.sunriseTime = sunrise
            s.sunsetTime = sunset
            s.moonPhase = moonPhase

            preMax = self._getCurrentBefore(i, lines)
            if not preMax:
                continue
            tokens1 = preMax.split()

            postMax = self._getCurrentAfter(i, lines)
            if not postMax:
                continue
            tokens2 = postMax.split()

            s.slackBeforeEbb = 'ebb' in postMax

            if s.slackBeforeEbb:
                s.floodSpeed = float(tokens1[5])
                s.maxFloodTime = self._parseTime(tokens1)
                s.ebbSpeed = float(tokens2[5])
                s.maxEbbTime = self._parseTime(tokens2)
            else:
                s.ebbSpeed = float(tokens1[5])
                s.maxEbbTime = self._parseTime(tokens1)
                s.floodSpeed = float(tokens2[5])
                s.maxFloodTime = self._parseTime(tokens2)

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks


# Class to retrieve and parse current data from tbone.biol.sc.edu website
# as of 12-9-2023 this class also works for tide.arthroinfo.org
class TBoneSCInterpreter(Interpreter):

    # Returns the datetime object parsed from the given data line from tbone.biol.sc.edu website
    def _parseTime(self, tokens):
        dayTimeStr = tokens[0] + ' ' + tokens[1]  # ex: 2018-11-17 22:41
        return dt.strptime(dayTimeStr, TIMEPARSEFMT_TBONE)

    # Returns the day-specific URL for the base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        monthStr = str(day.month)
        if day.month < 10: monthStr = '0'+monthStr
        dayStr = str(day.day)
        if day.day < 10: dayStr = '0'+dayStr
        return baseUrl + '&year={}&month={}&day={}'.format(day.year, monthStr, dayStr)

    # Returns the tbone.biol.sc.edu current data from the given url
    def _getWebLines(self, url, day):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read()
            soup = BeautifulSoup(html, 'html.parser')
            predictions = soup.find('pre')
            lines = predictions.text.lower().splitlines()
            # ignore the non-current speed data at the top, like current direction and gps coords
            start = 0
            for line in lines:
                if "knots" not in line:
                    start += 1
                else:
                    break
            return lines[start:]

    # Returns a list of Slack objects corresponding to the slack indexes within the list of data lines
    def _getSlackData(self, lines, indexes, sunrise, sunset, moonPhase):
        slacks = []
        for i in indexes:
            s = Slack()
            s.sunriseTime = sunrise
            s.sunsetTime = sunset
            s.moonPhase = moonPhase

            preMax = self._getCurrentBefore(i, lines)
            # todo: support a null value here to show middle of the night currents better
            if not preMax:
                continue
            tokens1 = preMax.split()

            postMax = self._getCurrentAfter(i, lines)
            if not postMax:
                continue
            tokens2 = postMax.split()

            s.slackBeforeEbb = 'ebb' in postMax

            if s.slackBeforeEbb:
                s.floodSpeed = float(tokens1[3])
                s.maxFloodTime = self._parseTime(tokens1)
                s.ebbSpeed = float(tokens2[3])
                s.maxEbbTime = self._parseTime(tokens2)
            else:
                s.ebbSpeed = float(tokens1[3])
                s.maxEbbTime = self._parseTime(tokens1)
                s.floodSpeed = float(tokens2[3])
                s.maxFloodTime = self._parseTime(tokens2)

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks


class TBoneSCOfflineInterpreter(TBoneSCInterpreter):
    # taken from xtide_saver.py
    def __getFileName(self, stationName):
        # remove chars before first comma
        match = re.match(r'^([^,]+)', stationName.lower())
        filename = match.group(1)
        # remove chars before first paren
        match = re.match(r'^([^(]+)', filename)
        filename = match.group(1)

        filename = filename.strip()
        filename = filename.replace('.', '')
        filename = filename.replace(' ', '-')
        return 'xtide-offline/' + filename + '.txt'

    def _getWebLines(self, url, day):
        xtideFile = self.__getFileName(self.station['name'])
        with open(xtideFile, 'r') as f:
            lines = f.read().splitlines()
        targetDayStr = dt.strftime(day, DATEFMT)
        for i, x in enumerate(lines):
            dayString = x.split()[0]
            if dayString == targetDayStr:
                return lines[i:i+400]
        raise Exception('did not find date {} in offline xtide data'.format(targetDayStr))


# Class to retrieve and parse current data from Noaa API
class NoaaAPIInterpreter(Interpreter):

    # Returns the datetime object parsed from the given data line from Noaa website
    def _parseTime(self, tokens):
        dayTimeStr = tokens[0] + ' ' + tokens[1]
        return dt.strptime(dayTimeStr, TIMEPARSEFMT_TBONE)

    # Returns the day-specific URL for the current base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        # yesterday = (day - datetime.timedelta(days=1)).strftime(DATEFMT).replace("-", "")
        today = day.strftime(DATEFMT).replace("-", "")
        # tomorrow = (day + datetime.timedelta(days=1)).strftime(DATEFMT).replace("-", "")
        twoWeeks = (day + datetime.timedelta(days=14)).strftime(DATEFMT).replace("-", "")
        return baseUrl + f'&begin_date={today}&end_date={twoWeeks}'

    # Returns the noaa current data from the given url
    def _getWebLines(self, url, day):
        urlFinal = self.getDayUrl(url, day)
        response = requests.get(urlFinal)
        if response.status_code != 200:
            raise Exception('NOAA API is down: ' + str(response))

        if 'current_predictions' not in response.json():
            raise Exception('NOAA API response unexpected format: ' + str(response) + "\n" + str(response.json()))
        jsonArray = response.json()['current_predictions']['cp']

        # convert json array to array of weblines - not ideal, fits into existing Interpreter functions better for now
        weblines = []
        for event in jsonArray:
            weblines.append("{} {} {:.2f}".format(event['Time'], event['Type'], event['Velocity_Major']))
        return weblines

    # Returns a list of Slack objects corresponding to the slack indexes within the list of data lines
    def _getSlackData(self, lines, indexes, sunrise, sunset, moonPhase):
        slacks = []
        for i in indexes:
            s = Slack()
            s.sunriseTime = sunrise
            s.sunsetTime = sunset
            s.moonPhase = moonPhase

            preMax = self._getCurrentBefore(i, lines)
            if not preMax:
                continue
            tokens1 = preMax.split()

            postMax = self._getCurrentAfter(i, lines)
            if not postMax:
                continue
            tokens2 = postMax.split()

            s.slackBeforeEbb = 'ebb' in postMax

            if s.slackBeforeEbb:
                s.floodSpeed = float(tokens1[3])
                s.maxFloodTime = self._parseTime(tokens1)
                s.ebbSpeed = float(tokens2[3])
                s.maxEbbTime = self._parseTime(tokens2)
            else:
                s.ebbSpeed = float(tokens1[3])
                s.maxEbbTime = self._parseTime(tokens1)
                s.floodSpeed = float(tokens2[3])
                s.maxFloodTime = self._parseTime(tokens2)

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks

# Class to retrieve and parse current data from Canada Currents REST API
# Uses the wcp1-events time series which provides SLACK, EXTREMA_FLOOD, and EXTREMA_EBB events
class CanadaAPIInterpreter(Interpreter):
    numAPICalls = 0

    def __init__(self, baseUrl, station):
        super().__init__(baseUrl, station)
        self._internal_station_id = None  # Cache for station ID lookup
        self._cached_slacks = []  # All slacks fetched from API
        self._cache_start = None  # Start date of cached range (datetime.date)
        self._cache_end = None    # End date of cached range (datetime.date)

    def _get_station_id(self):
        """Get the internal station ID, looking it up from ca_code if needed."""
        if not self._internal_station_id:
            result = get_canada_station_id_local(self.station)
            self._internal_station_id = result
        return self._internal_station_id

    # Returns the datetime object from the given time
    def _parseTime(self, timeStr):
        # convert UTC iso time string to local one
        parsed = parser.parse(timeStr)
        # confirmed 3/10/24 that this conversion will account for daylight savings
        datetime_obj_pacific = parsed.astimezone(pytz.timezone('US/Pacific'))
        # convert localized datetime object to a naive datetime object
        return datetime_obj_pacific.replace(tzinfo=None)

    # Returns the day-specific URL for the current base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        start = (day + datetime.timedelta(days=-1)).strftime("%Y-%m-%d")
        twoWeeks = (day + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        return baseUrl + '&from={}T00:00:00Z&to={}T00:30:00Z'.format(start, twoWeeks)

    def __getJsonResponse(self, url):
        r = requests.get(url)
        if r.status_code != 200:
            raise Exception(f'Canada currents API request failed: {r.status_code} - {r.text[:200]}')
        return r.json()

    def _cache_covers_day(self, day):
        """Check if the cache already has data for the given day."""
        if not self._cached_slacks or not self._cache_start or not self._cache_end:
            return False
        day_date = day.date() if hasattr(day, 'date') else day
        # Don't use the last day in cache as it may be incomplete
        return self._cache_start <= day_date < self._cache_end

    def _fetchAndCacheSlacks(self, day):
        """Fetch slacks from API for a 14-day window starting from day-1 and cache them."""
        station_id = self._get_station_id()
        if not station_id:
            return

        CanadaAPIInterpreter.numAPICalls += 1
        start = (day + datetime.timedelta(days=-1))
        end = (day + datetime.timedelta(days=14))

        url = (
            f"{CANADA_API_BASE_URL}/stations/{station_id}/data"
            f"?time-series-code=wcp1-events"
            f"&from={start.strftime('%Y-%m-%d')}T00:00:00Z"
            f"&to={end.strftime('%Y-%m-%d')}T00:30:00Z"
        )

        eventsResponse = self.__getJsonResponse(url)
        slacks = self.__parseSlacks(eventsResponse, moon.phase(day))

        # Update cache
        self._cached_slacks = slacks
        if slacks:
            self._cache_start = slacks[0].time.date()
            self._cache_end = slacks[-1].time.date()

    def __parseSlacks(self, eventsResponse, moonPhase):
        """
        Parse the wcp1-events response into Slack objects.

        The response contains events with qualifier: SLACK, EXTREMA_FLOOD, EXTREMA_EBB
        Events are in chronological order, so we can find the flood/ebb before and after each slack.
        """
        if not eventsResponse:
            return []

        slacks = []
        n = len(eventsResponse)

        for i, event in enumerate(eventsResponse):
            if event.get('qualifier') != 'SLACK':
                continue

            s = Slack()
            s.moonPhase = moonPhase
            s.time = self._parseTime(event['eventDate'])

            # Find the previous extrema (flood or ebb)
            prevExtrema = None
            for j in range(i - 1, -1, -1):
                if eventsResponse[j].get('qualifier') in ('EXTREMA_FLOOD', 'EXTREMA_EBB'):
                    prevExtrema = eventsResponse[j]
                    break

            # Find the next extrema (flood or ebb)
            nextExtrema = None
            for j in range(i + 1, n):
                if eventsResponse[j].get('qualifier') in ('EXTREMA_FLOOD', 'EXTREMA_EBB'):
                    nextExtrema = eventsResponse[j]
                    break

            # Need both previous and next to calculate slack properly
            if not prevExtrema or not nextExtrema:
                continue

            # Determine if this is slack before ebb (SBE) or slack before flood (SBF)
            # If next extrema is ebb, this is SBE
            s.slackBeforeEbb = nextExtrema.get('qualifier') == 'EXTREMA_EBB'

            if s.slackBeforeEbb:
                # Previous was flood, next is ebb
                s.floodSpeed = prevExtrema['value']
                s.maxFloodTime = self._parseTime(prevExtrema['eventDate'])
                s.ebbSpeed = -nextExtrema['value']  # Ebb speeds are stored as negative
                s.maxEbbTime = self._parseTime(nextExtrema['eventDate'])
            else:
                # Previous was ebb, next is flood
                s.ebbSpeed = -prevExtrema['value']  # Ebb speeds are stored as negative
                s.maxEbbTime = self._parseTime(prevExtrema['eventDate'])
                s.floodSpeed = nextExtrema['value']
                s.maxFloodTime = self._parseTime(nextExtrema['eventDate'])

            # Add sunrise/sunset data
            sunData = sun(self._astralCity.observer, date=s.time, tzinfo=timezone('US/Pacific'))
            s.sunriseTime = sunData['sunrise'].replace(tzinfo=None)
            s.sunsetTime = sunData['sunset'].replace(tzinfo=None)

            slacks.append(s)

        return slacks

    def _getSlacksOnDay(self, day, time_filter):
        """Get slacks from cache for the specified day, applying time filter."""
        day_str = dt.strftime(day, DATEFMT)
        result = []
        for s in self._cached_slacks:
            if dt.strftime(s.time, DATEFMT) == day_str:
                if _passesTimeFilter(s, time_filter):
                    result.append(s)
        return result

    def getSlacks(self, day, time_filter):
        """
        Returns a list of slacks for the given day.

        Uses cached data if available, otherwise fetches a 14-day window from the API.
        """
        station_id = self._get_station_id()
        if not station_id:
            return []

        # Fetch new data if cache doesn't cover the requested day
        if not self._cache_covers_day(day):
            self._fetchAndCacheSlacks(day)

        return self._getSlacksOnDay(day, time_filter)

class XTideDockerInterpreter(Interpreter):
    def __init__(self, baseUrl, station):
        super().__init__(baseUrl, station)
        self._events_cache = None  # list of parsed events across a cached range
        self._slacks_cache = None  # list[Slack] built from cached events
        self._cache_start = None   # datetime.date
        self._cache_end = None     # datetime.date

    @staticmethod
    def getDayUrl(baseUrl, day):
        return 'No url for local Docker'

    # Returns the datetime object parsed from a generic "YYYY-MM-DD HH:MM" pair (ignores timezone token)
    def _parseTime(self, tokens):
        # tokens example (split by whitespace):
        # ['2025-12-01', '1:33', 'AM', 'PST', '-0.00', 'knots', 'Slack,', 'Ebb', 'Begins']
        # or without AM/PM (24h) in some outputs
        date_part = tokens[0]
        time_part = tokens[1]
        # If AM/PM present, include it in parsing; otherwise treat as 24-hour time
        if len(tokens) > 2 and tokens[2].lower() in ('am', 'pm'):
            ampm = tokens[2].upper()
            return dt.strptime(f"{date_part} {time_part}{ampm}", TIMEPARSEFMT)
        else:
            return dt.strptime(f"{date_part} {time_part}", TIMEPARSEFMT_TBONE)

    def _run_xtide_range(self, start_day, end_day):
        begin = dt.strftime(start_day, '%Y-%m-%d') + ' 00:00'
        end = dt.strftime(end_day, '%Y-%m-%d') + ' 23:59'
        location = self.station['xtide_name'] if 'xtide_name' in self.station else self.station['name']
        cmd = [
            'docker', 'run', '--rm',
            'xtide',
            '-l', location,
            '-b', begin,
            '-e', end
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=False, check=True)
        except Exception as e:
            raise Exception('XTide Docker invocation failed: {}'.format(repr(e)))
        def _safe_decode(b):
            try:
                return b.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    return b.decode('latin-1')
                except Exception:
                    return b.decode('utf-8', errors='replace')
        stdout_text = _safe_decode(completed.stdout)
        _ = _safe_decode(completed.stderr)  # keep for potential debugging
        return stdout_text.splitlines()

    def _run_xtide_for_day(self, day):
        # Query a wider range to ensure we capture max currents that occur just before/after midnight
        # This handles edge cases like a slack at 3 AM with preMax at 11 PM previous day,
        # or a slack at 10 PM with postMax at 1 AM next day
        prev_day = day - td(days=1)
        next_day = day + td(days=1)
        begin = dt.strftime(prev_day, '%Y-%m-%d') + ' 12:00'  # Start at noon previous day
        end = dt.strftime(next_day, '%Y-%m-%d') + ' 12:00'    # End at noon next day
        location = self.station['xtide_name'] if 'xtide_name' in self.station else self.station['name']
        cmd = [
            'docker', 'run', '--rm',
            'xtide',
            '-l', location,
            '-b', begin,
            '-e', end
        ]
        try:
            # Capture raw bytes and decode manually to handle non-UTF8 output (degree symbol, etc.)
            completed = subprocess.run(cmd, capture_output=True, text=False, check=True)
        except Exception as e:
            raise Exception('XTide Docker invocation failed: {}'.format(repr(e)))
        # Try utf-8 first, then fall back to latin-1 which safely decodes b'\xb0' to '°'
        def _safe_decode(b):
            try:
                return b.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    return b.decode('latin-1')
                except Exception:
                    return b.decode('utf-8', errors='replace')
        stdout_text = _safe_decode(completed.stdout)
        stderr_text = _safe_decode(completed.stderr)
        # print('XTide Docker output: {}'.format(stdout_text))
        # print('XTide Docker error: {}'.format(stderr_text))
        return stdout_text.splitlines()

    def _parse_xtide_events(self, lines):
        # Return list of tuples (index, kind, time, speed)
        # kind in {'max_flood','max_ebb','slack_flood','slack_ebb'}
        events = []
        for idx, line in enumerate(lines):
            if 'knots' not in line:
                continue
            tokens = line.split()
            if len(tokens) < 6:
                continue
            # Basic guards to skip sunrise/sunset/moon lines
            if 'sunrise' in line or 'sunset' in line or 'moonrise' in line or 'moonset' in line or 'full moon' in line or 'new moon' in line or 'first quarter' in line or 'last quarter' in line:
                continue
            timeVal = self._parseTime(tokens)
            # Speed is the token before 'knots'; usually tokens[3]
            try:
                # find index of 'knots'
                kidx = tokens.index('knots')
                speed = float(tokens[kidx - 1])
            except Exception:
                continue
            lower = line.lower()
            if 'max flood' in lower:
                events.append((idx, 'max_flood', timeVal, abs(speed)))
            elif 'max ebb' in lower:
                # keep ebb speed negative to match expectations elsewhere
                events.append((idx, 'max_ebb', timeVal, -abs(speed)))
            elif 'slack' in lower and 'flood begins' in lower:
                events.append((idx, 'slack_flood', timeVal, 0.0))
            elif 'slack' in lower and 'ebb begins' in lower:
                events.append((idx, 'slack_ebb', timeVal, 0.0))
        return events

    def _build_slacks_from_events(self, events):
        # Build Slack objects for the whole cached range, computing sunrise/sunset per slack day
        slacks = []
        for i, (idx, kind, t, _) in enumerate(events):
            if kind not in ('slack_flood', 'slack_ebb'):
                continue
            preMax = None
            postMax = None
            if kind == 'slack_ebb':
                for j in range(i - 1, -1, -1):
                    if events[j][1] == 'max_flood':
                        preMax = events[j]
                        break
                for j in range(i + 1, len(events)):
                    if events[j][1] == 'max_ebb':
                        postMax = events[j]
                        break
                slackBeforeEbb = True
            else:
                for j in range(i - 1, -1, -1):
                    if events[j][1] == 'max_ebb':
                        preMax = events[j]
                        break
                for j in range(i + 1, len(events)):
                    if events[j][1] == 'max_flood':
                        postMax = events[j]
                        break
                slackBeforeEbb = False
            if not preMax or not postMax:
                continue

            # sunrise/sunset for the slack's calendar day
            sunData = sun(self._astralCity.observer, date=t, tzinfo=timezone('US/Pacific'))
            sunrise = sunData['sunrise'].replace(tzinfo=None)
            sunset = sunData['sunset'].replace(tzinfo=None)
            mphase = moon.phase(t)

            s = Slack()
            s.time = t
            s.sunriseTime = sunrise
            s.sunsetTime = sunset
            s.moonPhase = mphase
            s.slackBeforeEbb = slackBeforeEbb
            if slackBeforeEbb:
                s.floodSpeed = preMax[3] if preMax[1] == 'max_flood' else abs(preMax[3])
                s.maxFloodTime = preMax[2]
                s.ebbSpeed = postMax[3] if postMax[1] == 'max_ebb' else -abs(postMax[3])
                s.maxEbbTime = postMax[2]
            else:
                s.ebbSpeed = preMax[3] if preMax[1] == 'max_ebb' else -abs(preMax[3])
                s.maxEbbTime = preMax[2]
                s.floodSpeed = postMax[3] if postMax[1] == 'max_flood' else abs(postMax[3])
                s.maxFloodTime = postMax[2]
            slacks.append(s)
        return slacks

    def preload_range(self, start_day, end_day):
        # Normalize to dates without time
        start = dt(year=start_day.year, month=start_day.month, day=start_day.day)
        end = dt(year=end_day.year, month=end_day.month, day=end_day.day)
        lines = self._run_xtide_range(start, end)
        events = self._parse_xtide_events(lines)
        if not events:
            raise Exception('No XTide events parsed for range {} - {}'.format(start, end))
        self._events_cache = events
        self._slacks_cache = self._build_slacks_from_events(events)
        self._cache_start = start
        self._cache_end = end

    def _covers_date(self, day):
        if not self._cache_start or not self._cache_end:
            return False
        d = dt(year=day.year, month=day.month, day=day.day)
        return self._cache_start <= d <= self._cache_end

    def _filter_cached_slacks_for_day(self, day, time_filter):
        if not self._slacks_cache:
            return []
        day_str = dt.strftime(day, DATEFMT)
        result = []
        for s in self._slacks_cache:
            if dt.strftime(s.time, DATEFMT) != day_str:
                continue
            if _passesTimeFilter(s, time_filter):
                result.append(s)
        return result

    def getSlacks(self, day, time_filter):
        # Fast path: if we have a cached range that covers this day, just filter
        if self._covers_date(day):
            return self._filter_cached_slacks_for_day(day, time_filter)

        # Fallback: single-day execution (preserves old behavior if preload_range not used)
        try:
            lines = self._run_xtide_for_day(day)
        except Exception as e:
            print('Error running XTide via Docker: {}'.format(repr(e)))
            return []
        events = self._parse_xtide_events(lines)
        if not events:
            print('ERROR: no events parsed for {} from XTide'.format(day))
            return []
        # Build full-day slacks using the same logic but with day-specific sun times
        # reuse builder with events from just this day
        temp_slacks = self._build_slacks_from_events(events)
        # filter for the requested calendar day and time_filter
        res = []
        day_str = dt.strftime(day, DATEFMT)
        for s in temp_slacks:
            if dt.strftime(s.time, DATEFMT) != day_str:
                continue
            if _passesTimeFilter(s, time_filter):
                res.append(s)
        if not res:
            print('ERROR: no slacks constructed for {} from XTide'.format(day))
        return res


# Class to retrieve and parse current data from Canadian Hydrographic Service (CHS) PDF files
# These PDFs contain the annual current predictions for Canadian current stations
class CanadaPDFInterpreter(Interpreter):
    """
    Interpreter that downloads and parses CHS current prediction PDFs.

    The PDFs are annual prediction files that contain slack and maximum current data
    for Canadian current stations. The PDF URL pattern is:
    https://tides.gc.ca/sites/tides/files/{year-1}-11/{station_code}_{year}.pdf

    Requires the station to have a 'ca_code' field (e.g., "08108" for Seymour Narrows).
    """

    def __init__(self, baseUrl, station):
        super().__init__(baseUrl, station)
        self._cachedSlacks = []  # Cache of all slacks from the PDF
        self._cachedYear = None  # Year for which we have cached data
        self.numAPICalls = 0  # Track number of PDF downloads (for compatibility)

    def _getStationCode(self):
        """Get the CHS station code for PDF download."""
        if 'ca_code' in self.station and self.station['ca_code']:
            return self.station['ca_code']
        return None

    def _ensureCachedData(self, year):
        """Ensure we have cached data for the requested year."""
        if self._cachedYear == year and self._cachedSlacks:
            return True

        station_code = self._getStationCode()
        if not station_code:
            print(f"Error: Station '{self.station.get('name', 'unknown')}' does not have 'ca_code' configured")
            return False

        # Build the PDF URL
        pdf_url = canada_pdf_lib.build_pdf_url(station_code, year)
        self.numAPICalls += 1  # Count PDF downloads

        try:
            # Download and parse the PDF
            slacks = canada_pdf_lib.parse_current_pdf(pdf_url, Slack)

            # Add sunrise/sunset times to each slack
            for slack in slacks:
                sunData = sun(self._astralCity.observer, date=slack.time, tzinfo=timezone('US/Pacific'))
                slack.sunriseTime = sunData['sunrise'].replace(tzinfo=None)
                slack.sunsetTime = sunData['sunset'].replace(tzinfo=None)
                slack.moonPhase = moon.phase(slack.time)

            self._cachedSlacks = slacks
            self._cachedYear = year
            return True

        except Exception as e:
            print(f"Error downloading/parsing PDF for station code {station_code}: {e}")
            return False

    def _parseTime(self, tokens):
        """Not used for PDF parsing, but required by base class."""
        raise NotImplementedError("CanadaPDFInterpreter does not use _parseTime")

    @staticmethod
    def getDayUrl(baseUrl, day):
        """Return the PDF URL for the year containing the given day."""
        station_code = baseUrl  # We pass station code as baseUrl for this interpreter
        if station_code:
            return canada_pdf_lib.build_pdf_url(station_code, day.year)
        return ""

    def _getWebLines(self, url, day):
        """Not used for PDF parsing."""
        raise NotImplementedError("CanadaPDFInterpreter does not use _getWebLines")

    def _getSlackData(self, lines, indexes, sunrise, sunset, moonPhase):
        """Not used for PDF parsing."""
        raise NotImplementedError("CanadaPDFInterpreter does not use _getSlackData")

    def getSlacks(self, day, time_filter):
        """
        Returns a list of slacks for the given day.

        time_filter: 'day' for daytime only, 'night' for nighttime only, 'all' for all times
        """
        station_code = self._getStationCode()
        if not station_code:
            return []

        # Ensure we have cached data for this year
        if not self._ensureCachedData(day.year):
            return []

        # Filter slacks for the requested day
        day_str = dt.strftime(day, DATEFMT)
        result = []

        for slack in self._cachedSlacks:
            slack_day_str = dt.strftime(slack.time, DATEFMT)
            if slack_day_str != day_str:
                continue

            # Apply time filter
            if _passesTimeFilter(slack, time_filter):
                result.append(slack)

        return result

    def allSlacks(self, startDay):
        """
        Returns all slacks from the PDF for the year of startDay.
        """
        station_code = self._getStationCode()
        if not station_code:
            return []

        if not self._ensureCachedData(startDay.year):
            return []

        # Return slacks starting from startDay
        start_str = dt.strftime(startDay, DATEFMT)
        result = []
        for slack in self._cachedSlacks:
            if dt.strftime(slack.time, DATEFMT) >= start_str:
                result.append(slack)

        return result


# Class to retrieve and parse current data from dairiki.org website
# This interpreter parses the monthly table format from dairiki.org
class DairikiInterpreter(Interpreter):
    """
    Interpreter that downloads and parses current predictions from dairiki.org.

    The URL pattern is: https://www.dairiki.org/tides/monthly.php/{station_code}/{year}-{month}
    Example: https://www.dairiki.org/tides/monthly.php/nak/2026-10

    The monthly table contains columns:
    - Turn: slack current time
    - Max: maximum current time and speed (e.g., "7.5F" for flood, "-6.5E" for ebb)

    Requires the station to have a 'url_dairiki' field.
    """

    def __init__(self, baseUrl, station):
        super().__init__(baseUrl, station)
        self._cachedSlacks = []  # Cache of all slacks from the page
        self._cachedYearMonth = None  # (year, month) tuple for which we have cached data
        self.numAPICalls = 0  # Track number of page downloads (for compatibility)

    def _parseTime(self, tokens):
        """Not used for Dairiki parsing, but required by base class."""
        raise NotImplementedError("DairikiInterpreter does not use _parseTime")

    @staticmethod
    def getDayUrl(baseUrl, day):
        """Return the monthly URL for the given day."""
        if baseUrl:
            # baseUrl format: https://www.dairiki.org/tides/monthly.php/nak
            return f"{baseUrl}/{day.year}-{day.month:02d}"
        return ""

    def _getWebLines(self, url, day):
        """Not used for Dairiki parsing."""
        raise NotImplementedError("DairikiInterpreter does not use _getWebLines")

    def _getSlackData(self, lines, indexes, sunrise, sunset, moonPhase):
        """Not used for Dairiki parsing."""
        raise NotImplementedError("DairikiInterpreter does not use _getSlackData")

    def _parseSpeedValue(self, text):
        """
        Parse a speed value like '7.5F' (flood) or '-6.5E' (ebb).
        Returns (speed, is_flood) tuple.
        Flood speeds are positive, ebb speeds are negative.
        """
        text = text.strip()
        if not text:
            return None, None

        is_flood = text.endswith('F')
        is_ebb = text.endswith('E')

        if not is_flood and not is_ebb:
            return None, None

        try:
            # Remove the F or E suffix and parse the number
            speed_str = text[:-1]
            speed = float(speed_str)
            # Ensure ebb is negative
            if is_ebb and speed > 0:
                speed = -speed
            return speed, is_flood
        except ValueError:
            return None, None

    def _parseTimeStr(self, time_str, date):
        """
        Parse a time string like '02:01' or '14:34' with a given date.
        Returns a datetime object.
        """
        time_str = time_str.strip()
        if not time_str or time_str == '':
            return None

        try:
            # Parse HH:MM format
            parts = time_str.split(':')
            if len(parts) != 2:
                return None
            hour = int(parts[0])
            minute = int(parts[1])
            return dt(date.year, date.month, date.day, hour, minute)
        except (ValueError, TypeError):
            return None

    def _fetchMonthEvents(self, year, month):
        """
        Fetch the monthly page and parse all events (turns and maxes) for the month.
        Returns a dict mapping date_key to {'turns': [...], 'maxes': [...], 'date': datetime}.
        This is a lower-level method that doesn't build Slack objects.
        """
        url = f"{self.baseUrl}/{year}-{month:02d}"
        self.numAPICalls += 1

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                html = response.read()
                soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            print(f"Error fetching Dairiki page {url}: {e}")
            return {}

        # Find the tide table
        table = soup.find('table', {'class': 'tidetable'})
        if not table:
            print(f"Error: Could not find tide table at {url}")
            return {}

        current_date = None

        # Each row in tbody contains data
        tbody = table.find('tbody')
        if not tbody:
            print(f"Error: Could not find tbody in tide table at {url}")
            return {}

        rows = tbody.find_all('tr')

        # Group rows by date - each date can have 1-2 rows
        date_events = {}  # Maps date to list of events (turn times, max times, speeds)

        for row in rows:
            # Skip info rows
            if 'info' in row.get('class', []):
                continue

            cells = row.find_all('td')
            if not cells:
                continue

            # First cell contains date link
            first_cell = cells[0]
            date_link = first_cell.find('a')
            if date_link:
                # Extract date from href like "daily.php/nak/2026-10-01"
                href = date_link.get('href', '')
                # Parse date from href
                date_match = re.search(r'/(\d{4}-\d{2}-\d{2})$', href)
                if date_match:
                    date_str = date_match.group(1)
                    try:
                        current_date = dt.strptime(date_str, '%Y-%m-%d')
                    except ValueError:
                        continue

            if not current_date:
                continue

            date_key = dt.strftime(current_date, DATEFMT)
            if date_key not in date_events:
                date_events[date_key] = {'turns': [], 'maxes': [], 'date': current_date}

            # Parse the cells in this row
            # Table structure: Date | Turn | Max Time | Max Speed | Turn | Max Time | Max Speed | Turn
            # Cells have classes: 'first date', '', 'left', 'right', '', 'left', 'right', 'last'

            # Iterate through cells and extract data
            i = 0
            while i < len(cells):
                cell = cells[i]
                cell_class = ' '.join(cell.get('class', []))
                cell_text = cell.get_text(strip=True)

                # Skip date cell
                if 'date' in cell_class or 'first' in cell_class:
                    i += 1
                    continue

                # Check if this is a "Turn" column (slack time)
                # Turn columns don't have 'left' or 'right' class (except 'last')
                if ('left' not in cell_class and 'right' not in cell_class and
                    'empty' not in cell_class and cell_text):
                    # This is a turn (slack) time
                    time_obj = self._parseTimeStr(cell_text, current_date)
                    if time_obj:
                        date_events[date_key]['turns'].append(time_obj)
                    i += 1
                    continue

                # Check for max current (left = time, right = speed)
                if 'left' in cell_class and i + 1 < len(cells):
                    max_time_str = cell_text
                    next_cell = cells[i + 1]
                    speed_text = next_cell.get_text(strip=True)

                    time_obj = self._parseTimeStr(max_time_str, current_date)
                    speed, is_flood = self._parseSpeedValue(speed_text)

                    if time_obj and speed is not None:
                        date_events[date_key]['maxes'].append({
                            'time': time_obj,
                            'speed': speed,
                            'is_flood': is_flood
                        })
                    i += 2
                    continue

                i += 1

        return date_events

    def _getAdjacentMonthMaxes(self, year, month, direction):
        """
        Fetch max current data from an adjacent month.
        direction: 'prev' for previous month, 'next' for next month.
        Returns a list of max current dicts sorted by time.
        """
        if direction == 'prev':
            if month == 1:
                adj_year, adj_month = year - 1, 12
            else:
                adj_year, adj_month = year, month - 1
        else:  # next
            if month == 12:
                adj_year, adj_month = year + 1, 1
            else:
                adj_year, adj_month = year, month + 1

        adj_events = self._fetchMonthEvents(adj_year, adj_month)
        all_maxes = []
        for events in adj_events.values():
            all_maxes.extend(events['maxes'])
        all_maxes.sort(key=lambda x: x['time'])
        return all_maxes

    def _fetchAndParseMonth(self, year, month):
        """
        Fetch the monthly page and parse all slacks for the month.
        Returns a list of Slack objects.
        Handles edge cases where the max current before/after a slack is in an adjacent month.
        """
        date_events = self._fetchMonthEvents(year, month)
        if not date_events:
            return []

        # Collect all maxes from this month for quick lookup
        all_month_maxes = []
        for events in date_events.values():
            all_month_maxes.extend(events['maxes'])
        all_month_maxes.sort(key=lambda x: x['time'])

        # Identify the first and last day of the month
        first_day = dt(year, month, 1)
        if month == 12:
            last_day = dt(year + 1, 1, 1) - td(days=1)
        else:
            last_day = dt(year, month + 1, 1) - td(days=1)

        # Cache for adjacent month data (lazy load)
        prev_month_maxes = None
        next_month_maxes = None

        slacks = []

        # Now build Slack objects from the parsed events
        # For each slack (turn), find the max current before and after
        for date_key, events in date_events.items():
            turns = sorted(events['turns'], key=lambda x: x)
            current_date = events['date']

            # Get sunrise/sunset for this date
            sunData = sun(self._astralCity.observer, date=current_date, tzinfo=timezone('US/Pacific'))
            sunrise = sunData['sunrise'].replace(tzinfo=None)
            sunset = sunData['sunset'].replace(tzinfo=None)
            moonPhase = moon.phase(current_date)

            for turn_time in turns:
                # Find the max current before this slack
                max_before = None
                for m in reversed(all_month_maxes):
                    if m['time'] < turn_time:
                        max_before = m
                        break

                # If not found and this is early in the month, check previous month
                if max_before is None and current_date.day <= 1:
                    if prev_month_maxes is None:
                        prev_month_maxes = self._getAdjacentMonthMaxes(year, month, 'prev')
                    for m in reversed(prev_month_maxes):
                        if m['time'] < turn_time:
                            max_before = m
                            break

                # Find the max current after this slack
                max_after = None
                for m in all_month_maxes:
                    if m['time'] > turn_time:
                        max_after = m
                        break

                # If not found and this is late in the month, check next month
                if max_after is None and current_date.day >= last_day.day:
                    if next_month_maxes is None:
                        next_month_maxes = self._getAdjacentMonthMaxes(year, month, 'next')
                    for m in next_month_maxes:
                        if m['time'] > turn_time:
                            max_after = m
                            break

                if not max_before or not max_after:
                    # Still couldn't find required data - skip this slack
                    print(f"Warning: Could not find max current data for slack at {turn_time}")
                    continue

                s = Slack()
                s.time = turn_time
                s.sunriseTime = sunrise
                s.sunsetTime = sunset
                s.moonPhase = moonPhase

                # Determine if slack is before ebb (ebb comes after) or before flood
                s.slackBeforeEbb = not max_after['is_flood']  # If after is ebb, then slack is before ebb

                if s.slackBeforeEbb:
                    # Before: flood, After: ebb
                    s.floodSpeed = abs(max_before['speed'])
                    s.maxFloodTime = max_before['time']
                    s.ebbSpeed = -abs(max_after['speed'])
                    s.maxEbbTime = max_after['time']
                else:
                    # Before: ebb, After: flood
                    s.ebbSpeed = -abs(max_before['speed'])
                    s.maxEbbTime = max_before['time']
                    s.floodSpeed = abs(max_after['speed'])
                    s.maxFloodTime = max_after['time']

                slacks.append(s)

        # Sort slacks by time
        slacks.sort(key=lambda x: x.time)
        return slacks

    def _ensureCachedData(self, year, month):
        """Ensure we have cached data for the requested year/month."""
        if self._cachedYearMonth == (year, month) and self._cachedSlacks:
            return True

        if not self.baseUrl:
            print("Error: Station does not have 'url_dairiki' configured")
            return False

        slacks = self._fetchAndParseMonth(year, month)
        if slacks:
            self._cachedSlacks = slacks
            self._cachedYearMonth = (year, month)
            return True

        return False

    def getSlacks(self, day, time_filter):
        """
        Returns a list of slacks for the given day.
        time_filter: 'day' for daytime only, 'night' for nighttime only, 'all' for all times
        """
        if not self.baseUrl:
            return []

        # Ensure we have cached data for this month
        if not self._ensureCachedData(day.year, day.month):
            return []

        # Filter slacks for the requested day
        day_str = dt.strftime(day, DATEFMT)
        result = []

        for slack in self._cachedSlacks:
            slack_day_str = dt.strftime(slack.time, DATEFMT)
            if slack_day_str != day_str:
                continue

            # Apply time filter
            if _passesTimeFilter(slack, time_filter):
                result.append(slack)

        return result

    def allSlacks(self, startDay):
        """
        Returns all slacks from the page for the month of startDay.
        """
        if not self.baseUrl:
            return []

        if not self._ensureCachedData(startDay.year, startDay.month):
            return []

        # Return slacks starting from startDay
        start_str = dt.strftime(startDay, DATEFMT)
        result = []
        for slack in self._cachedSlacks:
            if dt.strftime(slack.time, DATEFMT) >= start_str:
                result.append(slack)

        return result
