import time
from typing import Optional
from django.db import models

class User(models.Model):
    wsid: str = models.CharField(max_length=64, db_index=True, unique=True)
    display_name: str = models.CharField(max_length=128, db_index=True)
    created_ts = models.IntegerField('created timestamp', default=time.time)


class MapaliticsToken(models.Model):
    token: str = models.CharField(max_length=32, db_index=True, unique=True)
    user: User = models.ForeignKey(User, null=True, db_index=True, on_delete=models.DO_NOTHING)
    created_ts = models.IntegerField('created timestamp', default=time.time)


class Zone(models.Model):
    zone_path: str = models.CharField(max_length=256, db_index=True, unique=True)


class TrackEvent(models.Model):
    user: Optional[User] = models.ForeignKey(User, db_index=True, on_delete=models.DO_NOTHING)
    created_ts = models.IntegerField('created timestamp', default=time.time)
    type: str = models.CharField(max_length=64, db_index=True)
    map_uid: str = models.CharField(max_length=32, db_index=True)
    race_time: int = models.IntegerField(default=-1, db_index=True)
    cp_count: int = models.IntegerField(default=-1)
    vx: float = models.FloatField(default=-1)
    vy: float = models.FloatField(default=-1)
    vz: float = models.FloatField(default=-1)
    px: float = models.FloatField(default=-1)
    py: float = models.FloatField(default=-1)
    pz: float = models.FloatField(default=-1)
    zone: Optional[Zone] = models.ForeignKey(Zone, null=True, db_index=True, on_delete=models.DO_NOTHING)
