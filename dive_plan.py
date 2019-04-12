'''
This program is used to identify if days in the future (or past) are considered diveable for a subset of dive sites
specified by dive_sites.json
'''

import data_collect
import interpreter as intp

from pandas.tseries.holiday import USFederalHolidayCalendar
from datetime import datetime as dt
from datetime import timedelta as td
import json


class Color:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'


def printInfo(shouldPrint, str):
    if shouldPrint:
        print(str)


def createOrAppend(sites, str):
    if sites:
        sites.add(str)
        return sites
    else:
        return {str}


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
        exitTime = entryTime + 2 * td(minutes=site['surface_swim_time']) + td(minutes=site['dive_duration'])
        markerBuoyEntryTime = minCurrentTime - td(minutes=30)
        return minCurrentTime, markerBuoyEntryTime, entryTime, exitTime
    except KeyError:
        return None


# Prints entry time for Slack s at the given site
def printDive(s, site, titleMessage):
    times = getEntryTimes(s, site)
    if not times:
        print('ERROR: a json key was expected that was not found')
    else:
        minCurrentTime, markerBuoyEntryTime, entryTime, exitTime = times
        if s.sunriseTime:
            warning = ''
            if entryTime < s.sunriseTime:
                warning = 'BEFORE'
            elif entryTime - td(minutes=30) < s.sunriseTime:
                warning = 'near'
            if warning:
                print('\t\tWARNING: entry time of {} is {} sunrise at {}'.format(intp.dateString(entryTime),
                    warning, intp.dateString(s.sunriseTime)))

        print('\t\t{}: {}'.format(titleMessage, s))
        print('\t\t\tMinCurrentTime = {}, Duration = {}, SurfaceSwim = {}'
              .format(intp.dateString(minCurrentTime), site['dive_duration'], site['surface_swim_time']))
        print('\t\t\t{}{}Entry Time: {}{}\t(Exit time: {})'  # Time to get in the water.
              .format(Color.BOLD, Color.UNDERLINE, intp.dateString(entryTime), Color.END, dt.strftime(exitTime, intp.TIMEFMT)))
        print('\t\t\tMarker Buoy Entrytime (60min dive, no surface swim):', intp.dateString(markerBuoyEntryTime))
        # moonAction = "waxing" if s.moonPhase <= 14 else "waning"
        # print('\t\t\tMoon phase: day {} of 28 day lunar month, {:.2f}% {}'.format(s.moonPhase, s.moonPhase % 14 / 14, moonAction))


# Returns true if the given slack is diveable within the parameters of the given site. Also returns description of
# reasoning the decision was made.
def isDiveable(s, site):
    if s.slackBeforeEbb and not site['diveable_before_ebb']:
        return False, 'Not diveable before ebb'
    elif not s.slackBeforeEbb and not site['diveable_before_flood']:
        return False, 'Not diveable before flood'
    elif site['diveable_off_slack'] and \
            (s.floodSpeed < site['max_diveable_flood'] or abs(s.ebbSpeed) < site['max_diveable_ebb']):
        return True, 'Diveable off slack'
    elif s.floodSpeed > site['max_flood'] or abs(s.ebbSpeed) > abs(site['max_ebb']) or \
            s.floodSpeed + abs(s.ebbSpeed) > site['max_total_speed']:
        return False, 'Current too strong'
    else:
        return True, 'Diveable'


# Checks the givens list of Slacks if a dive is possible. If so, prints information about the dive.
def printDiveDay(slacks, site, printNonDiveable, title):
    printed = False
    for s in slacks:
        if s.ebbSpeed > 0.0:
            print('WARNING - EBB SPEED IS POSITIVE')
        if s.floodSpeed < 0.0:
            print('WARNING - FLOOD SPEED IS NEGATIVE')
        # Check if diveable or not
        diveable, info = isDiveable(s, site)
        if not printed and (diveable or printNonDiveable):
            print('\t' + title)
            printed = True
        if diveable:
            printDive(s, site, info)
        else:
            printInfo(printNonDiveable, '\t\t{}:\t{}'.format(info, s))
    return printed


def main():

    # ---------------------------------- CONFIGURABLE PARAMETERS -----------------------------------------------------------
    START = dt.now()
    START = dt(2019, 3, 30)  # date to begin considering diveable conditions
    DAYS_IN_FUTURE = 0  # number of days after START to consider

    SITES = None  # Consider all sites
    # SITES = createOrAppend(SITES, 'Salt Creek')
    # SITES = createOrAppend(SITES, 'Deception Pass')
    # SITES = createOrAppend(SITES, 'Skyline Wall')
    # SITES = createOrAppend(SITES, 'Keystone Jetty')
    # SITES = createOrAppend(SITES, 'Possession Point')
    # SITES = createOrAppend(SITES, 'Mukilteo')
    # SITES = createOrAppend(SITES, 'Edmonds Underwater Park')
    # SITES = createOrAppend(SITES, 'Three Tree North')
    # SITES = createOrAppend(SITES, 'Alki Pipeline')
    # SITES = createOrAppend(SITES, 'Saltwater State Park')
    # SITES = createOrAppend(SITES, 'Day Island Wall')
    # SITES = createOrAppend(SITES, 'Sunrise Beach')
    SITES = createOrAppend(SITES, 'Fox Island Bridge')
    SITES = createOrAppend(SITES, 'Fox Island Bridge Hale')
    # SITES = createOrAppend(SITES, 'Fox Island East Wall')
    # SITES = createOrAppend(SITES, 'Titlow')
    # SITES = createOrAppend(SITES, 'Waterman Wall')
    # SITES = createOrAppend(SITES, 'Agate Pass')
    # SITES = createOrAppend(SITES, 'Redondo')

    FILTER_NON_WORKDAYS = True  # only consider diving on weekends and holidays
    FILTER_DAYLIGHT = True  # only consider slacks that occur during daylight hours

    PRINT_NON_DIVEABLE = True  # print non-diveable days and reason why not diveable

    possibleDiveDays = [  # Specify dates
        # dt(2019, 3, 31),
        # dt(2019, 3, 16),
        # dt(2019, 3, 3)
    ]
    # ----------------------------------------------------------------------------------------------------------------------


    if not possibleDiveDays:
        if FILTER_NON_WORKDAYS:
            possibleDiveDays = getNonWorkDays(DAYS_IN_FUTURE, START)
        else:
            possibleDiveDays = getAllDays(DAYS_IN_FUTURE, START)

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    for i in range(len(data['sites'])):
        siteData = data['sites'][i]
        if SITES and siteData['name'] not in SITES:
            continue
        station = getStation(data['stations'], siteData['data'])

        m = intp.MobilegeographicsInterpreter(station['url'])
        m2 = intp.NoaaInterpreter(station['url_noaa'])

        print('{} - {} - {}'.format(siteData['name'], siteData['data'], station['coords']))
        print(m.getDayUrl(m.baseUrl, possibleDiveDays[0]))
        print(m2.getDayUrl(m2.baseUrl, possibleDiveDays[0]))

        for day in possibleDiveDays:
            slacks = m.getSlacks(day, FILTER_DAYLIGHT)
            canDive = printDiveDay(slacks, siteData, PRINT_NON_DIVEABLE, "Mobile Geographics")

            slacks = m2.getSlacks(day, FILTER_DAYLIGHT)
            canDive |= printDiveDay(slacks, siteData, PRINT_NON_DIVEABLE, "NOAA")

            if not canDive:
                print('\tNot diveable on {}'.format(dt.strftime(day, intp.DATEFMT)))


if __name__ == '__main__':
    main()
