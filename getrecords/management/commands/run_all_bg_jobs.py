import asyncio
import json
import logging
from multiprocessing.managers import BaseManager
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.management.commands.cotd_quali_cache import run_cotd_quali_cache
from getrecords.models import CachedValue, CotdChallenge, CotdChallengeRanking, MapTotalPlayers, TmxMap, TmxMapAT, TmxMapScrapeState
from getrecords.nadeoapi import LOCAL_DEV_MODE, get_challenge_players, get_challenge_records, get_cotd_current, get_map_records, get_totd_maps, run_nadeo_services_auth
from getrecords.tmx_maps import tmx_date_to_ts
from getrecords.unbeaten_ats import TMX_MAPPACKID_UNBEATABLE_ATS, TMXIDS_UNBEATABLE_ATS
from getrecords.utils import chunk, model_to_dict
from getrecords.view_logic import RECENTLY_BEATEN_ATS_CV_NAME, TRACK_UIDS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_recently_beaten_ats_query, get_tmx_map, get_tmx_map_pack_maps, get_unbeaten_ats_query, refresh_nb_players_inner, update_tmx_map

from getrecords.management.commands.tmx_scraper import _run_async, run_all_tmx_scrapers

class Command(BaseCommand):
    help = "Run all bg jobs"
    loop = asyncio.new_event_loop()

    # def add_arguments(self, parser):
    #     parser.add_argument("poll_ids", nargs="+", type=int)

    def handle(self, *args, **options):
        run_all_bg_jobs_main(self.loop)
        self.loop.run_forever()


def run_all_bg_jobs_main(loop: asyncio.AbstractEventLoop):
    run_cotd_quali_cache(loop)
    run_all_tmx_scrapers(loop)



# def run_cotd_quali_cache(loop: asyncio.AbstractEventLoop):
#     _run_async(loop, cotd_quali_cache_main())


# async def cotd_quali_cache_main():
#     ''' Get info about the current / next COTD quali.
#         Once it starts, scrape quali rankings over time.
#         Once it ends, enter waiting period till next COTD.
#     '''
#     while True:
#         try:
#             logging.info(f"Getting next COTD info.")
#             next_cotd = await get_cotd_current()
#             # set to 1 minute after the hour
#             start_date = next_cotd['challenge']['startDate']
#             end_date = next_cotd['challenge']['endDate']
#             match_gen = next_cotd['competition']['matchesGenerationDate']
#             challenge_id = next_cotd['challenge']['id']
#             now = time.time()
#             logging.info(f"Next COTD info: {[challenge_id, start_date, end_date, int(now - start_date)]}")

#             # if we're before COTD, wait till it starts; sleep to 10 sec before to request TOTD info
#             sleep_before = (start_date - 10) - now
#             if sleep_before > 0:
#                 logging.info(f"Waiting for {sleep_before} seconds for COTD to start...")
#                 await asyncio.sleep(sleep_before)
#             # if we're after COTD, then new details aren't available yet, so throw an exception so we sleep and loop
#             if end_date < now:
#                 raise Exception(f"Got old COTD info")
#             # get the new TOTD info
#             # set this in the future
#             totd_start_date = end_date
#             totd_end_date = end_date
#             totd_uid = ""
#             # while start date not in correct range
#             i = 0
#             while not (totd_start_date < start_date < totd_end_date):
#                 if i > 0: await asyncio.sleep(10)
#                 totd_info = await get_totd_maps(2)
#                 totd_map = get_most_recent_totd_from_totd_maps_resp(totd_info)
#                 totd_start_date = totd_map['startTimestamp']
#                 totd_end_date = totd_map['endTimestamp']
#                 totd_uid = totd_map['mapUid']
#                 i += 1
#                 if i > 10:
#                     raise Exception(f"Tried to get TOTD 10 times and couldn't!")

#             # cotd has started!
#             logging.info(f"Got current TOTD: {json.dumps(totd_map)}; COTD has started...")
#             await run_cache_during_cotd_quali(challenge_id, totd_uid, start_date, end_date)
#             logging.info(f"COTD has ended")

#         except Exception as e:
#             logging.warn(f"Failed to get next COTD info ({e}). Sleeping 3.14 minutes.")
#             await asyncio.sleep(3.14 * 60)


# def get_most_recent_totd_from_totd_maps_resp(totd_info):
#     # https://webservices.openplanet.dev/live/campaigns/totds
#     days = totd_info['monthList'][0]['days']
#     maps = [d for d in days if 'mapUid' in d and len(d['mapUid'] > 10)]
#     return maps[-1]


# async def run_cache_during_cotd_quali(cid, uid, start_date, end_date):
#     challenge = CotdChallenge.objects.get_or_create(
#         challenge_id = cid, uid = uid, start_date = start_date, end_date = end_date
#     )
#     last_nb_players = 64
#     main_loop_period = 10 # seconds
#     loop = asyncio.get_event_loop()

#     while time.time() < (end_date + 30):
#         loop_start = time.time()
#         logging.info(f"COTD results cache runner starting at {loop_start}")

#         # loop and get all records for current size
#         c_players = await get_challenge_players(cid, uid)
#         last_nb_players = c_players['cardinal']
#         offsets = list(range(0, last_nb_players+100, 100))
#         requests = [get_challenge_records(cid, uid, 100, o) for o in offsets]
#         responses = await asyncio.gather(*requests, return_exceptions=True)

#         # save records
#         loop_mid = time.time()
#         new_records = [rec for resp, offset in zip(responses, offsets) for rec in gen_cotd_quali_challenge_block(challenge, resp, offset, int(loop_mid))]
#         CotdChallengeRanking.objects.bulk_create(new_records)

#         # report and sleep
#         loop_end = time.time()
#         loop_duration = loop_end - loop_start
#         sleep_for = main_loop_period - loop_duration
#         logging.info(f"COTD results cache runner loop duration: {loop_duration} s")
#         if sleep_for > 0:
#             logging.info(f"COTD results cache runner sleeping for {sleep_for} s")
#             await asyncio.sleep(sleep_for)


# async def gen_cotd_quali_challenge_block(challenge, resp, offset, loop_mid) -> list[CotdChallengeRanking]:
#     return [
#         CotdChallengeRanking(challenge=challenge, req_timestamp=loop_mid,
#                              rank=record['rank'], score=record['score'], player=record['player'])
#         for record in resp
#     ]
