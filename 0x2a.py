#!/usr/bin/env python3

from ratelimiter import RateLimiter
from dateutil.parser import parse
from dateutil.tz import tzutc
from datetime import datetime, timedelta
import requests
import asyncio
import getopt
import math
import time
import json
import sys
import os

authfile = 'auth.json'
configfile = 'config.json'

def load_json_from_file(filename):
    f = open(filename, 'r')
    ret = json.load(f)
    f.close()
    return ret

def dump_json_to_file(obj, filename):
    f = open(filename, 'w')
    json.dump(obj, f, indent=4)
    f.close()

if os.path.isfile(configfile):
    config = load_json_from_file(configfile)
    uid = config['client_id']
    secret = config['client_secret']
else:
    print(f'failed to load {configfile}')

api_url = 'https://api.intra.42.fr'
campus_id = 14
defaultparams = {'page[size]': 100}

auth_header = {}
auth_data = {'grant_type': 'client_credentials', 'client_id': uid, 
        'client_secret': secret}

if os.path.isfile(authfile):
    auth = load_json_from_file(authfile)
    if math.ceil(time.time()) > auth['created_at'] + auth['expires_in']:
        authed = False
    else:
        auth_header['Authorization'] = f'Bearer {auth["access_token"]}'
        authed = True
else:
    authed = False

default = '\033[0m'
red = '\033[91m'
green = '\033[92m'
orange = '\033[93m'
blue = '\033[94m'
purple = '\033[95m'
cyan = '\033[96m'
white = '\033[96m'

async def limited(until):
    duration = int(round(until - time.time()))

rate_limiter = RateLimiter(max_calls=2, period=1, callback=limited)

def get_auth_token():
    r = requests.post(f'{api_url}/oauth/token', data = auth_data)
    if r.status_code != 200:
        raise Exception('API response: {r.status_code}')
    auth = json.loads(r.text)
    dump_json_to_file(auth, authfile)
    auth_header['Authorization'] = f'Bearer {auth["access_token"]}'

async def get_data(endpoint, params = {}):
    params.update(defaultparams)
    async with rate_limiter:
        r = requests.get(f'{api_url}{endpoint}', params, headers = auth_header)
    if r.status_code != 200:
        raise Exception(f'API response: {r.status_code}')
    data = json.loads(r.text)
    pages = math.ceil(int(r.headers['X-Total']) / int(r.headers['X-Per-Page']))
    if pages == 1:
        return data
    data_list = [item for item in data]
    for n in range(2, pages):
        params.update({'page[number]': n})
        async with rate_limiter:
            r = requests.get(f'{api_url}{endpoint}', params, headers = auth_header)
        if r.status_code != 200:
            raise Exception(f'API response: {r.status_code}')
        data = json.loads(r.text)
        for item in data:
            data_list.append(item)
    return data_list

async def get_projects(cursus):
    if os.path.isfile(f'{cursus}_projects.json'):
        projects = load_json_from_file(f'{cursus}_projects.json')
    else:
        projects = [proj['slug'] for proj in await get_data(f'/v2/cursus/{cursus}/projects')]
        dump_json_to_file(projects, f'{cursus}_projects.json')
    return projects

async def get_project_users(project):
    return await get_data(f'/v2/projects/{project}/projects_users',
            {'filter[campus]': campus_id, 'filter[marked]': 'true'})

async def get_coalition_users(coalition):
    if os.path.isfile(f'{coalition}.json'):
        coalition_users = load_json_from_file(f'{coalition}.json')
    else:
        coalition_users = [item['user_id'] for item in await get_data(f'/v2/coalitions/{coalition}/coalitions_users')]
        dump_json_to_file(coalition_users, f'{coalition}.json')
    return coalition_users

async def get_user_locations(user):
    data = await get_data(f'/v2/users/{user}/locations')
    logtime = {}
    for item in data:
        start = parse(item.get('begin_at'))
        if item.get('end_at') == None:
            end = datetime.now().replace(microsecond=0, tzinfo=tzutc())
        else:
            end = parse(item.get('end_at'))
        start2 = None
        end2 = None
        if end <= start:
            continue
        if end.day > start.day:
            end2 = end
            end = datetime(start.year, start.month, start.day,
                    hour=23, minute=59, second=59, tzinfo=tzutc())
            start2 = datetime(end2.year, end2.month, end2.day, tzinfo=tzutc())
        duration = end - start
        key = start.date()
        if logtime.get(key) == None:
            logtime[key] = (duration)
        else:
            logtime[key] += (duration)
        if start2 != None:
            duration2 = end2 - start2
            key2 = start2.date()
            if logtime.get(key2) == None:
                logtime[key2] = duration2
            else:
                logtime[key2] += duration2
    return logtime

async def get_week_logtime(user):
    logtime = await get_user_locations(user)
    first = next(iter(logtime))
    monday = first - timedelta(days=first.weekday())
    dates = [value for key, value in logtime.items() if key >= monday]
    weektime = timedelta()
    for day in dates:
        weektime += day
    return weektime

async def get_user_color(user_id):
    vela_users = await get_coalition_users('42cursus-amsterdam-vela')
    vela_users += await get_coalition_users('vela')
    pyxis_users = await get_coalition_users('42cursus-amsterdam-pyxis')
    pyxis_users += await get_coalition_users('pyxis')
    cetus_users = await get_coalition_users('42cursus-amsterdam-cetus')
    cetus_users += await get_coalition_users('cetus')
    if user_id in vela_users:
        return red
    if user_id in pyxis_users:
        return purple
    if user_id in cetus_users:
        return blue
    return orange

async def print_users(users_lst, scores):
    vela, pyxis, cetus = scores
    for user in users_lst:
        color = await get_user_color(user[2])
        if user[0] >= 100:
            print(f'[{green}{str(user[0])}{default}] {color}{user[1]}{default}')
            if color == red:
                vela[0] += 1
            if color == purple:
                pyxis[0] += 1
            if color == blue:
                cetus[0] += 1
        else:
            print(f'[{red}{str(user[0])}{default}] {color}{user[1]}{default}')
            if color == red:
                vela[1] += 1
            if color == purple:
                pyxis[1] += 1
            if color == blue:
                cetus[1] += 1
    return (vela, pyxis, cetus)

async def print_finished(project_users):
    if project_users == []:
        return
    users_lst = []
    for user in project_users:
        users_lst.append((user['final_mark'], user['user']['login'], user['user']['id']))
    users_lst = sorted(users_lst, key=lambda user: (-user[0], user[1]))
    valid_lst = [(score, username, user_id) for (score, username, user_id) in
            users_lst if score >= 100]
    fail_lst = [(score, username, user_id) for (score, username, user_id) in
            users_lst if score < 100]
    project_name = project_users[0]["project"]["slug"]
    print(f'({cyan}{project_name}{default})')
    print(f'{green}valid{default}: {green}{len(valid_lst):>3d} {red}fail{default}: {red}{len(fail_lst):>3d} {orange}tries{default}: {orange}{len(users_lst):>3d}{default}')
    scores = ([0, 0], [0, 0], [0, 0])
    scores = await print_users(valid_lst, scores)
    scores = await print_users(fail_lst, scores)
    for counts in scores:
        counts.append(counts[0] + counts[1])
    print(f'{green}valid{default}: {red}{scores[0][0]:>3d}{purple}{scores[1][0]:>3d}{blue}{scores[2][0]:>3d}{default}')
    print(f'{red}fail{default}:  {red}{scores[0][1]:>3d}{purple}{scores[1][1]:>3d}{blue}{scores[2][1]:>3d}{default}')
    print(f'{orange}tries{default}: {red}{scores[0][2]:>3d}{purple}{scores[1][2]:>3d}{blue}{scores[2][2]:>3d}{default}')

async def print_projects(projects = [], cursus='42cursus'):
    if projects == []:
        projects = await get_projects(cursus)
    for slug in projects:
        project_users = await get_project_users(slug)
        if project_users == []:
            width = 27 - (len(slug) + 2) + 6
            print(f'({cyan}{slug}{default})')
        await print_finished(project_users)

async def print_logtime(users):
    for user in users:
        print(f'{orange}{user}{default} {cyan}logtime{default}:')
        user_locations = await get_user_locations(user)
        for key in user_locations:
            print(f'{purple}{key}{default}: {blue}{user_locations[key]}{default}')

async def print_weektime(users):
    for user in users:
        print(f'{orange}{user} {cyan}hours this week{default}:')
        print(f'{blue}{await get_week_logtime(user)}{default}')

def print_help():
    print(f'{purple}usage{default}: {red}{sys.argv[0]} {cyan}followed by any number of the following arguments{default}')
    print(f'{blue} -h            print help and exit{default}')
    print(f'{blue} -c {orange}<cursus>{blue}   check who finished all projects in {orange}<cursus>{default}')
    print(f'{blue} -p {orange}<projects>{blue} check who finished {orange}<projects>{blue} (list seperated by commas){default}')
    print(f'{blue} -l {orange}<user>{blue}     see logtimes for {orange}<user>{default}')
    print(f'{blue} -w {orange}<user>{blue}     see weektime for {orange}<user>{default}')

async def main(argv):
    if authed == False:
        get_auth_token()
    try:
        opts, args = getopt.getopt(argv, "hc:p:l:w:")
    except getopt.GetoptError:
        print_help()
        sys.exit(1)
    for opt, arg in opts:
        if opt == '-h':
            print_help()
            sys.exit()
        elif opt == '-c':
            await print_projects(cursus=arg)
        elif opt == '-p':
            await print_projects(arg.split(','))
        elif opt == '-l':
            await print_logtime(arg.split(','))
        elif opt == '-w':
            await print_weektime(arg.split(','))
    sys.exit()

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
