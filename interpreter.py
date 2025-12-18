import json
import urllib.request
from astral.sun import sun
from astral import LocationInfo
from astral import moon
from bs4 import BeautifulSoup
import datetime
from datetime import datetime as dt
from pytz import timezone
import requests
import re
from dateutil import parser
import pytz
import subprocess

# https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior
TIMEPARSEFMT = '%Y-%m-%d %I:%M%p'  # example: 2019-01-18 09:36AM
TIMEPARSEFMT_TBONE = '%Y-%m-%d %H:%M'  # example: 2019-01-18 22:36
TIMEPARSEFMT_CA = '%Y-%m-%dT%H:%M:%SZ'  # example: 2024-03-13T23:29:00Z
TIMEPRINTFMT = '%a %Y-%m-%d %I:%M%p'  # example: Fri 2019-01-18 09:36AM
DATEFMT = '%Y-%m-%d'  # example 2019-01-18
TIMEFMT = '%I:%M%p'  # example 09:36AM

def dateStr(date):
    return dt.strftime(date, TIMEPRINTFMT)

def timeStr(date):
    result = dt.strftime(date, TIMEFMT)
    if result.startswith('0'):
        return result[1:]  # remove leading 0 (i.e. 9:02AM instead of 09:02AM)
    return result

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
    # Includes night slacks if night=True
    def getSlacks(self, day, night):
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
        if night:
            slackIndexes = self._getAllDaySlacks(self._webLines)
        else:
            slackIndexes = self._getDaySlacks(self._webLines, sunrise, sunset)
        if not slackIndexes:
            print('ERROR: no slacks for {} found in webLines: {}'.format(day, self._webLines))
            return []
        return self._getSlackData(self._webLines, slackIndexes, sunrise, sunset, moon.phase(day))


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
        with urllib.request.urlopen(url) as response:
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
# warning: does not identify "min ebb" or "min flood" type slacks as the direction must change for this to locate a slack
class CanadaAPIInterpreter(Interpreter):
    urlFmt = 'https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/{}/data?time-series-code={}'
    cachedSlacks = []
    numAPICalls = 0

    # Returns the datetime object from the given time
    def _parseTime(self, timeStr):
        # return dt.strptime(timeStr, TIMEPARSEFMT_CA)
        # convert UTC iso time string to local one
        parsed = parser.parse(timeStr)
        # confirmed 3/10/24 that this conversion will account for daylight savings
        datetime_obj_pacific = parsed.astimezone(pytz.timezone('US/Pacific'))
        # convert localized datetime object to a naive datetime object
        return datetime_obj_pacific.replace(tzinfo=None)

    # Returns the day-specific URL for the current base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        start = (day + datetime.timedelta(days=-1)).strftime("%Y-%m-%d")  # start 1d earlier due to huge utc time zone difference
        twoWeeks = (day + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        return baseUrl + '&from={}T00:00:00Z&to={}T00:30:00Z'.format(start, twoWeeks)

    def __getJsonResponse(self, url):
        r = requests.get(url)
        if r.status_code != 200:
            raise Exception('Canada currents API is down')
        return r.json()

    # compares float directions (use epsilon of 5 since opposite direction is +/- 180)
    def __floatEqual(self, float1, float2, threshold=5.0):
        return abs(float1 - float2) <= threshold

    def _getAPIResponses(self, day):
        self.numAPICalls += 1
        urlDay = self.getDayUrl(self.urlFmt, day)
        dir = self.__getJsonResponse(urlDay.format(self.station['ca_id'], 'wcdp-extrema'))
        speed = self.__getJsonResponse(urlDay.format(self.station['ca_id'], 'wcsp-extrema'))
        return dir, speed

    # Returns a list of Slack objects corresponding to the slack indexes within the list of data lines
    def __parseSlacks(self, dirResponse, speedResponse, moonPhase):
        if len(dirResponse) != len(speedResponse):
            print('direction response length does not match speed response length')
            return None
        # print(json.dumps(dirResponse, indent=2))
        # print(json.dumps(speedResponse, indent=2))
        n = len(speedResponse)
        slacks = []
        for i in range(n):
            if speedResponse[i]['value'] == 0.0:
                s = Slack()
                s.moonPhase = moonPhase
                if i + 1 < n:
                    dirLater = dirResponse[i + 1]['value']
                    if not (self.__floatEqual(dirLater, self.station['ebb_dir']) or self.__floatEqual(dirLater, self.station['flood_dir'])):
                        print('error: direction {} does not match expected flood {} or ebb {} direction'.format(dirLater, self.station['flood_dir'], self.station['ebb_dir']))
                        return None
                    s.slackBeforeEbb = dirLater == self.station['ebb_dir']  # ebb after this slack means it's a SBE
                else:
                    dirBefore = dirResponse[i - 1]['value']
                    if not (self.__floatEqual(dirBefore, self.station['ebb_dir']) or self.__floatEqual(dirBefore, self.station['flood_dir'])):
                        print('error: direction {} does not match expected flood {} or ebb {} direction'.format(dirBefore, self.station['flood_dir'], self.station['ebb_dir']))
                        return None
                    s.slackBeforeEbb = dirBefore == self.station['flood_dir']  # flood before this slack means it's a SBE

                # can't get the current before or after slack in this case so ignore these very early or late slacks
                # todo: support a null value before or after to show all slacks in a day
                if i - 1 >= 0 and i + 1 < n:
                    if s.slackBeforeEbb:
                        s.floodSpeed = speedResponse[i - 1]['value']
                        s.maxFloodTime = self._parseTime(speedResponse[i - 1]['eventDate'])
                        s.ebbSpeed = -speedResponse[i + 1]['value']
                        s.maxEbbTime = self._parseTime(speedResponse[i + 1]['eventDate'])
                    else:
                        s.ebbSpeed = -speedResponse[i - 1]['value']
                        s.maxEbbTime = self._parseTime(speedResponse[i - 1]['eventDate'])
                        s.floodSpeed = speedResponse[i + 1]['value']
                        s.maxFloodTime = self._parseTime(speedResponse[i + 1]['eventDate'])
                    s.time = self._parseTime(speedResponse[i]['eventDate'])

                    # Note: astral sunrise and sunset times do account for daylight savings
                    sunData = sun(self._astralCity.observer, date=s.time, tzinfo=timezone('US/Pacific'))
                    # remove time zone info to compare with other local times
                    sunrise = sunData['sunrise'].replace(tzinfo=None)
                    sunset = sunData['sunset'].replace(tzinfo=None)
                    s.sunriseTime = sunrise
                    s.sunsetTime = sunset

                    slacks.append(s)
        self.cachedSlacks.extend(slacks)
        return slacks

    def __getSlacksOnDay(self, day, slacks, night):
        daySlacks = []
        for s in slacks:
            if dt.strftime(s.time, DATEFMT) == dt.strftime(day, DATEFMT):
                if not night and (s.time < s.sunriseTime or s.time > s.sunsetTime):
                    continue
                daySlacks.append(s)
        if self.cachedSlacks and daySlacks and dt.strftime(daySlacks[-1].time, DATEFMT) == dt.strftime(self.cachedSlacks[-1].time, DATEFMT):
            # cached slacks might not have a clean break at end and only include 1st half of final day, so don't return
            # cached slacks for the last day in the cache
            return []
        return daySlacks

    # Returns a list of slacks for the given day, retrieves new web data if the current data doesn't have info for day.
    # Includes night slacks if night=True
    def getSlacks(self, day, night):
        if 'ca_id' not in self.station or not self.station['ca_id']:
            return []
        slacks = self.__getSlacksOnDay(day, self.cachedSlacks, night)
        if slacks:
            return slacks
        # else:
        #     print('unable to use cached results for day: {}'.format(dt.strftime(day, DATEFMT)))
        #     for sl in self.cachedSlacks:
        #         print("\t{}".format(sl))
        #         print("\t comparing to: {}".format(dt.strftime(sl.time, DATEFMT)))

        dir, speed = self._getAPIResponses(day)
        allSlacks = self.__parseSlacks(dir, speed, moon.phase(day))

        # time zone difference with utz is so large we get all the slacks 1 day before to 14 days after and then pick
        # the ones on the requested day
        return self.__getSlacksOnDay(day, allSlacks, night)

class XTideDockerInterpreter(Interpreter):
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

    def _run_xtide_for_day(self, day):
        begin = dt.strftime(day, '%Y-%m-%d') + ' 00:00'
        end = dt.strftime(day, '%Y-%m-%d') + ' 23:59'
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

    def getSlacks(self, day, night):
        try:
            lines = self._run_xtide_for_day(day)
        except Exception as e:
            print('Error running XTide via Docker: {}'.format(repr(e)))
            return []
        events = self._parse_xtide_events(lines)
        if not events:
            print('ERROR: no events parsed for {} from XTide'.format(day))
            return []
        
        # Precompute sunrise/sunset for the day (local tz)
        sunData = sun(self._astralCity.observer, date=day, tzinfo=timezone('US/Pacific'))
        sunrise = sunData['sunrise'].replace(tzinfo=None)
        sunset = sunData['sunset'].replace(tzinfo=None)
        mphase = moon.phase(day)

        slacks = []
        # Build Slack objects by pairing slacks with surrounding maxima
        for i, (idx, kind, t, _) in enumerate(events):
            if kind not in ('slack_flood', 'slack_ebb'):
                continue

            # Find previous and next maxima according to direction switch
            preMax = None
            postMax = None
            if kind == 'slack_ebb':
                # flood before, ebb after
                # search backwards for max_flood
                for j in range(i - 1, -1, -1):
                    if events[j][1] == 'max_flood':
                        preMax = events[j]
                        break
                # search forwards for max_ebb
                for j in range(i + 1, len(events)):
                    if events[j][1] == 'max_ebb':
                        postMax = events[j]
                        break
                slackBeforeEbb = True
            else:
                # ebb before, flood after
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
                # Skip boundary slacks without surrounding maxima
                continue

            s = Slack()
            s.time = t
            s.sunriseTime = sunrise
            s.sunsetTime = sunset
            s.moonPhase = mphase
            s.slackBeforeEbb = slackBeforeEbb

            # preMax/postMax contain (idx, kind, time, speed)
            if slackBeforeEbb:
                # flood before, ebb after
                s.floodSpeed = preMax[3] if preMax[1] == 'max_flood' else abs(preMax[3])
                s.maxFloodTime = preMax[2]
                s.ebbSpeed = postMax[3] if postMax[1] == 'max_ebb' else -abs(postMax[3])
                s.maxEbbTime = postMax[2]
            else:
                s.ebbSpeed = preMax[3] if preMax[1] == 'max_ebb' else -abs(preMax[3])
                s.maxEbbTime = preMax[2]
                s.floodSpeed = postMax[3] if postMax[1] == 'max_flood' else abs(postMax[3])
                s.maxFloodTime = postMax[2]

            # Daytime filter if requested
            if night or (s.time >= sunrise and s.time <= sunset):
                slacks.append(s)

        if not slacks:
            print('ERROR: no slacks constructed for {} from XTide'.format(day))
        return slacks
