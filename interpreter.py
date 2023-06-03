import urllib.request
from astral.sun import sun
from astral import LocationInfo
from astral import moon
from bs4 import BeautifulSoup
import datetime
from datetime import datetime as dt
from pytz import timezone
import requests

# https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior
TIMEPARSEFMT = '%Y-%m-%d %I:%M%p'  # example: 2019-01-18 09:36AM
TIMEPARSEFMT_TBONE = '%Y-%m-%d %H:%M'  # example: 2019-01-18 22:36
TIMEPRINTFMT = '%a %Y-%m-%d %I:%M%p'  # example: Fri 2019-01-18 09:36AM
DATEFMT = '%Y-%m-%d'  # example 2019-01-18
TIMEFMT = '%I:%M%p'  # example 09:36AM

def dateString(date):
    return dt.strftime(date, TIMEPRINTFMT)

class Slack:
    time = None
    sunriseTime = None
    sunsetTime = None  # this is never used, but might be interesting to print it sometimes
    moonPhase = -1
    slackBeforeEbb = False
    ebbSpeed = 0.0  # negative number
    floodSpeed = 0.0  # positive number

    def __str__(self):
        if self.slackBeforeEbb:
            return '{} -> {} -> {}'.format(self.floodSpeed, dateString(self.time), self.ebbSpeed)
        else:
            return '{} -> {} -> {}'.format(self.ebbSpeed, dateString(self.time), self.floodSpeed)

    # string without date info (only time) for logbook entry
    def logString(self):
        if self.slackBeforeEbb:
            return '{} > {} > {}'.format(self.floodSpeed, dt.strftime(self.time, TIMEFMT), self.ebbSpeed)
        else:
            return '{} > {} > {}'.format(self.ebbSpeed, dt.strftime(self.time, TIMEFMT), self.floodSpeed)

    def __repr__(self):
        return self.__str__()

# Base class to download and parse current data from various websites
class Interpreter:

    def __init__(self, baseUrl):
        self.baseUrl = baseUrl
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
                # print('Base url empty')
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
                s.ebbSpeed = float(tokens2[5])
            else:
                s.ebbSpeed = float(tokens1[5])
                s.floodSpeed = float(tokens2[5])

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks


# Class to retrieve and parse current data from tbone.biol.sc.edu website
class TBoneSCInterpreter(Interpreter):

    # Returns the datetime object parsed from the given data line from tbone.biol.sc.edu website
    def _parseTime(self, tokens):
        dayTimeStr = tokens[0] + ' ' + tokens[1]  # ex: 2018-11-17 22:41
        return dt.strptime(dayTimeStr, TIMEPARSEFMT_TBONE)

    # Returns the day-specific URL for the base URL
    @staticmethod
    def getDayUrl(baseUrl, day):
        return baseUrl + '&year={}&month={}&day={}'.format(day.year, day.month, day.day)

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
                s.ebbSpeed = float(tokens2[3])
            else:
                s.ebbSpeed = float(tokens1[3])
                s.floodSpeed = float(tokens2[3])

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks


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
                s.ebbSpeed = float(tokens2[4])
            else:
                s.ebbSpeed = float(tokens1[4])
                s.floodSpeed = float(tokens2[4])

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
                s.ebbSpeed = float(tokens2[3])
            else:
                s.ebbSpeed = float(tokens1[3])
                s.floodSpeed = float(tokens2[3])

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks
