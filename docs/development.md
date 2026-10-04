# ARCHIVUM OPERIS — The Forgekeeper's Ledger

```text
[ COG SEAL: VERIFIED ]  [ ARCHIVE: DEVELOPMENT / HANDOFF ]
          o==[01]==[10]==o
             |  [O]  |
          o==[10]==[01]==o
```

The archive's outer seals carry Marsi's machine-cult character. Setup guides
and the engineering instructions below use plain language so the forge can be
built, understood and repaired.

## Layout

| Path | Responsibility |
| --- | --- |
| `marsi_local/demo.py` | Authored companion replies for no-model rehearsal |
| `marsi_local/personality.txt` | Marsi's conversational character |
| `marsi_local/lore.py`, `lore.json` | Local canon reference and topic selection |
| `marsi_local/electoo.py` | Cached circuitry, skull effigy and moving signals |
| `marsi_local/core.py` | Ollama, durable journal, working context, notes and recall |
| `marsi_local/speech.py` | Optional Whisper/Piper loading and WAV validation |
| `marsi_local/server.py` | Authenticated HTTP endpoints |
| `marsi_local/client.py` | Shared terminal/Pi API client |
| `marsi_local/pi.py`, `display.py`, `ambient.py` | Audio, ASCII terminal display and idle rites |
| `marsi_local/telemetry.py`, `liturgy.py` | Numeric readings, original ASCII art and persistent calendar |
| `config/` | Shareable setting examples, without credentials |
| `deploy/`, `scripts/` | Installation and startup templates |

Changing Qwen only needs a model download and `MARSI_MODEL` setting; changing
the body later need not change the server. This separation lets us upgrade the
computer while keeping the same Pi interface.

## Memory and behaviour

Conversation text is saved automatically in `data/companion.sqlite3` on the
Ubuntu server. The journal preserves successful exchanges and observances until
Forget. A separate working-context table retains up to 30 exchanges; the last six complete
exchanges, limited to about 6,000 characters, are candidates for Qwen's context.
The persona and topic-selected lore take precedence; whole newest exchanges
fit the remaining 10,500-byte prompt allowance, accounting for UTF-8 text.
This is a heuristic for our 4,096-token setting, not an exact tokenizer.
Up to three older human messages matched by literal words in the current input
are supplied as untrusted context, at most 500 characters each, searching at most
2,000 older human messages. This is simple
retrieval, not training. The display pages the journal and bounds its loaded
entries to 600; it never loads the full archive into RAM at startup.

Use `/remember TEXT` in the terminal client for an explicit note (up to 200
characters), `/notes` to inspect notes, and `/forget` to clear the current
session's journal, working context, notes and schedule. Each session holds up to
12 notes; at most 100 sessions retain working context. Older journal entries and
notes are not silently evicted by that limit. Both frontends default to the same `pi` session. Use
distinct `MARSI_SESSION` values for independent conversations.

The shared token is for one trusted household, not separate user accounts.
Anyone who has it can access any named session. Audio is not stored in the
repository or database; microphone uploads remain in memory, and reply WAVs
on the Pi use a temporary directory deleted after playback. SQLite deletion
removes records logically; it is not a forensic erase, and copies/backups remain.

Memory provides continuity; it does not retrain Qwen or make Marsi self-learning.
The model has no execution tools. Schedules and animations are ordinary application
code, and generated text is never interpreted as a shell command. The only
subprocess in the Pi app is the fixed `aplay` playback program.

## API

Authenticated requests use `Authorization: Bearer YOUR_TOKEN`. JSON requests
use `Content-Type: application/json`. The only unauthenticated route is health.

| Method / route | Input | Result |
| --- | --- | --- |
| `GET /health` | None | API process health and demo/local-llm mode |
| `POST /v1/chat` | `text`, `session_id`, optional boolean `want_audio` | Reply text, animation, source, optional WAV as `audio_base64` |
| `POST /v1/voice` | `audio/wav` bytes; `X-Marsi-Session` header | Transcript, reply, optional audio; `?want_audio=false` skips synthesis |
| `POST /v1/ritual` | `session_id`, optional `want_audio` | Authored ritual, independent of private memory |
| `POST /v1/art`, `POST /v1/sermon` | `session_id`, optional `want_audio` | Authored/procedural inscription, archived; speech excludes diagrams |
| `GET /v1/journal` | `session_id`, optional `before` or `after`, `limit` 1–100 | Chronological journal page and `has_more` |
| `GET /v1/telemetry` | None | Numeric server readings and fresh Pi readings |
| `POST /v1/telemetry` | `readings` object | Accept validated numeric Pi readings; return both machines |
| `POST /v1/speak` | `session_id`, `entry_id`, `want_audio=true` | Read a persisted art/sermon/morning entry's spoken version |
| `GET /v1/memory?session_id=pi` | Session in query | Explicit notes |
| `POST /v1/memory` | `session_id`, `text` | Add explicit note |
| `DELETE /v1/session` | `session_id` | Clear that session's journal, context, notes and schedule |

Chat text is capped at 2,000 characters. WAV uploads are capped at 2 MB and
20 seconds, mono 16-bit PCM. One task at a time runs on the old CPU; simultaneous
inference requests receive a retryable error. Telemetry/journal reads do not take
the inference lock, so the display can refresh while Qwen works. This is a small LAN prototype,
not a public internet service. No browser frontend or CORS is required.

## Verification

From the checkout:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q marsi_local
for script in scripts/*.sh deploy/marsi-xsession.sh; do bash -n "$script"; done
```

Tests exercise real local HTTP requests and a temporary SQLite database, with
fake Qwen/speech engines. They verify authentication, bounded and durable memory,
forgetting, busy handling, WAV limits, speech failure behaviour and quiet hours.
They also exercise journal migration and pagination, recall, numeric-only
telemetry, persistent routine targets, missed mornings and daylight-saving changes.
They do not benchmark real models. The script bot has its own separate test suite.

On Linux, install `python3-tk` and `xvfb`, then run:

```bash
xvfb-run -a python3 -m tests.pi_display_smoke
```

The GitHub workflow runs tests on Python 3.10 and 3.12 and includes the real Tk
widget smoke test for both supported screen sizes, exact commands and F8 key
repeat handling. A separate model-free decoder test installs speech requirements
on Python 3.10, 3.12 and 3.14. Actual microphone, speaker and model inference still need the
hardware acceptance sequence in the setup guides.

## Next milestones

1. Measure Qwen cold/warm latency and peak RAM on the i5; adjust model and thread
   count. Keep Whisper tiny initially. Record the OS and package versions used.
2. Verify microphone and speaker hardware on the Pi. Tune the display to its
   resolution and touch input. Only then enable boot startup.
3. Add streaming speech for shorter perceived delays and, if useful, a wake word
   with an obvious microphone indicator and physical mute option.
4. Improve archive retrieval and add a reviewable memory editor. Raster chibi art
   remains a separate optional image pipeline; current ASCII art needs no model.
5. Add narrow weather/news integrations after choosing a location and source.
   Read-only numeric hardware reporting already exists. Each future device-changing
   action needs a deliberate interface and an explicit policy.

## Prompt for continuing on Ubuntu

Copy this into your next development chat, opened in the repository:

> Continue Marsi, the local tech-priest companion, in mbvoyager/marsi-companion
> on branch main. Read docs/start-here.md, docs/ubuntu-server.md and
> docs/development.md, then inspect the current checkout and changes. Target hardware:
> Ubuntu on i5-4460, Intel HD graphics, 8 GB DDR3 and HDD; Raspberry Pi 3 B+ with 1 GB
> RAM, display, microphone and speaker. Initial stack: Ollama qwen3:1.7b CPU,
> faster-whisper tiny/int8, Piper voice on the server, Tkinter/sounddevice/aplay on
> the Pi. First verify a real Qwen text response, then speech and Pi audio. Keep
> Marsi tiny, cute, warm, devoted to the fictional Machine God and helpful to
> humanity. Keep this repository independent from the script-based Marsi bot.
> Preserve the plain, informative style of the setup guides and the Adeptus
> Mechanicus archive style of the README. Frame Marsi as a companion. Keep credentials,
> models and conversations out of Git. Explain each meaningful change simply and
> run appropriate tests. Do not claim consciousness or hardware results not measured.
