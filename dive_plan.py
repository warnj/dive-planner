'''
This program is used to identify if days in the future (or past) are considered diveable for a subset of dive sites
specified by dive_sites.json
'''

import data_collect
import interpreter as intp
import argparse

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


def printInfo(shouldPrint: bool, str: str) -> None:
    if shouldPrint:
        print(str)


def append(sites: list, name: str) -> list:
    if sites:
        sites.append(name)
        return sites
    else:
        return [name]


def getStation(stations: list[dict[str, str]], name: str) -> dict[str, str]:
    for station in stations:
        if station['name'] == name:
            return station
    print('Error, no matching current station found for url {}'.format(name))
    return None


# returns a list of datetime days that are weekends and holiday that occur between start (today by default) and
# futureDays in the future
def getNonWorkDays(futureDays: int, start=dt.now()) -> list[dt]:
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
def getAllDays(futureDays: int, start=dt.now()) -> list[dt]:
    start = dt(start.year, start.month, start.day)
    end = start + td(days=futureDays)
    delta = td(days=1)
    d = start
    days = []
    while d <= end:
        days.append(d)
        d += delta
    return days


# Returns [mincurrenttime, clubentrytime, myentrytime] for the given slack at the given site
# mincurrenttime = time of slack current, clubentrytime = 30min before mincurrenttime,
# myentrytime = mincurrenttime - surfaceswimtime - expecteddivetime/2
# Returns None if an expected json data point is not found
def getEntryTimes(s: intp.Slack, site: dict) -> (dt, dt, dt, dt):
    try:
        if s.slackBeforeEbb:
            delta = td(minutes=site['slack_before_ebb'])
        else:
            delta = td(minutes=site['slack_before_flood'])
        minCurrentTime = s.time + delta
        entryTime = minCurrentTime - td(minutes=site['dive_duration'] / 2) - td(minutes=site['surface_swim_time'])
        exitTime = entryTime + 2 * td(minutes=site['surface_swim_time']) + td(minutes=site['dive_duration'])
        clubEntryTime = minCurrentTime - td(minutes=30)
        return minCurrentTime, clubEntryTime, entryTime, exitTime
    except KeyError:
        return None


# Prints entry time for Slack s at the given site
def printDive(s: intp.Slack, site: dict, titleMessage: str) -> None:
    times = getEntryTimes(s, site)
    if not times:
        print('ERROR: a json key was expected that was not found')
    else:
        minCurrentTime, clubEntryTime, entryTime, exitTime = times
        if s.sunriseTime:
            warning = ''
            if entryTime < s.sunriseTime:
                warning = 'BEFORE'
            elif entryTime - td(minutes=30) < s.sunriseTime:
                warning = 'near'
            if warning:
                print('\t\tWARNING: entry time of {} is {} sunrise at {}'.format(intp.dateStr(entryTime),
                    warning, intp.dateStr(s.sunriseTime)))

        print('\t\t{}: {}'.format(titleMessage, s))
        print('\t\t\tMinCurrentTime = {}, Duration = {}, SurfaceSwim = {}'
              .format(intp.dateStr(minCurrentTime), site['dive_duration'], site['surface_swim_time']))
        print('\t\t\t{}Entry Time: {}{}\t(Exit time: {})'  # Time to get in the water.
              .format(Color.UNDERLINE, intp.dateStr(entryTime), Color.END, dt.strftime(exitTime, intp.TIMEFMT)))
        print('\t\t\t{}'.format(s.logString()))
        print('\t\t\t{}'.format(s.logStringWithSpeed()))
        print('\t\t\tSpeed sum = {:.1f}'.format(s.speedSum()))
        # print('\t\t\tClub Entry Time (60min dive, no surface swim):', intp.dateStr(clubEntryTime))
        # moonAction = "waxing" if s.moonPhase <= 14 else "waning"
        # print('\t\t\tMoon phase: day {} of 28 day lunar month, {:.2f}% {}'
        #       .format(s.moonPhase, s.moonPhase % 14 / 14, moonAction))


# Returns true if the given slack is diveable within the parameters of the given site. Also returns description of
# reasoning the decision was made.
def isDiveable(s: intp.Slack, site: dict, ignoreMaxSpeed: bool) -> (bool, str):
    if s.slackBeforeEbb and not site['diveable_before_ebb']:
        return False, 'Not diveable before ebb'
    elif not s.slackBeforeEbb and not site['diveable_before_flood']:
        return False, 'Not diveable before flood'
    elif site['diveable_off_slack'] and \
            (s.floodSpeed < site['max_diveable_flood'] or abs(s.ebbSpeed) < site['max_diveable_ebb']):
        return True, 'Diveable off slack'
    elif not ignoreMaxSpeed and (s.floodSpeed > site['max_flood'] or abs(s.ebbSpeed) > abs(site['max_ebb']) or
                                 s.floodSpeed + abs(s.ebbSpeed) > site['max_total_speed']):
        return False, 'Current too strong'
    else:
        return True, 'Diveable'


# Checks the given list of Slacks if a dive is possible. If so, prints information about the dive.
def printDiveDay(slacks: list[intp.Slack], site: str, printAll: bool, ignoreMaxSpeed: bool, title: str) -> bool:
    printed = False
    for s in slacks:
        if s.ebbSpeed > 0.0:
            print('WARNING - EBB SPEED IS POSITIVE')
        if s.floodSpeed < 0.0:
            print('WARNING - FLOOD SPEED IS NEGATIVE')
        # Check if diveable or not
        diveable, info = isDiveable(s, site, ignoreMaxSpeed)
        if not printed and (diveable or printAll):
            print('\t' + title)
            printed = True
        if diveable:
            printDive(s, site, info)
        else:
            printInfo(printAll, '\t\t{}:\t{}'.format(info, s))
    return printed


# returns true if given string site is a dive site name in the given json dive site data
def isDiveSite(site: str, sitesData: list) -> bool:
    for i in range(len(sitesData)):
        if site == sitesData[i]['name']:
            return True
    return False


# returns comma-separated list of dive site name in the given json dive site data
def listDiveSites(sitesData: list[dict]) -> str:
    r = ""
    for i in range(len(sitesData)):
        r += sitesData[i]['name']
        if i != len(sitesData) - 1:
            r += ', '
    return r


def main():
    # Dive site and current station data file
    data = json.loads(open(data_collect.absName('dive_sites.json')).read())

    # Command-line Args
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--night', action='store_true', default=False, dest='INCLUDE_NIGHT',
                        help='Consider slacks that occur during during the night')

    parser.add_argument('-s', '--ignorespeed', action='store_true', default=False, dest='IGNORE_MAX_SPEED',
                        help='Ignore the max current speeds in dive_sites.json')

    parser.add_argument('-w', '--includeworkdays', action='store_true', default=False, dest='INCLUDE_WORKDAYS',
                        help='Consider dives on any day, otherwise only considers diving on weekends and holidays')

    parser.add_argument('-i', '--ignorenondiveable', action='store_true', default=False, dest='IGNORE_NON_DIVEABLE',
                        help='Only print diveable slacks, otherwise non-diveable slack information is printed')

    parser.add_argument("--sort", action='store_true', default=False, dest="SORT",
                        help="Sort diveable days by from most optimal slack to least optimal slack")

    parser.add_argument("-f", "--futuredays", dest="DAYS_IN_FUTURE", default=7, type=int,
                        help="Number of days after start date to consider diving")

    parser.add_argument("-d", "--start-date", dest="START", default=dt.now(),
                        type=lambda d: dt.strptime(d, '%Y-%m-%d').date(),
                        help="Start date to begin considering diveable conditions in the format yyyy-mm-dd")

    parser.add_argument("--sites", default='', type=str, help="Comma-delimited list of dive sites from dive_sites.json "
                                                              "({})".format(listDiveSites(data['sites'])))
    args = parser.parse_args()

    # Parse site list - allow indeterminate whitespace and capitals
    SITES = []
    for item in args.sites.split(','):
        if not item:
            continue
        words = item.split()
        n = len(words)
        if n == 1:
            SITES.append(words[0].capitalize())
        elif n > 1:
            site = words[0].capitalize()
            for i in range(1, n):
                site += ' ' + words[i].capitalize()
            SITES.append(site)

    # ---------------------------------- MANUALLY CONFIGURABLE PARAMETERS ---------------------------------------------
    if not SITES:
        SITES = []  # Consider all sites
        # SITES = append(SITES, 'Nakwakto')
        # SITES = append(SITES, 'Weynton Pass')
        # SITES = append(SITES, 'Plumper Pass')
        # SITES = append(SITES, 'Seymour Narrows')
        # SITES = append(SITES, 'Whiskey Point')
        # SITES = append(SITES, 'Argonaut Wharf')
        # SITES = append(SITES, 'Gabriola Pass')
        # SITES = append(SITES, 'Dodd Narrows')
        # SITES = append(SITES, 'Active Pass')
        # SITES = append(SITES, 'Boat Pass')
        # SITES = append(SITES, 'Ten Mile Point')
        # SITES = append(SITES, 'Sechelt Rapids')

        # SITES = append(SITES, 'Sekiu')
        # SITES = append(SITES, 'Salt Creek')
        # SITES = append(SITES, 'Point Hudson')
        # SITES = append(SITES, 'Spieden Channel')
        # SITES = append(SITES, 'Lime Kiln Discovery')
        # SITES = append(SITES, 'Lime Kiln Haro')
        # SITES = append(SITES, 'Lime Kiln Admiralty')
        # SITES = append(SITES, 'Goose Island')
        # SITES = append(SITES, 'Green Point')
        # SITES = append(SITES, 'Skyline Wall Rosario')
        # SITES = append(SITES, 'Skyline Wall Allan Pass')
        # SITES = append(SITES, 'Skyline Wall')
        # SITES = append(SITES, 'Sares Head')
        SITES = append(SITES, 'Deception Pass')
        # SITES = append(SITES, 'Keystone Jetty')
        # SITES = append(SITES, 'Possession Point')
        # SITES = append(SITES, 'Mukilteo')
        # SITES = append(SITES, 'Hood Canal Bridge')
        # SITES = append(SITES, 'Misery Point')
        # SITES = append(SITES, 'Edmonds Underwater Park')
        # SITES = append(SITES, 'Alki Junkyard')
        # SITES = append(SITES, 'Saltwater State Park')
        # SITES = append(SITES, 'Sunrise Beach')
        # SITES = append(SITES, 'Day Island Wall')
        # SITES = append(SITES, 'Fox Island Bridge')
        # SITES = append(SITES, 'Fox Island Bridge Hale')
        # SITES = append(SITES, 'Fox Island East Wall')
        # SITES = append(SITES, 'Fox Island East Wall Gibson')
        # SITES = append(SITES, 'Titlow')
        # SITES = append(SITES, 'Waterman Wall')
        # SITES = append(SITES, 'Warren Avenue Bridge North')
        # SITES = append(SITES, 'Warren Avenue Bridge South')
        # SITES = append(SITES, 'Agate Pass')
        # SITES = append(SITES, 'Hammersley Inlet')

        # SITES = append(SITES, 'Hawea Point')
        # SITES = append(SITES, 'Red Hill')

    possibleDiveDays = [  # Specify dates
        # dt(2012, 2, 3),
        # dt(2013, 1, 22),
        # dt(2015, 2, 28),
        # dt(2020, 2, 5),
        # dt(2021, 12, 19),
        # dt(2022, 11, 13),
    ]

    args.START = dt(2024,6,1)
    # args.START = dt.now()
    args.DAYS_IN_FUTURE = 1
    # args.IGNORE_MAX_SPEED = True
    args.INCLUDE_WORKDAYS = True
    # args.INCLUDE_NIGHT = True
    # args.SORT = True
    # ------------------------------------------------------------------------------------------------------------------

    # Create list of dates based on given start date
    if not possibleDiveDays:
        if args.INCLUDE_WORKDAYS:
            possibleDiveDays = getAllDays(args.DAYS_IN_FUTURE, args.START)
        else:
            possibleDiveDays = getNonWorkDays(args.DAYS_IN_FUTURE, args.START)

    # Parameter validation
    if not possibleDiveDays:
        print('No dive days possible with current params. Is start date a workday and includeworkdays flag is not set?')
        parser.print_help()
        exit(1)
    if not SITES:
        print('No dive sites were specified')
        parser.print_help()
        exit(2)
    for site in SITES:
        if not isDiveSite(site, data['sites']):
            print('{} is not a valid dive site'.format(site))
            parser.print_help()
            exit(3)

    # Get slacks for each site and each day and print the data and splash times
    for i in range(len(data['sites'])):
        siteData = data['sites'][i]
        if SITES and siteData['name'] not in SITES:
            continue
        station = getStation(data['stations'], siteData['data'])

        m = intp.TBoneSCInterpreter(station['url_xtide_a'], station)
        # m = intp.TBoneSCOfflineInterpreter('dummy', station)
        if 'british columbia' in station['name'].lower():
            m2 = intp.CanadaAPIInterpreter("", station)
        else:
            m2 = intp.NoaaInterpreter(station['url_noaa'], station)
        # m2 = intp.NoaaAPIInterpreter(station['url_noaa_new'])

        print('{} - {} - {}'.format(siteData['name'], siteData['data'], station['coords']))
        print(m.getDayUrl(m.baseUrl, possibleDiveDays[0]))
        print(m2.getDayUrl(m2.baseUrl, possibleDiveDays[0]))

        if args.SORT:
            slacks = []
            for day in possibleDiveDays:
                slacks.extend(m.getSlacks(day, args.INCLUDE_NIGHT))
            # sort by the sum of the max current speeds from weakest to strongest
            slacks.sort(key=lambda x: abs(x.ebbSpeed)+abs(x.floodSpeed))
            printDiveDay(slacks, siteData, not args.IGNORE_NON_DIVEABLE, args.IGNORE_MAX_SPEED, "XTide")

            slacks = []
            for day in possibleDiveDays:
                slacks.extend(m2.getSlacks(day, args.INCLUDE_NIGHT))
            slacks.sort(key=lambda x: abs(x.ebbSpeed)+abs(x.floodSpeed))
            printDiveDay(slacks, siteData, not args.IGNORE_NON_DIVEABLE, args.IGNORE_MAX_SPEED, "NOAA / CA")
        else:
            for day in possibleDiveDays:
                canDive = False
                try:
                    slacks = m.getSlacks(day, args.INCLUDE_NIGHT)
                    canDive = printDiveDay(slacks, siteData, not args.IGNORE_NON_DIVEABLE, args.IGNORE_MAX_SPEED, "XTide")
                except Exception as e:
                    print('Error fetching and reading slacks from Xtide: ' + repr(e))

                try:
                    slacks = m2.getSlacks(day, args.INCLUDE_NIGHT)
                    canDive |= printDiveDay(slacks, siteData, not args.IGNORE_NON_DIVEABLE, args.IGNORE_MAX_SPEED, "NOAA / CA")
                except Exception as e:
                    print('Error fetching and reading slacks from NOAA: ' + repr(e))

                if not canDive:
                    print('\tNot diveable on {}'.format(dt.strftime(day, intp.DATEFMT)))

        if 'british columbia' in station['name'].lower():
            print('number of API calls: {}'.format(m2.numAPICalls))

if __name__ == '__main__':
    main()
