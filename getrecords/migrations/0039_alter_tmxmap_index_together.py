# Generated by Django 4.2.2 on 2024-11-20 05:53

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0038_tmxmappacktrackupdatelog_and_more'),
    ]

    operations = [
        migrations.AlterIndexTogether(
            name='tmxmap',
            index_together={('MapType', 'TrackID')},
        ),
    ]