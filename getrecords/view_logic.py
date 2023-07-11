
import time
from getrecords.models import MapTotalPlayers, TmxMapAT
from getrecords.nadeoapi import LOCAL_DEV_MODE, nadeo_get_nb_players_for_map
from getrecords.utils import run_async


# 5 min
NB_PLAYERS_CACHE_SECONDS = 5 * 60
# 8 hrs
NB_PLAYERS_MAX_CACHE_SECONDS = 8 * 60 * 60
# 10 sec
QUALI_TIMES_CACHE_SECONDS = 10

async def refresh_nb_players_inner(map_uid: str, updated_ago_min_secs=0) -> MapTotalPlayers:
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
            return mtp
        # if it's been less than 5 minutes, or an update is in prog, return cached
        if not LOCAL_DEV_MODE and (in_prog or delta < NB_PLAYERS_CACHE_SECONDS):
            return mtp
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
    return mtp


def get_unbeaten_ats_query():
    return TmxMapAT.objects.filter(AuthorTimeBeaten=False, Broken=False, Track__MapType__contains="TM_Race").all().select_related('Track')\
        .only('Track__TrackID', 'Track__TrackUID', 'Track__Name', 'Track__AuthorLogin', 'Track__Tags', 'Track__AuthorTime', 'Track__MapType', 'WR', 'LastChecked')\
        .order_by('Track__TrackID')\
        .distinct('Track__TrackID')

UNBEATEN_ATS_CV_NAME = "UnbeatenATs"
