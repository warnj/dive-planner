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


# Class to retrieve and parse current data from Noaa website
class NoaaInterpreter(Interpreter):

    # Returns the datetime object parsed from the given data line from Noaa website
    def _parseTime(self, tokens):
        dayTimeStr = tokens[0] + ' ' + tokens[1] + tokens[2][:-1]
        return dt.strptime(dayTimeStr, TIMEPARSEFMT)

    # Returns the day-specific URL for the current base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        return baseUrl + dt.strftime(day, DATEFMT)

    # Returns the noaa current data from the given url
    def _getWebLines(self, url, day):
        with urllib.request.urlopen(url) as response:
            html = response.read()
            soup = BeautifulSoup(html, 'html.parser')
            lines = soup.text.lower().splitlines()
            # ignore the non-current speed data at the top
            dayStr = dt.strftime(day, DATEFMT)
            start = 0
            for line in lines:
                if dayStr not in line:
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
                s.floodSpeed = float(tokens1[4])
                s.maxFloodTime = self._parseTime(tokens1)
                s.ebbSpeed = float(tokens2[4])
                s.maxEbbTime = self._parseTime(tokens2)
            else:
                s.ebbSpeed = float(tokens1[4])
                s.maxEbbTime = self._parseTime(tokens1)
                s.floodSpeed = float(tokens2[4])
                s.maxFloodTime = self._parseTime(tokens2)

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks

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
            raise Exception('NOAA API is down')

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
class CanadaAPIInterpreter(Interpreter):
    urlFmt = 'https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/{}/data?time-series-code={}'

    # Returns the datetime object from the given time
    def _parseTime(self, timeStr):
        return dt.strptime(timeStr, TIMEPARSEFMT_CA)

    # Returns the day-specific URL for the current base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        start = day.strftime("%Y-%m-%d")
        twoWeeks = (day + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
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
        urlDay = self.getDayUrl(self.urlFmt, day)
        dir = self.__getJsonResponse(urlDay.format(self.station['ca_id'], 'wcdp-extrema'))
        speed = self.__getJsonResponse(urlDay.format(self.station['ca_id'], 'wcsp-extrema'))
        return dir, speed

    # Returns a list of Slack objects corresponding to the slack indexes within the list of data lines
    def __parseSlacks(self, dirResponse, speedResponse, sunrise, sunset, moonPhase):
        if len(dirResponse) != len(speedResponse):
            return None
        n = len(speedResponse)
        slacks = []
        for i in range(n):
            if speedResponse[i]['value'] == 0.0:
                s = Slack()
                s.sunriseTime = sunrise
                s.sunsetTime = sunset
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
                    slacks.append(s)
        return slacks

    # Returns a list of slacks for the given day, retrieves new web data if the current data doesn't have info for day.
    # Includes night slacks if night=True
    def getSlacks(self, day, night):
        # todo: save the past speed and direction responses and check them before making new request
        # Note: astral sunrise and sunset times do account for daylight savings
        sunData = sun(self._astralCity.observer, date=day, tzinfo=timezone('US/Pacific'))
        # remove time zone info to compare with other local times
        sunrise = sunData['sunrise'].replace(tzinfo=None)
        sunset = sunData['sunset'].replace(tzinfo=None)
        dir, speed = self._getAPIResponses(day)
        return self.__parseSlacks(dir, speed, sunrise, sunset, moon.phase(day))

        # if night:
        #     slackIndexes = self._getAllDaySlacks(self._webLines)
        # else:
        #     slackIndexes = self._getDaySlacks(self._webLines, sunrise, sunset)
        # if not slackIndexes:
        #     print('ERROR: no slacks for {} found in webLines: {}'.format(day, self._webLines))
        #     return []
        # return self._getSlackData(self._webLines, slackIndexes, sunrise, sunset, moon.phase(day))
