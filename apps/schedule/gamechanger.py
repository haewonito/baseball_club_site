"""
One-way sync of a team's GameChanger calendar feed into `Event` rows.

GameChanger's "Copy calendar link" is an iCalendar (.ics) feed. Each event
has a stable UID, a title, UTC start/end and a STATUS; the feed we saw has no
LOCATION, and classifies nothing beyond the title ("... Practice" versus
"... @ Opponent"). So:

- Rows are matched on `Event.external_id` (the UID) and marked
  `source=gamechanger`. The sync only ever touches those rows, never
  hand-entered ones.
- GameChanger owns title, start/end and type. A title with "practice" in it is
  a practice; one with " vs " or " @ " is a game, stored as a tournament (the
  site has no separate game type). Anything else (e.g. the monthly "Dues"
  reminders on a real team's feed) isn't schedule material and is skipped.
- Coaches keep a local overlay: location, notes and status. The feed's
  location only fills a blank local one, never overwrites. `status` is
  rewritten only when the feed's own status changes (`Event.feed_status`),
  so a local cancel survives a sync.
- A future event that vanishes from the feed is marked cancelled
  (`feed_status="removed"`), and comes back if it reappears. Past events
  that vanish are left alone.
- If the fetch or parse fails, nothing changes. A feed with no events at all
  while the team still has upcoming synced ones is treated as a failure too,
  so a glitch can't cancel a whole schedule.
"""

import logging
import ssl
from datetime import datetime, time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi
from django.db import transaction
from django.utils import timezone
from icalendar import Calendar

from .models import Event, EventSource, EventStatus, EventType

logger = logging.getLogger(__name__)

ALLOWED_HOST_SUFFIX = ".gc.com"
MAX_FEED_BYTES = 2_000_000
FETCH_TIMEOUT_SECONDS = 20

FEED_SCHEDULED = "scheduled"
FEED_CANCELLED = "cancelled"
FEED_REMOVED = "removed"


class SyncError(Exception):
    pass


def normalize_feed_url(raw):
    """webcal:// is just https:// for calendar apps. Only GameChanger's own
    host is accepted, since an admin-entered URL is fetched server-side."""
    url = (raw or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith(ALLOWED_HOST_SUFFIX):
        raise SyncError("The calendar link must be an https://...gc.com (GameChanger) link.")
    return url


def fetch_feed(url):
    request = Request(url, headers={"User-Agent": "ChoiceSelectSite/1.0"})
    try:
        # certifi's CA bundle, not the OS one: python.org builds of Python on
        # macOS ship without system certificates and fail verification.
        context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS, context=context) as response:
            body = response.read(MAX_FEED_BYTES + 1)
    except Exception as exc:
        # Never include the URL: it carries a secret token.
        raise SyncError(f"Couldn't download the feed ({type(exc).__name__}).") from exc
    if len(body) > MAX_FEED_BYTES:
        raise SyncError("The feed is unexpectedly large; not syncing.")
    return body


def _classify(title):
    lowered = f" {title.lower()} "
    if "practice" in lowered:
        return EventType.PRACTICE
    if " vs " in lowered or " vs. " in lowered or " @ " in lowered:
        return EventType.TOURNAMENT
    return None


def _tidy_location(raw):
    """The feed's location is a multi-line address ("720 Boltz Dr\n, CO
    80525"); flatten it onto one line."""
    pieces = [piece.strip(" ,") for piece in str(raw).splitlines()]
    return ", ".join(piece for piece in pieces if piece)[:150]


def parse_feed(body):
    """Returns a list of dicts, one per VEVENT that has a UID and a start."""
    try:
        calendar = Calendar.from_ical(body)
    except Exception as exc:
        raise SyncError("The feed isn't a valid calendar file.") from exc

    tz = timezone.get_current_timezone()
    events = []
    for component in calendar.walk("VEVENT"):
        uid = str(component.get("UID", "")).strip()
        start = component.decoded("DTSTART", None)
        if not uid or start is None:
            continue
        end = component.decoded("DTEND", None)
        # All-day events come through as dates; give them a local midnight.
        if not hasattr(start, "hour"):
            start = timezone.make_aware(datetime.combine(start, time.min), tz)
        if end is not None and not hasattr(end, "hour"):
            end = timezone.make_aware(datetime.combine(end, time.min), tz)
        if timezone.is_naive(start):
            start = timezone.make_aware(start, tz)
        if end is not None and timezone.is_naive(end):
            end = timezone.make_aware(end, tz)

        title = str(component.get("SUMMARY", "")).strip()
        cancelled = str(component.get("STATUS", "")).strip().upper() == "CANCELLED"
        events.append(
            {
                "uid": uid,
                "title": title[:150],
                "start": start,
                "end": end,
                "location": _tidy_location(component.get("LOCATION", "")),
                "event_type": _classify(title),
                "feed_status": FEED_CANCELLED if cancelled else FEED_SCHEDULED,
            }
        )
    return events


def _status_for(feed_status):
    return EventStatus.CANCELLED if feed_status in (FEED_CANCELLED, FEED_REMOVED) else EventStatus.SCHEDULED


def apply_feed(team, feed_events, now=None):
    """Writes `feed_events` into `team`'s synced rows. Returns counts."""
    now = now or timezone.now()
    counts = {
        "created": 0,
        "updated": 0,
        "cancelled_removed": 0,
        "restored": 0,
        "unchanged": 0,
        "skipped": 0,
    }
    existing = {e.external_id: e for e in team.events.filter(source=EventSource.GAMECHANGER)}
    seen = set()

    for item in feed_events:
        seen.add(item["uid"])
        if item["event_type"] is None:
            counts["skipped"] += 1
            continue
        event = existing.get(item["uid"])
        if event is None:
            Event.objects.create(
                team=team,
                source=EventSource.GAMECHANGER,
                external_id=item["uid"],
                event_type=item["event_type"],
                title=item["title"],
                start_datetime=item["start"],
                end_datetime=item["end"],
                location_name=item["location"],
                status=_status_for(item["feed_status"]),
                feed_status=item["feed_status"],
            )
            counts["created"] += 1
            continue

        changed = []
        for field, value in (
            ("event_type", item["event_type"]),
            ("title", item["title"]),
            ("start_datetime", item["start"]),
            ("end_datetime", item["end"]),
        ):
            if getattr(event, field) != value:
                setattr(event, field, value)
                changed.append(field)
        if item["location"] and not event.location_name:
            event.location_name = item["location"]
            changed.append("location_name")
        if event.feed_status != item["feed_status"]:
            if event.feed_status == FEED_REMOVED:
                counts["restored"] += 1
            event.feed_status = item["feed_status"]
            event.status = _status_for(item["feed_status"])
            changed += ["feed_status", "status"]
        if changed:
            event.save(update_fields=changed + ["updated_at"])
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1

    for uid, event in existing.items():
        if uid in seen or event.start_datetime < now or event.feed_status == FEED_REMOVED:
            continue
        event.feed_status = FEED_REMOVED
        event.status = EventStatus.CANCELLED
        event.save(update_fields=["feed_status", "status", "updated_at"])
        counts["cancelled_removed"] += 1
    return counts


def sync_team(team, dry_run=False, now=None):
    """Fetch and apply one team's feed. Raises SyncError, leaving data alone."""
    if not team.gamechanger_feed_url.strip():
        raise SyncError("This team has no GameChanger calendar link.")
    url = normalize_feed_url(team.gamechanger_feed_url)
    feed_events = parse_feed(fetch_feed(url))
    now = now or timezone.now()

    if not feed_events and team.events.filter(
        source=EventSource.GAMECHANGER, start_datetime__gte=now
    ).exists():
        raise SyncError("The feed has no events but the team has upcoming synced ones; not touching them.")

    with transaction.atomic():
        counts = apply_feed(team, feed_events, now=now)
        if dry_run:
            transaction.set_rollback(True)
        else:
            team.gamechanger_last_synced_at = now
            team.save(update_fields=["gamechanger_last_synced_at"])
    return counts
