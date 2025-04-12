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
    challenge = models.ForeignKey(CotdChallenge, on_delete=models.DO_NOTHING, db_index=True)
    req_timestamp: int = models.IntegerField('request timestamp', db_index=True)
    score: int = models.IntegerField('score', db_index=True)
    rank: int = models.IntegerField('rank', db_index=True)
    player: str = models.CharField("player wsid", max_length=36, db_index=True)
    class Meta:
        ordering = ["-req_timestamp", "rank"]
        unique_together = [["req_timestamp", "rank", "challenge"]]
        # index_together = [
        #     ["challenge", "req_timestamp"],
        # ]


LONG_MAP_SECS = 315

class TmxMapScrapeState(models.Model):
    Name: str = models.CharField(max_length=16)
    LastScraped: int = models.IntegerField()


TMX_MAP_REMOVE_KEYS = ['Lightmap', 'UnlimiterRequired', 'MappackID', 'HasGhostBlocks', 'EmbeddedObjectsCount', 'EmbeddedItemsSize', 'AuthorCount', 'SizeWarning', 'CommentCount', 'ReplayCount', 'VideoCount', 'Length', 'Type', 'Environment', 'Vehicle', 'Routes', 'Difficulty', 'ActivityAt', 'ReplayType', 'UserRecord']


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
    RatingVoteCount: int = models.IntegerField(null=True)
    RatingVoteAverage: float = models.FloatField(null=True)
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

    class Meta:
        index_together = [('MapType', 'TrackID')]

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

            if 'VehicleName' not in kwargs or kwargs['VehicleName'] is None:
                kwargs['VehicleName'] = "!Unknown!"

            TmxMap.RemoveKeysFromTMX(kwargs)

            kwargs['LengthSecs'] = LengthSecs
            kwargs['LengthName'] = LengthName

            kwargs['RatingVoteCount'] = 0 if 'RatingVoteCount' not in kwargs else kwargs['RatingVoteCount']
            kwargs['RatingVoteAverage'] = 0 if 'RatingVoteAverage' not in kwargs else kwargs['RatingVoteAverage']

        super().__init__(*args, **kwargs)

    @staticmethod
    def RemoveKeysFromTMX(kwargs):
        for k in TMX_MAP_REMOVE_KEYS:
            if k in kwargs:
                del kwargs[k]
        # also sanitize some fields
        tid = kwargs['TrackID']
        if (len(kwargs['Name'])) >= 128:
            kwargs['Name'] = kwargs['Name'][:128]
            logging.info(f"Trimmed Name on map {tid}: {kwargs['Name']}")
        if (len(kwargs['GbxMapName'])) >= 128:
            kwargs['GbxMapName'] = kwargs['GbxMapName'][:128]
            logging.info(f"Trimmed GbxMapName on map {tid}: {kwargs['GbxMapName']}")
        if (len(kwargs.get('ModName', '') or '')) >= 128:
            kwargs['ModName'] = kwargs['ModName'][:128]
            logging.info(f"Trimmed ModName on map {tid}: {kwargs['ModName']}")



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
    total_time: int = models.IntegerField(default=0)




class CachedValue(models.Model):
    name = models.CharField(max_length=32, db_index=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    value = models.TextField()


class TmxMapPackTrackUpdateLog(models.Model):
    TrackID: int = models.IntegerField(null=False, db_index=True)
    PackID: int = models.IntegerField(null=False, db_index=True)
    last_updated: float = models.FloatField(default=0, db_index=True)
    class Meta:
        unique_together = [('TrackID', 'PackID')]




#
# TMX V2 map fields to TMX V1 map fields
#

'''
old format:

      {
         "TrackID":19387,
         "UserID":27144,
         "Username":"htimh1",
         "GbxMapName":"MIDNIGHT METROPOLIS",
         "AuthorLogin":"FE_OBpuQSvmlsJFIvMBWbw",
         "MapType":"TM_Race",
         "TitlePack":"Trackmania",
         "TrackUID":"QleO8OiNAkIXrZs6r0YLSrLBjEi",
         "Mood":"48x48Night",
         "DisplayCost":33603,
         "ModName":"",
         "Lightmap":8,
         "ExeVersion":"3.3.0",
         "ExeBuild":"2020-10-09_10_58",
         "AuthorTime":55910,
         "ParserVersion":1,
         "UploadedAt":"2020-10-28T18:44:42.18",
         "UpdatedAt":"2020-10-28T18:44:42.18",
         "Name":"MIDNIGHT METROPOLIS",
         "Tags":"3,7,22",
         "TypeName":"Script",
         "StyleName":"Scenery",
         "EnvironmentName":"Stadium",
         "VehicleName":"CarSport",
         "UnlimiterRequired":false,
         "RouteName":"Single",
         "LengthName":"1 min",
         "DifficultyName":"Intermediate",
         "Laps":1,
         "ReplayWRID":17673,
         "ReplayWRTime":54193,
         "ReplayWRUserID":22215,
         "ReplayWRUsername":"Insanity",
         "TrackValue":605,
         "Comments":"...",
         "MappackID":0,
         "Unlisted":false,
         "Unreleased":false,
         "Downloadable":true,
         "RatingVoteCount":0,
         "RatingVoteAverage":0.0,
         "HasScreenshot":true,
         "HasThumbnail":true,
         "HasGhostBlocks":false,
         "EmbeddedObjectsCount":181,
         "EmbeddedItemsSize":1493546,
         "IsMP4":true,
         "SizeWarning":false,
         "AwardCount":236,
         "CommentCount":53,
         "ReplayCount":36,
         "ImageCount":4,
         "VideoCount":1
      },

new format:


{
    "MapId":170211,
    "MapUid":"IhKmjHBxSQGbT9ivnFHQDA",
    "OnlineMapId":"a282e3f9-5585-4edf-9db1-c370ff1190d9",
    "Name":"Deep Dip 2",
    "GbxMapName":"Deep Dip 2",
    "UploadedAt":"2024-05-03T18:48:16.15",
    "UpdatedAt":"2024-05-11T09:27:54.767",
    "ActivityAt":"2024-09-28T20:27:27.503",
    "Uploader":{
       "UserId":20547,
       "Name":"SparklingW"
    },
    "Authors":[
       {
          "User":{
             "UserId":20547,
             "Name":"SparklingW"
          },
          "Role":""
       },
       ...
    ],
    "Tags":[
       {
          "TagId":4,
          "Name":"RPG",
          "Color":""
       },
       ...
    ],
    "Images":[
       {
          "Position":1,
          "Width":0,
          "Height":0,
          "HasHighQuality":true
       }
    ],
    "Type":0,
    "MapType": "TM_Race",
    "Environment":1,
    "Vehicle":1,
    "Mood":"Day",
    "MoodFull":"48x48Day",
    "Style":0,
    "Routes":0,
    "Difficulty":4,
    "Medals":{
       "Author":3272100,
       "Gold":3469000,
       "Silver":3927000,
       "Bronze":4909000
    },
    "CustomLength":null,
    "Length":3272100,
    "AwardCount":402,
    "CommentCount":33,
    "DownloadCount":18253,
    "ReplayCount":0,
    "ReplayType":0,
    "ReplayWRID":null,
    "TrackValue":0,
    "OnlineWR":{
       "AccountId":"BD45204C-80F1-4809-B983-38B3F0FFC1EF",
       "DisplayName":"WirtualTM",
       "RecordTime":2236032,
       "User":{
          "UserId":17372,
          "Name":"Wirtual"
       }
    },
    "TitlePack":"TMStadium",
    "Feature":null,
    "UserOnlineRecord":null,
    "UserRecord":null,
    "ReplayWR":null,
    "HasThumbnail":true,
    "HasImages": true,
    "IsPublic":true,
    "IsListed":true,
    "ServerSizeExceeded":false
 }

v2 output params:
MapId 		Int64 	Primary Key of the Map entry
MapUid 		String 	Map Gbx Uid
OnlineMapId 	question_mark 	String 	If found on the TM API, that's the map UUID, see here
Uploader 		Object 	Uploader info
Authors 		Object[] 	The Map Authors. Role is user-defined.
Type 		Enum 	The Map Type, used for internal purposes
MapType 		String 	The Maptype set in the Map Gbx, substring from last /
Environment 		Enum 	The Environment of the Map
Vehicle 		Enum 	The Vehicle set in the Map Gbx
VehicleName 		String 	Name of the Vehicle, see Get Map Vehicles
Mood 		Enum 	The base mood of the map
MoodFull 		String 	The original mood of the Map Gbx
Style 		Int32 	TagId of the first selected Tag in Tags, see Get Tags
Routes 		Enum 	The routes set by the uploader
Difficulty 		Enum 	The difficulty of the map set by the uploader
AwardCount 		Int32 	Count of Awards on the site
CommentCount 		Int32 	Count of Comments on the site
UploadedAt 		DateTime 	Upload time (UTC)
UpdatedAt 		DateTime 	Last update time of map page (UTC)
ActivityAt 	question_mark 	DateTime 	Last activity (replay, comment, award posted) date on the Map
ReplayType 		Enum 	The leaderboard type of the map on the site
TrackValue 		Int32 	Max. score of the map to be gained & competitiveness indicator
OnlineWR 	question_mark 	Object 	(TMX only) Online World Record data
OnlineWR.AccountId 		String 	Primary account id of TM player, see here
OnlineWR.DisplayName 		String 	Ingame display name of player
OnlineWR.RecordTime 		Int32 	RecordTime in milliseconds or stunt score in pt
OnlineWR.User 	question_mark 	Object 	TMX user associated to player, if available
ReplayCount 		Int32 	Count of Replays uploaded to Map
Titlepack 		String 	Name of TitlePack specified in Map Gbx (substring until @)
DownloadCount 		Int32 	Count of total downloads of map on the site
CustomLength 	question_mark 	Int32 	Optional, custom length of Map defined by user (in case AT is inaccurate) - this is always in milliseconds
Length 		Int32 	Auto-selected: CustomLength, if defined, otherwise Medals.Author
Tags 		Object[] 	The Tags assigned for the Map, see Get Tags
Images 		Object[] 	The uploaded custom images for the Map. Position can be used for the Map Image endpoint.
Medals 		Object 	Map Gbx scores (pt / respawns) or times (ms) depending on Type
HasThumbnail 		Boolean 	The Map has the Gbx thumbnail uploaded, see Map Thumbnail method
HasImages 		Boolean 	The map has at least one custom image uploaded
IsPublic 		Boolean 	Map is published. Relevant for logged-in users.
IsListed 		Boolean 	true: Map can be discovered, if IsPublic is true - false: Map can only be found by the Authors or by providing a key
Feature.Comment 	question_mark 	String 	Comment of frontpage feature, if it exists
Feature.Pinned 	question_mark 	Boolean 	Map is pinned in the frontpage features, if it is featured
InBookmarks 		Boolean 	(Login required) Map is in logged-in user's Play Later list
TimeStampAt 	question_mark 	Int32 	Requires videoid parameter - Timestamp of map in the video
Mappack.MappackId 		Int64 	Requires mappackid parameter - Mappack Id
Mappack.MapStatus 		Enum 	Requires mappackid parameter - Status of Map in specified Mappack
Mappack.MapPosition 		Int32 	Requires mappackid parameter - Position of Map in specified Mappack
GbxMapName 	question_mark 	String 	The formatted ingame from the Gbx file
ServerSizeExceeded 		Boolean 	Server max size limit is exceeded (TM2: 4,194,304, TM: 7,336,960)

'''

def tmx_v2_track_to_v1(j2: dict):
    j1 = dict()
    j1['TrackID'] = j2.get('MapId', None)
    j1['GbxMapName'] = j2.get('GbxMapName', None)
    uploader = j2.get('Uploader', dict())
    j1['UserID'] = uploader.get('UserId', None)
    j1['Username'] = uploader.get('Name', None)
    j1['AuthorLogin'] = "Unknown"
    j1['MapType'] = j2.get('MapType', None)
    j1['TitlePack'] = j2.get('TitlePack', None) or ''
    j1['TrackUID'] = j2.get('MapUid', None)
    j1['Mood'] = j2.get('MoodFull', "") or ''
    j1['DisplayCost'] = 0
    j1['ModName'] = None
    j1['Lightmap'] = 0
    j1['ExeVersion'] = j2.get('ExeVersion', '?')
    j1['ExeBuild'] = j2.get('Exebuild', '')
    j1['AuthorTime'] = j2.get('Medals', dict()).get('Author', -1)
    j1['ParserVersion'] = 1
    j1['UploadedAt'] = j2.get('UploadedAt', None)
    j1['UpdatedAt'] = j2.get('UpdatedAt', None)
    j1['Name'] = j2.get('Name', None)
    tags = j2['Tags']
    j1['Tags'] = ",".join([str(t["TagId"]) for t in tags])
    j1['TypeName'] = None or ''
    j1['StyleName'] = None or ''
    j1['EnvironmentName'] = j2.get('Environment', None)
    j1['VehicleName'] = j2.get('VehicleName', "CarSport")
    j1['UnlimiterRequired'] = False
    j1['RouteName'] = str(j2.get('Routes', None))
    if 'CustomLength' in j2 and j2['CustomLength'] is None:
        del j2['CustomLength']
    j1['LengthSecs'] = j2.get('CustomLength', j2.get('Length', -1)) // 1000
    if j1['LengthSecs'] < 0: j1['LengthSecs'] = max(j1['AuthorTime'] // 1000, -1)
    j1['LengthName'] = '2 m 30 s'
    j1['DifficultyName'] = int_to_difficulty(j2.get('Difficulty'))
    j1['Laps'] = 1
    j1['ReplayWRID'] = j2.get('ReplayWRID', None)
    j1['ReplayWRTime'] = j2.get('ReplayWR', dict()).get('RecordTime', None)
    j1['ReplayWRUserID'] = j2.get('ReplayWR', dict()).get('UserId', None)
    j1['ReplayWRUsername'] = j2.get('ReplayWR', dict()).get('DisplayName', None)
    j1['TrackValue'] = j2.get('TrackValue', 0)
    j1['AwardCount'] = j2.get('AwardCount', 0)
    j1['Comments'] = None or ''
    j1['MappackID'] = 0
    j1['Unlisted'] = j2.get('IsPublic', False)
    j1['Unreleased'] = False
    j1['Downloadable'] = True
    j1['RatingVoteCount'] = 0
    j1['RatingVoteAverage'] = 0.0
    j1['HasScreenshot'] = j2.get('HasThumbnail', False)
    j1['HasThumbnail'] = j2.get('HasImages', False)
    j1['HasGhostBlocks'] = False
    j1['EmbeddedObjectsCount'] = 0
    j1['EmbeddedItemsSize'] = 0
    j1['IsMP4'] = False
    j1['SizeWarning'] = False
    j1['AwardCount'] = j2.get('AwardCount', 0)
    j1['CommentCount'] = j2.get('CommentCount', 0)
    j1['ReplayCount'] = j2.get('ReplayCount', 0)
    j1['ImageCount'] = 0
    j1['VideoCount'] = 0
    return j1
