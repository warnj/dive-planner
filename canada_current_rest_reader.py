from datetime import datetime as dt
from datetime import timedelta as td
import requests
import json

# get the station id from: https://api-iwls.dfo-mpo.gc.ca/api/v1/stations
# follow directions here: https://charts.gc.ca/help-aide/announcements-annonces/2021/2021-11-18-eng.html
# other info here: https://tides.gc.ca/en/web-services-offered-canadian-hydrographic-service
import data_collect
from interpreter import Slack

def getDayUrl(baseUrl, day):
    start = day.strftime("%Y-%m-%d")
    twoWeeks = (day + td(days=2)).strftime("%Y-%m-%d")  # todo: increase this from 2d
    return baseUrl + '&from={}T00:00:00Z&to={}T00:30:00Z'.format(start, twoWeeks)

def getJsonResponse(url):
    r = requests.get(url)
    if r.status_code != 200:
        raise Exception('Canada currents API is down')
    return r.json()

# compares float directions (use epsilon of 5 since opposite direction is +/- 180)
# def floatEqual(f1, f2):
#     return f1-5 < f2 < f1+5
def floatEqual(float1, float2, threshold=5.0):
    return abs(float1 - float2) <= threshold

TIMEPARSEFMT_CA = '%Y-%m-%dT%H:%M:%SZ'  # example: 2024-03-13T23:29:00Z
def _parseTime(timeStr):
    return dt.strptime(timeStr, TIMEPARSEFMT_CA)

def parseSlacks(station, dirResponse, speedResponse):
    # print('len(speedResponse)', len(speedResponse))
    # print('len(dirResponse)', len(dirResponse))
    if len(dirResponse) != len(speedResponse):
        return None
    n = len(speedResponse)
    slacks = []
    for i in range(n):
        if speedResponse[i]['value'] == 0.0:
            s = Slack()
            if i+1 < n:
                dirLater = dirResponse[i+1]['value']
                if not (floatEqual(dirLater, station['ebb_dir']) or floatEqual(dirLater, station['flood_dir'])):
                    print('error: direction {} does not match expected flood {} or ebb {} direction'.format(dirLater, station['flood_dir'], station['ebb_dir']))
                    return None
                s.slackBeforeEbb = dirLater == station['ebb_dir']  # ebb after this slack means it's a SBE
            else:
                dirBefore = dirResponse[i - 1]['value']
                if not (floatEqual(dirBefore, station['ebb_dir']) or floatEqual(dirBefore, station['flood_dir'])):
                    print('error: direction {} does not match expected flood {} or ebb {} direction'.format(dirBefore, station['flood_dir'], station['ebb_dir']))
                    return None
                s.slackBeforeEbb = dirBefore == station['flood_dir']  # flood before this slack means it's a SBE

            # can't get the current before or after slack in this case so ignore these very early or late slacks
            # todo: support a null value before or after to show all slacks in a day
            if i-1 >= 0 and i+1 < n:
                if s.slackBeforeEbb:
                    s.floodSpeed = speedResponse[i-1]['value']
                    s.maxFloodTime = _parseTime(speedResponse[i-1]['eventDate'])
                    s.ebbSpeed = -speedResponse[i+1]['value']
                    s.maxEbbTime = _parseTime(speedResponse[i+1]['eventDate'])
                else:
                    s.ebbSpeed = -speedResponse[i-1]['value']
                    s.maxEbbTime = _parseTime(speedResponse[i-1]['eventDate'])
                    s.floodSpeed = speedResponse[i+1]['value']
                    s.maxFloodTime = _parseTime(speedResponse[i+1]['eventDate'])
                s.time = _parseTime(speedResponse[i]['eventDate'])
                slacks.append(s)
    return slacks

def checkCurrents(station):
    urlFmt = 'https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/{}/data?time-series-code={}'
    urlDay = getDayUrl(urlFmt, dt.now() + td(days=3))

    dir = getJsonResponse(urlDay.format('63aef12e84e5432cd3b6db8d', 'wcdp-extrema'))
    speed = getJsonResponse(urlDay.format('63aef12e84e5432cd3b6db8d', 'wcsp-extrema'))
    # print(json.dumps(dir, indent=2))
    # print(json.dumps(speed, indent=2))
    slacks = parseSlacks(station, dir, speed)
    for s in slacks:
        print(s)

siteName = 'Gabriola Pass'

data = json.loads(open(data_collect.absName('dive_sites_canada.json')).read())
for station in data['stations']:
    if station['name'] == siteName:
        checkCurrents(station)
