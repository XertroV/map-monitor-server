# Generated by Django 4.2.2 on 2023-07-07 05:33

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0019_tmxmapat'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tmxmapat',
            name='Track',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='getrecords.tmxmap', unique=True),
        ),
    ]
