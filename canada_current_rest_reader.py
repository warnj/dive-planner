from datetime import datetime as dt
from datetime import timedelta as td

import requests
import json

# Format date into YYYY-MM-DD format
# area_id = '5cebf1e03d0f4a073c4bbd3f'
# startTime = start.strftime("%Y-%m-%d")
# endTime = end.strftime("%Y-%m-%d")
# urlFinal = f"https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/{area_id}/data?time-series-code=wlp&from={startTime}T00:00:00Z&to={endTime}T00:30:00Z"

# get the station id from: https://api-iwls.dfo-mpo.gc.ca/api/v1/stations
# follow directions here: https://charts.gc.ca/help-aide/announcements-annonces/2021/2021-11-18-eng.html
# other info here: https://tides.gc.ca/en/web-services-offered-canadian-hydrographic-service

def getDayUrl(baseUrl, day):
    start = day.strftime("%Y-%m-%d")
    twoWeeks = (day + td(days=2)).strftime("%Y-%m-%d")
    return baseUrl + '&from={}T00:00:00Z&to={}T00:30:00Z'.format(start, twoWeeks)

def getJsonResponse(url):
    r = requests.get(url)
    if r.status_code != 200:
        raise Exception('Canada currents API is down')
    print(json.dumps(r.json(), indent=2))
    return r

# urlFmt = 'https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/{}/data?time-series-code={}&from={}T00:00:00Z&to={}T00:30:00Z'
urlFmt = 'https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/{}/data?time-series-code={}'

# start = dt.now() + td(days=3)
# end = dt.now() + td(days=4)
# strs = ['wcp-slack', 'wcdp-extrema', 'wcdp', 'wcsp-extrema', 'wcsp']
# strs = ['wcdp-extrema', 'wcsp-extrema']
# for s in strs:


urlDay = getDayUrl(urlFmt, dt.now() + td(days=3))

print(getJsonResponse(urlDay.format('63aef12e84e5432cd3b6db8d', 'wcdp-extrema')))

print(getJsonResponse(urlDay.format('63aef12e84e5432cd3b6db8d', 'wcsp-extrema')))




