# MARSI · The Companion Reliquary

```text
        +---------------------------------------------------+
        |           A R C H I V U M   M A R T I S           |
        |    LOCAL COMPANION // POCKET FORGE // SEAL 003    |
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
cogitator; a Raspberry Pi gives Marsi his animated face, microphone and voice.
Conversation, remembered notes, and small cheerful rituals belong to your own
little forge.

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
local conversation history and notes you choose to save.

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
| The Memory Dataslate | SQLite stores recent conversation and explicit notes | Ubuntu server |
| The Little Body | Animated face, push-to-talk, speaker playback | Raspberry Pi |

The first forge is an **i5-4460 with 8 GB RAM** and a **Pi 3 B+ with 1 GB RAM**.
The Pi carries no neural models. Downloads are needed during installation;
conversation and speech run locally once their models are available.

## Seal III · The Rite of First Awakening

Open these records in order. Keep the first trial small: one successful text
conversation, then speech, then the little body.

1. **[Start here — how the pieces fit together](docs/start-here.md)**
2. **[Ubuntu server setup — Git, Qwen, speech and startup](docs/ubuntu-server.md)**
3. **[Raspberry Pi setup — display, microphone and speaker](docs/raspberry-pi.md)**
4. **[The Wireless Vox — Bluetooth audio on the little body](docs/bluetooth-audio.md)**
5. **[The Trials of Awakening — test the existing features](docs/test-checklist.md)**
6. **[The Forgekeeper's Ledger — development and handoff](docs/development.md)**

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
- **Keep a little dataslate.** Recent conversation stays on the server. Use
  `/remember TEXT`, `/notes` and `/forget` in the terminal to tend explicit notes.
- **Bless the idle moment.** Silent rituals appear every 10–20 minutes when idle,
  with quiet hours from 22:00 to 08:00 in the Pi's local time.
- **Honour the human.** Useful answers, warmth and modest machine-cult humour.
  The human's curiosity leads the expedition.

## Seal V · The Unfinished Relics

This is a prototype. Actual Qwen speed, speech models and audio devices still
need verification on the target machines. The display and local API have
automated checks. Wake words, device control and generated chibi artwork are
future additions; Marsi can already help describe scenes and write art prompts.

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
