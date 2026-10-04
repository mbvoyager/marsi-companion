# Test Marsi's existing features

Work through these tests on the actual Ubuntu server and Raspberry Pi. A working
typed conversation verifies the connection and Qwen; it does not yet verify
speech recognition, voice synthesis or the audio hardware.

Keep a note of what passed, what failed, and the message shown. For Bluetooth
audio, complete [the Bluetooth guide](bluetooth-audio.md) first. Stop at the first
audio failure so later tests do not obscure its cause.

## 1. Conversation and display

- [ ] Marsi opens fullscreen, animates and responds to controls.
- [ ] Type `Hello Marsi. Explain what a Raspberry Pi does in two sentences.`
      Receive a useful reply from Qwen.
- [ ] Type `For this test, my imaginary pet is a blue duck called Cogbert.`
      Then ask `What is my imaginary pet called?` Check recent conversation.
- [ ] With **Voice** off, a typed reply appears without speaker playback.
- [ ] Long replies remain readable by scrolling the text area.
- [ ] Escape changes fullscreen to a window; Ctrl+Q closes Marsi. Reopen him.

The model's answers vary. Separate conversational quality from whether a
request completed. Record how long a cold first reply and a second reply take;
there is no promised response time for the i5-4460.

## 2. Speaker and voice synthesis

- [ ] A short local tone test is audible through the intended speakers.
      Use the Pi guide for wired audio or the Bluetooth guide for the receiver.
- [ ] Enable **Voice**, type `Say a short hello.`, and hear the reply while its
      text appears. This checks Piper plus playback, without a microphone.
- [ ] Press **Bless!** with Voice on and hear the ritual line.
- [ ] Turn Voice off and repeat Bless; the text and animation still work silently.

The first spoken request after restarting Ubuntu's Marsi service may need more
time because it loads the voice model. A voice error shown with a text reply
means conversation succeeded but speech needs attention.

## 3. Microphone and speech recognition

- [ ] Make a five-second local recording and hear your own speech on playback.
      Follow the selected audio guide. A playback-only receiver cannot pass this.
- [ ] With Voice off, press **Talk**, say `Hello Marsi, how are you?`, then press
      **Finish**. Check the `Heard:` text and the written reply. This tests Whisper
      and Qwen while keeping speaker playback out of the test.
- [ ] Repeat with Voice on and hear Marsi's answer. This verifies the whole path.
- [ ] Start a recording and let it reach 15 seconds. It should stop automatically
      and process the recording.
- [ ] In a quiet room, use a short silence-only recording. Expect either a
      no-speech message or a misrecognition to record as a speech-quality issue;
      silence detection is not a guarantee.

There is no wake word or idle recording in this version. The microphone records
only after Talk; Marsi should never begin a new recording just because he spoke.

## 4. Explicit notes and persistence

Use a separate test session to avoid mixing these checks with your normal
conversation. On the Pi, from `~/marsi-companion`, run:

```bash
MARSI_SESSION=feature-test .venv-pi/bin/python -m marsi_local.client
```

Enter these lines one at a time:

```text
/remember My test mascot is a blue duck called Cogbert.
/notes
What is my test mascot called?
/quit
```

- [ ] `/notes` lists the exact saved note. That is the reliable storage check;
      Qwen using it correctly is a separate conversational check.
- [ ] Reopen the same terminal test session and run `/notes`; the note remains.
- [ ] With no request in progress, restart the Marsi service **on Ubuntu**:

```bash
systemctl --user restart marsi-server
```

- [ ] Reopen the `feature-test` session on the Pi. `/notes` still lists the note.
- [ ] In that test session, run `/forget`, then `/notes`. The note list is empty.
      This deletes only that test session's stored conversation and notes.

The display uses the session configured in `.env.pi`, normally `pi`. Its **Forget**
button asks for confirmation. To test it without deleting your normal memories,
close Marsi and temporarily set `MARSI_SESSION=feature-test` in `.env.pi`. Reopen
him, cancel Forget once and check the test note is retained using the terminal.
Then confirm Forget and check `/notes` is empty. Restore the original session
setting and reopen Marsi. Add another test note first if the terminal test above
has already erased it.

Saved notes come from `/remember` or the memory API. Asking Qwen to remember
something stores a conversation turn, but does not itself create an explicit note.
Forget does not erase external backups or reset the local ritual timer.

## 5. Small rituals

- [ ] With Voice off, press **Bless!** several times, waiting for each result.
      Look for a blessing, salute, inspection or doodle. Selection is random;
      four clicks do not guarantee all four animations.
- [ ] Leave Rituals on and the display idle during the daytime. An automatic
      ritual should appear after the configured 10–20 minute interval.
- [ ] Automatic rituals are silent with the default
      `MARSI_RITUAL_SPEECH=false`, even when Voice is on.
- [ ] Turn Rituals off and leave the display idle; automatic rituals stop.
      Bless remains available for a manual ritual.

For a shorter timer test, write down the existing settings in `.env.pi`, then
temporarily use these values and restart Marsi:

```text
MARSI_RITUAL_MIN_SECONDS=30
MARSI_RITUAL_MAX_SECONDS=30
MARSI_QUIET_START=0
MARSI_QUIET_END=0
```

Equal quiet-hour values disable quiet hours. Leave him alone for at least
**2½ minutes**: the timer defers rituals until you have been idle for two minutes.
With the shorter interval, a ritual should then occur about every 30 seconds.
Interacting postpones eligibility; missed rituals do not build up a backlog.

To test spoken automatic rituals after playback works, temporarily set
`MARSI_RITUAL_SPEECH=true`, leave Voice and Rituals on, and restart. Restore all
normal timer, quiet-hour and speech settings when finished.

## 6. Connection loss and restart

- [ ] Close Marsi while idle or playing audio; the display exits and any active
      playback stops.
- [ ] On Ubuntu, run `systemctl --user stop marsi-server`. On the Pi, a typed
      request should show a connection error. His local animation continues;
      silent automatic rituals can still run when due. A stalled request can
      take up to 240 seconds to time out.
- [ ] On Ubuntu, run `systemctl --user start marsi-server`. Try another message
      from the Pi and receive a reply.
- [ ] If you enabled Ubuntu startup, reboot Ubuntu and verify the user service
      and a Pi conversation after it becomes ready.
- [ ] If you enabled Pi startup, reboot the Pi and verify its display. For
      Bluetooth, also verify receiver reconnection, output selection and playback.

Keep results as hardware observations, rather than assuming these steps have
already passed. Wake words, continuous listening, device control, knowledge
search and generated artwork are future features and are outside this checklist.
