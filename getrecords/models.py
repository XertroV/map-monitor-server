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
