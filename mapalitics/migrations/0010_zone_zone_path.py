# Generated by Django 4.1.5 on 2023-02-11 22:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapalitics', '0009_zone_trackevent_zone'),
    ]

    operations = [
        migrations.AddField(
            model_name='zone',
            name='zone_path',
            field=models.CharField(db_index=True, default='World', max_length=256, unique=True),
            preserve_default=False,
        ),
    ]
