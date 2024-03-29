# Generated by Django 4.1.5 on 2023-02-12 04:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0009_trackstats_total_time_userstats_total_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='ghost',
            name='segmented',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='trackstats',
            name='segmented_runs',
            field=models.IntegerField(db_index=True, default=0),
        ),
        migrations.AddField(
            model_name='userstats',
            name='segmented_runs',
            field=models.IntegerField(db_index=True, default=0),
        ),
        migrations.AddField(
            model_name='usertrackplay',
            name='segmented',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name='ghost',
            name='partial',
            field=models.BooleanField(db_index=True),
        ),
        migrations.AlterField(
            model_name='usertrackplay',
            name='partial',
            field=models.BooleanField(db_index=True),
        ),
    ]
