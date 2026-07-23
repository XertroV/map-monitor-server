import asyncio
import json
import logging
import time
import traceback

from django.core.management.base import BaseCommand

from getrecords.cotd_live_cache import (
    COTD_HISTORY_PERSIST_PERIOD,
    COTD_SCRAPE_PERIOD,
    set_live_rankings,
)
from getrecords.models import CachedValue, CotdChallenge
from getrecords.nadeoapi import (
    fetch_all_challenge_records,
    get_challenge,
    get_cotd_current,
    get_totd_maps,
    persist_challenge_records,
)
from getrecords.view_logic import CURRENT_COTD_KEY


class Command(BaseCommand):
    help = "Run cotd quali bg job"
    loop = asyncio.new_event_loop()

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
            start_date = next_cotd['challenge']['startDate']
            end_date = next_cotd['challenge']['endDate']
            challenge_id = next_cotd['challenge']['id']
            now = time.time()
            logging.info(f"Next COTD info: {[challenge_id, start_date, end_date, int(start_date - now)]}")
            await update_cached_next_cotd(next_cotd)

            sleep_before = (start_date - 10) - now
            if sleep_before > 0:
                logging.info(f"Waiting for {int(sleep_before) // 60} minutes for COTD to start...")
                await asyncio.sleep(sleep_before)
            if end_date < now:
                old_cotd_sleep = max(end_date + 60 * 60 * 4 - now, old_cotd_sleep)
                raise OldCOTDInfoEx(f"Got old COTD info")
            totd_start_date = end_date
            totd_end_date = end_date
            totd_uid = ""
            i = 0
            while not (totd_start_date < start_date < totd_end_date):
                if i > 0:
                    await asyncio.sleep(10)
                totd_info = await get_totd_maps(2)
                totd_map = get_most_recent_totd_from_totd_maps_resp(totd_info)
                totd_start_date = totd_map['startTimestamp']
                totd_end_date = totd_map['endTimestamp']
                totd_uid = totd_map['mapUid']
                i += 1
                if i > 10:
                    raise Exception(f"Tried to get TOTD 10 times and couldn't!")

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
        challenge_id=cid, uid=uid, start_date=start_date, end_date=end_date
    )
    try:
        if challenge.leaderboard_id < 0:
            resp = await get_challenge(challenge.challenge_id)
            challenge.leaderboard_id = resp['leaderboardId']
            challenge.name = resp['name']
            await challenge.asave()
    except Exception as e:
        logging.warn(f"Exception updating challenge name and leaderboardId: {e}")

    last_persisted_ts = 0
    while True:
        now = time.time()
        past_end = now >= end_date
        if now >= (end_date + 30) and last_persisted_ts > 0:
            break

        loop_start = time.time()
        logging.info(
            f"COTD results cache runner starting at {loop_start}, "
            f"running for another {end_date - loop_start} seconds"
        )

        scrape_t0 = time.time()
        req_ts, cardinal, new_records, json_records = await fetch_all_challenge_records(challenge)
        scrape_ms = (time.time() - scrape_t0) * 1000

        redis_t0 = time.time()
        set_live_rankings(
            challenge.challenge_id,
            challenge.uid,
            req_timestamp=req_ts,
            cardinal=cardinal,
            records=json_records,
        )
        redis_write_ms = (time.time() - redis_t0) * 1000

        should_persist = (
            last_persisted_ts == 0
            or (req_ts - last_persisted_ts) >= COTD_HISTORY_PERSIST_PERIOD
            or past_end
        )
        persist_ms = 0.0
        did_persist = False
        if should_persist and new_records:
            persist_t0 = time.time()
            await persist_challenge_records(new_records)
            persist_ms = (time.time() - persist_t0) * 1000
            last_persisted_ts = req_ts
            did_persist = True

        loop_duration = time.time() - loop_start
        logging.info(
            "COTD loop cardinal=%s scrape_ms=%.1f redis_write_ms=%.1f did_persist=%s "
            "persist_ms=%.1f row_count=%s loop_s=%.3f req_ts=%s",
            cardinal,
            scrape_ms,
            redis_write_ms,
            did_persist,
            persist_ms,
            len(new_records),
            loop_duration,
            req_ts,
        )

        if past_end and did_persist:
            break
        if now >= (end_date + 30):
            break

        sleep_for = max(COTD_SCRAPE_PERIOD - loop_duration, 10)
        if sleep_for > 0:
            logging.info(f"COTD results cache runner sleeping for {sleep_for} s")
            await asyncio.sleep(sleep_for)
