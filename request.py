#!/usr/bin/env python3

import time
import pytz
import steam.webauth as wa
import sqlite3
import re
from dotenv import dotenv_values
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dataclasses import dataclass

config = dotenv_values('.env')


@dataclass
class ItemTypes:
    full_type: str
    stattrack: bool
    souvenir: bool
    rarity: str


regexes = ["Consumer Grade", "Industrial Grade", "Mil-Spec Grade", "Classified", "Restricted", "Covert"]


def get_item_types(item_rarity: str) -> ItemTypes:
    stat = re.search('^StatTrak.', item_rarity)
    souv = re.search('^Souvenir.', item_rarity)
    rarity = None
    for regex in regexes:
        res = re.search(regex, item_rarity)
        if res:
            rarity = regex
            break
    return ItemTypes(item_rarity, bool(stat), bool(souv), rarity)


timezone = pytz.timezone('US/Eastern')
conn = sqlite3.connect('history.db')
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS users(steam_id TEXT, last_date_requested INTEGER)')
cursor.execute(
    'CREATE TABLE IF NOT EXISTS case_results(item TEXT, full_type TEXT, type TEXT, wear TEXT, stattrack INTEGER, souvenir INTEGER, date TEXT, datetime INTEGER)')

user = wa.WebAuth(config['USERNAME'])
passwd: str = str(input("Enter steam password: "))
session = user.cli_login(passwd)

last_requested = cursor.execute(
    "SELECT last_date_requested FROM users WHERE steam_id='{id}'".format(id=config['USERNAME']))
# Replace this url with one from steam64 id. it'll be .com/profiles/{steam64_id}/inventoryhistory...
history_url: str = 'https://steamcommunity.com/id/{id}/inventoryhistory/?ajax=1&cursor[time]={start_time}&app[]=730'
start = time.time()
end = 0
last_requested_list = last_requested.fetchall()
if len(last_requested_list):
    end = last_requested_list[0][0]

while start > end:
    s = session.get(history_url.format(id=config['STEAM_ID'], start_time=start))
    if not s.json() or s.json()['num'] == 0:
        break
    html: str = s.json()['html']
    descriptions = s.json()['descriptions']

    soup = BeautifulSoup(html, 'lxml')
    trade_history_events = soup.find_all('div', {'class': 'tradehistory_event_description'})
    unlocked_containers = [event for event in trade_history_events if
                           event.contents[0].translate('\n').strip() == 'Unlocked a container']

    for event in unlocked_containers:
        opening = event.parent.find_all('img', {'class': 'tradehistory_received_item_img'})
        t = event.parent.find_all('a', {'class': 'history_item economy_item_hoverable'})
        event_date_divs = event.parent.parent.find_all('div', {'class': 'tradehistory_date'})
        event_date_div = event_date_divs[-1].contents
        event_date = event_date_div[0].replace('\n', '').strip()
        event_time = event_date_div[1].contents
        event_date_time = event_date + ' ' + event_time[-1]
        event_dt = datetime.strptime(event_date_time, '%b %d, %Y %I:%M%p') + timedelta(hours=3)
        if int(time.mktime(event_dt.timetuple())) <= end:
            continue

        last = t[-1]
        description_identifier = last['data-classid'] + '_' + last['data-instanceid']
        item_type = descriptions['730'][description_identifier]['type']
        item_wear = descriptions['730'][description_identifier]['descriptions'][0]['value'].split('Exterior: ')
        if len(item_wear) == 2:
            item_wear = item_wear[1]
        else:
            item_wear = None
        for elem in opening:
            parent = elem.parent.parent.find('a')
            if parent is not None:
                item = parent.find('span', {'class': 'history_item_name'}).contents[0]
                types = get_item_types(item_type)
                query: str = "INSERT INTO case_results VALUES(\"{item}\", \"{full_type}\", \"{type}\", \"{wear}\", \"{stattrack}\", \"{souvenir}\", \"{date}\", \"{datetime}\")".format(
                    item=item, full_type=item_type, type=types.rarity, wear=item_wear,
                    stattrack=1 if types.stattrack else 0, souvenir=1 if types.souvenir else 0,
                    date=event_dt.strftime('%Y-%m-%d %I:%M%p'),
                    datetime=int(time.mktime(event_dt.timetuple())))
                print(query)
                cursor.execute(query)

    dates = soup.find_all('div', {'class': 'tradehistory_date'})
    # [date, time]
    ts_date_time = dates[-1].contents
    ts_date = ts_date_time[0].replace('\n', '').strip()
    ts_time = ts_date_time[1].contents
    timestamp = ts_date + ' ' + ts_time[-1]
    ts_format = '%b %d, %Y %I:%M%p'
    start = int(time.mktime(datetime.strptime(timestamp, ts_format).astimezone(timezone).timetuple()))

    time.sleep(1.5)

cursor.execute(
    "INSERT OR IGNORE INTO users (steam_id, last_date_requested) SELECT '{username}', MAX(datetime) FROM case_results".format(
        username='AreUThreatningMe'))
cursor.execute(
    "UPDATE users SET last_date_requested = (SELECT MAX(datetime) FROM case_results) WHERE steam_id='{username}'".format(
        username='AreUThreatningMe'))
conn.commit()
