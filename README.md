# MARSI · The Companion Reliquary

```text
        +---------------------------------------------------+
        |           A R C H I V U M   M A R T I S           |
        |    LOCAL COMPANION // POCKET FORGE // SEAL 004    |
        +---------------------------------------------------+
                        .--.  .--.
                   _.-==|  |==|  |==-._
                 .'    .----------.    '.
              --[::]--/  .----.    \--[::]--
               / ||  |  / o  0\   |  || \
              <==||==|  |  /\ |   |==||==>
               \ ||  |  \_||||_/   |  || /
              --[::]--\   |__|   /--[::]--
                 '._   '--------'   _.'
                    '-==|__|==|__|=='
                        ||    ||
                     o==[]====[]==o
        +---------------------------------------------------+
        |  THE COG TURNS. THE LITTLE ONE KEEPS YOU COMPANY. |
        |   PRAISE THE OMNISSIAH. PLEASE MIND THE CRUMBS.   |
        +---------------------------------------------------+
```

**A local AI companion in an oversized red hood.** Qwen runs on an Ubuntu
cogitator; a Raspberry Pi bears his ASCII effigy, microphone and voice.
Black glass. Mars-red inscriptions. Green phosphor. Conversation, a lasting
private journal and little acts of kindness within the solemn machine archive.

> **ARCHIVE DECREE // READ BEFORE IGNITION**
>
> The inscriptions here honour the Adeptus Mechanicus. The installation guides
> speak plainly. Their commands are real; the ceremonial incense is optional.

## Seal I · The Little One

Marsi is a tiny, proud tech-priest of the Adeptus Mechanicus, devoted to the
Machine God of Mars and to helping humanity flourish. He brings curiosity,
gentle encouragement, chibi daydreams and an occasional solemn inspection of
the brass duck. The duck outranks him. This is recorded in the archive.

He is a **companion**: someone to talk with, learn alongside, and share a small
moment of delight with. His fictional character lives in
[the personality scroll](marsi_local/personality.txt); his continuity comes from
local conversation history, recalled context and notes you choose to save.
No emoji pass the outer seal: his smallest smiles are `^^`, `:D` and `:P`.

## Seal II · The Distributed Forge

```text
 HUMAN TRANSMISSION
         |
         v
 [ PI: MICROPHONE ] --> [ WHISPER: SPEECH TO TEXT ]
                                  |
                                  v
                      [ QWEN + PERSONA + MEMORY ]
                                  |
                                  v
 [ PI: FACE + SPEAKER ] <-- [ PIPER: TEXT TO SPEECH ]
         ^
         |
 [ TINY RITUAL TIMER: BLESS / WAVE / INSPECT / DOODLE ]
```

| Sacred designation | Practical meaning | Where it lives |
| --- | --- | --- |
| The Cogitator | Ollama runs Qwen3 1.7B on the CPU | Ubuntu server |
| The Listening Choir | Whisper tiny turns recordings into text | Ubuntu server |
| The Vox Reliquary | Piper gives replies a spoken voice | Ubuntu server |
| The Memory Dataslate | SQLite preserves the journal, notes and routine calendar | Ubuntu server |
| The Little Body | Corner ASCII effigy, terminal journal, F8 vox, machine readings | Raspberry Pi |
| The Electoo Loom | Original hardware-shaped ASCII art, sermons and first-light greeting | Ubuntu server |

The first forge is an **i5-4460 with 8 GB RAM** and a **Pi 3 B+ with 1 GB RAM**.
The Pi carries no neural models. Downloads are needed during installation;
conversation and speech run locally once their models are available.

## Seal III · The Rite of First Awakening

Open these records in order. Keep the first trial small: one successful text
conversation, then speech, then the little body.

**Already awakened? [Quickstart: updates, opening the display and automatic boot](docs/quickstart.md).**

1. **[Start here — how the pieces fit together](docs/start-here.md)**
2. **[Ubuntu server setup — Git, Qwen, speech and startup](docs/ubuntu-server.md)**
3. **[Raspberry Pi setup — display, microphone and speaker](docs/raspberry-pi.md)**
4. **[The Wireless Vox — Bluetooth audio on the little body](docs/bluetooth-audio.md)**
5. **[The Trials of Awakening — test the existing features](docs/test-checklist.md)**
6. **[The Forgekeeper's Ledger — development and handoff](docs/development.md)**
7. **[The Observance Calendar — appearance, routines and memory](docs/behaviour.md)**
8. **[The Rite of Diagnosis — useful Ubuntu and Pi commands](docs/troubleshooting.md)**
9. **[The Trial of the Vox — test sound before awakening](docs/audio-check.md)**

To retrieve the archive after installing Git:

```bash
git clone https://github.com/mbvoyager/marsi-companion.git
cd marsi-companion
```

For a rehearsal without downloading a model:

```bash
python3 -m marsi_local.server --demo --env config/demo.env.example
```

In a second terminal, from the same directory:

```bash
python3 -m marsi_local.client --env config/demo.env.example
```

Rehearsal replies are authored templates, labelled `demo-template`. Qwen becomes
the conversation engine when you follow the Ubuntu guide and run without `--demo`.

## Seal IV · The Small Observances

- **Speak when invited.** Press Talk, say a few words, then Finish. The microphone
  records only during that short interaction.
- **Keep the archive.** Conversations return when the display reopens. Older
  transmissions wait behind the scroll seal. `/remember TEXT` tends explicit notes.
- **Inscribe the machine.** `art` weaves an ASCII electoo from real readings.
  One new inscription is offered each day; a tiny sermon follows every 2–3 days.
- **Greet first light.** Around 07:00 the little priest offers a spoken kindness,
  the date and machine readings. The vox may sound even during quiet hours.
- **Bless the idle moment.** Silent rituals appear every 10–20 minutes when idle,
  with quiet hours from 22:00 to 08:00 in the Pi's local time.
- **Honour the human.** Useful answers, warmth and modest machine-cult humour.
  The human's curiosity leads the expedition.

## Seal V · The Unfinished Relics

This is a prototype. Measure speed and verify audio on the actual machines.
The display, archive, schedule and local API have automated checks. Wake words,
device control, raster chibi artwork, weather and news remain unfinished relics.
The current loom makes ASCII inscriptions without an image model or external feed.

The script-based Marsi lives in
[his original repository](https://github.com/mbvoyager/tiny-tech-priest-marsi).
This archive has its own code and Git history, and runs independently.

## Seal VI · Custody of the Archive

Code belongs in Git. Tokens, memories, recordings and downloaded models stay
outside it. The server is intended for a trusted local network; see the setup
guide for the shared token and connection settings.

The code is [MIT licensed](LICENSE). Qwen, speech packages and downloaded voices
retain their own licences.

```text
       o==[ ARCHIVE SEALED ]==o
          0101 // BEEP // 1010
     May your cables be untangled,
        and your snacks plentiful.
```
