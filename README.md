# Football API

A FastAPI service that reads soccer scoreboards from ESPN's public JSON API,
normalizes matches and events with Pydantic, monitors live fixtures, and sends
Telegram notifications.

> ESPN's endpoints are undocumented and may change without notice. Use them
> responsibly and keep request frequency, error handling, and timeouts in mind.

## Features

- Today's FIFA World Cup and La Liga matches.
- Typed `Match`, `Team`, `Player`, and `MatchEvent` responses.
- Goals, cards, penalties, own goals, and shootout events.
- Automatic tournament discovery at startup and every day at 10:00.
- Adaptive polling before kickoff, during play, and at halftime.
- Telegram messages for detected matches, status transitions, and new events.
- Automatic event deduplication during each monitoring process.

## Requirements

- Python 3.10 or newer.

## Installation

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the application and development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Copy the example configuration:

```powershell
Copy-Item .env.example .env
```

## Configuration

```dotenv
ESPN_BASE_URL=https://site.api.espn.com/apis/site/v2/sports/soccer
TELEGRAM_API=https://example.com/telegram/send
MONITORED_TOURNAMENTS=["fifa.world","esp.1"]
MONITOR_TIMEZONE=Europe/Madrid
DAILY_SCAN_HOUR=10
```

| Variable | Description |
| --- | --- |
| `ESPN_BASE_URL` | Fixed ESPN soccer API base URL. |
| `TELEGRAM_API` | Endpoint that receives Telegram message requests. |
| `MONITORED_TOURNAMENTS` | JSON array of ESPN tournament codes. |
| `MONITOR_TIMEZONE` | Timezone used for daily scans and kickoff times. |
| `DAILY_SCAN_HOUR` | Hour of day when tournaments are scanned again. |

For a tournament such as `esp.1`, the ESPN request is built as:

```text
{ESPN_BASE_URL}/esp.1/scoreboard?dates=YYYYMMDD
```

## Running the server

Run the Python entry point:

```powershell
python main.py
```

Alternatively, run Uvicorn directly:

```powershell
uvicorn app.main:app --reload
```

The server is available at `http://127.0.0.1:8000` and the interactive API
documentation at `http://127.0.0.1:8000/docs`.

## API endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | API metadata. |
| `GET` | `/health` | Health check. |
| `GET` | `/api/v1/matches/fifa-world-cup` | Today's FIFA World Cup matches. |
| `GET` | `/api/v1/matches/la-liga` | Today's La Liga matches. |
| `GET` | `/api/v1/monitoring/queue` | Up to 20 upcoming monitor fetches. |

Match endpoints return normalized objects rather than ESPN's raw response:

```json
[
  {
    "id": "704821",
    "name": "Getafe at Atletico Madrid",
    "tournament": "esp.1",
    "starts_at": "2024-12-15T13:00:00Z",
    "status": "post",
    "status_name": "STATUS_FULL_TIME",
    "status_detail": "FT",
    "display_clock": "90'+4'",
    "clock_seconds": 5400,
    "period": 2,
    "completed": true,
    "venue": "Metropolitano",
    "home_team": {
      "id": "1068",
      "name": "Atletico Madrid",
      "abbreviation": "ATM",
      "logo": "https://example.com/atm.png"
    },
    "away_team": {
      "id": "2922",
      "name": "Getafe",
      "abbreviation": "GET",
      "logo": "https://example.com/get.png"
    },
    "home_score": 1,
    "away_score": 0,
    "events": []
  }
]
```

## Match events

Each match contains an `events` list. Every event has a stable ID, ESPN type,
normalized kind, match clock, team, affected players, and event flags.

Supported event kinds:

- `goal`
- `penalty`
- `penalty_shootout`
- `own_goal`
- `yellow_card`
- `red_card`
- `other`

Example:

```json
{
  "id": "c1e867b211054df2",
  "type_id": "70",
  "type": "Goal",
  "kind": "goal",
  "minute": "36'",
  "clock_seconds": 2101,
  "team": {
    "id": "1068",
    "name": "Atletico Madrid",
    "abbreviation": "ATM",
    "logo": null
  },
  "players": [
    {
      "id": "313415",
      "name": "Example Player",
      "short_name": "E. Player",
      "jersey": "9",
      "position": "F",
      "headshot": null
    }
  ],
  "score_value": 1,
  "scoring_play": true,
  "penalty_kick": false,
  "own_goal": false,
  "shootout": false
}
```

## Background monitoring

The monitor scans all configured tournaments when FastAPI starts and every day
at `DAILY_SCAN_HOUR` in `MONITOR_TIMEZONE`. Every discovered match receives its
own monitoring task.

| Match phase | Polling frequency |
| --- | --- |
| More than one hour before kickoff | Sleep until the one-hour threshold. |
| From one hour before kickoff | Every 10 minutes. |
| From five minutes before kickoff | Every minute. |
| From one minute before kickoff | Every 2 seconds. |
| Match in progress | Every 2 seconds. |
| First 14 minutes of halftime | Every 5 minutes. |
| After 14 minutes of halftime | Every 2 seconds. |
| Match completed | Monitoring stops. |

The monitor logs fixture discovery, kickoff, halftime, second-half kickoff,
full time, and every new match event. Active monitoring tasks are cancelled
cleanly when the application shuts down.

### Monitoring queue

Inspect the next fetch currently queued by every active match monitor, plus the
next daily scan for each configured tournament:

```http
GET /api/v1/monitoring/queue
GET /api/v1/monitoring/queue?limit=20
```

Entries are ordered by `scheduled_for` and include the tournament, optional
match, frequency, exact interval, and remaining seconds:

```json
[
  {
    "id": "match:esp.1:123",
    "kind": "match_poll",
    "tournament": "esp.1",
    "match_id": "123",
    "match_name": "Home FC vs Away FC",
    "scheduled_for": "2026-07-19T12:10:00+02:00",
    "seconds_until": 600,
    "interval_seconds": 600,
    "frequency": "every 10 minutes"
  },
  {
    "id": "daily:esp.1",
    "kind": "daily_scan",
    "tournament": "esp.1",
    "match_id": null,
    "match_name": null,
    "scheduled_for": "2026-07-20T10:00:00+02:00",
    "seconds_until": 78600,
    "interval_seconds": null,
    "frequency": "daily at 10:00"
  }
]
```

Only the next real fetch for each task is shown. Future recurring fetches are
not predicted because their frequency can change after every ESPN response.

## Telegram notifications

The Telegram API is called with:

```json
{
  "msg": "Message text"
}
```

One message is sent when a fixture is discovered. Further messages are sent
for:

- Match kickoff.
- Halftime.
- Second-half kickoff.
- Full time.
- Goals and own goals.
- Yellow and red cards.
- Penalties and penalty shootouts.

Messages include the match clock, score, team, and affected player when ESPN
provides that information. A discovered fixture is not notified twice during
the same process, and match events are identified by stable IDs.

## Accelerated match replay

Use a completed ESPN match to exercise the same transition, event, logging,
and Telegram handlers used by live monitoring. The replay starts with a
scheduled 0-0 match and no events, then advances through kickoff, first-half
events, halftime, the second half, remaining events, and full time.

Run a log-only replay of the first FIFA World Cup match from July 11, 2026:

```powershell
python simulate_match.py --date 20260711 --delay 0.25
```

Select a specific ESPN match:

```powershell
python simulate_match.py --date 20260711 --match-id 760512 --delay 0.25
```

Send real Telegram notifications during the accelerated replay:

```powershell
python simulate_match.py --date 20260711 --match-id 760512 --delay 0.25 --send-telegram
```

Telegram is disabled by default for simulations to prevent accidental message
spam. The `--delay` option controls the number of seconds between updates.

## Project structure

```text
app/
|-- api/
|   |-- dependencies.py
|   `-- routes/
|       |-- matches.py
|       |-- monitoring.py
|       `-- system.py
|-- clients/
|   |-- espn.py
|   `-- telegram.py
|-- core/
|   `-- config.py
|-- models/
|   |-- match.py
|   |-- match_event.py
|   |-- monitoring_fetch.py
|   |-- player.py
|   `-- team.py
|-- monitoring/
|   |-- coordinator.py
|   `-- policy.py
|-- services/
|   `-- matches.py
|-- simulation/
|   `-- replay.py
`-- main.py
```

## Tests

Run the test suite with:

```powershell
pytest
```

Tests use mocked HTTP transports for ESPN and Telegram, so they do not send
real notifications.

## Current persistence behavior

Matches and events are read from ESPN and stored in memory while the process is
running. Notification deduplication is also in memory. Restarting the process
resets that state; no database persistence is currently configured.
