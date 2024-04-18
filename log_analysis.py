# generates historical vis trends for sites from my dive log

import csv

def filter_by_site(csv_file, sites):
    r = []
    with open(csv_file, newline='', errors='ignore') as csvfile:
        reader = csv.DictReader(csvfile)
        for dive in reader:
            if not dive:
                continue
            for site in sites:
                if site.lower() in dive['Location'].lower():
                    r.append(dive)
    return r

def diveStr(dive):
    return "  {0:5} {1:9} {2:30} {3}".format(dive['ï»¿Dive'], dive['Date'], dive['Location'], dive['Vis (feet)'])

def append(sites: list, name: str) -> list:
    if sites:
        sites.append(name)
        return sites
    else:
        return [name]

def main():
    SITES = []
    # SITES = append(SITES, 'Ulua')
    # SITES = append(SITES, 'Deception')
    # SITES = append(SITES, 'Redondo')
    # SITES = append(SITES, 'Skyline')

    SITES = append(SITES, 'Brinnon')
    SITES = append(SITES, 'Flagpole')
    SITES = append(SITES, 'Sund')
    SITES = append(SITES, 'Hood')

    for entry in filter_by_site('dive_log.csv', SITES):
        print(diveStr(entry))

if __name__ == "__main__":
    main()
