# Generated by Django 4.2.2 on 2023-07-12 03:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0025_cachedvalue'),
    ]

    operations = [
        migrations.AddField(
            model_name='tmxmapat',
            name='RemovedFromTmx',
            field=models.BooleanField(default=False),
        ),
    ]
