# Generated by Django 4.2.2 on 2023-07-12 04:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0026_tmxmapat_removedfromtmx'),
    ]

    operations = [
        migrations.AddField(
            model_name='tmxmapat',
            name='Unbeatable',
            field=models.BooleanField(default=False),
        ),
    ]
