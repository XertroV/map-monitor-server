import asyncio
import json
import logging
from multiprocessing.managers import BaseManager
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.models import CachedValue, MapTotalPlayers, TmxMap, TmxMapAT, TmxMapScrapeState
from getrecords.nadeoapi import LOCAL_DEV_MODE, get_map_records, run_nadeo_services_auth
from getrecords.tmx_maps import tmx_date_to_ts
from getrecords.unbeaten_ats import TMX_MAPPACKID_UNBEATABLE_ATS, TMXIDS_UNBEATABLE_ATS
from getrecords.utils import chunk, model_to_dict
from getrecords.view_logic import CURRENT_COTD_KEY, RECENTLY_BEATEN_ATS_CV_NAME, TRACK_UIDS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_recently_beaten_ats_query, get_tmx_map, get_tmx_map_pack_maps, get_unbeaten_ats_query, refresh_nb_players_inner, update_tmx_map


# AT_CHECK_BATCH_SIZE = 360
AT_CHECK_BATCH_SIZE = 200

if LOCAL_DEV_MODE:
    AT_CHECK_BATCH_SIZE = 5


class Command(BaseCommand):
    help = "Run the tmx scraper"
    loop = asyncio.new_event_loop()

    # def add_arguments(self, parser):
    #     parser.add_argument("poll_ids", nargs="+", type=int)

    def handle(self, *args, **options):
        run_all_tmx_scrapers(self.loop)
        self.loop.run_forever()



def run_all_tmx_scrapers(loop: asyncio.AbstractEventLoop):
    logging.info(f"Starting TMX Scraper")
    print(f"Starting TMX Scraper")
    state = get_scrape_state()
    update_state = get_update_scrape_state()
    loop.create_task(check_tmx_unbeaten_loop())
    loop.create_task(run_nadeo_services_auth())
    loop.create_task(run_tmx_scraper(state, update_state))



def get_scrape_state(name: str = "main", default_last_scraped=0):
    state = TmxMapScrapeState.objects.filter(Name=name).first()
    if state is None:
        state = TmxMapScrapeState(Name=name, LastScraped=default_last_scraped)
        state.save()
    return state

def get_update_scrape_state():
    # june 24th
    return get_scrape_state("updated_tracks", 1687567560)

async def run_tmx_scraper(state: TmxMapScrapeState, update_state: TmxMapScrapeState):
    loop_seconds = 300
    while True:
        start = time.time()
        if await is_close_to_cotd():
            logging.info(f"tmx scraper sleeping as we are close to COTD")
            await asyncio.sleep(60)
            continue
        try:
            # to any fixes first (should be batched)
            await fix_at_beaten_first_nb()
            # await fix_tmx_records()
            if LOCAL_DEV_MODE:
                logging.info(f"Local dev: cache_recently_beaten_ats")
                await cache_recently_beaten_ats()
                logging.info(f"Local dev: cache_map_uids")
                await cache_map_uids()
                logging.info(f"Local dev: scrape_unbeaten_ats")
                await scrape_unbeaten_ats()
            latest_map = await get_latest_map_id()
            if latest_map > state.LastScraped:
                await scrape_range(state, latest_map)
            await scrape_update_range(update_state)
            await scrape_unbeaten_ats()
            await cache_unbeaten_ats()
            await cache_recently_beaten_ats()
            await cache_map_uids()
            sduration = max(0, loop_seconds - (time.time() - start))
            logging.info(f"txm scraper sleeping for {sduration}s")
            await asyncio.sleep(sduration)
        except Exception as e:
            sduration = max(0, loop_seconds - (time.time() - start))
            logging.warn(f"Exception in txm scraper: {e}. Sleeping for {sduration}s and trying again")
            traceback.print_exc()
            await asyncio.sleep(sduration)


async def is_close_to_cotd():
    next_cotd = await CachedValue.objects.filter(name=CURRENT_COTD_KEY).afirst()
    if next_cotd is None: return False
    try:
        next_cotd_j = json.loads(next_cotd.value)
        c = next_cotd_j['challenge']
        s = c['startDate']
        e = c['endDate']
        # close = within 6 minutes beforehand or during
        return (s - 6 * 60) <= time.time() <= e
    except Exception as e:
        logging.warn(f"Failed to read next COTD times: {e}")
    return False


async def scrape_range(state: TmxMapScrapeState, latest: int):
    while state.LastScraped < latest:
        # max 50 entries, but urls fail with too many (40 * 6 digits long breaks, but is okay with 5 digits)
        if state.LastScraped > 5040 and state.LastScraped < 15000:
            state.LastScraped = 15000
        to_scrape = list(range(state.LastScraped + 1, latest + 1)[:30])
        await update_maps_from_tmx(to_scrape)
        state.LastScraped = to_scrape[-1]
        await state.asave()
        logging.info(f"state.LastScraped: {state.LastScraped}")
        await asyncio.sleep(.8)


async def scrape_update_range(update_state: TmxMapScrapeState):
    max_time = time.time() - 1
    oldest_update = max_time
    down_to = update_state.LastScraped
    page = 1
    updated = list()
    while oldest_update > down_to:
        resp = await get_updated_maps(page)
        maps_page = resp['results']
        if len(maps_page) == 0:
            logging.warn(f"Got no more maps to update: page: {page}, oldest_update: {oldest_update}, down_to: {down_to}")
            break
        total_items = resp['totalItemCount']
        logging.info(f"scrape update range: page: {page}, oldest_update: {oldest_update}, down_to: {down_to}")
        for track in maps_page:
            oldest_update = tmx_date_to_ts(track['UpdatedAt'])
            if tmx_date_to_ts(track['UpdatedAt']) < down_to:
                break
            await update_tmx_map(track)
            updated.append(track['TrackID'])
        # oldest_map = maps_page[-1]
        page += 1
        await asyncio.sleep(.8)

    logging.info(f"Updating maps: {updated}")
    update_state.LastScraped = max_time
    await update_state.asave()



TMX_SEARCH_API_URL = "https://trackmania.exchange/mapsearch2/search?api=on"

async def get_latest_map_id() -> int:
    async with get_session() as session:
        async with session.get(TMX_SEARCH_API_URL) as resp:
            if resp.status == 200:
                j = await resp.json()
                return j['results'][0]['TrackID']
            else:
                raise Exception(f"Could not get latest maps: {resp.status} code")

async def update_maps_from_tmx(tids_or_uids: list[int | str]):
    tids_str = ','.join(map(str, tids_or_uids))
    async with get_session() as session:
        try:
            async with session.get(f"https://trackmania.exchange/api/maps/get_map_info/multi/{tids_str}", timeout=10.0) as resp:
                if resp.status == 200:
                    await _add_maps_from_json(dict(results=await resp.json()))
                else:
                    print(f"RETRY ME: {tids_str}")
                    raise Exception(f"Could not get map infos: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"TMX timeout for get map infos")

# priord: https://api2.mania.exchange/Enum/Index/6
# newest=2 (default), last updated=4

async def get_updated_maps(page: int):
    tmx_limit = 100
    async with get_session() as session:
        try:
            async with session.get(TMX_SEARCH_API_URL + f"&limit={tmx_limit}&page={page}&priord=4", timeout=10.0) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    raise Exception(f"Could not get map infos by last updated: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"TMX timeout for searching maps recently updated")


async def _add_maps_from_json(j: dict):
    if 'results' not in j:
        raise Exception(f"Response didn't contain .results")
    maps_j = j['results']
    track_ids = list()
    for map_j in maps_j:
        track_id = map_j['TrackID']
        track_ids.append(track_id)
        try:
            await update_tmx_map(map_j)
        except Exception as e:
            logging.warn(f"Failed to save map: {map_j} -- exception: {e}")
            raise e
        # logging.info(f"Saved tmx map: {track_id}")
    logging.info(f"Saved tmx maps: {track_ids}")


async def scrape_unbeaten_ats():
    try:
        # init
        at_rows_for = set()
        all_tmx_map_pks = set()
        all_tmx_maps: dict[int, TmxMap] = dict()
        async for _map in TmxMap.objects.filter(MapType__contains="TM_Race").values('TrackID', 'TrackUID', 'MapType', 'AuthorTime', 'id', 'pk'):
            all_tmx_map_pks.add(_map['pk'])
            all_tmx_maps[_map['pk']] = _map
        async for mapAT in TmxMapAT.objects.all():
            at_rows_for.add(mapAT.Track_id)
        missing_maps = all_tmx_map_pks - at_rows_for
        print(f"Missing # TmxMapATs: {len(missing_maps)}")
        # take at most AT_CHECK_BATCH_SIZE
        to_init = list(missing_maps)[:AT_CHECK_BATCH_SIZE]
        for pk in to_init:
            _at = TmxMapAT(Track_id=pk)  #all_tmx_maps[pk]
            await _at.asave()
        print(f"Initialized {len(to_init)} TmxMapATs")

        # now get ATs
        q = TmxMapAT.objects.filter(AuthorTimeBeaten=False, Broken=False, RemovedFromTmx=False, Unbeatable=False, Track__MapType__contains="TM_Race").order_by('LastChecked', 'Track_id')[:AT_CHECK_BATCH_SIZE]
        count = 0
        mats: list[TmxMapAT] = list()
        async for mapAT in q:
            mapAT.LastChecked = time.time()
            mats.append(mapAT)
        await TmxMapAT.objects.abulk_update(mats, ['LastChecked'])
        # for mapAT in mats:
        #     await mapAT.asave()
        for mapAT in mats:
            mapAT.LastChecked = time.time()
            if mapAT.Track_id not in all_tmx_maps:
                logging.warn(f"skipping {mapAT.Track_id} id, not in all maps")
                continue
            track = all_tmx_maps[mapAT.Track_id]
            tid = track['TrackID']
            if track['TrackUID'] is None:
                mapAT.Broken = True
                logging.warn(f"Checked AT found Broken: {track['TrackID']}")
            elif tid in TMXIDS_UNBEATABLE_ATS:
                mapAT.Unbeatable = True
                logging.warn(f"Found Unbeatable AT: {track['TrackID']}")
            else:
                # todo: scan tmx for removed maps somewhere else
                res = await get_map_records(track['TrackUID'])
                if len(res['tops']) > 0:
                    world_tops = res['tops'][0]['top']
                    if len(world_tops) > 0:
                        wr = world_tops[0]
                        score = wr['score']
                        mapAT.WR = score
                        if score <= track['AuthorTime']:
                            set_at_beaten(mapAT, track, world_tops)
                        try:
                            await refresh_nb_players_inner(track['TrackUID'], updated_ago_min_secs=86400)
                        except Exception as e:
                            logging.warn(f"Exception refreshing nb players from tmx scraper for {mapAT}: {e}")
                if LOCAL_DEV_MODE:
                    logging.info(f"Checked AT ({track['AuthorTime']} ms) for {track['TrackID']}: Beaten: {mapAT.AuthorTimeBeaten}, WR: {mapAT.WR}")#\n{res}")
            await mapAT.asave()
            count += 1
            if count >= AT_CHECK_BATCH_SIZE:
                break
        del mats
        del q
    except Exception as e:
        logging.error(f"Exception during tmx AT scrape (will reraise): {e}")
        traceback.print_exception(e)
        raise e



def set_at_beaten(mapAT: TmxMapAT, track: TmxMap, world_tops: list[dict]):
    mapAT.AuthorTimeBeaten = True
    accounts = list()
    for record in world_tops:
        if record['score'] <= track['AuthorTime']:
            accounts.append(record['accountId'])
    mapAT.ATBeatenFirstNb = len(accounts)
    mapAT.WR = world_tops[0]['score']
    mapAT.WR_Player = world_tops[0]['accountId']
    mapAT.ATBeatenUsers = ",".join(accounts)
    mapAT.ATBeatenTimestamp = time.time()
    mapAT.UploadedToNadeo = True


def set_at_beaten_replay(mapAT: TmxMapAT, newTrack: dict, ts):
    if newTrack["ReplayWRTime"] > newTrack["AuthorTime"]: return
    mapAT.AuthorTimeBeaten = True
    accounts = [newTrack["ReplayWRUsername"] + " (TMX)"]
    mapAT.ATBeatenFirstNb = len(accounts)
    mapAT.WR = newTrack["ReplayWRTime"]
    mapAT.WR_Player = newTrack["ReplayWRUsername"] + " (TMX)"
    mapAT.ATBeatenUsers = ",".join(accounts)
    mapAT.ATBeatenTimestamp = ts
    # mapAT.UploadedToNadeo = True
    mapAT.TmxReplayVerified = True
    mapAT.ATBeatenOnTmx = True

def unset_at_beaten_replay(mapAT: TmxMapAT):
    mapAT.AuthorTimeBeaten = False
    mapAT.ATBeatenFirstNb = -1
    mapAT.WR = -1
    mapAT.WR_Player = ""
    mapAT.ATBeatenUsers = ""
    mapAT.ATBeatenTimestamp = -1
    mapAT.TmxReplayVerified = False
    mapAT.ATBeatenOnTmx = False
    mapAT.LastChecked = -1


async def tmx_replay_timestamp(t: dict) -> float:
    try:
        wrTime = t.get("ReplayWRTime", None)
        if wrTime is None: return -1
        if wrTime <= t['AuthorTime']:
            replay_j = await replay_exists_on_tmx(t['ReplayWRID'])
            if replay_j is None: return -1
            return tmx_date_to_ts(replay_j['UploadedAt'])
        return -1
    except Exception as e:
        logging.warn(f"Error in tmx_replay_exists_and_beats_at: {e}")
    return -1


async def replay_exists_on_tmx(replayID: int) -> bool:
    async with get_session() as session:
        try:
            async with session.get(f"https://trackmania.exchange/api/replays/get_replay_info/{replayID}", timeout=10.0) as resp:
                if resp.status == 200:
                    # returns 200 with 0 length for nonexistent replays?
                    try:
                        j = await resp.json()
                        if j["ReplayID"] == replayID:
                            return j
                    except Exception as e:
                        return None
                    # return await resp.json()
        except asyncio.TimeoutError as e:
            logging.warn(f"TMX timeout for replay_exists_on_tmx")


async def fix_at_beaten_first_nb():
    q = TmxMapAT.objects.filter(ATBeatenFirstNb=-1, AuthorTimeBeaten=True)
    toupdate = []
    async for mapAT in q[:1000]:
        mapAT.ATBeatenFirstNb = len(mapAT.ATBeatenUsers.split(","))
        toupdate.append(mapAT)
    if len(toupdate) == 0: return
    logging.info(f"{time.time()} Fixing {len(toupdate)} mapATs for ATBeatenFirstNb")
    await TmxMapAT.objects.abulk_update(toupdate, ['ATBeatenFirstNb'])
    logging.info(f"{time.time()} Fixed {len(toupdate)} mapATs for ATBeatenFirstNb")



async def cache_unbeaten_ats():
    tracks = list()
    q = get_unbeaten_ats_query()
    uids = list()
    keys = ['TrackID', 'TrackUID', 'Track_Name', 'AuthorLogin', 'Tags', 'MapType', 'AuthorTime', 'WR', 'LastChecked']
    async for mapAT in q:
        if "TM_Race" not in mapAT.Track.MapType: continue
        tracks.append([mapAT.Track.TrackID, mapAT.Track.TrackUID, mapAT.Track.Name, mapAT.Track.AuthorLogin, mapAT.Track.Tags, mapAT.Track.MapType, mapAT.Track.AuthorTime, mapAT.WR, mapAT.LastChecked])
        uids.append(mapAT.Track.TrackUID)
    q = MapTotalPlayers.objects.filter(uid__in=uids)

    nbPlayersMap = dict()
    async for mtp in q:
        nbPlayersMap[mtp.uid] = mtp.nb_players
    keys.append('NbPlayers')
    for track in tracks:
        uid = track[1]
        if uid in nbPlayersMap:
            track.append(nbPlayersMap[uid])
        else:
            track.append(-1)

    resp = dict(keys=keys, nbTracks=len(tracks), tracks=tracks)
    cv = await CachedValue.objects.filter(name=UNBEATEN_ATS_CV_NAME).afirst()
    if cv is None:
        cv = CachedValue(name=UNBEATEN_ATS_CV_NAME, value="")
    cv.value = json.dumps(resp)
    await cv.asave()
    logging.info(f"Cached unbeaten ATs; len={len(cv.value)} / {len(tracks)}")

async def cache_recently_beaten_ats():
    logging.info(f"unbeaten start")
    keys = ['TrackID', 'TrackUID', 'Track_Name', 'AuthorLogin', 'Tags', 'MapType', 'AuthorTime', 'WR', 'LastChecked', "ATBeatenTimestamp", "ATBeatenUsers", "NbPlayers"]

    nb = 200
    tracks = await gen_recently_beaten_from_query(get_recently_beaten_ats_query()[:nb])

    tracks100k = await gen_recently_beaten_from_query(
            get_recently_beaten_ats_query().filter(Track__TrackID__lte=100_000)[:nb]
        )

    resp = dict(keys=keys, all=dict(nbTracks=len(tracks), tracks=tracks),
                below100k=dict(nbTracks=len(tracks100k), tracks=tracks100k))
    cv = await CachedValue.objects.filter(name=RECENTLY_BEATEN_ATS_CV_NAME).afirst()
    if cv is None:
        cv = CachedValue(name=RECENTLY_BEATEN_ATS_CV_NAME, value="")
    cv.value = json.dumps(resp)
    await cv.asave()
    logging.info(f"Cached recently beaten ATs; len={len(cv.value)} / {len(tracks)}")


async def cache_map_uids():
    logging.info(f"track ids to uid cache start")
    q = TmxMap.objects.all()
    track_uids = {}
    async for track in q:
        track_uids[track.TrackID] = track.TrackUID
    cv = await CachedValue.objects.filter(name=TRACK_UIDS_CV_NAME).afirst()
    if cv is None:
        cv = CachedValue(name=TRACK_UIDS_CV_NAME, value="")
    cv.value = json.dumps(track_uids)
    await cv.asave()
    logging.info(f"Cached track ids to uid; len={len(cv.value)} / {len(track_uids)}")



async def gen_recently_beaten_from_query(q: 'BaseManager[TmxMapAT]'):
    tracks = []
    uids = []
    nbPlayersMap = dict()
    async for mapAT in q:
        if "TM_Race" not in mapAT.Track.MapType: continue
        tracks.append([mapAT.Track.TrackID, mapAT.Track.TrackUID, mapAT.Track.Name, mapAT.Track.AuthorLogin, mapAT.Track.Tags, mapAT.Track.MapType, mapAT.Track.AuthorTime, mapAT.WR, mapAT.LastChecked, mapAT.ATBeatenTimestamp, mapAT.ATBeatenUsers])
        uids.append(mapAT.Track.TrackUID)
    logging.info(f"Got unbeaten tracks: {len(tracks)}")
    q = MapTotalPlayers.objects.filter(uid__in=uids)
    async for mtp in q:
        nbPlayersMap[mtp.uid] = mtp.nb_players
    logging.info(f"Got nb players for: {len(nbPlayersMap)}")
    for track in tracks:
        uid = track[1]
        nbPlayers = -2
        if uid in nbPlayersMap:
            nbPlayers = nbPlayersMap[uid]
        else:
            nbPlayers = (await refresh_nb_players_inner(uid, 86400))[0].nb_players
        track.append(nbPlayers)
    return tracks








async def check_tmx_unbeaten_loop():
    sleep_len = 86400 // 6
    while True:
        start = time.time()
        if await is_close_to_cotd():
            logging.info(f"tmx scraper sleeping as we are close to COTD")
            await asyncio.sleep(60)
            continue
        try:
            await update_unbeatable_maps_list()
            await run_check_tmx_unbeaten_removed_updated()
        except Exception as e:
            logging.error(f"Exception checking tmx unbeaten/removed/updated: {e}")
        await asyncio.sleep(sleep_len - (time.time() - start))



async def run_check_tmx_unbeaten_removed_updated():
    logging.info(f"{time.time()} run_check_tmx_unbeaten_removed_updated start")
    q = get_unbeaten_ats_query()
    tids = []
    tid_to_mapAT = dict()
    async for mapAT in q:
        tids.append(mapAT.Track.TrackID)
        tid_to_mapAT[mapAT.Track.TrackID] = mapAT

    for _batch_ids in chunk(tids, 30):
        batch_ids = list(_batch_ids)
        # logging.info(f"run_check_tmx_unbeaten_removed_updated: {len(batch_ids)}")
        batch_resp = await get_maps_from_tmx(batch_ids)
        resp_ids = [t['TrackID'] for t in batch_resp]
        removed = set(batch_ids) - set(resp_ids)
        if len(removed) > 0:
            logging.info(f"Marking {len(removed)} mapAT records removed from TMX")
        for tid in removed:
            tid_to_mapAT[tid].RemovedFromTmx = True
            await tid_to_mapAT[tid].asave()

        saved_offline_wrs = []
        for t in batch_resp:
            tid = t['TrackID']
            wrTS = await tmx_replay_timestamp(t)
            if wrTS > 0:
                logging.info(f"Found replay WR: {t['TrackID']}")
                set_at_beaten_replay(tid_to_mapAT[tid], t, wrTS)
                await tid_to_mapAT[tid].asave()
                saved_offline_wrs.append(tid)
            # save every map to get updated UIDs or things
            await update_tmx_map(t)

        if len(saved_offline_wrs) > 0:
            logging.info(f"Marked {len(saved_offline_wrs)} as having AT beaten offline.")

        await asyncio.sleep(.5)
    logging.info(f"{time.time()} run_check_tmx_unbeaten_removed_updated end")


async def get_maps_from_tmx(tids_or_uids: list[int | str]) -> list[dict]:
    tids_str = ','.join(map(str, tids_or_uids))
    async with get_session() as session:
        try:
            async with session.get(f"https://trackmania.exchange/api/maps/get_map_info/multi/{tids_str}", timeout=10.0) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"RETRY ME: {tids_str}")
                    raise Exception(f"Could not get map infos: {resp.status} code.")
        except asyncio.TimeoutError as e:
            raise Exception(f"TMX timeout for get map infos")



async def fix_tmx_records():
    pass
    # q = TmxMapAT.objects.filter(
    #     ATBeatenUsers__contains=" (TMX)"
    # )
    # count = 0
    # async for mapAT in q:
    #     unset_at_beaten_replay(mapAT)
    #     await mapAT.asave()
    #     count += 1
    # if count > 0:
    #     logging.info(f"Fixed {count} TMX replay records")
    # q = TmxMapAT.objects.filter(
    #     ATBeatenUsers__contains=" (TMX)", TmxReplayVerified=True, ATBeatenOnTmx=False
    # )
    # async for mapAT in q:
    #     mapAT.ATBeatenOnTmx = True
    #     await mapAT.asave()


async def update_unbeatable_maps_list():
    global TMXIDS_UNBEATABLE_ATS
    try:
        logging.info(f"Updating unbeatable ATs (pre len: {len(TMXIDS_UNBEATABLE_ATS)})")
        maps = await get_tmx_map_pack_maps(TMX_MAPPACKID_UNBEATABLE_ATS)
        tids = []
        for t in maps:
            tids.append(t['TrackID'])
        TMXIDS_UNBEATABLE_ATS = TMXIDS_UNBEATABLE_ATS.union(set(tids))
        logging.info(f"Updated unbeatable ATs (post len: {len(TMXIDS_UNBEATABLE_ATS)})")
    except Exception as e:
        logging.warn(f"Exception while updating unbeaten maps from map pack: {e}")
