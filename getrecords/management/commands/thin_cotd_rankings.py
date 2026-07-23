"""Thin CotdChallengeRanking history to ~one snapshot per 60s bucket per challenge.

Keeps the latest req_timestamp in each (challenge_id, floor(req_timestamp/60)) bucket,
which always includes the overall latest snapshot for each challenge.

Usage:
  python manage.py thin_cotd_rankings --dry-run
  python manage.py thin_cotd_rankings --execute
  python manage.py thin_cotd_rankings --execute --challenge-id 123
"""

from __future__ import annotations

import logging
import time

from django.core.management.base import BaseCommand
from django.db import connection

from getrecords.cotd_live_cache import COTD_HISTORY_PERSIST_PERIOD


class Command(BaseCommand):
    help = "Thin COTD ranking snapshots to ~1 per minute per challenge"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count deletable rows without deleting (default if --execute omitted)",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually delete surplus snapshots",
        )
        parser.add_argument(
            "--challenge-id",
            type=int,
            default=None,
            help="Only thin this CotdChallenge.pk (DB id, not Nadeo challenge_id)",
        )
        parser.add_argument(
            "--bucket-seconds",
            type=int,
            default=COTD_HISTORY_PERSIST_PERIOD,
            help=f"Snapshot bucket size in seconds (default {COTD_HISTORY_PERSIST_PERIOD})",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.5,
            help="Seconds to sleep between challenge batches when deleting",
        )

    def handle(self, *args, **options):
        execute = options["execute"]
        dry_run = options["dry_run"] or not execute
        challenge_pk = options["challenge_id"]
        bucket = options["bucket_seconds"]
        sleep_s = options["sleep"]

        if execute and dry_run and options["dry_run"]:
            # explicit --dry-run wins over --execute if both passed
            execute = False
            dry_run = True

        challenge_ids = self._challenge_ids(challenge_pk)
        self.stdout.write(f"Challenges to process: {len(challenge_ids)} (bucket={bucket}s)")

        total_delete_rows = 0
        total_keep_ts = 0
        total_drop_ts = 0

        for i, cid in enumerate(challenge_ids):
            keep_ts, drop_ts, approx_rows = self._plan_for_challenge(cid, bucket)
            total_keep_ts += len(keep_ts)
            total_drop_ts += len(drop_ts)
            total_delete_rows += approx_rows
            if not drop_ts:
                continue
            logging.info(
                "challenge_pk=%s keep_snapshots=%s drop_snapshots=%s approx_rows=%s",
                cid,
                len(keep_ts),
                len(drop_ts),
                approx_rows,
            )
            if execute:
                deleted = self._delete_timestamps(cid, drop_ts)
                self.stdout.write(f"  challenge {cid}: deleted {deleted} rows ({len(drop_ts)} snapshots)")
                if sleep_s > 0:
                    time.sleep(sleep_s)
            elif i < 5 or approx_rows > 10000:
                self.stdout.write(
                    f"  challenge {cid}: would drop {len(drop_ts)} snapshots (~{approx_rows} rows), keep {len(keep_ts)}"
                )

        mode = "EXECUTED" if execute else "DRY-RUN"
        self.stdout.write(
            f"{mode}: keep_snapshots={total_keep_ts} drop_snapshots={total_drop_ts} "
            f"approx_delete_rows={total_delete_rows}"
        )

    def _challenge_ids(self, challenge_pk: int | None) -> list[int]:
        with connection.cursor() as cur:
            if challenge_pk is not None:
                return [challenge_pk]
            cur.execute(
                "SELECT DISTINCT challenge_id FROM getrecords_cotdchallengeranking ORDER BY challenge_id"
            )
            return [r[0] for r in cur.fetchall()]

    def _plan_for_challenge(self, challenge_pk: int, bucket: int) -> tuple[list[int], list[int], int]:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT req_timestamp, COUNT(*) AS n
                FROM getrecords_cotdchallengeranking
                WHERE challenge_id = %s
                GROUP BY req_timestamp
                ORDER BY req_timestamp
                """,
                [challenge_pk],
            )
            rows = cur.fetchall()

        if not rows:
            return [], [], 0

        # Keep the highest req_timestamp in each bucket.
        best_in_bucket: dict[int, int] = {}
        counts = {ts: n for ts, n in rows}
        for ts, _n in rows:
            b = ts // bucket
            prev = best_in_bucket.get(b)
            if prev is None or ts > prev:
                best_in_bucket[b] = ts

        keep = set(best_in_bucket.values())
        # Always keep absolute latest (redundant with above, but explicit).
        keep.add(rows[-1][0])
        drop = [ts for ts, _n in rows if ts not in keep]
        approx_rows = sum(counts[ts] for ts in drop)
        return sorted(keep), drop, approx_rows

    def _delete_timestamps(self, challenge_pk: int, drop_ts: list[int]) -> int:
        deleted = 0
        # Delete in chunks of timestamps to keep statements bounded.
        chunk_size = 20
        with connection.cursor() as cur:
            for i in range(0, len(drop_ts), chunk_size):
                chunk = drop_ts[i : i + chunk_size]
                cur.execute(
                    """
                    DELETE FROM getrecords_cotdchallengeranking
                    WHERE challenge_id = %s AND req_timestamp IN %s
                    """,
                    [challenge_pk, tuple(chunk)],
                )
                deleted += cur.rowcount
        return deleted
