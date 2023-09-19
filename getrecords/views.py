import asyncio
from datetime import timedelta
import json
import logging
import time
from typing import Coroutine, Optional

from numpy import random

from django.db import IntegrityError
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseRedirect, JsonResponse, HttpResponseNotAllowed, HttpRequest, HttpResponseForbidden, HttpResponse, HttpResponseNotFound, HttpResponseBadRequest, HttpResponsePermanentRedirect
from django.core import serializers
from django.db.models import Model
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache

from getrecords.http import get_session, http_head_okay
from getrecords.management.commands.tmx_scraper import get_scrape_state
from getrecords.openplanet import ARCHIVIST_PLUGIN_ID, MAP_MONITOR_PLUGIN_ID, TokenResp, check_token, sha_256
from getrecords.rmc_exclusions import EXCLUDE_FROM_RMC
from getrecords.s3 import upload_ghost_to_s3
from getrecords.tmx_maps import get_tmx_tags_cached
from getrecords.utils import model_to_dict, run_async, sha_256_b_ts

from .models import CachedValue, Challenge, CotdChallenge, CotdChallengeRanking, CotdQualiTimes, Ghost, MapTotalPlayers, TmxMap, TmxMapAT, Track, TrackStats, User, UserStats, UserTrackPlay
from .nadeoapi import LOCAL_DEV_MODE, core_get_maps_by_uid, get_and_save_all_challenge_records, nadeo_get_nb_players_for_map, nadeo_get_surround_for_map
import getrecords.nadeoapi as nadeoapi
from .view_logic import NB_PLAYERS_CACHE_SECONDS, NB_PLAYERS_MAX_CACHE_SECONDS, RECENTLY_BEATEN_ATS_CV_NAME, TRACK_UIDS_CV_NAME, UNBEATEN_ATS_CV_NAME, get_tmx_map, get_unbeaten_ats_query, refresh_nb_players_inner, QUALI_TIMES_CACHE_SECONDS, tmx_map_still_public


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

def json_resp_q_times_from_v2(qt: list[dict], ch: CotdChallenge, length, offset, refresh_in=QUALI_TIMES_CACHE_SECONDS):
    resp = dict()
    resp['challenge_id'] = ch.challenge_id
    resp['uid'] = ch.uid
    resp['length'] = length
    resp['offset'] = offset
    resp['json_payload'] = qt
    resp['refresh_in'] = refresh_in
    resp['challenge'] = model_to_dict(ch)
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
        challenge, created = CotdChallenge.objects.get_or_create(challenge_id=challenge_id, uid=map_uid, start_date=start_date, end_date=end_date)
    if created:
        logging.info(f"{'created' if created else 'got'} challenge {challenge.challenge_id}")
    return challenge, created

def get_or_insert_all_cotd_results(challenge_id: int, map_uid: str):
    challenge, created = get_or_create_challenge(challenge_id, map_uid)
    ranking = CotdChallengeRanking.objects.filter(challenge=challenge).first()
    rankings = []
    # check if we need to update
    if ranking is None or ranking.req_timestamp < (challenge.end_date):
        logging.info(f"Updating rankings")
        rankings = run_async(get_and_save_all_challenge_records(challenge))
    else:
        logging.info(f"Using cached rankings")
        rankings = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=ranking.req_timestamp).all()
    return rankings


def cached_api_challenges_id_records_maps_uid(request, challenge_id: int, map_uid: str):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])
    challenge = CotdChallenge.objects.filter(challenge_id=challenge_id, uid=map_uid).first()
    if challenge is None: return JsonResponse([], safe=False)
    length = int(request.GET.get('length', '10'))
    offset = int(request.GET.get('offset', '0'))
    return JsonResponse(get_challenge_records_v2(challenge, length, offset), safe=False)


def get_challenge_records_v2(challenge, length, offset):
    latest_ts = CotdChallengeRanking.objects.filter(challenge=challenge).latest('req_timestamp').req_timestamp
    rankings = CotdChallengeRanking.objects.filter(challenge=challenge, req_timestamp=latest_ts)[offset:offset+length].all()
    return [challenge_ranking_to_json(r) for r in rankings]

def get_challenge_records_v2_latest_req_ts(challenge) -> int | None:
    try:
        rank1 = CotdChallengeRanking.objects.filter(challenge=challenge).latest('req_timestamp')
        if rank1 is not None:
            return rank1.req_timestamp
    except CotdChallengeRanking.DoesNotExist as e:
        return None


def challenge_ranking_to_json(r: CotdChallengeRanking):
    return {
        'score': r.score, 'time': r.score, 'rank': r.rank, 'player': r.player
    }




def get_cotd_leaderboards(request, challenge_id: int, map_uid: str):
    if request.method != "GET": return HttpResponseNotAllowed(['GET'])

    # check for v2
    challenge = CotdChallenge.objects.filter(challenge_id=challenge_id, uid=map_uid).first()
    if challenge is not None:
        length = int(request.GET.get('length', '10'))
        offset = int(request.GET.get('offset', '0'))
        v2_times = get_challenge_records_v2(challenge, length, offset)
        return json_resp_q_times_from_v2(v2_times, challenge, length, offset)



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
    return json_resp_mtp(run_async(refresh_nb_players_inner(map_uid)))
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
    if vehicle == 1: return m.VehicleName == "CarSport"
    return True

def tmx_mtype_match(m: TmxMap, mtype) -> bool:
    if len(mtype) == 0: return True
    return m.MapType == mtype

def tmx_etags_match(m: TmxMap, etags: list[int]) -> bool:
    tags = list(map(int, m.Tags.split(',')))
    for t in etags:
        if t in tags: return False
    return True

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
        etags = request.GET.get('etags', '')
        exclude_tags: list[int] = []
        if len(etags) > 0:
            exclude_tags = list(map(int, request.GET.get('etags', '').split(",")))
        length_op = int(request.GET.get('lengthop', '0'))
        length = int(request.GET.get('length', '0'))
        vehicles = int(request.GET.get('vehicles', '0'))
        mtype = request.GET.get('mtype', '')
    except Exception as e:
        return HttpResponseBadRequest(f"Exception processing query params: {e}")

    state = get_scrape_state()

    count = 0
    # now the random part
    while count < 1000:
        count += 1
        tid = random.randint(1, state.LastScraped + 1)
        track = TmxMap.objects.filter(pk=tid).first()
        if track is None:
            logging.info(f"No track: {tid}")
            continue
        if not tmx_len_match(track, length_op, length) \
            or not tmx_vehicle_match(track, vehicles) \
            or not tmx_mtype_match(track, mtype) \
            or not tmx_etags_match(track, exclude_tags) \
            or not tmx_map_downloadable(track) \
            or not tmx_map_okay_rmc(track) \
            or not tmx_map_still_public(track):
            logging.info(f"Track did not match: {tid}")
            continue
        return JsonResponse({'results': [model_to_dict(track)], 'totalItemCount': 1})
        # track.Tags
    return HttpResponseNotFound("Searched 1k maps but did not find a map")



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



def tmx_api_tags_gettags(request):
    return JsonResponse(get_tmx_tags_cached(), safe=False)
    # return HttpResponsePermanentRedirect(f"https://trackmania.exchange/api/tags/gettags")

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



def tmx_next_map(request, map_id: int):
    next_map = TmxMap.objects.filter(TrackID__gt=map_id, MapType__contains="TM_Race").order_by('TrackID').first()
    if next_map is None:
        return JsonResponse(dict(next=1))
    return JsonResponse(dict(next=next_map.TrackID, next_uid=next_map.TrackUID))

def tmx_prev_map(request, map_id: int):
    prev_map = TmxMap.objects.filter(TrackID__lt=map_id, MapType__contains="TM_Race").order_by('-TrackID').first()
    if prev_map is None:
        return JsonResponse(dict(prev=1))
    return JsonResponse(dict(prev=prev_map.TrackID, prev_uid=prev_map.TrackUID))

def tmx_count_at_map(request, map_id: int):
    return JsonResponse(dict(maps_so_far=TmxMap.objects.filter(TrackID__lt=map_id, MapType__contains="TM_Race").count()))


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
