'''
Saves 53 years of Xtide current station predictions from each xtide station in dive_sties.json. Operation is idempotent.
'''

import data_collect
import json
import urllib.request
from bs4 import BeautifulSoup
import re
import os
import time

# GLEN = 5133  # days to the end of 2037 which is limit for some xtide harmonic files
GLEN = 19345  # 53 years - should cover my effective entire diveable life
# GLEN = 10

def getFileName(stationName):
    # regex = re.compile('[^a-zA-Z]')  # remove all non-alphabetic
    # regex = re.compile('[(),]') # remove parens and commas
    # filename = regex.sub('', filename)

    # remove chars before first comma
    match = re.match(r'^([^,]+)', stationName.lower())
    filename = match.group(1)
    # remove chars before first paren
    match = re.match(r'^([^(]+)', filename)
    filename = match.group(1)

    filename = filename.strip()
    filename = filename.replace('.', '')
    filename = filename.replace(' ', '-')
    return 'xtide-offline/' + filename + '.txt'


def main():
    data = json.loads(open(data_collect.absName('dive_sites.json')).read())
    for station in data['stations']:
        if 'url_xtide_a' in station and station['url_xtide_a']:  # and station['xtide_limit_2037']:
            filename = getFileName(station['name'])
            if os.path.exists(filename):
                print(f"The file '{filename}' exists, skipping download")
                continue
                # with open(filename, 'r') as f:
                #     print(f.read())
            print('downloading predictions for {}'.format(filename))
            # url = station['url_xtide_a'].replace('glen=14', 'glen={}'.format(GLEN))
            # with urllib.request.urlopen(url) as response:
            #     html = response.read()
            #     soup = BeautifulSoup(html, 'html.parser')
            #     predictions = soup.find('pre')
            #     lines = predictions.text.lower().splitlines()[2:]  # 1st 2 lines are gps coords and emptyline
            #     with open(filename, 'w') as file:
            #         for line in lines:
            #             file.write(line + '\n')
            # exit(0)
            # time.sleep(10)
        else:
            print('station {} does not contain a valid xtide url'.format(station['name']))

if __name__ == "__main__":
    main()
