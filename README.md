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
- Automatic tournament discovery at startup and every day at 05:00.
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
DAILY_SCAN_HOUR=5
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

## Project structure

```text
app/
|-- api/
|   |-- dependencies.py
|   `-- routes/
|       |-- matches.py
|       `-- system.py
|-- clients/
|   |-- espn.py
|   `-- telegram.py
|-- core/
|   `-- config.py
|-- models/
|   |-- match.py
|   |-- match_event.py
|   |-- player.py
|   `-- team.py
|-- monitoring/
|   |-- coordinator.py
|   `-- policy.py
|-- services/
|   `-- matches.py
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
