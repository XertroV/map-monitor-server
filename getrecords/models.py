from datetime import timezone
import time
from django.db import models
from django.utils import timezone

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

class AuthToken(models.Model):
    token_for: str = models.CharField(max_length=64, db_index=True, unique=True)
    access_token: str = models.CharField(max_length=1024)
    refresh_token: str = models.CharField(max_length=1024)
    refresh_after: int = models.IntegerField()
    expiry_ts: int = models.IntegerField()


class KnownOpenplanetToken(models.Model):
    hashed: str = models.CharField(max_length=64, db_index=True, unique=True)
    account_id: str = models.CharField(max_length=64, db_index=True, unique=True)
    display_name: str = models.CharField(max_length=64, db_index=True)
    token_time: int = models.IntegerField()
    expire_at: int = models.IntegerField()





class User(models.Model):
    wsid: str = models.CharField(max_length=48, db_index=True, unique=True)
    display_name: str = models.CharField(max_length=64, db_index=True)
    first_seen_ts: int = models.IntegerField(default=time.time)
    last_seen_ts: int = models.IntegerField(default=time.time)

class Track(models.Model):
    uid: str = models.CharField(max_length=36, unique=True, db_index=True)
    map_id: str = models.CharField(max_length=48, unique=True, db_index=True)
    name: str = models.TextField(max_length=256)
    url: str = models.TextField(max_length=256)
    thumbnail_url: str = models.TextField(max_length=256)
    tmx_track_id: int = models.IntegerField(default=-123)

class Ghost(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_index=True)
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_index=True)
    url: str = models.CharField(max_length=128)
    timestamp: int = models.IntegerField(default=time.time)
    hash_hex: str = models.CharField(max_length=64)
    partial = models.BooleanField()
    duration = models.IntegerField()
    class Meta:
        index_together = [
            ('user', 'track'),
        ]

class UserTrackPlay(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_index=True)
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_index=True)
    partial = models.BooleanField()
    score = models.IntegerField()
    ghost = models.ForeignKey(Ghost, on_delete=models.DO_NOTHING, db_index=True)
    timestamp: int = models.IntegerField(default=time.time)
    class Meta:
        index_together = [
            ('user', 'track'),
        ]

class TrackStats(models.Model):
    track = models.ForeignKey(Track, on_delete=models.DO_NOTHING, db_index=True)
    total_runs: int = models.IntegerField(default=0)
    partial_runs: int = models.IntegerField(default=0)
    unique_users: int = models.IntegerField(default=0)

class UserStats(models.Model):
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, db_index=True)
    total_runs: int = models.IntegerField(default=0)
    partial_runs: int = models.IntegerField(default=0)
    unique_maps: int = models.IntegerField(default=0)




'''



'''
