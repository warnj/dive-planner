'''
This program is used to collect past dives from the Marker Buoy dive club
Meetup page and save them to a .csv file.
'''

from selenium import webdriver
from datetime import timedelta as td
import pickle, time, datetime, os, csv

def absName(fileName):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), fileName)

def save_cookie(driver, path):
    with open(path, 'wb') as filehandler:
        pickle.dump(driver.get_cookies(), filehandler)

def load_cookie(driver, path):
    with open(path, 'rb') as cookiesfile:
        cookies = pickle.load(cookiesfile)
        for cookie in cookies:
            driver.add_cookie(cookie)

def getDataFileName():
    name = './dive_meetup_data.csv'
    filename = name
    i = 1
    while os.path.isfile(filename):
        filename = name.replace('data', 'data_' + str(i))
        i += 1
    return filename

# Scrolls the current page to the bottom, waits pausetime, then repeats scroll. Returns after scrolltime has elapsed.
def scroll(d, pausetime, scrolltime):
    endTime = datetime.datetime.now() + td(seconds=scrolltime)
    last_height = d.execute_script("return document.body.scrollHeight")  # Get scroll height
    while datetime.datetime.now() < endTime:
        d.execute_script("window.scrollTo(0, document.body.scrollHeight);")  # Scroll down to bottom
        time.sleep(pausetime)  # Wait to load page
        new_height = d.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            print('No new data to load')  # shouldn't happen if pausetime is long enough
            break
        last_height = new_height

# Iterates through main list element in given driver, writes dive data to file with given csv writer
def parseDives(d, w):
    # To find exact xpath, go to the ul element containing the dives in Chrome with 'inspect element' right click
    # option. Then right-click on element -> copy -> copy XPath.
    list = d.find_element_by_xpath('//*[@id="mupMain"]/div[4]/div[2]/div/div/div/div[2]/div/div/ul')
    for i, diveElem in enumerate(list.find_elements_by_tag_name('li')):
        text = diveElem.text.splitlines()
        if len(text) > 1:  # some list elements are not dives
            linkText = ''
            try:
                link = diveElem.find_element_by_tag_name('a')
                # Also works: link = diveElem.find_element_by_class_name('eventCard--link')
                linkText = link.get_attribute('href')
            except Exception as e:
                print('exception getting link by tag name', e)

            title = text[0].lower()
            date = text[1]
            location = text[3].lower()
            descr = ''
            if len(text) >= 7:  # Cancelled meetups do not show descriptions
                descr = text[6].lower()
            w.writerow([date, title, location, descr, linkText])

def main():
    d = webdriver.Firefox()
    d.get('https://secure.meetup.com/login')

    # Use cookie to login
    print('Logging in with cookie')
    load_cookie(d, absName('cookies.pkl'))

    # # Painful process of manual login
    # d.maximize_window()
    # input('Log in manually, then enter any key to continue.')
    # save_cookie(d, absName('cookies.pkl'))

    d.get('https://www.meetup.com/Marker-Buoy-Dive-Club/events/past')

    scrollSeconds = 600
    pauseSeconds = 5
    print('Scrolling for {}s. Content load pause = {}s'.format(scrollSeconds, pauseSeconds))
    scroll(d, pauseSeconds, scrollSeconds)

    print('Parsing web content and saving dive data to file')
    filename = absName(getDataFileName())
    with open(filename, 'w', encoding='utf-8', newline='\n') as f:
        w = csv.writer(f, delimiter=',')
        parseDives(d, w)
    print('Data saved to file:', filename)



if __name__ == "__main__":
    main()
