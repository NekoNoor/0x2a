#!/usr/bin/env python3

from ratelimiter import RateLimiter
from dateutil.parser import parse
from dateutil.tz import tzutc
from datetime import datetime, timedelta
import requests
import asyncio
import math
import time
import json
import sys
import os

authfile = 'auth.json'
configfile = 'config.json'
projectsfile = 'projects.json'

velafile = 'vela.json'
pyxisfile = 'pyxis.json'
cetusfile = 'cetus.json'

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

white = '\033[0m'
red = '\033[91m'
green = '\033[92m'
orange = '\033[93m'
blue = '\033[94m'
purple = '\033[95m'
cyan = '\033[96m'

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

async def get_data(endpoint, params):
    async with rate_limiter:
        r = requests.get(f'{api_url}{endpoint}', params, headers = auth_header)
    if r.status_code != 200:
        raise Exception(f'API response: {r.status_code}')
    return json.loads(r.text)

async def get_projects(cursus):
    projects = await get_data(f'/v2/cursus/{cursus}/projects', 
            {'page[size]': 100})
    projlist = []
    for proj in projects:
        projlist.append((proj['name'], proj['slug']))
    return projlist


async def get_project_users(project):
    return await get_data(f'/v2/projects/{project}/projects_users', 
            {'page[size]': 100, 'filter[campus]': campus_id,
                'filter[marked]': 'true'})

async def get_coalition_users(coalition):
    async with rate_limiter:
        r = requests.get(f'{api_url}/v2/coalitions/{coalition}/coalitions_users',
                {'page[size]': 100}, headers = auth_header)
    if r.status_code != 200:
        raise Exception(f'API response: {r.status_code}')
    pagecount = int(r.headers['X-Total'])
    coalition_users = []
    for n in range(1, pagecount):
        data = await get_data(f'/v2/coalitions/{coalition}/coalitions_users',
                {'page[size]': 100, 'page[number]': n})
        if data == []:
            break
        for item in data:
            coalition_users.append(item['user_id'])
    return coalition_users

async def get_user_locations(user):
    async with rate_limiter:
        r = requests.get(f'{api_url}/v2/users/{user}/locations',
                {'page[size]': 100}, headers = auth_header)
    if r.status_code != 200:
        raise Exception(f'API response: {r.status_code}')
    pagecount = int(r.headers['X-Total'])
    logtime = {}
    for n in range(1, pagecount):
        data = await get_data(f'/v2/users/{user}/locations',
                {'page[size]': 100, 'page[number]': n})
        if data == []:
            break
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

async def get_vpc_users():
    if os.path.isfile(velafile):
        vela_users = load_json_from_file(velafile)
    else:
        vela_users = await get_coalition_users('42cursus-amsterdam-vela')
        dump_json_to_file(vela_users, velafile)
    if os.path.isfile(pyxisfile):
        pyxis_users = load_json_from_file(pyxisfile)
    else:
        pyxis_users = await get_coalition_users('42cursus-amsterdam-pyxis')
        dump_json_to_file(pyxis_users, pyxisfile)
    if os.path.isfile(cetusfile):
        cetus_users = load_json_from_file(cetusfile)
    else:
        cetus_users = await get_coalition_users('42cursus-amsterdam-cetus')
        dump_json_to_file(cetus_users, cetusfile)
    return vela_users, pyxis_users, cetus_users

async def print_users(users_lst, scores):
    vela, pyxis, cetus = scores
    vela_users, pyxis_users, cetus_users = await get_vpc_users()
    for user in users_lst:
        color = white
        if user[2] in vela_users:
            color = red
        if user[2] in pyxis_users:
            color = purple
        if user[2] in cetus_users:
            color = blue
        if user[0] >= 100:
            print(f'[{green}{str(user[0])}{white}] {color}{user[1]}{white}')
            if color is red:
                vela[0] += 1
            if color is purple:
                pyxis[0] += 1
            if color is blue:
                cetus[0] += 1
        else:
            print(f'[{red}{str(user[0])}{white}] {color}{user[1]}{white}')
            if color is red:
                vela[1] += 1
            if color is purple:
                pyxis[1] += 1
            if color is blue:
                cetus[1] += 1
    return (vela, pyxis, cetus)

async def print_finished(project_users):
    if project_users == []:
        return
    users_lst = []
    for user in project_users:
        users_lst.append((user['final_mark'], user['user']['login'],
            user['user']['id']))
    users_lst = sorted(users_lst, key=lambda x: (-x[0], x[1]))
    valid_lst = [(score, username, user_id) for (score, username, user_id) in
            users_lst if score >= 100]
    fail_lst = [(score, username, user_id) for (score, username, user_id) in
            users_lst if score < 100]
    project_name = project_users[0]["project"]["name"]
    width = 20 - (len(project_name) + 2)
    print(f'({cyan}{project_name}{white}){green}{len(valid_lst):>{width}}{red}{len(fail_lst):>3d}{orange}{len(users_lst):>3d}{white}')
    scores = ([0, 0], [0, 0], [0, 0])
    scores = await print_users(valid_lst, scores)
    scores = await print_users(fail_lst, scores)
    for counts in scores:
        counts.append(counts[0] + counts[1])
    print(f'\n{green}valid:\n{red}{scores[0][0]:>3d}{purple}{scores[1][0]:>3d}{blue}{scores[2][0]:>3d}{white}')
    print(f'{red}fail:\n{red}{scores[0][1]:>3d}{purple}{scores[1][1]:>3d}{blue}{scores[2][1]:>3d}{white}')
    print(f'{orange}total:\n{red}{scores[0][2]:>3d}{purple}{scores[1][2]:>3d}{blue}{scores[2][2]:>3d}{white}\n')

async def main():
    if authed == False:
        get_auth_token()
    if len(sys.argv) > 1:
        project_users = await get_project_users(sys.argv[1])
        await print_finished(project_users)
        return
    if os.path.isfile(projectsfile):
        projects = load_json_from_file(projectsfile)
    else:
        projects = await get_projects('42cursus')
        dump_json_to_file(projects, projectsfile)
    for proj in projects:
        project_users = await get_project_users(proj[1])
        if project_users == []:
            project_name = proj[0]
            width = 20 - (len(project_name) + 2) + 6
            print(f'({cyan}{proj[0]}{white}){orange}{0:>{width}}{white}')
        await print_finished(project_users)

if __name__ == "__main__":
    asyncio.run(main())
