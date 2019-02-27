'''
This program is used to identify if days in the future (or past) are considered diveable for a subset of dive sites
specified by dive_sites.json
'''

import data_collect

from pandas.tseries.holiday import USFederalHolidayCalendar
from astral import Astral
from bs4 import BeautifulSoup
from datetime import datetime as dt
from datetime import timedelta as td
import urllib.request, json

TIMEPARSEFMT = '%Y-%m-%d %I:%M%p'  # example: 2019-01-18 09:36AM
TIMEPRINTFMT = '%a %Y-%m-%d %I:%M%p'  # example: Fri 2019-01-18 09:36AM
DATEFMT = '%Y-%m-%d'  # example 2019-01-18

# Base class to download and parse current data from various websites
class Interpreter:

    def __init__(self, baseUrl):
        self.baseUrl = baseUrl
        self._webLines = None
        self._astral = Astral()  # https://astral.readthedocs.io/en/latest
        self._astralCity = self._astral["Seattle"]

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
            if 'slack' in line:
                slacks.append(i)
        return slacks

    # Returns list with indexes of the slack currents in the first 24hrs of the given list of data lines.
    def _getAllDaySlacks(self, webLines):
        day = webLines[0].split()[0]
        slacksIndexes = []
        for i, line in enumerate(webLines):
            if line.split()[0] != day:
                return slacksIndexes
            elif 'slack' in line:
                slacksIndexes.append(i)
        return slacksIndexes

    # Returns list with indexes of the daytime (between given sunrise and sunset) slack currents in the given
    # list of data lines.
    def _getDaySlacks(self, webLines, sunrise, sunset):
        slacksIndexes = []
        for i, line in enumerate(webLines):
            if 'slack' in line:
                time = self._parseTime(line.split())
                if time > sunset:
                    return slacksIndexes
                elif time > sunrise:
                    slacksIndexes.append(i)
        return None

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
    
    def allSlacks(self, startDay):
        url = self.getDayUrl(self.baseUrl, startDay)
        lines = self._getWebLines(url, startDay)
        slackIndexes = self._getAllSlacks(lines)
        return self._getSlackData(lines, slackIndexes, None, None, -1)

    # Returns a list of slacks from given web data lines. Includes night slacks if daylight=False
    def getSlacks(self, day, daylight):
        if not self._canReuseWebData(day):
            url = self.getDayUrl(self.baseUrl, day)
            self._webLines = self._getWebLines(url, day)

        # Note: astral sunrise and sunset times do account for daylight savings
        sun = self._astralCity.sun(date=day, local=True)
        sunrise = sun['sunrise'].replace(tzinfo=None)
        sunset = sun['sunset'].replace(tzinfo=None)
        if daylight:
            slackIndexes = self._getDaySlacks(self._webLines, sunrise, sunset)
        else:
            slackIndexes = self._getAllDaySlacks(self._webLines)
        return self._getSlackData(self._webLines, slackIndexes, sunrise, sunset, self._astral.moon_phase(date=day))


# Class to retrieve and parse current data from mobilegeographics website
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

            s.slackBeforeEbb = 'flood' in preMax

            postMax = self._getCurrentAfter(i, lines)
            if not postMax:
                continue
            tokens2 = postMax.split()

            if s.slackBeforeEbb:
                s.floodSpeed = float(tokens1[5])
                s.ebbSpeed = float(tokens2[5])
            else:
                s.ebbSpeed = float(tokens1[5])
                s.floodSpeed = float(tokens2[5])

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

            s.slackBeforeEbb = 'flood' in preMax

            postMax = self._getCurrentAfter(i, lines)
            if not postMax:
                continue
            tokens2 = postMax.split()

            if s.slackBeforeEbb:
                s.floodSpeed = float(tokens1[4])
                s.ebbSpeed = float(tokens2[4])
            else:
                s.ebbSpeed = float(tokens1[4])
                s.floodSpeed = float(tokens2[4])

            s.time = self._parseTime(lines[i].split())
            slacks.append(s)
        return slacks





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
            return '{} -> {} -> {}'.format(self.floodSpeed, dt.strftime(self.time, TIMEPRINTFMT), self.ebbSpeed)
        else:
            return '{} -> {} -> {}'.format(self.ebbSpeed, dt.strftime(self.time, TIMEPRINTFMT), self.floodSpeed)

    def __repr__(self):
        return self.__str__()


def printinfo(str):
    if PRINTINFO:
        print(str)


def createOrAppend(str):
    global SITES
    if SITES:
        SITES.add(str)
    else:
        SITES = {str}


def getStation(stations, name):
    for station in stations:
        if station['name'] == name:
            return station
    print('Error, no matching current station found for url {}'.format(name))
    return None


# returns a list of datetime days that are weekends and holiday that occur between start (today by default) and
# futureDays in the future
def getNonWorkDays(futureDays, start=dt.now()):
    start = dt(start.year, start.month, start.day)
    end = start + td(days=futureDays)

    cal = USFederalHolidayCalendar()  # does not include some business holidays like black friday
    holidays = cal.holidays(start=start, end=end).to_pydatetime()

    delta = td(days=1)
    d = start
    workdays = {0, 1, 2, 3, 4}
    nonWorkDays = []
    while d <= end:
        if d.weekday() not in workdays:
            nonWorkDays.append(d)
        elif d in holidays:
            nonWorkDays.append(d)
        d += delta
    return nonWorkDays


# returns a list of datetime days that occur between start (today by default) and futureDays in the future
def getAllDays(futureDays, start=dt.now()):
    start = dt(start.year, start.month, start.day)
    end = start + td(days=futureDays)
    delta = td(days=1)
    d = start
    days = []
    while d <= end:
        days.append(d)
        d += delta
    return days


# Returns [mincurrenttime, markerbuoyentrytime, myentrytime] for the given slack at the given site
# mincurrenttime = time of slack current, markerbuoyentrytime = 30min before mincurrenttime,
# myentrytime = mincurrenttime - surfaceswimtime - expecteddivetime/2
# Returns None if an expected json data point is not found
def getEntryTimes(s, site):
    try:
        if s.slackBeforeEbb:
            delta = td(minutes=site['slack_before_ebb'])
        else:
            delta = td(minutes=site['slack_before_flood'])
        minCurrentTime = s.time + delta
        entryTime = minCurrentTime - td(minutes=site['dive_duration'] / 2) - td(minutes=site['surface_swim_time'])
        markerBuoyEntryTime = minCurrentTime - td(minutes=30)
        return minCurrentTime, markerBuoyEntryTime, entryTime
    except KeyError:
        return None


# Prints entry time for Slack s at the given site
def printDive(s, site):
    times = getEntryTimes(s, site)
    if not times:
        print('ERROR: a json key was expected that was not found')
    else:
        minCurrentTime, markerBuoyEntryTime, entryTime = times
        if s.sunriseTime:
            warning = ''
            if entryTime < s.sunriseTime:
                warning = 'BEFORE'
            elif entryTime - td(minutes=30) < s.sunriseTime:
                warning = 'near'
            if warning:
                print('\tWARNING: entry time of {} is {} sunrise at {}'.format(dt.strftime(entryTime, TIMEPRINTFMT),
                    warning, dt.strftime(s.sunriseTime, TIMEPRINTFMT)))

        print('\tDiveable: ' + str(s))
        print('\t\tMinCurrentTime = {}, Duration = {}, SurfaceSwim = {}'
                .format(dt.strftime(minCurrentTime, TIMEPRINTFMT), site['dive_duration'], site['surface_swim_time']))
        print('\t\tEntry Time: ' + dt.strftime(entryTime, TIMEPRINTFMT))  # Time to get in the water.
        print('\t\tMarker Buoy Entrytime (60min dive, no surface swim):', dt.strftime(markerBuoyEntryTime, TIMEPRINTFMT))
        moonAction = "waxing" if s.moonPhase <= 14 else "waning"
        print('\t\tMoon phase: day {} of 28 day lunar month, {:.2f}% {}'.format(s.moonPhase, s.moonPhase % 14 / 14, moonAction))


# Checks the givens list of Slacks if a dive is possible. If so, prints information about the dive.
def printDiveDay(slacks, site):
    for s in slacks:
        assert s.ebbSpeed <= 0.0
        assert s.floodSpeed >= 0.0
        # Check if diveable or not
        if s.slackBeforeEbb and not site['diveable_before_ebb']:
            printinfo('\t' + str(s) + '\t Not diveable before ebb')
        elif not s.slackBeforeEbb and not site['diveable_before_flood']:
            printinfo('\t' + str(s) + '\t Not diveable before flood')
        elif site['diveable_off_slack'] and \
                (s.floodSpeed < site['max_diveable_flood'] or abs(s.ebbSpeed) < site['max_diveable_ebb']):
            print('\t' + str(s) + '\t Diveable off slack')
            printDive(s, site)
        elif s.floodSpeed > site['max_flood'] or abs(s.ebbSpeed) > abs(site['max_ebb']) or \
                s.floodSpeed + abs(s.ebbSpeed) > site['max_total_speed']:
            printinfo('\t' + str(s) + '\t Current too strong')
        else:
            printDive(s, site)


# ---------------------------------- CONFIGURABLE PARAMETERS -----------------------------------------------------------
START = dt.now()
# START = dt(2019, 1, 10)  # date to begin considering diveable conditions
DAYS_IN_FUTURE = 10  # number of days after START to consider

SITES = None  # Consider all sites
# createOrAppend('Salt Creek')
# createOrAppend('Deception Pass')
# createOrAppend('Skyline Wall')
# createOrAppend('Keystone Jetty')
# createOrAppend('Possession Point')
# createOrAppend('Mukilteo')
# createOrAppend('Edmonds Underwater Park')
# createOrAppend('Three Tree North')
# createOrAppend('Alki Pipeline')
# createOrAppend('Saltwater State Park')
# createOrAppend('Day Island Wall')
# createOrAppend('Sunrise Beach')
# createOrAppend('Fox Island Bridge')
# createOrAppend('Fox Island East Wall')
# createOrAppend('Titlow')
# createOrAppend('Waterman Wall')
# createOrAppend('Agate Pass')

filterNonWorkDays = True  # only consider diving on weekends and holidays
filterDaylight = True  # only consider slacks that occur during daylight hours

PRINTINFO = True  # print non-diveable days and reason why not diveable

possibleDiveDays = None  # Specify dates
possibleDiveDays = [
    # dt(2016, 11, 5),
    # dt(2016, 3, 5),
    # dt(2014, 6, 7)
    # dt(2019, 1, 19),
    # dt(2018, 12, 27)
]
# ----------------------------------------------------------------------------------------------------------------------

def main():
    global possibleDiveDays

    if not possibleDiveDays:
        if filterNonWorkDays:
            possibleDiveDays = getNonWorkDays(DAYS_IN_FUTURE, START)
        else:
            possibleDiveDays = getAllDays(DAYS_IN_FUTURE, START)

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    for i in range(len(data['sites'])):
        siteData = data['sites'][i]
        if SITES and siteData['name'] not in SITES:
            continue
        station = getStation(data['stations'], siteData['data'])

        m = MobilegeographicsInterpreter(station['url'])
        m2 = NoaaInterpreter(station['url_noaa'])

        print('{} - {} - {}'.format(siteData['name'], siteData['data'], station['coords']))
        print(m.getDayUrl(m.baseUrl, possibleDiveDays[0]))
        print(m2.getDayUrl(m2.baseUrl, possibleDiveDays[0]))

        for day in possibleDiveDays:
            print("Mobile Geographics")
            slacks = m.getSlacks(day, filterDaylight)
            printDiveDay(slacks, siteData)  # interpret Slack objects with json data to identify diveable times

            print("NOAA")
            slacks = m2.getSlacks(day, filterDaylight)
            printDiveDay(slacks, siteData)  # interpret Slack objects with json data to identify diveable times


if __name__ == '__main__':
    main()
