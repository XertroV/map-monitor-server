# Generated by Django 4.2.2 on 2023-07-11 00:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0023_tmxmapat_wr_tmxmapat_wr_player'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tmxmap',
            name='TrackID',
            field=models.IntegerField(db_index=True, unique=True),
        ),
    ]
