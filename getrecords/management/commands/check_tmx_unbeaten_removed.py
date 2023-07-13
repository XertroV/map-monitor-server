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
from getrecords.nadeoapi import LOCAL_DEV_MODE, get_map_records
from getrecords.tmx_maps import tmx_date_to_ts
from getrecords.unbeaten_ats import TMXIDS_UNBEATABLE_ATS
from getrecords.utils import chunk, model_to_dict
from getrecords.view_logic import RECENTLY_BEATEN_ATS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_recently_beaten_ats_query, get_tmx_map, get_unbeaten_ats_query, refresh_nb_players_inner

class Command(BaseCommand):
    help = "Run the tmx unbeaten checker"

    # def add_arguments(self, parser):
    #     parser.add_argument("poll_ids", nargs="+", type=int)

    def _run_async(self, coro: Coroutine):
        loop = asyncio.new_event_loop()
        task = loop.create_task(coro)
        loop.run_until_complete(task)
        return task.result()

    def handle(self, *args, **options):
        logging.info(f"Starting TMX unbeaten checker")
        print(f"Starting TMX unbeaten checker")
        self._run_async(check_tmx_unbeaten_loop())
