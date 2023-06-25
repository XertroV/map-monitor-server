import asyncio
import logging
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.models import TmxMap, TmxMapScrapeState

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
        state = get_scrape_state()
        self._run_async(run_tmx_scraper(state))
        
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


def get_scrape_state():
    state = TmxMapScrapeState.objects.filter(Name="main").first()
    if state is None:
        state = TmxMapScrapeState(Name="main", LastScraped=0)
        state.save()
    return state

async def run_tmx_scraper(state: TmxMapScrapeState):
    while True:
        try:
            latest_map = await get_latest_map_id()
            if latest_map > state.LastScraped:
                await scrape_range(state, latest_map)
        except Exception as e:
            logging.warn(f"Exception in txm scraper: {e}. Sleeping for 300s and trying again")
        await asyncio.sleep(300)

async def scrape_range(state: TmxMapScrapeState, latest: int):
    while state.LastScraped < latest:
        # max 50 entries
        to_scrape = list(range(state.LastScraped + 1, latest + 1)[:48])
        await update_maps_from_tmx(to_scrape)
        state.LastScraped = to_scrape[-1]
        await state.asave()

async def get_latest_map_id() -> int:
    async with get_session() as session:
        async with session.get("https://trackmania.exchange/mapsearch2/search?api=on") as resp:
            if resp.status == 200:
                j = await resp.json()
                return j['results'][0]['TrackID']
            else:
                logging.warning(f"Could not get latest maps: {resp.status} code")

async def update_maps_from_tmx(tids_or_uids: list[int | str]):
    tids_str = ','.join(map(str, tids_or_uids))
    async with get_session() as session:
        try:
            async with session.get(f"https://trackmania.exchange/api/maps/get_map_info/multi/{tids_str}", timeout=10.0) as resp:
                if resp.status == 200:
                    await _add_maps_from_json(dict(results=await resp.json()), False)
                else:
                    logging.warning(f"Could not get map infos: {resp.status} code.")
                    print(f"RETRY ME: {tids_str}")
                    return update_maps_from_tmx(tids_or_uids)
        except asyncio.TimeoutError as e:
            logging.warning(f"TMX timeout for get map infos")
            return update_maps_from_tmx(tids_or_uids)



async def _add_maps_from_json(j: dict, add_to_random_maps = True, log_replacement = True):
    if 'results' not in j:
        logging.warning(f"Response didn't contain .results")
        return
    maps_j = j['results']
    track_ids = list()
    for map_j in maps_j:
        track_id = map_j['TrackID']
        track_ids.append(track_id)
        try:
            _map = TmxMap(**map_j)
            if not _map.Downloadable:
                continue
            await _map.asave()
        except Exception as e:
            logging.warn(f"Failed to save map: {map_j} -- exception: {e}")
            raise e
        # logging.info(f"Saved tmx map: {track_id}")
    logging.info(f"Saved tmx maps: {track_ids}")
        # map_in_db = await Map.find_one(Eq(Map.TrackID, track_id))
        # if map_in_db is not None:
        #     _map.id = map_in_db.id
        #     await _map.replace()
        #     if log_replacement:
        #         logging.info(f"Replacing map in db: {_map.TrackID}")
        # else:
        #     await _map.save()  # using insert_many later doesn't populate .id
        # if add_to_random_maps:
        #     fresh_random_maps.append(_map)
        # maps_to_cache.append(_map)
        # added_c += 1
        # if track_id in known_maps:
        #     continue
        # map_docs.append(_map)
        # known_maps.add(track_id)