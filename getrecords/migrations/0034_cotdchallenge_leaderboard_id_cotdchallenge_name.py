# Generated by Django 4.2.2 on 2023-09-19 05:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0033_alter_cotdchallenge_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotdchallenge',
            name='leaderboard_id',
            field=models.IntegerField(default=-1),
        ),
        migrations.AddField(
            model_name='cotdchallenge',
            name='name',
            field=models.CharField(db_index=True, default='(missing)', max_length=64),
        ),
    ]
