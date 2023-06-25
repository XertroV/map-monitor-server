import asyncio
from datetime import timedelta
import json
import logging
import time
from typing import Coroutine, Optional
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseNotAllowed, HttpRequest, HttpResponseForbidden, HttpResponse, HttpResponseNotFound
from django.core import serializers
from django.db.models import Model
from django.utils import timezone
from django.db import transaction

from getrecords.openplanet import ARCHIVIST_PLUGIN_ID, MAP_MONITOR_PLUGIN_ID, TokenResp, check_token, sha_256
from getrecords.s3 import upload_ghost_to_s3
from getrecords.utils import sha_256_b_ts

from .models import Challenge, CotdQualiTimes, Ghost, MapTotalPlayers, Track, TrackStats, User, UserStats, UserTrackPlay
from .nadeoapi import LOCAL_DEV_MODE, nadeo_get_nb_players_for_map, nadeo_get_surround_for_map
import getrecords.nadeoapi as nadeoapi

# 5 min
NB_PLAYERS_CACHE_SECONDS = 5 * 60
# 8 hrs
NB_PLAYERS_MAX_CACHE_SECONDS = 8 * 60 * 60
# 10 sec
QUALI_TIMES_CACHE_SECONDS = 10

def model_to_dict(m: Model):
    return serializers.serialize('python', [m])[0]['fields']


def json_resp(m: Model):
    return JsonResponse(model_to_dict(m))

def json_resp_mtp(m: MapTotalPlayers):
    resp = model_to_dict(m)
    resp['refresh_in'] = NB_PLAYERS_CACHE_SECONDS # - (time.time() - m.updated_ts)
    if (m.nb_players > 10000):
        resp['refresh_in'] = NB_PLAYERS_MAX_CACHE_SECONDS
    # print(f"Response: {json.dumps(resp)}")
    return JsonResponse(resp)

def json_resp_q_times(qt: CotdQualiTimes, ch: Challenge, refresh_in=QUALI_TIMES_CACHE_SECONDS):
    resp = model_to_dict(qt)
    resp['json_payload'] = json.loads(resp['json_payload'])
    resp['refresh_in'] = refresh_in
    resp['challenge'] = model_to_dict(ch)
    return JsonResponse(resp)


def log_auth_debug(request: HttpRequest):
    if not LOCAL_DEV_MODE: return
    print(f"Auth header: {request.headers.get('Authorization', None)}")
    print(f"headers: {request.headers}")


def requires_openplanet_auth(plugin_id: int):
    def requires_openplanet_auth_inner(f):
        def _inner(request: HttpRequest, *args, **kwargs):
            auth = request.headers.get('Authorization', '')
            if not auth.startswith('openplanet '):
                if LOCAL_DEV_MODE: log_auth_debug(request)
                return HttpResponseForbidden(json.dumps({'error': 'authorization required'}))
            token = auth.replace('openplanet ', '')
            tr: Optional[TokenResp] = run_async(check_token(token, plugin_id))
            if tr is None:
                if LOCAL_DEV_MODE: log_auth_debug(request)
                return HttpResponseForbidden(json.dumps({'error': 'token did not validate'}))
            request.tr = tr
            user = User.objects.filter(wsid=tr.account_id).first()
            if user is None:
                user = User(wsid=tr.account_id, display_name=tr.display_name)
            else:
                user.last_seen_ts = time.time()
            if tr.display_name != user.display_name:
                user.display_name = tr.display_name
            user.save()
            return f(request, *args, user=user, **kwargs)
        return _inner
    return requires_openplanet_auth_inner


# Create your views here.
def index(request):
    return JsonResponse(dict(test=True))


def get_cotd_leaderboards(request, challenge_id: int, map_uid: str):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    # return CallCompApiPath("/api/challenges/" + challengeid + "/records/maps/" + mapid + "?" + LengthAndOffset(length, offset));
    challenge_res = Challenge.objects.filter(challenge_id=challenge_id)
    challenge = None
    if (challenge_res.count() > 0):
        challenge = challenge_res[0]
    else:
        challenge = get_and_cache_challenge(challenge_id)
    if challenge is None:
        return HttpResponseNotFound(f"Could not find challenge with id: {challenge_id}")

    length = int(request.GET.get('length', '10'))
    offset = int(request.GET.get('offset', '0'))

    q_times = CotdQualiTimes.objects.filter(uid=map_uid, challenge_id=challenge_id, length=length, offset=offset).first()

    if q_times is None:
        q_times = CotdQualiTimes(uid=map_uid, challenge_id=challenge_id, length=length, offset=offset)
    else:
        delta = time.time() - q_times.updated_ts
        in_prog = q_times.last_update_started_ts > q_times.updated_ts and (time.time() - q_times.last_update_started_ts < 60)
        challenge_over = q_times.updated_ts > (challenge.end_ts + QUALI_TIMES_CACHE_SECONDS * 3)
        if not LOCAL_DEV_MODE and (challenge_over or in_prog or delta < QUALI_TIMES_CACHE_SECONDS):
            return json_resp_q_times(q_times, challenge, refresh_in=(999999 if challenge_over else QUALI_TIMES_CACHE_SECONDS))

    logging.info(f"Updating quali_times: {q_times}")

    q_times.last_update_started_ts = time.time()
    q_times.save()
    records: list[dict] = run_async(nadeoapi.get_challenge_records(challenge_id, map_uid, length, offset))
    for rec in records:
        del rec['uid']
    q_times.json_payload = json.dumps(records)
    q_times.updated_ts = time.time()
    q_times.save()
    return json_resp_q_times(q_times, challenge)



def get_and_cache_challenge(_id: int):
    logging.info(f"Getting challnge: {_id}")
    resp = run_async(nadeoapi.get_challenge(_id))
    logging.info(f"Got challenge response: {resp}")
    if resp is None:
        return None
    challenge = Challenge(challenge_id=_id, uid=resp['uid'], name=resp['name'], leaderboard_id=resp['leaderboardId'],
                          start_ts = resp['startDate'], end_ts=resp['endDate'])
    try:
        challenge.save()
    except Exception as e:
        logging.error(f"Failed to save challenge: {e}, returning it anyway")
    return challenge



def get_nb_players(request, map_uid):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    mtp = get_object_or_404(MapTotalPlayers, uid=map_uid)
    return json_resp(mtp)

# @requires_openplanet_auth(MAP_MONITOR_PLUGIN_ID)
def refresh_nb_players(request, map_uid, user=None):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    mtps = MapTotalPlayers.objects.filter(uid=map_uid)
    last_known = 0
    mtp = None
    if mtps.count() > 0:
        mtp = mtps[0]
        last_known = mtp.nb_players
        delta = time.time() - mtp.updated_ts
        in_prog = mtp.last_update_started_ts > mtp.updated_ts and (time.time() - mtp.last_update_started_ts < 60)
        # if it's been less than 5 minutes, or an update is in prog, return cached
        if not LOCAL_DEV_MODE and (in_prog or delta < NB_PLAYERS_CACHE_SECONDS):
            return json_resp_mtp(mtp)
    else:
        mtp = MapTotalPlayers(uid=map_uid)
    mtp.last_update_started_ts = time.time()
    mtp.save()
    records = run_async(nadeo_get_nb_players_for_map(map_uid))
    mtp.nb_players = 0
    mtp.last_highest_score = 0
    tops = records['tops'][0]['top']
    if (len(tops) > 1):
        last_player = tops[0]
        mtp.nb_players = last_player['position']
        mtp.last_highest_score = last_player['score']
    mtp.updated_ts = time.time()
    mtp.save()
    return json_resp_mtp(mtp)


def get_surround_score(request, map_uid, score):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    return JsonResponse(run_async(nadeo_get_surround_for_map(map_uid, score)))



def get_track_mb_create(uid: str) -> Track:
    track = Track.objects.filter(uid=uid).first()
    if track is None:
        track = Track(uid=uid)
        track_info = run_async(nadeoapi.core_get_maps_by_uid([uid]))
        # logging.warn(f"track_info: {track_info}")
        if track_info is list and len(track_info) > 0:
            track_info2: dict = track_info[0]
            track.map_id = track_info2.get('mapId', None)
            track.name = track_info2.get('name', None)
            track.url = track_info2.get('fileUrl', None)
            track.thumbnail_url = track_info2.get('thumbnailUrl', None)
        track.save()
    return track


def increment_stats(user: User, track: Track, ghost: Ghost):
    utp = UserTrackPlay.objects.filter(user=user, track=track).first()

    with transaction.atomic():
        track_stats = TrackStats.objects.filter(track=track).first()
        if track_stats is None: track_stats = TrackStats(track=track)
        track_stats.total_runs += 1 if not ghost.segmented else 0
        track_stats.segmented_runs += 1 if ghost.segmented else 0
        track_stats.partial_runs += 1 if ghost.partial else 0
        if not ghost.segmented:
            track_stats.total_time += ghost.duration
        if utp is None:
            track_stats.unique_users += 1
        track_stats.save()

    with transaction.atomic():
        user_stats = UserStats.objects.filter(user=user).first()
        if user_stats is None: user_stats = UserStats(user=user)
        user_stats.total_runs += 1 if not ghost.segmented else 0
        user_stats.segmented_runs += 1 if ghost.segmented else 0
        user_stats.partial_runs += 1 if ghost.partial else 0
        if not ghost.segmented:
            user_stats.total_time += ghost.duration
        if utp is None:
            user_stats.unique_maps += 1
        user_stats.save()


@requires_openplanet_auth(ARCHIVIST_PLUGIN_ID)
def ghost_upload(request: HttpRequest, map_uid: str, score: int, user: User):
    if request.method != "POST": return HttpResponseNotAllowed(['POST'])
    now = int(time.time())
    partial = request.GET.get('partial', 'false').lower() == 'true'
    segmented = request.GET.get('segmented', 'false').lower() == 'true'
    ghost_data = request.body
    track = get_track_mb_create(map_uid)
    ghost_hash = sha_256_b_ts(ghost_data, now)
    s3_url = upload_ghost_to_s3(ghost_hash, ghost_data)
    ghost = Ghost(user=user, track=track, url=s3_url,
                  timestamp=now, hash_hex=ghost_hash,
                  partial=partial, segmented=segmented,
                  duration=score, size_bytes=len(ghost_data))
    ghost.save()
    # do this before we make the UTP record so we can test if we need to increment the unique_* properties of TrackStats and UserStats
    increment_stats(user, track, ghost)
    utp = UserTrackPlay(user=user, track=track, partial=partial, segmented=segmented, score=score, ghost=ghost, timestamp=now)
    utp.save()
    return json_resp(ghost)




@requires_openplanet_auth(ARCHIVIST_PLUGIN_ID)
def register_token_archivist(request, user: User):
    if user is None: return JsonErrorResponse({'error': 'user was None'}, status_code=403)
    return JsonResponse({'username': user.display_name})

@requires_openplanet_auth(MAP_MONITOR_PLUGIN_ID)
def register_token_mm(request, user: User):
    if user is None: return JsonErrorResponse({'error': 'user was None'}, status_code=403)
    return JsonResponse({'username': user.display_name})







class JsonErrorResponse(JsonResponse):
    def __init__(self, *args, status_code=500, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_code = status_code



def run_async(coro: Coroutine):
    loop = asyncio.new_event_loop()
    task = loop.create_task(coro)
    loop.run_until_complete(task)
    return task.result()
