import asyncio
import logging
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.models import TmxMap, TmxMapAT, TmxMapScrapeState
from getrecords.nadeoapi import LOCAL_DEV_MODE, get_map_records
from getrecords.tmx_maps import tmx_date_to_ts
from getrecords.utils import model_to_dict


AT_CHECK_BATCH_SIZE = 360

if LOCAL_DEV_MODE:
    AT_CHECK_BATCH_SIZE = 10


class Command(BaseCommand):
    help = "Run the tmx scraper"

    # def add_arguments(self, parser):
    #     parser.add_argument("poll_ids", nargs="+", type=int)

    def _run_async(self, coro: Coroutine):
        loop = asyncio.new_event_loop()
        task = loop.create_task(coro)
        loop.run_until_complete(task)
        return task.result()

    def handle(self, *args, **options):
        logging.info(f"Starting TMX Scraper")
        print(f"Starting TMX Scraper")
        state = get_scrape_state()
        update_state = get_update_scrape_state()
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
            if LOCAL_DEV_MODE:
                await scrape_unbeaten_ats()
            latest_map = await get_latest_map_id()
            if latest_map > state.LastScraped:
                await scrape_range(state, latest_map)
            await scrape_update_range(update_state)
            await scrape_unbeaten_ats()
            sduration = max(0, loop_seconds - (time.time() - start))
            logging.info(f"txm scraper sleeping for {sduration}s")
            await asyncio.sleep(sduration)
        except Exception as e:
            sduration = max(0, loop_seconds - (time.time() - start))
            logging.warn(f"Exception in txm scraper: {e}. Sleeping for {sduration}s and trying again")
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
    while oldest_update > down_to:
        resp = await get_updated_maps(page)
        maps_page = resp['results']
        if len(maps_page) == 0:
            logging.warn(f"Got no more maps to update: page: {page}, oldest_update: {oldest_update}, down_to: {down_to}")
            break
        else:
            logging.info(f"Updating maps: {[t['TrackID'] for t in maps_page]}")
        total_items = resp['totalItemCount']
        logging.info(f"scrape update range: page: {page}, oldest_update: {oldest_update}, down_to: {down_to}")
        for track in maps_page:
            await update_tmx_map(track)
        oldest_map = maps_page[-1]
        oldest_update = tmx_date_to_ts(oldest_map['UpdatedAt'])
        page += 1
        await asyncio.sleep(.8)

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
            _map = TmxMap(**map_j)
            # if not _map.Downloadable:
            #     continue
            await _map.asave()
        except Exception as e:
            logging.warn(f"Failed to save map: {map_j} -- exception: {e}")
            raise e
        # logging.info(f"Saved tmx map: {track_id}")
    logging.info(f"Saved tmx maps: {track_ids}")

async def update_tmx_map(j: dict):
    tid = j.get('TrackID', -1)
    if (tid < 0):
        logging.warn(f"Update tmx map given bad data: {j}")
        return
    _map = await TmxMap.objects.filter(TrackID=tid).afirst()

    tmp_map = TmxMap(**j)
    if _map is not None:
        tmp_map.pk = _map.pk
    await tmp_map.asave()




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
        print(f"Missing: {len(missing_maps)}")
        # take at most AT_CHECK_BATCH_SIZE
        to_init = list(missing_maps)[:AT_CHECK_BATCH_SIZE]
        for pk in to_init:
            _at = TmxMapAT(Track_id=pk)  #all_tmx_maps[pk]
            await _at.asave()
        print(f"Initialized {len(to_init)} TmxMapATs")

        # now get ATs
        q = TmxMapAT.objects.filter(AuthorTimeBeaten=False, Broken=False, Track__MapType__contains="TM_Race").order_by('LastChecked', 'Track_id')[:AT_CHECK_BATCH_SIZE]
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
            if track['TrackUID'] is None:
                mapAT.Broken = True
                logging.info(f"Checked AT found Broken: {track['TrackID']}")
            else:
                res = await get_map_records(track['TrackUID'])
                if len(res['tops']) > 0:
                    world_tops = res['tops'][0]['top']
                    if len(world_tops) > 0:
                        wr = world_tops[0]
                        score = wr['score']
                        mapAT.WR = score
                        if score <= track['AuthorTime']:
                            set_at_beaten(mapAT, track, world_tops)
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
    mapAT.WR = world_tops[0]['score']
    mapAT.WR_Player = world_tops[0]['accountId']
    mapAT.ATBeatenUsers = ",".join(accounts)
    mapAT.ATBeatenTimestamp = time.time()
    mapAT.UploadedToNadeo = True


# adsf
