import asyncio
import base64
from datetime import timedelta
from functools import reduce
import json
import logging
import operator
from random import shuffle
import time
from typing import Coroutine, Optional
from PIL import Image
from io import BytesIO
import numpy as np
import zipfile

from numpy import random

from django.db import IntegrityError
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect, JsonResponse, HttpResponseNotAllowed, HttpRequest, HttpResponseForbidden, HttpResponse, HttpResponseNotFound, HttpResponseBadRequest, HttpResponsePermanentRedirect, FileResponse
from django.core import serializers
from django.db.models import Model, Q
from django.utils import timezone
from django.db import transaction
from django.views.decorators.cache import cache_page

from getrecords.http import get_session, http_head_okay
from getrecords.management.commands.tmx_scraper import get_scrape_state
from getrecords.openplanet import ARCHIVIST_PLUGIN_ID, MAP_MONITOR_PLUGIN_ID, TokenResp, check_token, sha_256
from getrecords.rmc_exclusions import EXCLUDE_FROM_RMC
from getrecords.s3 import upload_ghost_to_s3
from getrecords.tmx_maps import get_tmx_tags_cached, update_tmx_tag_lookup, update_tmx_tags_cached, tmx_tags_lookup
from getrecords.utils import model_to_dict, run_async, sha_256_b_ts
from mapmonitor.settings import CACHE_5_MIN, CACHE_8HRS_TTL, CACHE_COTD_TTL, CACHE_ICONS_TTL

from .models import CachedValue, Challenge, CotdChallenge, CotdChallengeRanking, CotdQualiTimes, Ghost, MapTotalPlayers, TmxMap, TmxMapAT, Track, TrackStats, User, UserStats, UserTrackPlay
from .nadeoapi import LOCAL_DEV_MODE, core_get_maps_by_uid, get_and_save_all_challenge_records, nadeo_get_nb_players_for_map, nadeo_get_surround_for_map
import getrecords.nadeoapi as nadeoapi
from .view_logic import CURRENT_COTD_KEY, NB_PLAYERS_CACHE_SECONDS, NB_PLAYERS_MAX_CACHE_SECONDS, RECENTLY_BEATEN_ATS_CV_NAME, TRACK_UIDS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_tmx_map, get_unbeaten_ats_query, refresh_nb_players_inner, QUALI_TIMES_CACHE_SECONDS, tmx_map_still_public


def json_resp(m: Model):
    return JsonResponse(model_to_dict(m))

def json_resp_mtp(m: MapTotalPlayers, refresh_soon: bool):
    resp = model_to_dict(m)
    resp['refresh_in'] = NB_PLAYERS_CACHE_SECONDS # - (time.time() - m.updated_ts)
    if refresh_soon:
        resp['refresh_in'] = CACHE_COTD_TTL
    if (m.nb_players > 100000):
        resp['refresh_in'] = NB_PLAYERS_MAX_CACHE_SECONDS
    # print(f"Response: {json.dumps(resp)}")
    return JsonResponse(resp)

def json_resp_q_times(qt: CotdQualiTimes, ch: Challenge, refresh_in=QUALI_TIMES_CACHE_SECONDS):
    resp = model_to_dict(qt)
    resp['json_payload'] = json.loads(resp['json_payload'])
    resp['refresh_in'] = refresh_in
    resp['challenge'] = model_to_dict(ch)
    return JsonResponse(resp)

def json_resp_q_times_from_v2(qt: list[dict], ch: CotdChallenge, length, offset, refresh_in=QUALI_TIMES_CACHE_SECONDS):
    resp = dict()
    resp['challenge_id'] = ch.challenge_id
    resp['uid'] = ch.uid
    resp['length'] = length
    resp['offset'] = offset
    resp['json_payload'] = qt
    resp['refresh_in'] = refresh_in
    resp['challenge'] = model_to_dict(ch)
    resp['challenge']['start_ts'] = ch.start_date
    resp['challenge']['end_ts'] = ch.end_date
    resp['created_ts'] = 0.0
    resp['updated_ts'] = 0.0
    resp['last_update_started_ts'] = 0.0
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


def get_players_cotd_quali_history(request: HttpRequest, wsid: str):
    # CotdChallengeRanking()
    pass

# dev interface (idempotent)
def get_all_cotd_results(req, challenge_id: int, map_uid: str):
    # 4942, QAT5zOEWq65ZVGRbF6QveBMlIHf
    if req.method != "GET": return HttpResponseNotAllowed(['GET'])
    rankings = get_or_insert_all_cotd_results(challenge_id, map_uid)
    return JsonResponse([challenge_ranking_to_json(r) for r in rankings], safe=False)

def get_or_create_challenge(challenge_id: int, map_uid: str):
    challenge = CotdChallenge.objects.filter(challenge_id=challenge_id, uid=map_uid).first()
    created = False
    if challenge is None:
        resp = run_async(nadeoapi.get_challenge(challenge_id))
        start_date = resp['startDate']
        end_date = resp['endDate']
        challenge, created = CotdChallenge.objects.get_or_create(
            challenge_id=challenge_id, uid=map_uid, start_date=start_date, end_date=end_date
        )
        if challenge.leaderboard_id < 0:
            resp = run_async(nadeoapi.get_challenge(challenge.challenge_id))
            challenge.leaderboard_id = resp['leaderboardId']
            challenge.name = resp['name']
            challenge.save()
    if created:
        logging.info(f"{'created' if created else 'got'} challenge {challenge.challenge_id}")
    return challenge, created

def get_or_insert_all_cotd_results(challenge_id: int, map_uid: str):
    challenge, created = get_or_create_challenge(challenge_id, map_uid)
    ranking = CotdChallengeRanking.objects.filter(challenge=challenge).first()
    rankings = []
    # check if we need to update
    if ranking is None or ranking.req_timestamp < (challenge.end_date):
        logging.info(f"Caching rankings")
        rankings = run_async(get_and_save_all_challenge_records(challenge))
    else:
        # logging.info(f"Using cached rankings")
        rankings = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=ranking.req_timestamp).all()
    return rankings

COTD_UPPER_LIMIT = 20000

@cache_page(CACHE_COTD_TTL)
def cached_api_challenges_id_records_maps_uid(request, challenge_id: int, map_uid: str):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    challenge = CotdChallenge.objects.filter(challenge_id=challenge_id, uid=map_uid).first()
    if challenge is None: return JsonResponse([], safe=False)
    length = int(request.GET.get('length', '10'))
    offset = int(request.GET.get('offset', '0'))
    just_cutoffs = 'cutoffs' in request.GET
    resp = []
    if just_cutoffs:
        latest_record = get_challenge_records_v2_latest(challenge)
        if latest_record is not None:
            worst_time = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=latest_record.req_timestamp).order_by('rank').last()
            resp = get_challenge_records_v2_by_ranks(challenge, list(range(64, COTD_UPPER_LIMIT, 64)) + [worst_time.rank])
    else:
        resp = get_challenge_records_v2(challenge, length, offset)
    return JsonResponse(resp, safe=False)


def get_challenge_records_v2(challenge, length, offset):
    latest_record = get_challenge_records_v2_latest(challenge)
    if latest_record is not None:
        rankings = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=latest_record.req_timestamp)[offset:offset+length].all()
        return [challenge_ranking_to_json(r) for r in rankings]
    return []

def get_challenge_records_v2_by_ranks(challenge, ranks: list[int]):
    latest_record = get_challenge_records_v2_latest(challenge)
    if latest_record is not None:
        rankings = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=latest_record.req_timestamp, rank__in=ranks).all()
        return [challenge_ranking_to_json(r) for r in rankings]
    return []

def get_challenge_records_v2_latest_req_ts(challenge) -> int | None:
    latest = get_challenge_records_v2_latest(challenge)
    if latest:
        return latest.req_timestamp
    return None

def get_challenge_records_v2_latest(challenge) -> CotdChallengeRanking | None:
    try:
        rank1 = CotdChallengeRanking.objects.filter(challenge=challenge).latest('req_timestamp')
        if rank1 is not None:
            return rank1
    except CotdChallengeRanking.DoesNotExist as e:
        return None


def challenge_ranking_to_json(r: CotdChallengeRanking):
    return {
        'score': r.score, 'time': r.score, 'rank': r.rank, 'player': r.player
    }


@cache_page(CACHE_COTD_TTL)
def cached_api_challenges_id_records_maps_uid_players(request: HttpRequest, challenge_id: int, map_uid: str):
    ''' caches /api/challenges/ID/records/maps/UID/players
    '''
    if request.method not in ["GET", "POST"]: return HttpResponseNotAllowed(['GET', 'POST'])
    challenge = CotdChallenge.objects.filter(challenge_id=challenge_id, uid=map_uid).first()
    resp = dict(
        uid=map_uid,
        cardinal=0,
        records=list()
    )
    if (challenge is None):
        return JsonResponse(resp)
        # return HttpResponseNotFound(f"Challenge / UID combination not found: {challenge_id}, {map_uid}")

    player_ids = []
    if request.method == "GET":
        player_ids = request.GET.get('players[]', '').split(',')
    elif request.method == "POST" and len(request.body) > 0:
        player_ids = json.loads(request.body).get('players', [])
    req_ts = get_challenge_records_v2_latest_req_ts(challenge)
    if req_ts is not None:
        records = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=req_ts, player__in=player_ids).all()
        resp['records'] = [challenge_ranking_to_json(r) for r in records]
        resp['cardinal'] = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=req_ts).count()
    return JsonResponse(resp)


@cache_page(CACHE_COTD_TTL)
def cached_api_cotd_current(request: HttpRequest):
    next_cotd = CachedValue.objects.filter(name=CURRENT_COTD_KEY).first()
    if next_cotd is not None:
        return HttpResponse(next_cotd.value, content_type='application/json')
    return JsonResponse(dict(error='not yet initialized'))



@cache_page(CACHE_COTD_TTL)
def get_cotd_leaderboards(request, challenge_id: int, map_uid: str):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])

    # check for v2
    challenge_v2 = CotdChallenge.objects.filter(challenge_id=challenge_id, uid=map_uid).first()
    if challenge_v2 is not None:
        if challenge_v2.leaderboard_id < 0:
            resp = run_async(nadeoapi.get_challenge(challenge_v2.challenge_id))
            challenge_v2.leaderboard_id = resp['leaderboardId']
            challenge_v2.name = resp['name']
            challenge_v2.save()
        length = int(request.GET.get('length', '10'))
        offset = int(request.GET.get('offset', '0'))
        v2_times = get_challenge_records_v2(challenge_v2, length, offset)
        return json_resp_q_times_from_v2(v2_times, challenge_v2, length, offset)

    # legacy v1
    # return CallCompApiPath("/api/challenges/" + challengeid + "/records/maps/" + mapid + "?" + LengthAndOffset(length, offset));
    challenge_res = Challenge.objects.filter(challenge_id=challenge_id)
    challenge = None
    if (challenge_res.count() > 0):
        challenge = challenge_res[0]
    else:
        challenge = get_and_cache_challenge(challenge_id)
    if challenge is None:
        return HttpResponseNotFound(f"Could not find challenge with id: {challenge_id}")

    q_times = None
    # only do this if the challenge has ended so we can cut over to v2
    length = int(request.GET.get('length', '10'))
    offset = int(request.GET.get('offset', '0'))
    if challenge.end_ts < time.time():
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
    else:
        q_times = CotdQualiTimes(uid=map_uid, challenge_id=challenge_id, length=length, offset=offset)
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



# @cache_page(CACHE_8HRS_TTL)
# def get_player_stats(request, wsid):





@cache_page(CACHE_COTD_TTL)
def get_nb_players(request, map_uid):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    mtp = get_object_or_404(MapTotalPlayers, uid=map_uid)
    return json_resp(mtp)


# @requires_openplanet_auth(MAP_MONITOR_PLUGIN_ID)
@cache_page(CACHE_COTD_TTL)
def refresh_nb_players(request, map_uid, user=None):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    return json_resp_mtp(*run_async(refresh_nb_players_inner(map_uid)))
    # mtps = MapTotalPlayers.objects.filter(uid=map_uid)
    # last_known = 0
    # mtp = None
    # if mtps.count() > 0:
    #     mtp = mtps[0]
    #     last_known = mtp.nb_players
    #     delta = time.time() - mtp.updated_ts
    #     in_prog = mtp.last_update_started_ts > mtp.updated_ts and (time.time() - mtp.last_update_started_ts < 60)
    #     # if it's been less than 5 minutes, or an update is in prog, return cached
    #     if not LOCAL_DEV_MODE and (in_prog or delta < NB_PLAYERS_CACHE_SECONDS):
    #         return json_resp_mtp(mtp)
    # else:
    #     mtp = MapTotalPlayers(uid=map_uid)
    # mtp.last_update_started_ts = time.time()
    # mtp.save()
    # records = run_async(nadeo_get_nb_players_for_map(map_uid))
    # mtp.nb_players = 0
    # mtp.last_highest_score = 0
    # tops = records['tops'][0]['top']
    # if (len(tops) > 1):
    #     last_player = tops[0]
    #     mtp.nb_players = last_player['position']
    #     mtp.last_highest_score = last_player['score']
    # mtp.updated_ts = time.time()
    # mtp.save()
    # return json_resp_mtp(mtp)



@cache_page(CACHE_5_MIN)
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





class LengthOp:
    EQ = 0
    LT = 1
    GT = 2
    LTE = 3
    GTE = 4

def tmx_len_match(m: TmxMap, op: LengthOp, l_enum: int) -> bool:
    if l_enum <= 0: return True
    if op == LengthOp.EQ: return m.LengthEnum == l_enum
    if op == LengthOp.LT: return m.LengthEnum < l_enum
    if op == LengthOp.GT: return m.LengthEnum > l_enum
    if op == LengthOp.LTE: return m.LengthEnum <= l_enum
    if op == LengthOp.GTE: return m.LengthEnum >= l_enum
    return True

def tmx_vehicle_match(m: TmxMap, vehicle) -> bool:
    if vehicle == 0: return True
    if vehicle == 1: return m.VehicleName == "CarSport" or m.VehicleName == "CarSnow" or m.VehicleName == "CarRally"
    print(f"Unknown vehicle: {vehicle} / {m.VehicleName}")
    return True

def tmx_mtype_match(m: TmxMap, mtype) -> bool:
    if len(mtype) == 0: return True
    return m.MapType == mtype

def tmx_etags_match(m: TmxMap, etags: list[int]) -> bool:
    tags = list(map(int, (m.Tags or "").split(',')))
    for t in etags:
        if t in tags: return False
    return True

def tmx_tags_match(m: TmxMap, incl_tags: list[int], require_all_tags: bool) -> bool:
    if len(incl_tags) == 0: return True
    tags = list(map(int, (m.Tags or "").split(',')))
    if require_all_tags:
        for t in incl_tags:
            if t not in tags: return False
        return True
    for t in incl_tags:
        if t in tags: return True
    return False


def tmx_map_downloadable(m: TmxMap) -> bool:
    return m.Downloadable and not (m.Unlisted or m.Unreleased)

def tmx_map_okay_rmc(m: TmxMap) -> bool:
    return m.TrackID not in EXCLUDE_FROM_RMC


def tmx_compat_mapsearch2(request: HttpRequest):
    # try twice in case of random exception
    for i in range(2):
        try:
            return mapsearch2_inner(request)
        except Exception as e:
            logging.error(f"Exception in mapsearch2: {e}")
    return HttpResponseRedirect(f"https://trackmania.exchange{request.get_full_path()}")


def mapsearch2_inner(request):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    try:
        is_random = request.GET.get('random', '0') == '1'
        if not is_random:
            return HttpResponseBadRequest(f"Only random=1 supported")
        tags = request.GET.get('tags', '')
        include_tags: list[int] = []
        if len(tags) > 0:
            include_tags = list(map(int, request.GET.get('tags', '').split(",")))
        require_all_tags = request.GET.get('tagsinc', '0') == '1'
        etags = request.GET.get('etags', '')
        exclude_tags: list[int] = []
        if len(etags) > 0:
            exclude_tags = list(map(int, request.GET.get('etags', '').split(",")))
        length_op = int(request.GET.get('lengthop', '0'))
        length = int(request.GET.get('length', '0'))
        vehicles = int(request.GET.get('vehicles', '0'))
        mtype = request.GET.get('mtype', '')
        author = request.GET.get('author', None)
    except Exception as e:
        return HttpResponseBadRequest(f"Exception processing query params: {e}")

    state = get_scrape_state()

    batch_size = 20
    count = 0
    last_track = None
    # now the random part
    while count < 2000:
        count += batch_size
        rand_tids = list(random.randint(1, state.LastScraped + 1) for _ in range(batch_size))
        q_dict = dict(TrackID__in=rand_tids)
        if author is not None: q_dict = dict(Username__iexact=author)
        tracks: list[TmxMap] = TmxMap.objects.filter(**q_dict).all()
        resp_tids: list[int] = [t.TrackID for t in tracks]
        if author is not None:
            rand_tids = clone_and_shuffle(resp_tids)
            if len(rand_tids) == 0:
                return HttpResponseNotFound(f"No maps found for author: {author}")
        print(f"Searched: {rand_tids}")
        print(f"search got tracks: {len(tracks)} / {resp_tids}")
        no_track = []
        no_match = []
        for tid in rand_tids:
            track: TmxMap | None = None
            for _track in tracks:
                if _track.TrackID == tid:
                    track = _track
                    break
            if track is None:
                # logging.info(f"No track {tid}")
                no_track.append(tid)
                continue
            last_track = track
            if not tmx_len_match(track, length_op, length) \
                or not tmx_vehicle_match(track, vehicles) \
                or not tmx_mtype_match(track, mtype) \
                or not tmx_etags_match(track, exclude_tags) \
                or not tmx_tags_match(track, include_tags, require_all_tags) \
                or not tmx_map_downloadable(track) \
                or not tmx_map_okay_rmc(track) \
                or not tmx_map_still_public(track):
                # logging.info(f"Track did not match: {track.TrackID}")
                no_match.append(track.TrackID)
                continue
            logging.info(f"Found track: {track.TrackID} / not found: {no_track} / no match: {no_match}")
            return JsonResponse({'results': [model_to_dict(track)], 'totalItemCount': 1})
        # track.Tags
    if last_track is not None:
        return JsonResponse({'results': [model_to_dict(last_track)], 'totalItemCount': 1})
    return HttpResponseNotFound("Searched 2k maps but did not find a map")


def clone_and_shuffle(xs: list) -> list:
    ret = [x for x in xs]
    shuffle(ret)
    return ret


def map_dl(request, mapid: int):
    tmx_url = f"https://trackmania.exchange/maps/download/{mapid}"
    cgf_url = f"https://cgf.s3.nl-1.wasabisys.com/{mapid}.Map.Gbx"
    if http_head_okay(tmx_url):
        return HttpResponseRedirect(tmx_url)
    track = TmxMap.objects.filter(TrackID=mapid).first()
    if track is not None and track.TrackUID is not None:
        maps_resp = run_async(core_get_maps_by_uid([track.TrackUID]))
        if maps_resp is not None and len(maps_resp) >= 1:
            return HttpResponseRedirect(maps_resp[0]['fileUrl'])
    # do this last because some are just a saved error page
    if http_head_okay(cgf_url):
        return HttpResponseRedirect(cgf_url)
    return HttpResponseNotFound(f"Could not find track with ID: {mapid}! (Unknown ID or missing UID or not uploaded to Nadeo)")


@cache_page(CACHE_8HRS_TTL)
def tmx_api_tags_gettags(request):
    return JsonResponse(get_tmx_tags_cached(), safe=False)
    # return HttpResponsePermanentRedirect(f"https://trackmania.exchange/api/tags/gettags")


@cache_page(CACHE_8HRS_TTL)
def tmx_api_tags_gettags_refresh(request):
    run_async(update_tmx_tags_cached())
    return JsonResponse(get_tmx_tags_cached(), safe=False)
    # return HttpResponsePermanentRedirect(f"https://trackmania.exchange/api/tags/gettags")


def api_tmx_get_map(req, trackid: int):
    track = TmxMap.objects.filter(TrackID=trackid).first()
    if track is None:
        return HttpResponseNotFound(f"Could not find track with ID: {trackid}!")
    return JsonResponse(model_to_dict(track))


def tmx_maps_get_map_info_multi(request, mapids: str):
    try:
        tmxIds = list(map(int, mapids.split(',')))
        tracks = TmxMap.objects.filter(TrackID__in=tmxIds)
        print(f"Got ids: {len(tmxIds)} and tracks: {len(tracks)}")
        resp = []
        done = set()
        for track in tracks:
            if track.TrackID in done:
                # print(f"Skipping duplicate: {track.TrackID}")
                continue
            done.add(track.TrackID)
            resp.append(model_to_dict(track))
        return JsonResponse(resp, safe=False)
    except Exception as e:
        print(f"Exception getting map ids: {e}")
        return HttpResponseRedirect(f"https://trackmania.exchange/api/maps/get_map_info/multi/{mapids}")




def tmx_uid_to_tid_map(request):
    maps = TmxMap.objects.all()
    ret = []
    for m in maps:
        ret.append([m.TrackID, m.TrackUID])
    return JsonResponse(ret, safe=False)


def get_requests_query_tags(request):
    s = request.GET.get('tags', '')
    if len(s) == 0:
        return []
    return list(map(int, s.split(',')))


def tags_to_names(tags: list[int]) -> list[str]:
    if len(tmx_tags_lookup) == 0:
        update_tmx_tag_lookup()
    ret = []
    for t in tags:
        ret.append(tmx_tags_lookup.get(t, f"Unk({t})"))
    return ret


def tmx_next_map(request, map_id: int):
    tags = get_requests_query_tags(request)
    next_maps = TmxMap.objects.filter(TrackID__gt=map_id, MapType__contains="TM_Race")
    if len(tags) > 0:
        next_maps = next_maps.filter(reduce(operator.or_, (Q(Tags__contains=f"{t}") for t in tags)))
    next_maps = next_maps.order_by('TrackID')

    if len(tags) > 0:
        for next_map in next_maps:
            map_tags = list(map(int, (next_map.Tags or "").split(',')))
            if any(t in map_tags for t in tags):
                return JsonResponse(dict(next=next_map.TrackID, next_uid=next_map.TrackUID, tags=map_tags, tag_names=tags_to_names(map_tags), name=next_map.Name, author=next_map.Username))
    else:
        next_map = next_maps.first()
        map_tags = list(map(int, (next_map.Tags or "").split(',')))
        if next_map is not None:
            return JsonResponse(dict(next=next_map.TrackID, next_uid=next_map.TrackUID, tags=map_tags, tag_names=tags_to_names(map_tags), name=next_map.Name, author=next_map.Username))

    return JsonResponse(dict(next=1))

def tmx_prev_map(request, map_id: int):
    prev_map = TmxMap.objects.filter(TrackID__lt=map_id, MapType__contains="TM_Race").order_by('-TrackID').first()
    if prev_map is None:
        return JsonResponse(dict(prev=1))
    return JsonResponse(dict(prev=prev_map.TrackID, prev_uid=prev_map.TrackUID))

def tmx_count_at_map(request, map_id: int):
    return JsonResponse(dict(maps_so_far=TmxMap.objects.filter(TrackID__lt=map_id, MapType__contains="TM_Race").count()))


def get_unbeaten_at_details(request, trackid:int):
    track = TmxMap.objects.filter(TrackID=trackid).first()
    if track is None:
        return HttpResponseNotFound(f"Could not find track with ID: {trackid}!")
    map_at = TmxMapAT.objects.filter(Track_id=track.pk).first()
    if map_at is None:
        return HttpResponseNotFound(f"Could not find AT for track with ID: {trackid}!")
    ret = model_to_dict(map_at)
    ret['Track'] = model_to_dict(track)
    return JsonResponse(ret)


def unbeaten_ats(request):
    unbeaten_ats = CachedValue.objects.filter(name=UNBEATEN_ATS_CV_NAME).first()
    if unbeaten_ats is not None:
        return JsonResponse(json.loads(unbeaten_ats.value))
    return JsonResponse(dict(error='not yet initialized'))


def recently_beaten_ats(request):
    beaten_ats = CachedValue.objects.filter(name=RECENTLY_BEATEN_ATS_CV_NAME).first()
    if beaten_ats is not None:
        return JsonResponse(json.loads(beaten_ats.value))
    return JsonResponse(dict(error='not yet initialized'))


def track_ids_to_uid(request):
    cached_value = CachedValue.objects.filter(name=TRACK_UIDS_CV_NAME).first()
    if cached_value is not None:
        return JsonResponse(json.loads(cached_value.value))
    return JsonResponse(dict(error='not yet initialized'))





def debug_nb_dup_tids(request):
    return
    all_tids = list(TmxMap.objects.only('TrackID', 'UpdateTimestamp').order_by('TrackID', '-UpdateTimestamp', 'id'))
    seen_tids = set()
    dup_recs: list[dict] = list()
    dup_tids: list[TmxMap] = list()
    last = None
    for tid in all_tids:
        if tid.TrackID in seen_tids:
            dup_recs.append(dict(orig=[last.pk, last.TrackID, last.UpdateTimestamp], todel=[tid.pk, tid.TrackID, tid.UpdateTimestamp]))
            dup_tids.append(tid)
        else:
            seen_tids.add(tid.TrackID)
        last = tid

    if request.GET.get('purge', '').lower() == 'true':
        for tid in dup_tids:
            tid.delete()

    return JsonResponse(dict(TrackID_Duplicates=dict(total=len(all_tids), uniq=len(seen_tids), dups=dup_recs)))


class JsonErrorResponse(JsonResponse):
    def __init__(self, *args, status_code=500, **kwargs):
        super().__init__(*args, **kwargs)
        self.status_code = status_code


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

@cache_page(CACHE_ICONS_TTL)
def convert_webp_to_png(request: HttpRequest):
    if (request.method != "POST"): return HttpResponseNotAllowed(['POST'])
    if len(request.body) > 12000: return HttpResponseBadRequest("Image too big, max 12kb after b64 encoding")
    im = Image.open(BytesIO(base64.decodebytes(request.body)), formats=['webp'])
    return finish_icon_img_request(im)

@cache_page(CACHE_ICONS_TTL)
def convert_rgba_to_png(request: HttpRequest):
    if (request.method != "POST"): return HttpResponseNotAllowed(['POST'])
    if len(request.body) > 24000: return HttpResponseBadRequest("Image too big, max 24kb after b64 encoding")
    bs = base64.decodebytes(request.body)
    if len(bs) % 4 != 0: return HttpResponseBadRequest("Image bytes must be len%4==0 (and in bgra format)")
    img_bytes = b''.join(bytes((r,g,b,a)) for (b,g,r,a) in chunks([b for b in bs], 4))
    im = Image.frombytes('RGBA', (64, 64), img_bytes)
    return finish_icon_img_request(im)

def finish_icon_img_request(im: Image):
    im = im.resize((64, 64))
    im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    bs = BytesIO()
    im.save(bs, "png", optimize=True)
    print(f'generated size: {bs.tell()}')
    bs.seek(0)
    return FileResponse(bs)


def lm_conversion_req(request: HttpRequest):
    if (request.method != "POST"): return HttpResponseNotAllowed(['POST'])
    max_mb = 10
    if len(request.body) > (1024**2) * max_mb: return HttpResponseBadRequest(f"LM zip too big, max {max_mb} MB after b64 encoding (was {len(request.body) / (1024**2):.2f} MB)")
    zip_bytes = BytesIO(base64.decodebytes(request.body))
    zip_bytes.seek(0)
    output = BytesIO()
    with zipfile.ZipFile(zip_bytes) as zf:
        for name in zf.namelist():
            processed = process_lm_file(name, zf)
            if processed:
                new_name = name[:-5] + ".png"
                output.write(len(new_name).to_bytes(4, 'little'))
                output.write(new_name.encode())
                # output.write(b'\x00')
                data_size = processed.tell()
                processed.seek(0)
                output.write(data_size.to_bytes(4, 'little'))
                output.write(processed.read(data_size))
                print(f"{new_name}: {data_size}")
    output.seek(0)
    return FileResponse(output)

def process_lm_file(name: str, zf: zipfile.ZipFile) -> BytesIO | None:
    can_process = name == "ProbeGrid.webp" or (name.startswith("LightMap") and name.endswith(".webp"))
    if not can_process: return None
    data = zf.read(name)
    im = Image.open(BytesIO(data), formats=['webp'])
    im = im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    bs = BytesIO()
    im.save(bs, "png")
    return bs
