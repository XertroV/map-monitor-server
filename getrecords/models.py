import time
from django.db import models

from getrecords.tmx_maps import *

_MAP_MONITOR_PLUGIN_ID = 308

# Create your models here.

class MapTotalPlayers(models.Model):
    uid: str = models.CharField(max_length=32, db_index=True, unique=True)
    nb_players = models.IntegerField('number of players', default=0)
    last_highest_score = models.IntegerField(default=0)
    created_ts = models.IntegerField('created timestamp', default=time.time)
    updated_ts = models.IntegerField('updated timestamp', default=time.time)
    last_update_started_ts = models.IntegerField(default=0)
    def __str__(self):
        return f"{self.uid} / nb:{self.nb_players}"


class Challenge(models.Model):
    challenge_id: int = models.IntegerField('challenge id', db_index=True, unique=True)
    uid: str = models.CharField(max_length=64, db_index=True, unique=True)
    name: str = models.CharField(max_length=64, db_index=True)
    leaderboard_id = models.IntegerField('leaderboardId')
    start_ts = models.IntegerField('start timestamp', db_index=True)
    end_ts = models.IntegerField('end timestamp', db_index=True)
    created_ts = models.IntegerField('created timestamp', default=time.time)
    updated_ts = models.IntegerField('updated timestamp', default=time.time)


class CotdQualiTimes(models.Model):
    challenge_id: int = models.IntegerField('challenge id', db_index=True)
    uid: str = models.CharField(max_length=32, db_index=True)
    length: int = models.IntegerField('length')
    offset: int = models.IntegerField('offset')
    json_payload: str = models.TextField('quali json sz', default="[]")
    created_ts = models.IntegerField('created timestamp', default=time.time)
    updated_ts = models.IntegerField('updated timestamp', default=time.time)
    last_update_started_ts = models.IntegerField(default=0)
    def __str__(self):
        return f"Quali Times: {self.challenge_id} / {self.uid} / l:{self.length}/o:{self.offset}"
    class Meta:
        unique_together = [('challenge_id', 'uid', 'length', 'offset')]


class CotdChallenge(models.Model):
    challenge_id: int = models.IntegerField('challenge id', db_index=True)
    uid: str = models.CharField(max_length=32, db_index=True)
    name: str = models.CharField(max_length=64, db_index=True, default="(missing)")
    leaderboard_id: int = models.IntegerField(default=-1)
    start_date: int = models.IntegerField('start date', db_index=True)
    end_date: int = models.IntegerField('end date', db_index=True)
    created_ts = models.IntegerField('created timestamp', default=time.time)
    updated_ts = models.IntegerField('updated timestamp', default=time.time)
    class Meta:
        unique_together: [('challenge_id', 'uid')]
        ordering = ['-challenge_id', '-start_date']

class CotdChallengeRanking(models.Model):
    '''Replaces CotdQualiTimes; one row per entry'''
    challenge = models.ForeignKey(CotdChallenge, on_delete=models.DO_NOTHING)
    req_timestamp: int = models.IntegerField('request timestamp', db_index=True)
    score: int = models.IntegerField('score', db_index=True)
    rank: int = models.IntegerField('rank', db_index=True)
    player: str = models.CharField("player wsid", max_length=36, db_index=True)
    class Meta:
        ordering = ["-req_timestamp", "rank"]
        unique_together = [["req_timestamp", "rank", "challenge"]]


LONG_MAP_SECS = 315

class TmxMapScrapeState(models.Model):
    Name: str = models.CharField(max_length=16)
    LastScraped: int = models.IntegerField()


TMX_MAP_REMOVE_KEYS = ['Lightmap', 'UnlimiterRequired', 'MappackID', 'HasGhostBlocks', 'EmbeddedObjectsCount', 'EmbeddedItemsSize', 'AuthorCount', 'SizeWarning', 'CommentCount', 'ReplayCount', 'VideoCount']


class TmxMap(models.Model):
    TrackID: int = models.IntegerField(db_index=True, unique=True)
    UserID: int = models.IntegerField(db_index=True)
    Username: str = models.CharField(max_length=32, db_index=True)
    AuthorLogin: str = models.CharField(max_length=64, db_index=True)
    Name: str = models.CharField(max_length=128)
    GbxMapName: str = models.CharField(max_length=128)
    TrackUID: str = models.CharField(max_length=32, db_index=True, null=True)
    TitlePack: str = models.CharField(max_length=64, db_index=True)
    ExeVersion: str = models.CharField(max_length=32, db_index=True)
    ExeBuild: str = models.CharField(max_length=32, db_index=True)
    Mood: str = models.CharField(max_length=32)
    ModName: str | None = models.CharField(max_length=128, null=True)
    # this really shouldn't be null, but is on 83259
    AuthorTime: int = models.IntegerField(null=True)
    ParserVersion: int = models.IntegerField()
    UploadedAt: str = models.CharField(max_length=32)
    UpdatedAt: str = models.CharField(max_length=32)
    UploadTimestamp: float = models.FloatField()
    UpdateTimestamp: float = models.FloatField()
    Tags: str | None = models.CharField(max_length=32, null=True)
    TypeName: str = models.CharField(max_length=32)
    StyleName: str | None = models.CharField(max_length=32, db_index=True, null=True)
    RouteName: str = models.CharField(max_length=32)
    LengthName: str = models.CharField(max_length=32)
    LengthSecs: int = models.IntegerField(db_index=True)
    LengthEnum: int = models.IntegerField()
    DifficultyName: str = models.CharField(max_length=32)
    DifficultyInt: int | None = models.IntegerField(null=True)
    Laps: int = models.IntegerField()
    Comments: str = models.TextField()
    Downloadable: bool = models.BooleanField()
    Unlisted: bool = models.BooleanField()
    Unreleased: bool = models.BooleanField()
    RatingVoteCount: int = models.IntegerField()
    RatingVoteAverage: float = models.FloatField()
    VehicleName: str = models.CharField(max_length=32)
    EnvironmentName: str = models.CharField(max_length=32)
    HasScreenshot: bool = models.BooleanField()
    HasThumbnail: bool = models.BooleanField()
    MapType: str | None = models.CharField(max_length=32, null=True)
    WasTOTD: bool = models.BooleanField(default=False)

    TrackValue: int = models.IntegerField(default=0)
    AwardCount: int = models.IntegerField(default=0)
    ImageCount: int = models.IntegerField(default=0)
    IsMP4: bool = models.BooleanField(default=False)
    DisplayCost: int = models.IntegerField(default=0)

    ReplayWRID: int = models.IntegerField(null=True)
    ReplayWRTime: int = models.IntegerField(null=True)
    ReplayWRUserID: int = models.IntegerField(null=True)
    ReplayWRUsername: str = models.CharField(max_length=64, null=True)

    def __init__(self, *args, LengthName="2 m 30 s", LengthSecs=None, **kwargs):
        if LengthSecs is None:
            LengthSecs = 0
            # can be in formats: "Long", "2 m 30 s", "1 min", "2 min", "15 secs"
            if LengthName == "Long":
                LengthSecs = LONG_MAP_SECS
            elif " m " in LengthName:
                _mins, rest = LengthName.split(" m ")
                mins_s = int(_mins) * 60
                secs = int(rest.split(" s")[0])
                LengthSecs = mins_s + secs
            elif " min" in LengthName:
                LengthSecs = 60 * int(LengthName.split(" min")[0])
            elif " secs" in LengthName:
                LengthSecs = int(LengthName.split(" secs")[0])
            else:
                raise Exception(f"Unknown LengthName format; {LengthName}")
        if len(kwargs) > 0:
            kwargs['LengthEnum'] = length_secs_to_enum(LengthSecs)
            kwargs['UploadTimestamp'] = tmx_date_to_ts(kwargs['UploadedAt'])
            kwargs['UpdateTimestamp'] = tmx_date_to_ts(kwargs['UpdatedAt'])
            kwargs['DifficultyInt'] = difficulty_to_int(kwargs["DifficultyName"])

            TmxMap.RemoveKeysFromTMX(kwargs)

            kwargs['LengthSecs'] = LengthSecs
            kwargs['LengthName'] = LengthName

        super().__init__(*args, **kwargs)

    @staticmethod
    def RemoveKeysFromTMX(kwargs):
        for k in TMX_MAP_REMOVE_KEYS:
            if k in kwargs:
                del kwargs[k]



class TmxMapAT(models.Model):
    Track: TmxMap = models.OneToOneField("TmxMap", on_delete=models.CASCADE, db_index=True)
    UploadedToNadeo = models.BooleanField(default=False)
    AuthorTimeBeaten = models.BooleanField(default=False, db_index=True)
    ATBeatenTimestamp = models.IntegerField(default=-1)
    ATBeatenUsers = models.TextField(default="")
    ATBeatenFirstNb = models.IntegerField(default=-1, db_index=True)
    LastChecked = models.FloatField(default=0, db_index=True)
    Broken = models.BooleanField(default=False, db_index=True)
    WR = models.IntegerField(default=-1)
    WR_Player = models.CharField(default="", max_length=40)
    RemovedFromTmx = models.BooleanField(default=False, db_index=True)
    Unbeatable = models.BooleanField(default=False, db_index=True)
    TmxReplayVerified = models.BooleanField(default=False, db_index=True)
    ATBeatenOnTmx = models.BooleanField(default=False, db_index=True)



class AuthToken(models.Model):
    token_for: str = models.CharField(max_length=64, db_index=True, unique=True)
    access_token: str = models.CharField(max_length=1024)
    refresh_token: str = models.CharField(max_length=1024)
    refresh_after: int = models.IntegerField()
    expiry_ts: int = models.IntegerField()


class KnownOpenplanetToken(models.Model):
    plugin_site_id: str = models.IntegerField(db_index=True, default=_MAP_MONITOR_PLUGIN_ID)
    hashed: str = models.CharField(max_length=64, db_index=True)
    account_id: str = models.CharField(max_length=64, db_index=True)
    display_name: str = models.CharField(max_length=64, db_index=True)
    token_time: int = models.IntegerField()
    expire_at: int = models.IntegerField()
    class Meta:
        unique_together = [('account_id', 'plugin_site_id')]
        index_together = [('account_id', 'plugin_site_id')]


class User(models.Model):
    wsid: str = models.CharField(max_length=48, db_index=True, unique=True)
    display_name: str = models.CharField(max_length=64, db_index=True)
    first_seen_ts: int = models.IntegerField(default=time.time)
    last_seen_ts: int = models.IntegerField(default=time.time)


class UserPrefs(models.Model):
    user = models.OneToOneField(User, on_delete=models.DO_NOTHING, db_index=True)
    profile_is_public = models.BooleanField(default=True)


class Track(models.Model):
    uid: str = models.CharField(max_length=36, unique=True, db_index=True)
    map_id: str = models.CharField(max_length=48, db_index=True, null=True)
    name: str = models.TextField(max_length=256, null=True)
    url: str = models.TextField(max_length=256, null=True)
    thumbnail_url: str = models.TextField(max_length=256, null=True)
    tmx_track_id: int = models.IntegerField(default=-123)
    last_updated_ts: int = models.IntegerField(default=time.time)


class Ghost(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_index=True)
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_index=True)
    url: str = models.CharField(max_length=128)
    timestamp: int = models.IntegerField(default=time.time)
    hash_hex: str = models.CharField(max_length=64)
    partial = models.BooleanField(db_index=True)
    segmented = models.BooleanField(default=False, db_index=True)
    duration = models.IntegerField()
    size_bytes = models.IntegerField(default=-1)
    class Meta:
        index_together = [
            ('user', 'track'),
        ]

class UserTrackPlay(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_index=True)
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_index=True)
    partial = models.BooleanField(db_index=True)
    segmented = models.BooleanField(default=False, db_index=True)
    score = models.IntegerField()
    ghost = models.ForeignKey(Ghost, on_delete=models.DO_NOTHING, db_index=True)
    timestamp: int = models.IntegerField(default=time.time)
    class Meta:
        index_together = [
            ('user', 'track'),
        ]

class TrackStats(models.Model):
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_index=True)
    total_runs: int = models.IntegerField(default=0, db_index=True)
    partial_runs: int = models.IntegerField(default=0, db_index=True)
    segmented_runs: int = models.IntegerField(default=0, db_index=True)
    unique_users: int = models.IntegerField(default=0, db_index=True)
    total_time: int = models.IntegerField(default=0, db_index=True)

class UserStats(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_index=True)
    total_runs: int = models.IntegerField(default=0, db_index=True)
    partial_runs: int = models.IntegerField(default=0, db_index=True)
    segmented_runs: int = models.IntegerField(default=0, db_index=True)
    unique_maps: int = models.IntegerField(default=0, db_index=True)
    total_time: int = models.IntegerField(default=0, db_index=True)




class CachedValue(models.Model):
    name = models.CharField(max_length=32, db_index=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    value = models.TextField()
