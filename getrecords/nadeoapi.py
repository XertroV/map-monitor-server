import asyncio
from dataclasses import dataclass
import json
import logging
import math
from pathlib import Path
import random
import time
from aiohttp import BasicAuth

import jwt
from mapmonitor.settings import DEBUG

from .utils import read_config_file
from .http import get_session
from .models import AuthToken, CotdChallenge, CotdChallengeRanking


LOCAL_DEV_MODE = DEBUG


# ubi_account_info = read_config_file('.ubisoft-acct', ['email', 'password'])
dedi_server_acct_info = read_config_file('.dedi-server-acct', ['user', 'password'])
# print(dedi_server_acct_info)

UNBEATEN_ATS_CONFIG = read_config_file('.tmx-mappack-unbeaten-ats', ['apikey', 's3_apikey'])
TMX_MAPPACK_UNBEATEN_ATS_APIKEY = UNBEATEN_ATS_CONFIG['apikey']
TMX_MAPPACK_UNBEATEN_ATS_S3_APIKEY = UNBEATEN_ATS_CONFIG['s3_apikey']

UBI_SESSIONS_URL = "https://public-ubiservices.ubi.com/v3/profiles/sessions"
NADEO_AUDIENCE_REG_URL = "https://prod.trackmania.core.nadeo.online/v2/authentication/token/ubiservices"
NADEO_AUDIENCE_BASIC_URL = "https://prod.trackmania.core.nadeo.online/v2/authentication/token/basic"
NADEO_REFRESH_URL = "https://prod.trackmania.core.nadeo.online/v2/authentication/token/refresh"


TTG_CLUB_ID = 55829


@dataclass
class UbiAuthResp:
    platformType: str
    ticket: str
    twoFactorAuthenticationTicket: str
    profileId: str
    userId: str
    nameOnPlatform: str
    environment: str
    expiration: str
    spaceId: str
    clientIp: str
    clientIpCountry: str
    serverTime: str
    sessionId: str
    sessionKey: str
    rememberMeTicket: str


@dataclass
class NadeoToken:
    accessToken: str
    refreshToken: str

    @property
    def accessTokenJson(self):
        return jwt.decode(self.accessToken, options={"verify_signature": False})

    @property
    def refreshTokenJson(self):
        return jwt.decode(self.refreshToken, options={"verify_signature": False})


async def get_token_for_audience(audience: str):
    body = {'audience': audience}
    async with get_session() as session:
        async with await session.post(
            NADEO_AUDIENCE_BASIC_URL,
            headers={'Content-Type': 'application/json'},
            auth=BasicAuth(dedi_server_acct_info['user'], dedi_server_acct_info['password']),
            json=body
        ) as resp:
            if not resp.ok:
                logging.warn(f"Error getting token for audience {audience}; {resp.status}, {await resp.content.read()}")
                return
            return NadeoToken(**(await resp.json()))


NadeoCoreToken: NadeoToken | None = None
NadeoLiveToken: NadeoToken | None = None
NadeoClubToken: NadeoToken | None = None

nadeoServicesTask: None | asyncio.Task = None

async def await_nadeo_services_initialized():
    if tokens_need_reacquire():
        await reacquire_all_tokens()
    # global nadeoServicesTask
    # if nadeoServicesTask is None:
    #     nadeoServicesTask = asyncio.create_task(run_nadeo_services_auth())
    # while NadeoLiveToken is None:
    #     await asyncio.sleep(.05)
    # while NadeoClubToken is None:
    #     await asyncio.sleep(.05)

def all_tokens() -> list[NadeoToken | None]:
    return [NadeoLiveToken, NadeoCoreToken, NadeoClubToken]

def tokens_need_reacquire() -> bool:
    buffer_seconds = 150.0 + 200.0 * random.random()
    for t in all_tokens():
        if t is None: return True
        if check_refresh_after(t, buffer_seconds): return True
    return False

async def reacquire_token(for_name: str, force=False) -> NadeoToken:
    tmpNadeoToken = None
    existing = await AuthToken.objects.filter(token_for=for_name, expiry_ts__gt=int(time.time() + 10)).afirst()
    if existing is not None:
        t = existing
        tmpNadeoToken = NadeoToken(accessToken=t.access_token, refreshToken=t.refresh_token)

    if force or check_refresh_after(tmpNadeoToken):
        tmpNadeoToken = await get_token_for_audience(for_name)
        logging.warn(f"Got {for_name} token: {tmpNadeoToken is not None}")
        if tmpNadeoToken is not None:
            await AuthToken.objects.aupdate_or_create(
                token_for=for_name,
                defaults=dict(access_token=tmpNadeoToken.accessToken, refresh_token=tmpNadeoToken.refreshToken,
                            expiry_ts=tmpNadeoToken.accessTokenJson.get('exp'), refresh_after=tmpNadeoToken.accessTokenJson.get('rat'))
            )
    return tmpNadeoToken



async def reacquire_all_tokens(force=False):
    global NadeoCoreToken, NadeoLiveToken, NadeoClubToken

    NadeoCoreToken, NadeoLiveToken, NadeoClubToken = \
        await asyncio.gather(
            reacquire_token('NadeoServices'),
            reacquire_token('NadeoLiveServices'),
            reacquire_token('NadeoClubServices'),
        )

    # # NadeoCoreToken = await get_token_for_audience(ubi, 'NadeoServices')
    # # logging.warn(f"Got core token: {NadeoCoreToken is not None}")
    # # if LOCAL_DEV_MODE:
    # #     logging.warn(f"Got core token: {NadeoCoreToken.accessToken}")
    # tmpNadeoToken = None
    # existing = await AuthToken.objects.filter(token_for="NadeoLiveServices", expiry_ts__gt=int(time.time() + 10)).afirst()
    # if existing is not None:
    #     t = existing
    #     tmpNadeoToken = NadeoToken(accessToken=t.access_token, refreshToken=t.refresh_token)

    # if force or check_refresh_after(tmpNadeoToken):
    #     NadeoLiveToken = await get_token_for_audience('NadeoLiveServices')
    #     logging.warn(f"Got live token: {NadeoLiveToken is not None}")
    #     await AuthToken.objects.aupdate_or_create(
    #         token_for='NadeoLiveServices',
    #         defaults=dict(access_token=NadeoLiveToken.accessToken, refresh_token=NadeoLiveToken.refreshToken,
    #                       expiry_ts=NadeoLiveToken.accessTokenJson.get('exp'), refresh_after=NadeoLiveToken.accessTokenJson.get('rat'))
    #     )
    # else:
    #     NadeoLiveToken = tmpNadeoToken
    # if LOCAL_DEV_MODE:
    #     logging.warn(f"Got live token: {NadeoLiveToken.accessToken}")


def check_refresh_after(t: NadeoToken, buffer_seconds: float = 0.0) -> bool:
    if t is None: return True
    return t.accessTokenJson.get('rat') < (time.time() + buffer_seconds)


NADEO_SVC_AUTH_STARTED = False
async def run_nadeo_services_auth():
    global NADEO_SVC_AUTH_STARTED
    if NADEO_SVC_AUTH_STARTED: return
    NADEO_SVC_AUTH_STARTED = True
    await reacquire_all_tokens()
    while True:
        await asyncio.sleep(60)
        ts = all_tokens()
        for t in ts:
            if t is None: continue
            refreshAfter = t.accessTokenJson.get('rat')
            if time.time() > refreshAfter + 10:
                await reacquire_all_tokens()
                break


def get_token_for(audience):
    if audience == "NadeoServices" and NadeoCoreToken is not None:
        return NadeoCoreToken.accessToken
    if audience == "NadeoLiveServices" and NadeoLiveToken is not None:
        return NadeoLiveToken.accessToken
    if audience == "NadeoClubServices" and NadeoClubToken is not None:
        return NadeoClubToken.accessToken
    raise Exception(f'cannot get token for audience: {audience}')

def get_nadeo_session(audience: str):
    session = get_session()
    session.headers['Authorization'] = f"nadeo_v1 t={get_token_for(audience)}"
    return session

def get_core_session():
    return get_nadeo_session('NadeoServices')

def get_live_session():
    return get_nadeo_session('NadeoLiveServices')

def get_club_session():
    return get_nadeo_session('NadeoClubServices')


TOTD_MAP_LIST = "https://live-services.trackmania.nadeo.live/api/token/campaign/month?length={length}&offset=0"

async def get_totd_maps(length=100):
    await await_nadeo_services_initialized()
    async with get_live_session() as session:
        async with await session.get(TOTD_MAP_LIST.format(length=length)) as resp:
            if resp.status == 200:
                return await resp.json()
            logging.warn(f"get totd maps got status: {resp.status}, {await resp.text()}")
            return None

GET_CHALLENGE_URL = "https://meet.trackmania.nadeo.club/api/challenges/{id}"

async def get_challenge(_id: int):
    url = GET_CHALLENGE_URL.format(id=_id)
    await await_nadeo_services_initialized()
    async with get_club_session() as session:
        async with await session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            logging.warn(f"get challenge with id {_id} failed: {resp.status}, {await resp.text()}")
            return None

GET_CHALLENGE_RECORDS_URL = "https://meet.trackmania.nadeo.club/api/challenges/{id}/records/maps/{map_uid}?length={length}&offset={offset}"

async def get_challenge_records(_id: int, map_uid: str, length: int = 10, offset: int = 0):
    url = GET_CHALLENGE_RECORDS_URL.format(id=_id, map_uid=map_uid, length=length, offset=offset)
    await await_nadeo_services_initialized()
    async with get_club_session() as session:
        async with await session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            logging.warn(f"get challenge records with id {_id}, map: {map_uid} failed: {resp.status}, {await resp.text()}")
            return None


async def get_and_save_all_challenge_records(challenge: CotdChallenge):
        cid = challenge.challenge_id
        uid = challenge.uid
        c_players = await get_challenge_players(cid, uid)
        last_nb_players = c_players['cardinal']
        offsets = list(range(0, last_nb_players+100, 100))
        requests = [get_challenge_records(cid, uid, 100, o) for o in offsets]
        responses = await asyncio.gather(*requests, return_exceptions=True)
        # create (but dont save) records
        loop_mid = time.time()
        new_records = [rec for resp, offset in zip(responses, offsets) for rec in gen_cotd_quali_challenge_block(challenge, resp, offset, int(loop_mid))]
        return await CotdChallengeRanking.objects.abulk_create(new_records)


def gen_cotd_quali_challenge_block(challenge, resp, offset, loop_mid) -> list[CotdChallengeRanking]:
    return [
        CotdChallengeRanking(challenge=challenge, req_timestamp=loop_mid,
                             rank=record['rank'], score=record['score'], player=record['player'])
        for record in resp
    ]


GET_CHALLENGE_PLAYERS_URL = "https://meet.trackmania.nadeo.club/api/challenges/{id}/records/maps/{map_uid}/players?players[]="

# {"uid":"jAtn7LQt2MTG5xv4BeiQwZAX1K","cardinal":376,"records":[{"player":"0a2d1bc0-4aaa-4374-b2db-3d561bdab1c9","score":52414,"rank":230}]}
async def get_challenge_players(_id: int, map_uid: str, *player_wsids: list[str]):
    url = GET_CHALLENGE_PLAYERS_URL.format(id=_id, map_uid=map_uid) + ",".join(player_wsids)
    await await_nadeo_services_initialized()
    async with get_club_session() as session:
        async with await session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            logging.warn(f"get challenge players with id {_id}, map: {map_uid} failed: {resp.status}, {await resp.text()}")
            return None

COTD_CURRENT_URL = "https://meet.trackmania.nadeo.club/api/cup-of-the-day/current"

async def get_cotd_current():
    await await_nadeo_services_initialized()
    async with get_club_session() as session:
        async with await session.get(COTD_CURRENT_URL) as resp:
            if resp.status == 200:
                return await resp.json()
            if resp.status == 204:
                logging.warn(f"api COTD current 204, sleeping for 180 seconds")
                await asyncio.sleep(180)
            else:
                logging.warn(f"api COTD current failed: {resp.status}, {await resp.text()}")
            return None


MAP_RECORD = "https://live-services.trackmania.nadeo.live/api/token/leaderboard/group/Personal_Best/map/{mapUid}/top?length={length}&onlyWorld={onlyWorld}&offset={offset}"


async def get_map_records(mapUid: str, length: int = 20, offset: int = 0, only_world: bool = True, retry_fix_401=True):
    await await_nadeo_services_initialized()
    async with get_live_session() as session:
        async with await session.get(MAP_RECORD.format(mapUid=mapUid, length=length, offset=offset, onlyWorld=str(only_world).lower())) as resp:
            if resp.status == 200:
                return await resp.json()
            logging.warn(f"get_map_records status: {resp.status}, {await resp.text()}")
            if (retry_fix_401 and resp.status == 401):
                await reacquire_all_tokens(True)
                return await get_map_records(mapUid, length, offset, only_world, retry_fix_401 = False)
            return None



MAP_SCORE_AROUND = "https://live-services.trackmania.nadeo.live/api/token/leaderboard/group/Personal_Best/map/{mapUid}/surround/1/1?onlyWorld=true&score={score}"

async def get_map_scores_around(mapUid: str, score: int, retry_fix_401=True):
    await await_nadeo_services_initialized()
    async with get_live_session() as session:
        async with await session.get(MAP_SCORE_AROUND.format(mapUid=mapUid, score=score)) as resp:
            if resp.status == 200:
                return await resp.json()
            logging.warn(f"get_map_scores_around status: {resp.status}, {await resp.text()}")
            if (retry_fix_401 and resp.status == 401):
                await reacquire_all_tokens(True)
                return await get_map_scores_around(mapUid, score, retry_fix_401 = False)
            return None

async def nadeo_get_nb_players_for_map(map_uid: str):
    a_long_time = 1000 * 86400 * 21
    a_long_time += int(time.time()) % a_long_time
    resp = await get_map_scores_around(map_uid, a_long_time)
    # print(resp)
    return resp


async def nadeo_get_surround_for_map(map_uid: str, score: int):
    resp = await get_map_scores_around(map_uid, score)
    # print(resp)
    return resp


MAP_INFO_BY_UID_URL = "https://prod.trackmania.core.nadeo.online/maps/?mapUidList="

async def core_get_maps_by_uid(uids: list[str]):
    await await_nadeo_services_initialized()
    url = MAP_INFO_BY_UID_URL + ",".join(uids)
    async with get_core_session() as session:
        async with await session.get(url) as resp:
            if not resp.ok:
                print(f"Error getting maps for uids: {uids}; {resp.status}, {await resp.content.read()}")
                logging.warn(f"Error getting maps for uids: {uids}; {resp.status}, {await resp.content.read()}")
                return
            return await resp.json()

''' wait for up to 2 minutes for maps to be uploaded '''
async def await_maps_uploaded(mapUids: list[str]):
    await await_nadeo_services_initialized()
    mapsNotUploaded = set(mapUids)
    counter = 0
    logging.info(f"Awaiting map uploads: {len(mapsNotUploaded)} : {mapsNotUploaded}")
    while len(mapsNotUploaded) > 0 and counter <= 60:
        if counter > 0:
            await asyncio.sleep(2)
        counter += 1
        url = MAP_INFO_BY_UID_URL + ",".join(mapsNotUploaded)
        async with get_core_session() as session:
            async with await session.get(url) as resp:
                if not resp.ok:
                    logging.warn(f"Error getting maps for uids: {mapUids}; {resp.status}, {await resp.content.read()}")
                    return
                mapInfos = await resp.json()
                for mapInfo in mapInfos:
                    uid = mapInfo['mapUid']
                    if uid in mapsNotUploaded:
                        mapsNotUploaded.remove(uid)
                logging.info(f"Maps not yet uploaded; {mapsNotUploaded}")
    if len(mapsNotUploaded) > 0:
        logging.warn(f"Some maps are not yet uploaded! {mapsNotUploaded}")
    else:
        logging.info(f"All maps uploaded: {set(mapUids)}")


CREATE_ROOM_URL = f"https://live-services.trackmania.nadeo.live/api/token/club/{TTG_CLUB_ID}/room/create"
DELETE_ROOM_URL = lambda activityId: f"https://live-services.trackmania.nadeo.live/api/token/club/{TTG_CLUB_ID}/activity/{activityId}/delete"
GET_ROOM_URL = lambda activityId: f"https://live-services.trackmania.nadeo.live/api/token/club/{TTG_CLUB_ID}/room/{activityId}/"
GET_PASSWORD_URL = lambda activityId: f"https://live-services.trackmania.nadeo.live/api/token/club/{TTG_CLUB_ID}/room/{activityId}/get-password"
POST_JOIN_URL = lambda activityId: f"https://live-services.trackmania.nadeo.live/api/token/club/{TTG_CLUB_ID}/room/{activityId}/join"

''' example settings:

[{"key":"S_TimeLimit","value":"3600","type":"integer"},{"key":"S_WarmUpNb","value":"1","type":"integer"},{"key":"S_WarmUpDuration","value":"10","type":"integer"},{"key":"S_WarmUpTimeout","value":"10","type":"integer"}]

'''

async def create_club_room(name: str, mapUids=list[str], region: str = "eu-west", scalable=0, password=0, maxPlayers=64, script="TrackMania/TM_TimeAttack_Online.Script.txt", settings=None):
    await await_nadeo_services_initialized()
    valid_regions = ["eu-west", "ca-central"]
    if region not in valid_regions:
        region = valid_regions[0]
    assert scalable in [0, 1]
    assert password in [0, 1]
    data = {
        "name":name,
        "region":region,
        "maxPlayersPerServer":maxPlayers,
        "script":script,
        "settings":[] if settings is None else settings,
        "maps":mapUids,
        "scalable":scalable,
        "password":password
    }
    async with get_live_session() as session:
        async with session.post(CREATE_ROOM_URL, json=data) as resp:
            if not resp.ok:
                logging.warn(f"Error creating club room; {resp.status}, {await resp.content.read()}")
                return
            data = await resp.json()
            logging.info(f"Create room response: {data}")
            if password == 0:
                return data
        logging.info(f"Getting password for club room: {data['activityId']}")
        async with session.get(GET_PASSWORD_URL(data['activityId'])) as resp:
            if not resp.ok:
                logging.warn(f"Error getting pw for club room; {resp.status}, {await resp.content.read()}; {data}")
                return data
            pwData = await resp.json()
            data['password'] = pwData['password']
            return data

async def get_club_room(activityId: int):
    await await_nadeo_services_initialized()
    async with get_live_session() as session:
        async with session.get(GET_ROOM_URL(activityId)) as resp:
            if not resp.ok:
                logging.warn(f"Error getting club room {activityId}; {resp.status}, {await resp.content.read()}")
            else:
                data = await resp.json()
                async with session.get(GET_PASSWORD_URL(data['activityId'])) as resp:
                    if not resp.ok:
                        logging.warn(f"Error getting pw for club room; {resp.status}, {await resp.content.read()}; {data}")
                        return data
                    pwData = await resp.json()
                    data['password'] = pwData['password']
                    return data

async def delete_club_room(activityId: int):
    await await_nadeo_services_initialized()
    async with get_live_session() as session:
        async with session.post(DELETE_ROOM_URL(activityId)) as resp:
            if not resp.ok:
                logging.warn(f"Error deleting club room {activityId}; {resp.status}, {await resp.content.read()}")
            else:
                logging.info(f"Deleted activity: {activityId}")


async def join_club_room(activityId: int):
    await await_nadeo_services_initialized()
    async with get_live_session() as session:
        async with session.post(POST_JOIN_URL(activityId)) as resp:
            if not resp.ok:
                logging.warn(f"Error getting join info for {activityId}; {resp.status}, {await resp.content.read()}")
                if resp.status == 504: # timeout
                    await asyncio.sleep(1.0)
                    return await join_club_room(activityId)
            else:
                data: dict = await resp.json()
                # logging.debug(f"Join link data: {data}")
                return data

async def await_join_club_room(activityId: int):
        count = 0
        while count < 60:
            if count > 0:
                await asyncio.sleep(.75)
            count += 1
            join_resp: dict = await join_club_room(activityId)
            if not join_resp.get('starting', True):
                return join_resp['joinLink']
        logging.warn(f"Server was not started! checked 60 times sleeping .75s between.")


# works!
async def run_club_room_creation_test():
    if not LOCAL_DEV_MODE: return
    await await_nadeo_services_initialized()
    name = f"TTG-{gen_uid(6)}"
    logging.info(f"Creating room named {name}")
    map_list = ["RCvWrXBMxPl2RkLbbabPW_m_Cp2","RCeN91YppQKsVeaxljyNZrv08Ia","AIUiDusbordueNQMAfniaEeRpl2"]
    await await_maps_uploaded(map_list)
    logging.info(f"Ensured maps are uploaded")
    room_resp = await create_club_room(name, map_list, password=1)
    logging.info(f"Got room resp: {room_resp}")
    join_link = await await_join_club_room(room_resp['activityId'])
    join_link += f":{room_resp['password']}"
    logging.info(f"Got join link for room: {join_link}")
    exists_start = time.time()
    # while join_link is not None:
    logging.info(f"waiting 315 seconds, should still be active")
    await asyncio.sleep(315.)
    join_info = await join_club_room(room_resp['activityId'])
    logging.info(f"waiting 30 seconds, should not active")
    await asyncio.sleep(30.)
    join_info = await join_club_room(room_resp['activityId'])
        # if join_info.get('starting', False):
        #     break
    logging.info(f"Server active for {time.time() - exists_start} seconds")
    logging.info(f"deleting room")
    await delete_club_room(room_resp['activityId'])
    logging.info(f"Deleted room")



async def upload_map(map_file: str, map_id: str, map_uid: str, map_name: str, author_id: str, at: int, gold: int, silver: int, bronze: int, token: str = ""):
    map_path = Path(map_file)
    map_bytes = map_path.read_bytes()
    url = f"https://prod.trackmania.core.nadeo.online/maps/{map_id}"
    boundary = "BoundaryAvd6SChorflHbz03MQHQyJWA92quH6vii3RgZ9bc"

    content = f"""--{boundary}
Content-Disposition: form-data; name="nadeoservices-core-parameters"\r
Content-Type: application/json\r

{{
  "isPlayable" : true,
  "authorScore" : {at},
  "goldScore" : {gold},
  "silverScore" : {silver},
  "bronzeScore" : {bronze},
  "createdWithGamepadEditor" : false,
  "createdWithSimpleEditor" : false,
  "name" : "{map_name}",
  "mapType" : "TrackMania\\\\TM_Race",
  "mapStyle" : "",
  "collectionName" : "Stadium",
  "author" : "{author_id}",
  "mapUid" : "{map_uid}"
}}
--{boundary}
Content-Disposition: form-data; name="data"; filename="{map_path.name}"\r
Content-Type: application/octet-stream\r
Content-Transfer-Encoding: binary\r

""".encode()
    print(f"DEV Original payload:\n{content}")
    content = content + map_bytes
    content = content + f"\n--{boundary}--\n".encode()

    headers = {
        "accept": "*/*",
        "accept-encoding": "deflate,gzip,identity",
        # "user-agent": "ManiaPlanet/3.3.0 (Win64; rv: 2023-09-25_23_51; context: none; distro: AZURO)",
        "pragma": "no-cache",
        "cache-control": "no-cache, no-store, must-revalidate",
        "accept-language": "en-US,en",
        "nadeo-game-build": "2023-09-25_23_51",
        "nadeo-game-crossplay": "1",
        "nadeo-game-lang": "en-US",
        "nadeo-game-name": "ManiaPlanet",
        "nadeo-game-platform": "PC_Windows",
        "nadeo-game-version": "3.3.0",
        "content-type": f'multipart/form-data; boundary="{boundary}"',
        "content-length": str(len(content))
    }
    print(f"DEV headers: {headers}")
    if len(token) > 0:
        headers["Authorization"] = f"nadeo_v1 t={token}"
    await await_nadeo_services_initialized()
    async with get_core_session() as session:
        session.headers.update(headers)
        # return None
        async with session.post(url, data=content) as resp:
            if not resp.ok:
                logging.warn(f"Error uploading map {map_uid}; {resp.status}, {await resp.content.read()}")
                # if resp.status == 504: # timeout
                #     await asyncio.sleep(1.0)
                #     return await join_club_room(activityId)
            else:
                data: dict = await resp.json()
                logging.warn(f"map upload response: {data}")
                return data


# 0a2d1bc0-4aaa-4374-b2db-3d561bdab1c9
# UxvNHnVgILyFAU0wAdpu0uBuszc
# curl -H 'Authorization: nadeo_v1 t=' 'https://live-services.trackmania.nadeo.live/api/token/club/46587/activity?length=100&offset=0'
