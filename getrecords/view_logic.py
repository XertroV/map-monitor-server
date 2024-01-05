
import asyncio
import logging
import time
from getrecords.http import get_session
from getrecords.models import MapTotalPlayers, TmxMap, TmxMapAT
from getrecords.nadeoapi import LOCAL_DEV_MODE, nadeo_get_nb_players_for_map
from getrecords.utils import run_async


# 5 min
NB_PLAYERS_CACHE_SECONDS = 5 * 60
# 8 hrs
NB_PLAYERS_MAX_CACHE_SECONDS = 8 * 60 * 60
# 10 sec
QUALI_TIMES_CACHE_SECONDS = 10

async def refresh_nb_players_inner(map_uid: str, updated_ago_min_secs=0) -> tuple[MapTotalPlayers, bool]:
    mtps = MapTotalPlayers.objects.filter(uid=map_uid)
    last_known = 0
    mtp = None
    if await mtps.acount() > 0:
        mtp = await mtps.afirst()
        last_known = mtp.nb_players
        delta = time.time() - mtp.updated_ts
        in_prog = mtp.last_update_started_ts > mtp.updated_ts and (time.time() - mtp.last_update_started_ts < 60)
        # check for explict only-update-in-some-cases flag
        if (delta < updated_ago_min_secs):
            return (mtp, False)
        # if it's been less than 5 minutes, or an update is in prog, return cached
        if not LOCAL_DEV_MODE and (in_prog or delta < NB_PLAYERS_CACHE_SECONDS):
            return (mtp, True)
    else:
        mtp = MapTotalPlayers(uid=map_uid)
    mtp.last_update_started_ts = time.time()
    await mtp.asave()
    records = await nadeo_get_nb_players_for_map(map_uid)
    mtp.nb_players = 0
    mtp.last_highest_score = 0
    tops = records['tops'][0]['top']
    if (len(tops) > 1):
        last_player = tops[0]
        mtp.nb_players = last_player['position']
        mtp.last_highest_score = last_player['score']
    mtp.updated_ts = time.time()
    await mtp.asave()
    return (mtp, False)


def get_unbeaten_ats_query():
    return TmxMapAT.objects.filter(AuthorTimeBeaten=False, Broken=False, RemovedFromTmx=False, Unbeatable=False, Track__Unreleased=False, Track__MapType__contains="TM_Race").all().select_related('Track')\
        .only('Track__TrackID', 'Track__TrackUID', 'Track__Name', 'Track__AuthorLogin', 'Track__Tags', 'Track__AuthorTime', 'Track__MapType', 'WR', 'LastChecked')\
        .order_by('Track__TrackID')\
        .distinct('Track__TrackID')

def get_recently_beaten_ats_query():
    return TmxMapAT.objects.filter(AuthorTimeBeaten=True, ATBeatenFirstNb=1, Track__MapType__contains="TM_Race").all().select_related('Track')\
        .only('Track__TrackID', 'Track__TrackUID', 'Track__Name', 'Track__AuthorLogin', 'Track__Tags', 'Track__AuthorTime', 'Track__MapType',
              'WR', 'LastChecked', 'ATBeatenTimestamp', 'ATBeatenUsers')\
        .order_by('-ATBeatenTimestamp')

UNBEATEN_ATS_CV_NAME = "UnbeatenATs"
RECENTLY_BEATEN_ATS_CV_NAME = "RecentlyBeatenATs"
TRACK_UIDS_CV_NAME = "TrackIDToUID"
CURRENT_COTD_KEY = "COTD_current"


async def get_tmx_map(tid: int, timeout=1.5):
    async with get_session() as session:
        try:
            async with session.get(f"https://trackmania.exchange/api/maps/get_map_info/multi/{tid}", timeout=timeout) as resp:
                if resp.status == 200:
                    maps = (await resp.json())
                    if len(maps) == 0: return None
                    return maps[0]
                else:
                    raise Exception(f"Could not get map info for {tid}: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"TMX timeout for get map infos")


# https://api2.mania.exchange/Method/Index/15
async def get_tmx_map_pack_maps(mpid: int):
    async with get_session() as session:
        try:
            async with session.get(f"https://trackmania.exchange/api/mappack/get_mappack_tracks/{mpid}") as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    raise Exception(f"Could not get mappack maps for {mpid}: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"TMX timeout for get mappack maps {mpid}")


async def update_tmx_map(j: dict):
    tid = j.get('TrackID', -1)
    if (tid < 0):
        logging.warn(f"Update tmx map given bad data: {j}")
        return
    _map = await TmxMap.objects.filter(TrackID=tid).afirst()

    tmp_map = TmxMap(**j)
    if _map is None:
        await tmp_map.asave()
    if _map is not None:
        if not j.get('VehicleName', None):
            j['VehicleName'] = "!Unknown!"
        TmxMap.RemoveKeysFromTMX(j)
        await TmxMap.objects.filter(TrackID=tid).aupdate(**j)


def tmx_map_still_public(m: TmxMap) -> bool:
    if m.Unlisted or m.Unreleased: return False
    try:
        new_map: dict = run_async(get_tmx_map(m.TrackID))
        # none is returned if status isn't 200, e.g., 404
        if new_map is None: return False
        if new_map.get('Unlisted', False) or new_map.get('Unreleased', False):
            m.Unlisted = new_map.get('Unlisted', False)
            m.Unreleased = new_map.get('Unreleased', False)
            m.save()
            return False
    except Exception as e:
        logging.warn(f"Exception checking if tmx map still public: {e}")
    return True
