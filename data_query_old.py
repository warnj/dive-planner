'''
This program is used to identify current trends and metrics from past Marker Buoy club dives as saved
in dive_meetup_data_old_format_with_slacks.csv.
'''

from dive_plan import *
from data_collect import absName
from datetime import datetime as dt
import json, csv
import numpy as np

MEETUP_TIME_FORMAT = '%a, %b %d, %Y, %I:%M %p'
SITE_MAP = {  # dive site -> tokens that the listing must contain
    'Day Island Wall': ['day island'],
    'Skyline Wall': ['skyline'],
    'Keystone Jetty': ['keystone'],
    'Deception Pass': ['deception pass'],
    'Fox Island Bridge': ['fox island bridge'],
    'Fox Island East Wall': ['fox island', 'east'],
    'Fox Island West Wall': ['fox island', 'west'],
    'Sunrise Beach': ['sunrise', 'beach'],
    'Three Tree North': ['three tree'],
    'Alki Pipeline': ['alki', 'pipeline'],  # this is effectively the same as junkyard
    'Alki Junkyard': ['alki', 'junk', 'yard'],
    'Saltwater State Park': ['salt', 'water', 'state', 'park'],
    'Edmonds Underwater Park': ['edmonds'],
    'Mukilteo': ['mukilteo'],  # require this to be in the location/decr and address
    'Redondo': ['redondo'],
    'Titlow': ['titlow'],
    'Possession Point': ['possession point'],
    'Salt Creek': ['salt creek'],
    'Sund Rock': ['sund', 'rock'],
}
# tags that indicate non-dive activities to ignore
SKIP = ['friends of', 'club meet', 'sunset hill', 'lujac', 'boat', 'charter', 'long island', 'davidson rock', 'forum']

class Dive:
    # website data
    date = None  # dt object
    title = ""
    descr = ""
    location = ""
    address = ""
    url = ""

    # interpreted data
    splash = ""  # if able to get splash time, put it here
    site = ""
    slack = None  # Slack object

    def __str__(self):
        return '{}  {}  {}  {}'.format(dt.strftime(self.date, MEETUP_TIME_FORMAT), self.title, self.location, self.url)

    def __repr__(self):
        return self.__str__()

# returns list of Dive objects parsed from given csv file and if the dives contains Slacks from the file or not
def getDives(file):
    dives = []
    slacks = False
    with open(absName(file), 'r', encoding='utf-8', newline='\n') as f:
        reader = csv.reader(f, delimiter=',')
        for line in reader:
            dive = Dive()
            assert len(line) >= 6
            assert len(line) <= 7
            if len(line) == 6 or len(line) == 7 and not line[6]:
                dive.date, dive.title, dive.location, dive.address, dive.descr, dive.url = \
                    dt.strptime(line[0], MEETUP_TIME_FORMAT), line[1], line[2], line[3], line[4], line[5]
            else:
                dive.date, dive.title, dive.location, dive.address, dive.descr, dive.url, dive.slack = \
                    dt.strptime(line[0], MEETUP_TIME_FORMAT), line[1], line[2], line[3], line[4], line[5], parseSlack(line[6])
                slacks = True
            dives.append(dive)
    return dives, slacks

def parseSlack(s):
    slack = Slack()
    arrow = " -> "
    n = len(arrow)
    first = s.index(arrow)
    last = s.rindex(arrow)

    a = float(s[:first])
    date = s[first+n:last]
    b = float(s[last+n:])

    slack.time = dt.strptime(date, TIMEPRINTFMT)
    slack.slackBeforeEbb = b <= 0
    if slack.slackBeforeEbb:
        slack.floodSpeed = a
        slack.ebbSpeed = b
    else:
        slack.floodSpeed = b
        slack.ebbSpeed = a
    return slack

def createOrAppend(str):
    global SITES
    if SITES:
        SITES.add(str)
    else:
        SITES = {str}

def appendMap(map, key, value):
    if key in map:
        map[key].append(value)
    else:
        map[key] = [value]

# returns the json data for the given site from the given json data
def getSiteData(SITES, siteName, data):
    if SITES and siteName not in SITES:
        return None
    # find corresponding site in dive_sites.json
    for location in data["sites"]:
        if location['name'].lower() == siteName.lower():
            return location
    print('ERROR: no location in dive_sites.json matched site:', siteName)
    return None

# Compares given str with the SITE_MAP tags for each site. Returns the name of the site if one is found
# and None if the given str doesn't match all the tags for any site.
def compareLocationTags(str, dive):
    for site, tags in SITE_MAP.items():
        foundAllTags = True
        for tag in tags:
            if tag not in str:
                foundAllTags = False
                break
        if foundAllTags:
            return site
    return None

# determines dive site for each of the given dives from SITE_MAP. Returns map from site -> [dives]
# TODO: potential improvement here by incorporating address and description to get dive site
def refineDives(dives):
    results = {}
    for dive in dives:
        skip = False
        for str in SKIP:
            if str in dive.title or str in dive.location:
                appendMap(results, "Skip", dive)
                skip = True
                break
        if not skip:
            site = compareLocationTags(dive.location, dive)
            if not site:
                site = compareLocationTags(dive.title, dive)
            # if not site:
            #     site = compareLocationTags(dive.descr, dive)
            if not site:
                appendMap(results, "Unclassified", dive)
            else:
                appendMap(results, site, dive)
    return results

# Prints statistics on the slacks in the given list of dives
def printSlackMetrics(dives):
    beforeFloodFloodSpeeds, beforeFloodEbbSpeeds = [], []
    beforeEbbFloodSpeeds, beforeEbbEbbSpeeds = [], []
    speedSums = []
    for dive in dives:
        s = dive.slack
        speedSums.append(abs(s.ebbSpeed) + abs(s.floodSpeed))
        if s.slackBeforeEbb:
            beforeEbbFloodSpeeds.append(s.floodSpeed)
            beforeEbbEbbSpeeds.append(s.ebbSpeed)
        else:
            beforeFloodFloodSpeeds.append(s.floodSpeed)
            beforeFloodEbbSpeeds.append(s.ebbSpeed)
    beforeFloodFloodSpeeds = np.array(beforeFloodFloodSpeeds)
    beforeFloodEbbSpeeds = np.array(beforeFloodEbbSpeeds)
    beforeEbbFloodSpeeds = np.array(beforeEbbFloodSpeeds)
    beforeEbbEbbSpeeds = np.array(beforeEbbEbbSpeeds)
    speedSums = np.array(speedSums)
    assert len(beforeEbbFloodSpeeds) == len(beforeEbbEbbSpeeds)
    assert len(beforeFloodFloodSpeeds) == len(beforeFloodEbbSpeeds)
    assert len(beforeFloodFloodSpeeds) + len(beforeEbbFloodSpeeds) == len(speedSums)
    print("{} dives before Ebb".format(len(beforeEbbFloodSpeeds)))
    if len(beforeEbbFloodSpeeds) > 0:
        print("\t{:.2f} avg Flood speed, {} max Flood speed".format(np.average(beforeEbbFloodSpeeds), np.max(beforeEbbFloodSpeeds)))
        print("\t{:.2f} avg Ebb speed,   {} max Ebb speed".format(np.average(beforeEbbEbbSpeeds), np.min(beforeEbbEbbSpeeds)))
    print("{} dives before Flood".format(len(beforeFloodFloodSpeeds)))
    if len(beforeFloodFloodSpeeds) > 0:
        print("\t{:.2f} avg Ebb speed,   {} max Ebb speed".format(np.average(beforeFloodEbbSpeeds), np.min(beforeFloodEbbSpeeds)))
        print("\t{:.2f} avg Flood speed, {} max Flood speed".format(np.average(beforeFloodFloodSpeeds), np.max(beforeFloodFloodSpeeds)))
    print("{:.2f} avg sum speed, {:.2f} max sum speed".format(np.average(speedSums), np.max(speedSums)))


FILENAME = 'dive_meetup_data_old_format_with_urls_with_slacks.csv'
SITES = None  # show data for all sites
# createOrAppend("Salt Creek")
# createOrAppend("Deception Pass")
# createOrAppend("Skyline Wall")
# createOrAppend("Keystone Jetty")
# createOrAppend("Possession Point")
# createOrAppend("Mukilteo")
# createOrAppend("Edmonds Underwater Park")
# createOrAppend("Three Tree North")
# createOrAppend("Alki Pipeline")
# createOrAppend("Saltwater State Park")
# createOrAppend("Day Island Wall")
# createOrAppend("Sunrise Beach")
# createOrAppend("Fox Island Bridge")
# createOrAppend("Fox Island East Wall")
# createOrAppend("Titlow")


def main():
    PRINT_LOCATION_CLASSIFICATION = False
    PRINT_DIVE_DETAILS = True

    print('Extracting dives from data file', FILENAME)
    dives, slacks = getDives(FILENAME)

    if not slacks:
        print('No slacks in {}, make sure to run data_add_slacks.py first. Exiting.'.format(FILENAME))
        exit(0)

    print('Classifying dive sites')
    results = refineDives(dives)

    # Print how the dives were classified into locations
    if PRINT_LOCATION_CLASSIFICATION:
        for site, vals in results.items():
            print(site)
            for dive in vals:
                print('\t', dive)

    print('Getting slack metrics for each dive site')
    data = json.loads(open(absName('dive_sites.json')).read())
    for site, sitedives in results.items():
        siteData = getSiteData(SITES, site, data)
        if siteData == None:
            continue
        station = getStation(data['stations'], siteData['data'])
        print('{} - {}\n{} - {}'.format(siteData['name'], siteData['data'], station['url'], station['coords']))

        # Print each dive, its corresponding slack, and predicted entry time
        if PRINT_DIVE_DETAILS:
            for dive in sitedives:
                print('\t', dive)
                print('\t\t', dive.slack)
                minCurrentTime, markerBuoyEntryTime, entryTime = getEntryTimes(dive.slack, siteData)
                minCurrentTime = dt.strftime(minCurrentTime, MEETUP_TIME_FORMAT)
                markerBuoyEntryTime = dt.strftime(markerBuoyEntryTime, MEETUP_TIME_FORMAT)
                entryTime = dt.strftime(entryTime, MEETUP_TIME_FORMAT)
                print('\t\tMarkerBuoyEntryTime = {}   MyEntryTime = {}   MinCurrentTime = {}'.format(markerBuoyEntryTime, entryTime, minCurrentTime))

        printSlackMetrics(sitedives)


if __name__ == "__main__":
    main()