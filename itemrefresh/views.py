import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Coroutine
from django.http import HttpRequest, HttpResponseNotAllowed, JsonResponse, HttpResponseBadRequest, FileResponse
from django.shortcuts import render
import requests
import zipfile

# Create your views here.

def create_map(request: HttpRequest):
    if request.method != "POST": return HttpResponseNotAllowed(['POST'], "POST only")
    item_paths: list[str] = list()
    try:
        item_paths = json.loads(request.body)
    except Exception as e:
        return HttpResponseBadRequest("cannot parse item paths")
    if not isinstance(item_paths, list):
        return HttpResponseBadRequest("item paths not a list")
    map_bytes = generate_map_bytes(item_paths)
    return FileResponse(map_bytes)






def run_async(coro: Coroutine):
    loop = asyncio.new_event_loop()
    task = loop.create_task(coro)
    loop.run_until_complete(task)
    return task.result()
