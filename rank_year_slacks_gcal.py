'''
This program is used to rank the longest and shortest slack times for a current
station over a given time interval. Longer slacks are present when the max
current speed on the exchange before and after slack is smaller.

Posts the resulting top slacks for the year as events in Google Calendar

https://developers.google.com/calendar/api/quickstart/python
https://developers.google.com/calendar/api/guides/create-events#python
https://console.cloud.google.com/apis/credentials?project=sonorous-reach-118520
'''

import dive_plan, data_collect
import interpreter as intp
import json
from must_do_dives import getSite
from datetime import datetime as dt
from datetime import timedelta as td
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GCAL_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

# returns list of slacks in given list that are divable for the given site, mostly taken from must_do_dives.py
def getDiveableSlacks(slacks, site):
    diveableSlacks = []
    for s in slacks:
        if s.ebbSpeed > 0.0:
            print('WARNING - EBB SPEED IS POSITIVE')
        if s.floodSpeed < 0.0:
            print('WARNING - FLOOD SPEED IS NEGATIVE')

        # Check if diveable or not
        diveable, info = dive_plan.isDiveable(s, site, False)
        if diveable:
            diveableSlacks.append(s)
    return diveableSlacks

# returns the string representation of the number as an ordinal (1st, 2nd, 3rd, 4th, 5th, etc)
def ordinal(n: int):
    if 11 <= (n % 100) <= 13:
        suffix = 'th'
    else:
        suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
    return str(n) + suffix

# creates events for the given slacks in Google Calendar
# NOTE: manual deletion of old token.json files is required
def postToGCal(orderedSlacks, siteName, source):
    # If modifying these scopes, delete the file token.json.
    SCOPES = ['https://www.googleapis.com/auth/calendar.events']
    calId = 'f0eb53c40a265c4da118dd813487433110fc0ff7bbc3f1bf8d66c693506bd823@group.calendar.google.com'

    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        print('token exists!')
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=56584)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('calendar', 'v3', credentials=creds)
        for i in range(len(orderedSlacks)):
            start = dt.strftime(orderedSlacks[i].time, GCAL_DATETIME_FORMAT)
            end = dt.strftime(orderedSlacks[i].time + td(hours=2), GCAL_DATETIME_FORMAT)
            title = '{} best {} slack'.format(ordinal(i+1), siteName)
            print('Creating event {} starting at {} and ending at {}'.format(title, start, end))
            event = {
                'summary': title,
                'location': siteName,
                'description': str(orderedSlacks[i]) + '  (source is {})'.format(source),
                'start': {
                    'dateTime': start,
                    'timeZone': 'America/Los_Angeles',
                },
                'end': {
                    'dateTime': end,
                    'timeZone': 'America/Los_Angeles',
                },
            }
            event = service.events().insert(calendarId=calId, body=event).execute()
            print('Event created: %s' % (event.get('htmlLink')))

    except HttpError as error:
        print('An error occurred: %s' % error)

def main():
    # SITE = 'Whiskey Point'
    SITE = 'Deception Pass'

    NOAA = True
    # NOAA = False

    # NIGHT = True
    NIGHT = False

    data = json.loads(open(data_collect.absName('dive_sites.json')).read())
    siteJson = getSite(data['sites'], SITE)

    station = dive_plan.getStation(data['stations'], siteJson['data'])
    if NOAA:
        if 'british columbia' in station['name'].lower():
            print('using Canadian Currents API')
            m = intp.CanadaAPIInterpreter("", station)
        else:
            m = intp.NoaaAPIInterpreter(station['url_noaa_api'], station)
    else:
        m = intp.TBoneSCInterpreter(station['url_xtide_a'], station['name'])

    slacks = []
    days = dive_plan.getAllDays(365, dt(2026, 1, 1))
    # days = dive_plan.getAllDays(230)
    for day in days:
        slacks.extend(m.getSlacks(day, night=NIGHT))

    # filter out the non-diveable slacks
    diveableSlacks = getDiveableSlacks(slacks, siteJson)

    # sort by the sum of the max current speeds from weakest to strongest
    diveableSlacks.sort(key=lambda x: abs(x.ebbSpeed)+abs(x.floodSpeed))

    for s in diveableSlacks:
        print('{}\tSpeed sum = {:0.1f}'.format(s, abs(s.ebbSpeed)+abs(s.floodSpeed)))

    # create gcal events for the top dives over this time period
    postToGCal(diveableSlacks[:30], SITE, 'NOAA' if NOAA else 'XTide')


if __name__ == '__main__':
    main()
