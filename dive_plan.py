'''
This program is used to identify if days in the future (or past) are considered diveable for a subset of dive sites
specified by dive_sites.json
'''

import data_collect
import interpreter as intp
import interpreter_tides as intp_tides
from interpreter_common import DiveWindow
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
    print('Error, no matching station found for name {}'.format(name))
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


def getDiveDays(futureDays: int, start=dt.now(), include_workdays: bool = True,
                include_fridays: bool = False) -> list[dt]:
    """
    Returns list of days to consider for diving.

    Args:
        futureDays: Number of days in the future to consider
        start: Start date
        include_workdays: If True, include all days
        include_fridays: If True and include_workdays is False, also include Fridays
                        (useful for night dives since the next day is Saturday)
    """
    if include_workdays:
        return getAllDays(futureDays, start)

    # Get non-work days (weekends + holidays)
    start = dt(start.year, start.month, start.day)
    end = start + td(days=futureDays)

    cal = USFederalHolidayCalendar()
    holidays = cal.holidays(start=start, end=end).to_pydatetime()

    # Weekdays to exclude: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4
    # If include_fridays, only exclude Mon-Thu
    workdays_to_exclude = {0, 1, 2, 3} if include_fridays else {0, 1, 2, 3, 4}

    delta = td(days=1)
    d = start
    diveDays = []
    while d <= end:
        if d.weekday() not in workdays_to_exclude:
            diveDays.append(d)
        elif d in holidays:
            diveDays.append(d)
        d += delta
    return diveDays


# Returns [mincurrenttime, clubentrytime, myentrytime] for the given dive window at the given site
# mincurrenttime = time of slack current / high/low tide, clubentrytime = 30min before mincurrenttime,
# myentrytime = mincurrenttime - surfaceswimtime - expecteddivetime/2
# Returns None if an expected json data point is not found
def getEntryTimes(s: DiveWindow, site: dict) -> (dt, dt, dt, dt):
    return intp._getEntryTimes(s, site)


# Prints entry time for a DiveWindow at the given site (delegates to the DiveWindow subclass)
def printDive(s: DiveWindow, site: dict, titleMessage: str) -> None:
    s.printDive(site, titleMessage, Color)


# Returns true if the given dive window is diveable within the parameters of the given site.
# Also returns description of reasoning the decision was made.
def isDiveable(s: DiveWindow, site: dict, ignoreMaxSpeed: bool) -> (bool, str):
    return s.isDiveable(site, ignoreMaxSpeed)


# Checks the given list of DiveWindows if a dive is possible. If so, prints information about the dive.
def printDiveDay(windows: list[DiveWindow], site: dict, printAll: bool, ignoreMaxSpeed: bool, title: str) -> bool:
    printed = False
    for s in windows:
        # Current-specific sanity checks
        if isinstance(s, intp.Slack):
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
    parser.add_argument('-t', '--time-filter', choices=['day', 'night', 'early_night', 'all'], default='day', dest='TIME_FILTER',
                        help='Filter slacks by time of day: day (sunrise to sunset), night (sunset to sunrise), early_night (45min after sunset to 11pm), or all')

    parser.add_argument('-s', '--ignorespeed', action='store_true', default=False, dest='IGNORE_MAX_SPEED',
                        help='Ignore the max current speeds in dive_sites.json')

    parser.add_argument('-w', '--includeworkdays', action='store_true', default=False, dest='INCLUDE_WORKDAYS',
                        help='Consider dives on any day, otherwise only considers diving on weekends and holidays')

    parser.add_argument('-i', '--ignorenondiveable', action='store_true', default=False, dest='IGNORE_NON_DIVEABLE',
                        help='Only print diveable slacks, otherwise non-diveable slack information is printed')

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
        # SITES = append(SITES, 'Browning Pass')
        # SITES = append(SITES, 'Weynton Pass')
        # SITES = append(SITES, 'Plumper Pass')
        # SITES = append(SITES, 'Kelsey Bay')
        # SITES = append(SITES, 'Surge Narrows')
        # SITES = append(SITES, 'Seymour Narrows')
        # SITES = append(SITES, 'Row and be Dammed')
        # SITES = append(SITES, 'Whiskey Point')
        # SITES = append(SITES, 'Argonaut Wharf')
        # SITES = append(SITES, 'Gabriola Pass')
        # SITES = append(SITES, 'Dodd Narrows')
        # SITES = append(SITES, 'Active Pass')
        # SITES = append(SITES, 'Boat Pass')
        # SITES = append(SITES, 'Ten Mile Point')
        # SITES = append(SITES, 'Ten Mile Point Discovery')
        # SITES = append(SITES, 'Sechelt Rapids')
        # SITES = append(SITES, 'Ogden Breakwater')
        # SITES = append(SITES, 'First Narrows Vancouver')
        # SITES = append(SITES, 'Second Narrows Vancouver')

        # SITES = append(SITES, 'Sekiu')
        # SITES = append(SITES, 'Third Beach Pinnacle')
        # SITES = append(SITES, 'Hoko Reef')
        # SITES = append(SITES, 'Salt Creek NOAA')
        # SITES = append(SITES, 'Salt Creek NOAA Shallow')
        # SITES = append(SITES, 'Salt Creek XTide')
        # SITES = append(SITES, 'Ediz Hook')
        # SITES = append(SITES, 'Point Hudson')
        # SITES = append(SITES, 'Spieden Channel')
        # SITES = append(SITES, 'Lime Kiln Discovery')
        # SITES = append(SITES, 'Lime Kiln Haro')
        # SITES = append(SITES, 'Lime Kiln Admiralty')
        # SITES = append(SITES, 'Peavine Pass')
        # SITES = append(SITES, 'Goose Island')
        # SITES = append(SITES, 'Kings Point')
        # SITES = append(SITES, 'Deadman Island')
        # SITES = append(SITES, 'Green Point')
        # SITES = append(SITES, 'Skyline Wall Rosario')
        # SITES = append(SITES, 'Skyline Wall Allan Pass')
        # SITES = append(SITES, 'Skyline Wall')
        # SITES = append(SITES, 'Sares Head')
        # SITES = append(SITES, 'Deception Pass')
        SITES = append(SITES, 'Keystone Jetty')
        # SITES = append(SITES, 'Possession Point')
        # SITES = append(SITES, 'Mukilteo')
        # SITES = append(SITES, 'Hood Canal Bridge')
        # SITES = append(SITES, 'Misery Point')
        # SITES = append(SITES, 'Edmonds Underwater Park')
        # SITES = append(SITES, 'Alki Junkyard')
        # SITES = append(SITES, 'Agate Pass Bridge')
        # SITES = append(SITES, 'Agate Pass Drift')
        # SITES = append(SITES, 'Waterman Wall')
        # SITES = append(SITES, 'Warren Avenue Bridge North')
        # SITES = append(SITES, 'Warren Avenue Bridge South')
        # SITES = append(SITES, 'Saltwater State Park')
        # SITES = append(SITES, 'Sunrise Beach')
        # SITES = append(SITES, 'Day Island Wall')
        # SITES = append(SITES, 'Fox Island Bridge')
        # SITES = append(SITES, 'Fox Island Bridge Hale')
        # SITES = append(SITES, 'Fox Island East Wall')
        # SITES = append(SITES, 'Fox Island East Wall Gibson')
        # SITES = append(SITES, 'Titlow')
        # SITES = append(SITES, 'Hammersley Inlet')
        #
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

    args.START = dt(2026, 3, 13)
    # args.START = dt.now()
    args.DAYS_IN_FUTURE = 2
    args.IGNORE_MAX_SPEED = True
    args.INCLUDE_WORKDAYS = True
    # args.TIME_FILTER = 'all'          # All slacks regardless of time
    # args.TIME_FILTER = 'day'          # Only daytime slacks (sunrise to sunset)
    # args.TIME_FILTER = 'night'        # Only nighttime slacks (sunset to sunrise)
    # args.TIME_FILTER = 'early_night'  # Only early night slacks (45min after sunset to 11pm)
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

    # Get slacks/tide windows for each site and each day and print the data and splash times
    for i in range(len(data['sites'])):
        siteData = data['sites'][i]
        if SITES and siteData['name'] not in SITES:
            continue

        # Determine if this is a tide-based or current-based site
        is_tide_site = 'data_tides' in siteData

        interpreters = []
        if is_tide_site:
            # Tide-based site: look up station in tide_stations
            station = getStation(data['tide_stations'], siteData['data_tides'])
            if not station:
                print(f"Error: No tide station found for site '{siteData['name']}' (data_tides='{siteData['data_tides']}')")
                continue
            print(siteData['name'])

            tide_interp = intp_tides.get_tide_interpreter(station)
            interpreters.append((tide_interp, "Tide"))

        else:
            # Current-based site: look up station in stations (existing behavior)
            station = getStation(data['stations'], siteData['data'])
            if not station:
                print(f"Error: No station found for site '{siteData['name']}'")
                continue
            print(siteData['name'])

            # Dairiki interpreter - works for both US and Canadian stations if configured
            if 'url_dairiki' in station and station['url_dairiki']:
                interpreters.append((intp.DairikiInterpreter(station['url_dairiki'], station), "Dairiki"))

            # Canadian station: add Canada interpreters
            if 'ca_code' in station and station['ca_code']:
                # NOTE: for really good current days, the pdf may have a * for weak current instead of max/turn - then no output is provided!
                interpreters.append((intp.CanadaPDFInterpreter(station['ca_code'], station), "Canada PDF"))
                interpreters.append((intp.CanadaAPIInterpreter('', station), "Canada API"))
            # US station: add XTide-based interpreter (only if not a Canadian station)
            elif 'xtide_name' in station and station['xtide_name']:
                interpreters.append((intp.XTideDockerInterpreter(station['name'], station), "XTide Docker"))
            elif 'url_xtide_a' in station and station['url_xtide_a']:
                interpreters.append((intp.TBoneSCInterpreter(station['url_xtide_a'], station), "XTide"))

            # NOAA interpreter
            if 'url_noaa_api' in station and station['url_noaa_api']:
                interpreters.append((intp.NoaaAPIInterpreter(station['url_noaa_api'], station), "NOAA"))

        if not interpreters:
            print(f"Error: No interpreters could be configured for station '{station['name']}'")
            continue

        for interpreter, label in interpreters:
            if hasattr(interpreter, 'getDayUrl'):
                url = interpreter.getDayUrl(
                    getattr(interpreter, 'baseUrl', getattr(interpreter, 'base_url', '')),
                    possibleDiveDays[0])
                if url:
                    print(url)

        for day in possibleDiveDays:
            canDive = False
            for interpreter, label in interpreters:
                try:
                    slacks = interpreter.getSlacks(day, args.TIME_FILTER)
                    canDive |= printDiveDay(slacks, siteData, not args.IGNORE_NON_DIVEABLE, args.IGNORE_MAX_SPEED, label)
                except Exception as e:
                    print(f'Error fetching and reading slacks from {label}: ' + repr(e))

            if not canDive:
                print('\tNot diveable on {}'.format(dt.strftime(day, intp.DATEFMT)))

        for interpreter, label in interpreters:
            if hasattr(interpreter, 'numAPICalls') and interpreter.numAPICalls > 0:
                print(f'{label} API calls: {interpreter.numAPICalls}')

if __name__ == '__main__':
    main()
