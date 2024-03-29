# Generated by Django 4.2.2 on 2023-09-18 23:29

from django.db import migrations, models
import django.db.models.deletion
import time


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0031_tmxmapat_atbeatenontmx_tmxmapat_tmxreplayverified'),
    ]

    operations = [
        migrations.CreateModel(
            name='CotdChallenge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('challenge_id', models.IntegerField(db_index=True, verbose_name='challenge id')),
                ('uid', models.CharField(db_index=True, max_length=32)),
                ('start_date', models.IntegerField(db_index=True, verbose_name='start date')),
                ('end_date', models.IntegerField(db_index=True, verbose_name='end date')),
                ('created_ts', models.IntegerField(default=time.time, verbose_name='created timestamp')),
                ('updated_ts', models.IntegerField(default=time.time, verbose_name='updated timestamp')),
            ],
        ),
        migrations.CreateModel(
            name='CotdChallengeRanking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('req_timestamp', models.IntegerField(db_index=True, verbose_name='request timestamp')),
                ('score', models.IntegerField(db_index=True, verbose_name='score')),
                ('rank', models.IntegerField(db_index=True, verbose_name='rank')),
                ('player', models.CharField(db_index=True, max_length=36, verbose_name='player wsid')),
                ('challenge', models.ForeignKey(on_delete=django.db.models.deletion.DO_NOTHING, to='getrecords.cotdchallenge')),
            ],
            options={
                'ordering': ['-req_timestamp', 'rank'],
            },
        ),
    ]
