import asyncio
import json
import logging
from multiprocessing.managers import BaseManager
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.models import CachedValue, CotdChallenge, CotdChallengeRanking, MapTotalPlayers, TmxMap, TmxMapAT, TmxMapScrapeState
from getrecords.nadeoapi import LOCAL_DEV_MODE, get_and_save_all_challenge_records, get_challenge, get_challenge_players, get_challenge_records, get_cotd_current, get_map_records, get_totd_maps, run_nadeo_services_auth
from getrecords.view_logic import CURRENT_COTD_KEY, RECENTLY_BEATEN_ATS_CV_NAME, TRACK_UIDS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_recently_beaten_ats_query, get_tmx_map, get_tmx_map_pack_maps, get_unbeaten_ats_query, refresh_nb_players_inner, update_tmx_map

class Command(BaseCommand):
    help = "Run cotd quali bg job"
    loop = asyncio.new_event_loop()

    # def add_arguments(self, parser):
    #     parser.add_argument("poll_ids", nargs="+", type=int)

    def handle(self, *args, **options):
        while True:
            try:
                self.loop = asyncio.new_event_loop()
                run_cotd_quali_cache(self.loop)
                self.loop.run_forever()
            except Exception as e:
                logging.warn(f"Exception in main COTD quali BG job; sleeping and restarting. Exception: {e}")
                time.sleep(60)


def run_cotd_quali_cache(loop: asyncio.AbstractEventLoop):
    loop.create_task(cotd_quali_cache_main())

class OldCOTDInfoEx(Exception):
    pass

async def cotd_quali_cache_main():
    ''' Get info about the current / next COTD quali.
        Once it starts, scrape quali rankings over time.
        Once it ends, enter waiting period till next COTD.
    '''
    while True:
        old_cotd_sleep = 3.14 * 60
        try:
            logging.info(f"Getting next COTD info.")
            next_cotd = await get_cotd_current()
            while next_cotd is None:
                await asyncio.sleep(3.14)
                next_cotd = await get_cotd_current()
            # set to 1 minute after the hour
            start_date = next_cotd['challenge']['startDate']
            end_date = next_cotd['challenge']['endDate']
            match_gen = next_cotd['competition']['matchesGenerationDate']
            challenge_id = next_cotd['challenge']['id']
            now = time.time()
            logging.info(f"Next COTD info: {[challenge_id, start_date, end_date, int(start_date - now)]}")
            await update_cached_next_cotd(next_cotd)

            # if we're before COTD, wait till it starts; sleep to 10 sec before to request TOTD info
            sleep_before = (start_date - 10) - now
            if sleep_before > 0:
                logging.info(f"Waiting for {int(sleep_before) // 60} minutes for COTD to start...")
                await asyncio.sleep(sleep_before)
            # if we're after COTD, then new details aren't available yet, so throw an exception so we sleep and loop
            if end_date < now:
                old_cotd_sleep = max(end_date + 60 * 60 * 4 - now, old_cotd_sleep)
                raise OldCOTDInfoEx(f"Got old COTD info")
            # get the new TOTD info
            # set this in the future
            totd_start_date = end_date
            totd_end_date = end_date
            totd_uid = ""
            # while start date not in correct range
            i = 0
            while not (totd_start_date < start_date < totd_end_date):
                if i > 0: await asyncio.sleep(10)
                totd_info = await get_totd_maps(2)
                totd_map = get_most_recent_totd_from_totd_maps_resp(totd_info)
                totd_start_date = totd_map['startTimestamp']
                totd_end_date = totd_map['endTimestamp']
                totd_uid = totd_map['mapUid']
                i += 1
                if i > 10:
                    raise Exception(f"Tried to get TOTD 10 times and couldn't!")

            # cotd has started!
            logging.info(f"Got current TOTD: {json.dumps(totd_map)}; COTD has started...")
            await run_cache_during_cotd_quali(challenge_id, totd_uid, start_date, end_date)
            logging.info(f"COTD has ended")

        except OldCOTDInfoEx as e:
            logging.warn(f"Got old cotd. Sleeping {old_cotd_sleep / 60 + 3.14} minutes.")
            await asyncio.sleep(old_cotd_sleep)
        except Exception as e:
            logging.warn(f"Failed to get next COTD info ({e}). Sleeping 3.14 minutes.")
            traceback.print_exception(e, limit=3)
        await asyncio.sleep(3.14 * 60)


async def update_cached_next_cotd(next_cotd):
    _, created = await CachedValue.objects.aupdate_or_create({'value': json.dumps(next_cotd)}, name=CURRENT_COTD_KEY)


def get_most_recent_totd_from_totd_maps_resp(totd_info):
    # https://webservices.openplanet.dev/live/campaigns/totds
    days = totd_info['monthList'][0]['days']
    maps = [d for d in days if 'mapUid' in d and len(d['mapUid']) > 10]
    return maps[-1]


async def run_cache_during_cotd_quali(cid, uid, start_date, end_date):
    challenge, created = await CotdChallenge.objects.aget_or_create(
        challenge_id = cid, uid = uid, start_date = start_date, end_date = end_date
    )
    try:
        if challenge.leaderboard_id < 0:
            resp = await get_challenge(challenge.challenge_id)
            challenge.leaderboard_id = resp['leaderboardId']
            challenge.name = resp['name']
            await challenge.asave()
    except Exception as e:
        logging.warn(f"Exception updating challenge name and leaderboardId: {e}")

    main_loop_period = 20 # seconds

    while time.time() < (end_date + 30):
        loop_start = time.time()
        logging.info(f"COTD results cache runner starting at {loop_start}, running for another {end_date - loop_start} seconds")

        # loop and get all records for current size and save
        await get_and_save_all_challenge_records(challenge)

        # report and sleep
        loop_end = time.time()
        loop_duration = loop_end - loop_start
        sleep_for = max(main_loop_period - loop_duration, 10)
        logging.info(f"COTD results cache runner loop duration: {loop_duration} s")
        if sleep_for > 0:
            logging.info(f"COTD results cache runner sleeping for {sleep_for} s")
            await asyncio.sleep(sleep_for)
