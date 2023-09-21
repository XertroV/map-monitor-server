# Generated by Django 4.2.2 on 2023-09-21 00:24

from django.db import migrations
from django.db.models import Min, Count

from getrecords.models import CotdChallenge

def delete_challenge_record_duplicates(apps, schema_editor):
    CotdChallengeRanking = apps.get_model("getrecords", "CotdChallengeRanking")
    nb_challenges = CotdChallenge.objects.count()
    print(f"Checking {nb_challenges} challenges")
    for i, challenge in enumerate(CotdChallenge.objects.all()):
        non_dupe_pks = list(
            CotdChallengeRanking.objects.values('challenge', 'req_timestamp', 'rank')
                .annotate(Min('pk'), count=Count('pk'))
                .order_by()
                .values_list('pk__min', flat=True)
        )

        dupes = CotdChallengeRanking.objects.exclude(pk__in=non_dupe_pks)
        dupes.delete()
        print(f"Done {challenge.challenge_id}; {i / nb_challenges * 100:.1f}")
    print(f"Done all")

class Migration(migrations.Migration):

    dependencies = [
        ('getrecords', '0034_cotdchallenge_leaderboard_id_cotdchallenge_name'),
    ]

    operations = [
        migrations.RunPython(delete_challenge_record_duplicates),
        migrations.AlterUniqueTogether(
            name='cotdchallengeranking',
            unique_together={('req_timestamp', 'rank', 'challenge')},
        ),
    ]
