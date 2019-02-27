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
                print('\tWARNING: entry time of {} is {} sunrise at {}'.format(intp.dateString(entryTime),
                    warning, intp.dateString(s.sunriseTime)))

        print('\tDiveable: ' + str(s))
        print('\t\tMinCurrentTime = {}, Duration = {}, SurfaceSwim = {}'
                .format(intp.dateString(minCurrentTime), site['dive_duration'], site['surface_swim_time']))
        print('\t\tEntry Time: ' + intp.dateString(entryTime))  # Time to get in the water.
        print('\t\tMarker Buoy Entrytime (60min dive, no surface swim):', intp.dateString(markerBuoyEntryTime))
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

        m = intp.MobilegeographicsInterpreter(station['url'])
        m2 = intp.NoaaInterpreter(station['url_noaa'])

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
