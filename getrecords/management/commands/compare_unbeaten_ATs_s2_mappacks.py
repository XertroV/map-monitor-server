import asyncio
import json
import logging
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.http import get_session
from getrecords.management.commands.tmx_scraper import check_tmx_unbeaten_loop
from getrecords.models import CachedValue, MapTotalPlayers, TmxMap, TmxMapAT, TmxMapScrapeState
from getrecords.nadeoapi import LOCAL_DEV_MODE, TMX_MAPPACK_UNBEATEN_ATS_APIKEY, get_map_records
from getrecords.tmx_maps import tmx_date_to_ts
from getrecords.unbeaten_ats import TMXIDS_UNBEATABLE_ATS
from getrecords.utils import chunk, model_to_dict
from getrecords.view_logic import RECENTLY_BEATEN_ATS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_recently_beaten_ats_query, get_tmx_map, get_tmx_map_pack_maps, get_unbeaten_ats_query, refresh_nb_players_inner

class Command(BaseCommand):
    help = "compare 3306 and 4412"

    def _run_async(self, coro: Coroutine):
        loop = asyncio.new_event_loop()
        task = loop.create_task(coro)
        loop.run_until_complete(task)
        return task.result()

    def handle(self, *args, **options):
        logging.info(f"compare_map_packs")
        print(f"compare_map_packs")
        self._run_async(compare_map_packs())

async def compare_map_packs():
    mp1 = 3306
    mp2 = 4412
    print(f"getting maps for {mp1} and {mp2}")
    mp1_maps = await get_tmx_map_pack_maps(mp1)
    with open(f"mp{mp1}_maps.json", "w") as f:
        json.dump(mp1_maps, f)
    print(f"got {len(mp1_maps)} maps for {mp1}")
    mp2_maps = await get_tmx_map_pack_maps(mp2, TMX_MAPPACK_UNBEATEN_ATS_APIKEY)
    with open(f"mp{mp2}_maps.json", "w") as f:
        json.dump(mp2_maps, f)
    print(f"got {len(mp2_maps)} maps for {mp2}")
    mp1_mapids = [m['TrackID'] for m in mp1_maps]
    mp2_mapids = [m['TrackID'] for m in mp2_maps]
    mp1_mapids_set = set(mp1_mapids)
    mp2_mapids_set = set(mp2_mapids)
    mp1_only = mp1_mapids_set - mp2_mapids_set
    mp2_only = mp2_mapids_set - mp1_mapids_set
    print(f"mp1 only: {len(mp1_only)} | {mp1_only}")
    print(f"mp2 only: {len(mp2_only)} | {mp2_only}")
