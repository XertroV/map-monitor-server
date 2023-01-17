import asyncio
from datetime import timedelta
import json
import time
from typing import Coroutine
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseNotAllowed, HttpRequest, HttpResponseForbidden
from django.core import serializers
from django.db.models import Model
from django.utils import timezone

from getrecords.openplanet import check_token

from .models import MapTotalPlayers
from .nadeoapi import nadeo_get_nb_players_for_map


def json_resp(m: Model):
    return JsonResponse(serializers.serialize('python', [m])[0]['fields'])


def requires_openplanet_auth(f):
    def _inner(request: HttpRequest, *args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('openplanet '):
            return HttpResponseForbidden(json.dumps({'error': 'authorization required'}))
        token = auth.replace('openplanet ', '')
        tr = run_async(check_token(token))
        if tr is None:
            return HttpResponseForbidden(json.dumps({'error': 'token did not validate'}))
        request.tr = tr
        return f(request, *args, **kwargs)
    return _inner


# Create your views here.
def index(request):
    return JsonResponse(dict(test=True))


def get_nb_players(request, map_uid):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    mtp = get_object_or_404(MapTotalPlayers, uid=map_uid)
    return json_resp(mtp)

@requires_openplanet_auth
def refresh_nb_players(request, map_uid):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    mtps = MapTotalPlayers.objects.filter(uid=map_uid)
    last_known = 0
    mtp = None
    if mtps.count() > 0:
        mtp = mtps[0]
        last_known = mtp.nb_players
        delta = time.time() - mtp.updated_ts
        in_prog = mtp.last_update_started_ts > mtp.updated_ts and (time.time() - mtp.last_update_started_ts < 60)
        # if it's been less than 15 minutes, or an update is in prog, return cached
        if in_prog or delta < (0 * 15 * 60):
            return json_resp(mtp)
    else:
        mtp = MapTotalPlayers(uid=map_uid)
    mtp.last_update_started_ts = time.time()
    mtp.save()
    records = run_async(nadeo_get_nb_players_for_map(map_uid))
    last_player = records['tops'][0]['top'][0]
    mtp.nb_players = last_player['position']
    mtp.last_highest_score = last_player['score']
    mtp.updated_ts = time.time()
    mtp.save()
    return json_resp(mtp)


def run_async(coro: Coroutine):
    loop = asyncio.new_event_loop()
    task = loop.create_task(coro)
    loop.run_until_complete(task)
    return task.result()
