import asyncio
import json
import logging
import time
import traceback
from typing import Coroutine

from django.core.management.base import BaseCommand, CommandError

from getrecords.kacky import update_kacky_reloaded_5

class Command(BaseCommand):
    help = "test kr5 stuff"

    def _run_async(self, coro: Coroutine):
        loop = asyncio.new_event_loop()
        task = loop.create_task(coro)
        loop.run_until_complete(task)
        return task.result()

    def handle(self, *args, **options):
        logging.info(f"test kr5")
        self._run_async(test_kr5())

async def test_kr5():
    await update_kacky_reloaded_5()
