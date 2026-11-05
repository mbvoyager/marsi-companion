# Ubuntu server: first a conversation, then a voice

Use a supported Ubuntu LTS installation; the minimal server edition saves memory.
No special firmware is required. The project requires Python 3.10 or newer. Start
with CPU inference and leave GPU setup for a future machine.

## 1. Install Git and get the project and a Python environment

Run these commands in a terminal on Ubuntu:

```bash
sudo apt update
sudo apt install -y git curl nano python3 python3-venv
cd ~
git clone https://github.com/mbvoyager/marsi-companion.git
cd marsi-companion
bash scripts/setup-server.sh --text-only
```

The install command includes **Git**, which downloads the project and lets you
update its code later. It also installs curl, the nano text editor, Python, and
Python's virtual environment support. Installing Ubuntu alone does not guarantee
Git is installed.

For SSH installation and process checks, see the
[troubleshooting command guide](troubleshooting.md#ubuntu-service-and-models).
Once both machines are installed, [quickstart](quickstart.md) gives the short
update, restart and Pi automatic-start sequence.

The setup script creates a private Python environment, `.venv-server`, and
`.env.server` with a newly generated shared token. It preserves an existing
settings file. The text server also installs an offline language checker from
`requirements-text.txt`. Speech packages are added separately; the template demo
still runs without these packages.

The setup script creates your server settings locally in
**`~/marsi-companion/.env.server`**. This file is excluded from Git because it
contains your local settings and shared token. The leading
dot makes it a hidden file, so a normal `ls` command will not show it. To list
the project including hidden files, or open the settings:

```bash
ls -la ~/marsi-companion
nano ~/marsi-companion/.env.server
```

In nano, Ctrl+O followed by Enter saves changes; Ctrl+X exits. If the file is
missing, run `bash scripts/setup-server.sh --text-only` from the project directory.
The script creates it and preserves a settings file that already exists.

This is the companion's separate repository, using its `main` branch. If you
already cloned `tiny-tech-priest-marsi`, leave that folder in place and clone
`marsi-companion` alongside it. Existing Ollama installations and downloaded
Qwen models can be reused; you do not need to install or download them again.

## 2. Install Ollama and download Qwen

Use [Ollama's official Linux installation instructions](https://docs.ollama.com/linux).
Their installer can be downloaded and inspected before running:

```bash
curl -fsSL https://ollama.com/install.sh -o /tmp/marsi-ollama-install.sh
less /tmp/marsi-ollama-install.sh
sh /tmp/marsi-ollama-install.sh
ollama pull qwen3:1.7b
```

This initial setup needs internet access. Keep Ollama on its default loopback
address, `127.0.0.1:11434`. The Pi talks to Marsi's server, not directly to Ollama.

## 3. Start Marsi and test typed conversation

In the project directory:

```bash
.venv-server/bin/python -m marsi_local.server
```

In a second terminal:

```bash
cd ~/marsi-companion
MARSI_SERVER_URL=http://127.0.0.1:8765 .venv-server/bin/python -m marsi_local.client --env .env.server
```

Try: `Hello Marsi. Explain what an LLM is in two simple sentences.` Then ask a
follow-up to check recent conversation. Use `/quit` to leave the client and
Ctrl+C in the server terminal to stop the server.

For a no-model rehearsal, start the server with `--demo` instead. Its answers
come from a small companion-only phrase set and are labelled `demo-template`.
Demo mode does not verify Qwen or speech performance.

If Qwen is too slow, try `ollama pull qwen3:0.6b`, set
`MARSI_MODEL=qwen3:0.6b` in `.env.server`, and restart Marsi. That gives a smaller
baseline with lower conversational quality. Move to a larger model only after
measuring latency and memory on the actual server.

## 4. Add local speech

Stop Marsi, then install the optional packages and download a voice:

```bash
.venv-server/bin/python -m pip install -r requirements-server.txt
mkdir -p models/piper
cd models/piper
../../.venv-server/bin/python -m piper.download_voices en_US-lessac-medium
cd ../..
.venv-server/bin/python -m marsi_local.speech
.venv-server/bin/python -m marsi_local.speech --check-recognition
```

The first speech command downloads/caches Whisper tiny and checks the configured
Piper voice. The recognition check also runs WAV decoding, speech detection and
Whisper inference using a second of generated silence; it does not save audio or
conversation. This catches runtime failures that loading the models alone misses.
After both succeed, test actual speech from the Pi. Piper needs the
voice's `.onnx` model and matching `.onnx.json` file. The example settings already
point to `models/piper/en_US-lessac-medium.onnx`.

Marsi is configured for **English only**: Qwen is instructed to answer in English
even to German messages or requests to switch languages. Whisper recognition is
fixed to `en`, including when an older `.env.server` still contains
`MARSI_WHISPER_LANGUAGE=de` or a blank value; that legacy setting is ignored.
Speak English into the microphone. Typed messages in other languages can still
be understood, but the reply should remain English. Archived conversations and
notes are preserved; you do not need to use Forget.

The prompt alone is insufficient for small models. The server now checks replies
with an offline English/German detector before accepting them. It removes German
companion examples from the working context while retaining their original archive
entries and bounded human context. A detected German draft gets at most one
English rewrite using the remaining inference time budget. A rejected draft is
never returned, saved as a new answer or sent to Piper. If the rewrite also fails
or runs out of time, Marsi stays in character with an English notice:
"My little vox-cog has tangled its words, dear keeper. Could you ask me once more
in English? ^^" It can be spoken normally. The visible journal preserves this
notice, but it is excluded from Qwen's working conversation examples. Only a
fixed technical reason is logged on Ubuntu, without conversation text or drafts.
Repetition and language repair share that one retry.

Existing installations need this **Ubuntu-only** dependency update:

```bash
cd ~/marsi-companion
git pull --ff-only
.venv-server/bin/python -m pip install -r requirements-text.txt
systemctl --user restart marsi-server
```

The checker runs locally and sends no conversation to a language service. Its
initial package download includes bundled language models. Python 3.12+ uses
Lingua 2.2; Python 3.10/3.11 use 2.1.1 for compatibility. See
[Lingua's release notes](https://github.com/pemistahl/lingua-py/releases/tag/v2.2.0).
No Pi update is needed for this server-side output check.

Piper must use an English voice. The server checks the language in its matching
`.onnx.json` before loading it and gives an actionable error for other languages.
The example `en_US-lessac-medium` above is suitable. Check `MARSI_PIPER_MODEL` if
you previously installed a German voice.

To check the actual model's language behaviour after updating and restarting the
server, run this while Marsi is idle:

```bash
.venv-server/bin/python -m marsi_local.conversation --check-english
```

It asks two German questions, including a request to answer in German, with
synthetic German conversation history. Both returned answers must pass the
English/German check. `[REPAIR]` reports a needed rewrite; `[PASS]` appears only
after both model answers pass. A recovery notice does not count as an answer:
the technical check prints `[FAILED]` and exits with status 1 in that case.
Review meaning and relevance yourself: language detection is statistical,
can miss short or mixed snippets, and does not grade conversational quality or
other languages. The check uses a temporary journal, without reading or changing
your normal conversations or notes, and does not synthesize audio.

The speech models are initialized lazily in the server, so the first spoken
request after a restart may be slower even when their files are already cached.

## 5. Prepare the server and set up the Raspberry Pi

This is the handoff from Ubuntu to the Pi. You have now prepared the conversation
and speech engines. First make the server reachable below, then install and
configure the Pi using its separate guide. Test the Pi before proceeding to
automatic startup in step 6. You can install Raspberry Pi OS earlier, but the Pi's
conversation test needs the Ubuntu server to be running.

### Prepare Ubuntu

Find the server's LAN address with `hostname -I`. Reserve that address in the
router if possible, so the Pi's settings stay valid. Keep a note of the address
and open `~/marsi-companion/.env.server` to find the `MARSI_TOKEN` value.
You will put these two values into the Pi's settings after its setup script runs.

If Marsi is still running from an earlier test, stop that copy with Ctrl+C.
Start Marsi from the project directory with:

```bash
cd ~/marsi-companion
.venv-server/bin/python -m marsi_local.server --host 0.0.0.0
```

Leave this terminal open while you set up and test the Pi. The address
`0.0.0.0` tells Marsi to accept connections through the server's network
interfaces; the Pi's settings must use the server's actual LAN address.

### Set up the Raspberry Pi

Now follow the **[Raspberry Pi setup guide](raspberry-pi.md)**. Install Raspberry
Pi OS if you have not already done so, then complete the interface installation
in its step 1. That setup script creates **`~/marsi-companion/.env.pi` on the Pi**.

In the Pi's settings, copy the server's `MARSI_TOKEN` value and set
`MARSI_SERVER_URL` to `http://YOUR_SERVER_IP:8765`. The Pi guide shows exactly
where to edit those fields and how to test typed chat, the display, and speech.

### Allow the connection if a firewall is enabled

This starter API uses ordinary HTTP and is intended for your trusted home LAN.
Keep port 8765 off the public internet. Once the Pi is on your network, find its
address by running `hostname -I` **on the Pi**. If Ubuntu's firewall is enabled,
allow that address before the Pi's conversation test. Run this in a second
terminal **on Ubuntu**, for example:

```bash
sudo ufw allow from YOUR_PI_IP to any port 8765 proto tcp
```

Replace the placeholder before running that command. Do not enable a firewall
from a remote session until its SSH rule is configured.

### Check health from LAN or Wi-Fi

Open `http://YOUR_SERVER_IP:8765/health` in a browser on a device in the same
home network. Use the Ubuntu LAN address from `hostname -I`. The installed
Marsi service listens on port 8765 on the server's network interfaces.
From the Pi or a laptop on that network, the equivalent command is

```bash
curl -sS --max-time 5 http://YOUR_SERVER_IP:8765/health
```

The running server responds with `{"status": "ok", "mode": "local-llm"}`.
This status is available without a token. Chat and journal requests use the
configured token. Use a chat to check model inference and speech after the
HTTP check passes.

If UFW currently allows only the Pi, use the same rule above with the address
of each additional device. To allow the entire trusted subnet, find its CIDR
with `ip -4 route show scope link` on Ubuntu. Use the route whose source address
matches the Ubuntu LAN address, for example `192.168.1.0/24`. Substitute your
subnet below. This grants access to port 8765 from that network.
[Ubuntu firewall documentation](https://ubuntu.com/server/docs/how-to/security/firewalls/#allow-access-from-specific-hosts)

```bash
sudo ufw allow proto tcp from YOUR_TRUSTED_LAN_SUBNET to any port 8765
```

Continue with the typed conversation, display, and microphone/speaker checks
in the Pi guide. Return here for step 6 once those tests work.

## 6. Start the server automatically

Do this after the Pi can talk to the manually started server.
These commands assume the checkout is `~/marsi-companion`:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/marsi-server.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now marsi-server
sudo loginctl enable-linger "$USER"
```

Stop the manually started server first; only one process should own port 8765
and this memory file. Lingering allows the user service to run without an active
login. The service reads `.env.server` from the checkout and restarts after a crash.

```bash
systemctl --user status marsi-server
journalctl --user -u marsi-server -n 50
systemctl --user restart marsi-server
systemctl --user stop marsi-server
```

Ollama also needs its own service running. Inspect it with `systemctl status ollama`.

The running Marsi service also creates daily ASCII art, sermons every 2–3 days
and a morning entry at 07:00. Schedules and the conversation journal stay in the
private SQLite database across restarts. Set Ubuntu's timezone correctly with
`timedatectl`; the morning uses this clock. The scheduled session defaults to
`pi`, matching the Pi settings. See [behaviour and memory](behaviour.md) for
configuration, retrieval-based continuity and how the Pi speaks the morning entry.

## Useful checks

- `free -h` shows RAM; `top` shows CPU use. Measure a cold response and a second
  warm response; the HDD mainly affects loading, and a CPU-only model needs time
  for generation. Do not assume a particular tokens-per-second rate.
- `curl http://127.0.0.1:8765/health` checks whether Marsi's API process is up.
  It does not prove that Qwen or speech models are ready; a chat verifies inference.
- A model-not-found reply means the configured model has not been pulled.
- A timeout means check Ollama and try a shorter prompt or smaller model.
- If speech packages cannot install, keep the working text mode and capture the
  installation error for the next development session.

Official speech instructions:
[Whisper CPU configuration](https://github.com/SYSTRAN/faster-whisper) and
[Piper Python API and voice downloads](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md).

## Repeated or irrelevant replies

If Marsi repeats long stock paragraphs or evades harmless questions, update
the **Ubuntu server**, where the persona, conversation context and generation
settings run. Run as the user who installed Marsi:

```bash
cd ~/marsi-companion
git pull --ff-only
systemctl --user restart marsi-server
systemctl --user status marsi-server --no-pager
```

This update preserves `.env.server`, models, the conversation journal and notes.
It filters repetitive examples out of Qwen's working prompt without deleting
their original journal entries, gives ordinary questions priority, and limits
lore to relevant topics. The Pi does not need updating for this server-side fix.

Then, while not requesting a conversation from the Pi, run:

```bash
.venv-server/bin/python -m marsi_local.conversation --check
```

This contacts the installed Qwen through the configured Ollama URL. It starts
with synthetic repetitive history, then asks three different questions:
arithmetic, a network explanation and a kind response to a completed task.
It prints the actual answers and elapsed time. A first cold request can be
slower. It uses a temporary test database, removes it afterwards, and does not
read or modify your normal journal, notes or recordings. No speech engines or
Pi audio are involved.

`[CHECK COMPLETE]` means inference finished without a detected long repetition.
Read each answer to judge whether it actually fits the question; this check
cannot grade conversational quality. If it fails or the replies are still
irrelevant, keep the output and check the installed model and Ollama version:

```bash
ollama --version
grep '^MARSI_MODEL=' .env.server
```

The second command displays the model setting only. Keep the full settings file,
which includes the token, private. A small model can still make mistakes even
when the software works; compare different topics before changing hardware or
switching to a larger model.

## Speech recognition fails after the microphone test passes

### PyAV decoder compatibility

If the original traceback ends with `TypeError: open() got an unexpected keyword
argument 'metadata_errors'`, the installed PyAV version is incompatible with
faster-whisper's decoder. [PyAV 19 removed that option](https://github.com/PyAV-Org/PyAV/releases/tag/v19.0.0).
Marsi's speech requirements therefore limit PyAV to versions below 19. This is
an audio library mismatch on Ubuntu; changing microphone settings will not fix it.

For an existing installation, run the following on Ubuntu, locally or over SSH.
Stop the service before replacing packages so it cannot retain the old library
in memory:

```bash
cd ~/marsi-companion
git pull --ff-only
systemctl --user stop marsi-server
.venv-server/bin/python -m pip install -r requirements-server.txt
.venv-server/bin/python -m pip check
.venv-server/bin/python -m unittest tests.speech_decoder_smoke -v
.venv-server/bin/python -m marsi_local.speech --check-recognition
```

The package installer replaces an incompatible PyAV version with a compatible
release. The decoder test uses generated WAV audio at 16 and 48 kHz, without
downloading a model; the recognition check then exercises Whisper itself.
These commands preserve settings, downloaded models and conversation memory.
After both checks pass, start Marsi again:

```bash
systemctl --user start marsi-server
```

Then retry Talk on the Pi. If a command fails, keep its complete output and
resolve that error before continuing. You can also start the service again with
the command above to restore typed conversation while investigating speech.

### Diagnose other recognition failures

If a local recording on the Pi is clear, and Marsi can speak typed replies, the
speaker path and Piper work. A transcription exception still needs diagnosis on
**Ubuntu**, where Whisper runs. The older message `Speech recognition failed.
Try a shorter, clearer recording.` also covered software/runtime errors, so it
did not establish that the recording was unclear.

Run on Ubuntu from the same checkout and user as the server service:

```bash
cd ~/marsi-companion
git pull --ff-only
.venv-server/bin/python -m marsi_local.speech --check-recognition
```

The command tests two stages: decoding/speech detection, then Whisper inference
with speech detection skipped. It prints no synthetic transcript, calls neither
Qwen nor Piper, and does not use the memory database. An empty transcript from
silence is expected. Passing the check verifies engine execution, not microphone
selection, transcription accuracy or available RAM while Qwen is also running.

If it fails, keep the **whole traceback**, including the original error before
Marsi's final message. That identifies the failing package or configuration.
For a failure in the speech-detection stage, compare with this diagnostic:

```bash
.venv-server/bin/python -m marsi_local.speech --check-recognition --no-vad
```

This skips VAD only for that terminal check. Normal Pi voice requests retain
speech detection. Do not change packages or permanently disable it before
identifying the actual exception. Faster-whisper documents its
[speech detection and generator-based transcription](https://github.com/SYSTRAN/faster-whisper#usage).

After updating the code, restart the running Ubuntu service to load it:

```bash
systemctl --user restart marsi-server
journalctl --user -u marsi-server -n 40 --no-pager
```

Server logs now record the failing exception's class, without its message,
transcripts, audio or token. Recognition and voice errors preserve their cause
in an explicitly invoked terminal diagnostic.

For an actual short test WAV copied to Ubuntu, run:

```bash
.venv-server/bin/python -m marsi_local.speech --transcribe /tmp/marsi-mic-test.wav
```

Unlike the silent check, this deliberately prints the recognized words in your
terminal. It does not save a conversation, generate a reply or modify the server.
For comparison, append `--no-vad`. The WAV must meet the same limits as a Pi
upload: mono 16-bit PCM, a supported rate, at most 20 seconds and 2 MB.
