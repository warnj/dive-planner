'''
Crawls http://tide.arthroinfo.org/sites_allcurrent.html and saves all current station GPS coordinates.
Allows you to provide GPS coordinates of a dive site and returns a sorted list of nearest current stations.
'''
import urllib.request
from bs4 import BeautifulSoup
import re, sys
import geopy.distance

FILE_NAME = "current_stations_new.txt"
XTIDE_URL = 'http://tide.arthroinfo.org/sites_allcurrent.html'

# downloads site name and location from xtide and saves to file
def download_stations():
    site_count = 0
    coord_count = 0
    with urllib.request.urlopen(XTIDE_URL) as response:
        html = response.read()
        soup = BeautifulSoup(html, 'html.parser')
        with open(FILE_NAME, "w") as f:
            for link in soup.findAll('a'):
                cleanlink = link.get('href')
                if (cleanlink.startswith('map.')):
                    coords = re.findall('[.0-9]+', cleanlink)
                    assert len(coords) == 3
                    f.write(coords[1] + ',-' + coords[2] + '\n')
                    coord_count += 1
                elif (cleanlink.startswith('tideshow.')):
                    site = cleanlink[18:]
                    f.write(site + '\n')
                    site_count += 1
    print('{} sites and {} gps coordinates written to {}'.format(site_count, coord_count, FILE_NAME))

# returns the name and distance in miles of the xtide current station closest to the given gps coordinates
def find_closest_station(dive_site_coords):
    f = open(FILE_NAME, "r")
    content = f.readlines()
    f.close()
    sites = {}
    for i in range(0, len(content), 2):
        coords = content[i].rstrip().split(',')
        coords = float(coords[0]), float(coords[1])
        site = content[i+1].rstrip()
        sites[site] = coords
    min_dist = sys.float_info.max
    min_dist_site = None
    for site, coords in sites.items():
        dist = geopy.distance.geodesic(dive_site_coords, coords).mi
        if (dist < min_dist):
            min_dist = dist
            min_dist_site = site
    return min_dist_site, min_dist

# print info about nearest xtide current stations to the given gps coordinates
def find_closest_stations(dive_site_coords, nearest):
    f = open(FILE_NAME, "r")
    content = f.readlines()
    f.close()
    sites = {}
    all_coords = []
    for i in range(0, len(content), 2):
        coords = content[i].rstrip().split(',')
        coords = float(coords[0]), float(coords[1])
        site = content[i+1].rstrip()
        sites[coords] = site
        all_coords.append(coords)
    all_coords = sorted(all_coords, key=lambda x: geopy.distance.geodesic(dive_site_coords, x).miles)
    for i in range(nearest):
        print("Station: {} is {:.2f}mi away".format(sites[all_coords[i]], geopy.distance.geodesic(dive_site_coords, all_coords[i]).mi))

def main():
    # download_stations()

    # site, dist = find_closest_station((48.405147, -122.656243))
    # site, dist = find_closest_station((48.455865, -123.265408))
    # site, dist = find_closest_station((50.040152, -125.221638))
    # print("Current station: {} is {:.2f}mi away".format(site, dist))

    # find_closest_stations((48.425859, -122.675265), 10)
    # find_closest_stations((50.592204, -126.800397), 10)
    find_closest_stations((47.865230, -122.634994), 10)

if __name__ == "__main__":
    main()
