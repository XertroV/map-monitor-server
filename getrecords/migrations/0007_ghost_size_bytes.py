# Generated by Django 4.1.5 on 2023-02-09 07:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0006_track_last_updated_ts_alter_track_map_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ghost',
            name='size_bytes',
            field=models.IntegerField(default=-1),
        ),
    ]
