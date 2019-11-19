'''
This program is used to identify and save the nearest period of slack current where the dives in the specified
.csv file took place.
'''

import dive_plan
import data_query_old as dqo
import interpreter as intp
import data_collect

from datetime import datetime as dt
from datetime import timedelta as td
import json, csv

# For the site with the given data and the given mobilegeographics current url, returns the
# Slack object with corrected time closest to the given meetup time.
def getSlackForDive(meetTime, siteData, url):
    m = intp.MobilegeographicsInterpreter(url)
    slacks = m.getSlacks(meetTime, night=True)

    estMeetupTimes = {}  # estimated meetup time for the slack -> slack
    for slack in slacks:
        times = dive_plan.getEntryTimes(slack, siteData)
        if not times:
            continue
        estMeetupTimes[times[1] - td(minutes=45)] = slack  # takes ~45min to meet and gear up
    # find the estMeetupTime closest to the actual meetup time. This gives the slack the dive was planned for.
    minDelta, slackDove = td(hours=99999).total_seconds(), None
    for estTime, slack in estMeetupTimes.items():
        diff = abs((meetTime - estTime).total_seconds())
        if diff < minDelta:
            minDelta, slackDove = diff, slack
    return slackDove

def main():
    inputFile = 'dive_meetup_data_old_format.csv'
    outputFile = inputFile.replace(".csv", "") + "_with_slacks.csv"
    PRINT_LOCATION_CLASSIFICATION = False

    print('Extracting dives from data file', inputFile)
    dives, slacks = dqo.getDives(inputFile)

    if slacks:
        print('Slacks already present in file {}, no need to run this program. Exiting now.')
        exit(0)

    print('Classifying dive sites')
    results = dqo.refineDives(dives)

    # Print how the dives were classified into locations
    if PRINT_LOCATION_CLASSIFICATION:
        for site, vals in results.items():
            print(site)
            for dive in vals:
                print('\t', dive)

    print('Identifying the nearest period of slack current for each dive')
    data = json.loads(open(data_collect.absName('dive_sites.json')).read())
    for site, sitedives in results.items():
        siteData = dqo.getSiteData(None, site, data)  # go through all sites
        if siteData == None:
            continue

        # for each dive at this location, find the slack that was dove
        station = dive_plan.getStation(data['stations'], siteData['data'])
        print('{} - {}\n{} - {}'.format(siteData['name'], siteData['data'], station['url'], station['coords']))
        for dive in sitedives:
            dive.slack = getSlackForDive(dive.date, siteData, station['url'])
            print('\t', dive)
            print('\t\t', dive.slack)

    print('Writing slacks to file', outputFile)
    with open(data_collect.absName(outputFile), 'w', encoding='utf-8', newline='\n') as f:
        w = csv.writer(f, delimiter=',')
        for dive in dives:
            w.writerow([dt.strftime(dive.date, dqo.MEETUP_TIME_FORMAT), dive.title, dive.location, dive.address, dive.descr, dive.url, dive.slack])
    print('Done writing to file', data_collect.absName(outputFile))

if __name__ == "__main__":
    main()
