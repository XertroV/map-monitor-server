import asyncio
import json
import logging
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.models import CachedValue, MapTotalPlayers, TmxMap, TmxMapAT, TmxMapScrapeState
from getrecords.nadeoapi import LOCAL_DEV_MODE, get_map_records
from getrecords.tmx_maps import tmx_date_to_ts
from getrecords.unbeaten_ats import TMXIDS_UNBEATABLE_ATS
from getrecords.utils import chunk, model_to_dict
from getrecords.view_logic import RECENTLY_BEATEN_ATS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_recently_beaten_ats_query, get_tmx_map, get_unbeaten_ats_query, refresh_nb_players_inner, update_tmx_map


# AT_CHECK_BATCH_SIZE = 360
AT_CHECK_BATCH_SIZE = 200

if LOCAL_DEV_MODE:
    AT_CHECK_BATCH_SIZE = 5


class Command(BaseCommand):
    help = "Run the tmx scraper"
    loop = asyncio.new_event_loop()

    # def add_arguments(self, parser):
    #     parser.add_argument("poll_ids", nargs="+", type=int)

    def _run_async(self, coro: Coroutine):
        task = self.loop.create_task(coro)
        self.loop.run_until_complete(task)
        return task.result()

    def handle(self, *args, **options):
        logging.info(f"Starting TMX Scraper")
        print(f"Starting TMX Scraper")
        state = get_scrape_state()
        update_state = get_update_scrape_state()
        self.loop.create_task(check_tmx_unbeaten_loop())
        self._run_async(run_tmx_scraper(state, update_state))

        pass
        # todo
        # for poll_id in options["poll_ids"]:
        #     try:
        #         poll = Poll.objects.get(pk=poll_id)
        #     except Poll.DoesNotExist:
        #         raise CommandError('Poll "%s" does not exist' % poll_id)

        #     poll.opened = False
        #     poll.save()

        #     self.stdout.write(
        #         self.style.SUCCESS('Successfully closed poll "%s"' % poll_id)
        #     )


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
        try:
            # to any fixes first (should be batched)
            await fix_at_beaten_first_nb()
            if LOCAL_DEV_MODE:
                await cache_recently_beaten_ats()
            #     await scrape_unbeaten_ats()
            latest_map = await get_latest_map_id()
            if latest_map > state.LastScraped:
                await scrape_range(state, latest_map)
            await scrape_update_range(update_state)
            await scrape_unbeaten_ats()
            await cache_unbeaten_ats()
            await cache_recently_beaten_ats()
            sduration = max(0, loop_seconds - (time.time() - start))
            logging.info(f"txm scraper sleeping for {sduration}s")
            await asyncio.sleep(sduration)
        except Exception as e:
            sduration = max(0, loop_seconds - (time.time() - start))
            logging.warn(f"Exception in txm scraper: {e}. Sleeping for {sduration}s and trying again")
            traceback.print_exc()
            await asyncio.sleep(sduration)

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


def set_at_beaten_replay(mapAT: TmxMapAT, newTrack: dict):
    if newTrack["ReplayWRTime"] > newTrack["AuthorTime"]: return
    mapAT.AuthorTimeBeaten = True
    accounts = [newTrack["ReplayWRUsername"] + " (TMX)"]
    mapAT.ATBeatenFirstNb = len(accounts)
    mapAT.WR = newTrack["ReplayWRTime"]
    mapAT.WR_Player = newTrack["ReplayWRUsername"] + " (TMX)"
    mapAT.ATBeatenUsers = ",".join(accounts)
    mapAT.ATBeatenTimestamp = time.time()
    # mapAT.UploadedToNadeo = True


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
    tracks = []
    uids = []
    nbPlayersMap = dict()
    keys = ['TrackID', 'TrackUID', 'Track_Name', 'AuthorLogin', 'Tags', 'MapType', 'AuthorTime', 'WR', 'LastChecked', "ATBeatenTimestamp", "ATBeatenUsers", "NbPlayers"]

    logging.info(f"unbeaten start - query")
    q = get_recently_beaten_ats_query()
    logging.info(f"unbeaten start - got query")
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
            nbPlayers = (await refresh_nb_players_inner(uid, 86400)).nb_players
        track.append(nbPlayers)
    logging.info(f"Patched with nb players")

    resp = dict(keys=keys, nbTracks=len(tracks), tracks=tracks)
    cv = await CachedValue.objects.filter(name=RECENTLY_BEATEN_ATS_CV_NAME).afirst()
    if cv is None:
        cv = CachedValue(name=RECENTLY_BEATEN_ATS_CV_NAME, value="")
    cv.value = json.dumps(resp)
    await cv.asave()
    logging.info(f"Cached recently beaten ATs; len={len(cv.value)} / {len(tracks)}")

# adsf










async def check_tmx_unbeaten_loop():
    sleep_len = 86400 // 4
    while True:
        start = time.time()
        await run_check_tmx_unbeaten_removed_updated()
        await asyncio.sleep(sleep_len - (time.time() - start))



async def run_check_tmx_unbeaten_removed_updated():
    q = get_unbeaten_ats_query()
    tids = []
    tid_to_mapAT = dict()
    async for mapAT in q:
        tids.append(mapAT.Track.TrackID)
        tid_to_mapAT[mapAT.Track.TrackID] = mapAT

    for _batch_ids in chunk(tids, 30):
        batch_ids = list(_batch_ids)
        logging.info(f"run_check_tmx_unbeaten_removed_updated: {batch_ids}")
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
            wrTime = t.get("ReplayWRTime", None)
            if wrTime is None: continue
            if wrTime <= t['AuthorTime']:
                set_at_beaten_replay(tid_to_mapAT[tid], t)
                await tid_to_mapAT[tid].asave()
                saved_offline_wrs.append(tid)
                await update_tmx_map(t)

        if len(saved_offline_wrs) > 0:
            logging.info(f"Marked {len(saved_offline_wrs)} as having AT beaten offline.")

        await asyncio.sleep(.5)


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
