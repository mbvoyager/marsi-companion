# Marsi's appearance, routines and memory

The terminal archive wears blackened iron, oxide red, worn ivory and muted green.
Parallel circuit traces, cog teeth and mechanical inscriptions span its upper
and lower borders and archive rail. An elongated skull reliquary stands beside
the journal. Travelling signals and optical lenses respond to idle, listening,
thinking and speaking states. Static drawings are cached; the five-frame-per-second
animation moves existing items. Typing, voice and history remain available at
800x480 and 480x320. This uses ordinary Tk widgets, not a terminal emulator.

MARSI speaks as a small, warm Tech-Priest physically beneath a forge cathedral
on Mars in the Warhammer 40,000 universe. The terminal is an aperture through
an unexplained interdimensional machine flow to our present-day, near-side Terra.
He knows our world has computers and publications describing his universe.
Imperial Terra and our Terra remain distinct, as do their calendars. This
connection and his personal reliquary are original character lore.

His hunger is for data: observations, readings, diagrams, histories and tested
ideas. He asks a specific question when useful, without demanding secrets,
money or constant attention. Unknown telemetry stays unknown. His appearance
is grim; his manner remains gentle. An explicit question about the actual
software receives an honest answer; ordinary conversation stays in character.

The artworks are original procedural ASCII compositions inspired by sacred
machine diagrams, guided by the owner's four electoo and reliquary references.
They do not reproduce rulebook illustrations or require an
image-generation model. Hardware readings influence the random composition,
and the caption names the readings used. `art` makes another composition now.

The local [lore library](../marsi_local/lore.json) contains over 100 short
reference entries across Mechanicus, Imperial, Chaos and alien subjects, with
official source links. Setting facts accompany a relevant lore question or
a pronoun-based follow-up; ordinary questions receive no default creed.
Up to three topic records are selected by English/German aliases, within
2,800 characters. Whole newest exchanges use the remaining
prompt budget. This is local retrieval, not training, live browsing or an
exhaustive encyclopaedia. The 10,500-byte prompt allowance is a heuristic for
the model's 4,096-token context, not an exact tokenizer; long prompts and
token-heavy languages can still exceed it.
Optional notes and older recalled messages are also bounded to 1,600 and 800
UTF-8 bytes respectively, preserving complete values and favouring newer ones.
Their full saved versions remain in the database.

The persona prioritizes a direct answer, then a little character flavour. Human
daily life, feelings and ordinary questions are welcome. The machine faith
should not make Marsi dismiss harmless topics or turn each reply into a sermon.
Long repeated passages are excluded from the next working prompt, while the
human's earlier messages remain available as bounded reference data. The
original journal entries are preserved. If a newly generated answer repeats a
long passage, the server tries once more with that example removed, using the
remaining inference time budget. A persistent loop produces an explicit error
and is not saved as another successful conversation.

Generation uses Qwen3's recommended non-thinking sampling (temperature 0.7,
top-p 0.8, top-k 20, min-p 0), plus modest presence/repetition penalties. These
can reduce looping; they do not guarantee relevance, factual accuracy or varied
conversation. See [Qwen's model guidance](https://huggingface.co/Qwen/Qwen3-1.7B)
and [Ollama's options](https://docs.ollama.com/modelfile).
The presence penalty is 0.5 rather than Qwen's stronger 1.5 suggestion for severe
repetition; high penalties can also degrade language quality. Test the actual
model with [the Ubuntu conversation check](ubuntu-server.md#repeated-or-irrelevant-replies).

Restart the server after changing persona or lore. Restart the Pi display for
artwork changes. All machine readings are actual supplied numbers or unknown;
travelling decorative lights do not measure a literal interdimensional signal.

## Routine schedule

The Ubuntu service evaluates persistent schedules once per minute. It creates
entries even when the Pi display is closed, as long as Ubuntu's Marsi service
is running. The Pi retrieves them when connected.

| Routine | Timing | Default sound |
| --- | --- | --- |
| Machine artwork | Once each day, at a randomly chosen time from 09:00 to before 21:00 | Silent |
| Tiny sermon with art | Every 2 or 3 days; the next interval is chosen after each sermon | Spoken when the Pi is idle and outside quiet hours |
| Morning greeting | Around 07:00, using the date and actual available machine readings | Spoken, including during quiet hours |
| Small blessing or inspection | Every 10–20 minutes, after two idle minutes | Silent |

The first sermon is scheduled 2–3 days after the scheduler first runs. Manual
`sermon` and `art` do not consume or postpone the scheduled ones. A late server
start catches up at most one artwork and one sermon, without a backlog. A missed
morning may appear during the three-hour window from 07:00 to before 10:00;
after that it is skipped. Dates and routine targets use Ubuntu's local clock.
Set both machines to the intended timezone, and keep their clocks synchronized.

Spoken observances require the Pi display, Voice, Idle rites and
`MARSI_OBSERVANCE_SPEECH=true`. The display waits for an idle moment, keeps the
latest pending spoken observance, and skips speech older than ten minutes.
It records the last successfully played observance ID locally under `data/`
so a display restart does not replay it. Quiet-hour sermons remain in the
journal even when their speech is skipped. Morning speech explicitly overrides
quiet hours by default, as requested. It never starts a microphone recording.

Use these optional settings in **Ubuntu's `.env.server`**:

```text
MARSI_OBSERVANCES=true
MARSI_COMPANION_SESSION=pi
MARSI_MORNING_HOUR=7
```

`MARSI_COMPANION_SESSION` should match the everyday Pi's `MARSI_SESSION`.
Only that session receives scheduled entries. To stop scheduled generation,
set `MARSI_OBSERVANCES=false` and restart the server.

Use these optional settings in **the Pi's `.env.pi`**:

```text
MARSI_OBSERVANCE_SPEECH=true
MARSI_MORNING_SPEECH_DURING_QUIET=true
MARSI_RITUAL_SPEECH=false
MARSI_QUIET_START=22
MARSI_QUIET_END=8
```

Set the morning override to `false` if you later prefer silence at 07:00.
The Idle rites switch stops the Pi's spontaneous small rituals and scheduled
speech. It does not delete or disable the server's daily archive entries.
Voice off always prevents playback. Manual ART, BLESS and `sermon` follow Voice;
their spoken versions read a sentence, rather than pronouncing ASCII diagrams.

Weather, news and location-based information are not enabled in this version.
They can be added with narrow API integrations; they do not require a general
autonomous agent. A later weather addition needs a chosen location and service.
Marsi currently makes no automatic external requests for such information.

## Machine readings

The Pi and server read their own CPU activity, one-minute load, RAM use, filesystem
use, CPU count, uptime and a CPU/SoC thermal sensor where available. The screen
shows the main readings beside the figure; Qwen receives the numeric readings
for conversation. An unknown or unsupported value is `--` on screen and `null`
in the API. CPU percentage needs two samples. Load is not a percentage.

The Pi sends readings to the authenticated server every ten seconds. They stay
in memory; readings older than 90 seconds are not used as current Pi data.
No hostnames, IP addresses, serial numbers, usernames, process lists or file
contents are collected by this feature. Daily art captions and morning entries
preserve only the small numeric selection printed in their text.
Marsi may occasionally wish for another sensor, but installing one is a future
hardware choice. He does not discover or control arbitrary devices.

## Conversation archive and learning

Successful conversations, recognized human speech, artworks, sermons and rituals
are saved in `data/companion.sqlite3` on Ubuntu. The display reopens the latest
80 entries and loads older pages on request. It keeps at most 600 loaded entries
to protect Pi memory; the full journal remains on the server until you delete it.
LATEST returns from an older page to recent entries.
Failed transmissions and local help/error notices are not server memories.

The old database is upgraded automatically. Previously retained exchanges are
imported once, with the migration time because older records had no timestamps.
The old implementation already removed exchanges beyond its retention limit;
those cannot be recovered by the upgrade.

For continuity, Qwen receives six recent exchanges, explicit notes and up to
three older human messages found by a small literal-word search. The search
examines at most 2,000 older human messages and skips common words. For example,
a later question containing `telescope` can recall an older message about your
telescope. This is a simple retrieval aid, not a guarantee of perfect recall.
`/remember TEXT` creates a reliable explicit note; `/notes` lists the stored
notes. Asking in ordinary conversation saves an exchange, not a formal note.

This is how Marsi learns conversational context here: storage and retrieval.
His model weights are not retrained, and he cannot rewrite his own code.
The long-term journal is separate from the bounded working context, so keeping
an archive does not send every old conversation to the small model at once.

FORGET asks for confirmation in the display and deletes that session's journal,
working context, notes and schedule state. The terminal `/forget` performs the
same deletion immediately. Other sessions and external backups remain. The next
scheduler pass initializes new routine targets for the configured session.
SQLite deletion is logical deletion, not secure erasure of storage media.

## Local commands

| Input | Action |
| --- | --- |
| `art` or `/art` | Generate and archive a machine-shaped ASCII artwork |
| `sermon` or `/sermon` | Give and archive a tiny sermon now |
| `bless` or `/ritual` | Perform and archive a short ritual |
| `history` or `/history` | Display: load an older page; terminal: print the latest page |
| `/remember TEXT` | Save an explicit note, up to 200 characters |
| `notes` or `/notes` | List saved notes |
| `forget` or `/forget` | Clear this session; the display asks first |
| `help` or `/help` | Show local commands |
| `exit`, `/exit`, `/quit` | Close this frontend; the Ubuntu service continues |

These commands are typed. Spoken utterances remain conversation, so Whisper
misrecognizing an exit or forget command cannot close the display or erase memory.
Exact command words are reserved; `Tell me about art` is ordinary conversation.
