# Test Marsi's existing features

Work through these tests on the actual Ubuntu server and Raspberry Pi. A working
typed conversation verifies the connection and Qwen; it does not yet verify
speech recognition, voice synthesis or the audio hardware.

Keep a note of what passed, what failed, and the message shown. For Bluetooth
audio, complete [the Bluetooth guide](bluetooth-audio.md) first. Stop at the first
audio failure so later tests do not obscure its cause.

Before opening the display, close any existing Marsi instance and run on the Pi:

```bash
cd ~/marsi-companion
.venv-pi/bin/python -m marsi_local.audio --check
```

- [ ] Hear the tone from the intended speaker and hear your own words on the
      five-second recording replay. Follow [audio recovery](audio-check.md) if
      the local test fails.
- [ ] `--status` checks settings silently, without recording or playing sound.
      `SUSPENDED` alone is normal while the device is idle.

## 1. Conversation and display

- [ ] Marsi opens fullscreen with black/red/green styling, a small ASCII figure
      and readable Pi/server readings. Missing sensors show `--`.
- [ ] Type `Hello Marsi. Explain what a Raspberry Pi does in two sentences.`
      Your words appear immediately with an estimated ASCII progress bar below
      them, followed by a useful reply from Qwen. The human line appears once;
      the progress bar disappears on reply arrival, even while audio is playing.
- [ ] During a slow reply, scroll older messages and try LATEST. The current
      pending message and its estimate remain available. An exceeded estimate
      says `a longer thought` and never reaches 100% before the actual reply.
- [ ] After F8/FINISH, a sealed-recording notice and estimate appear; recognized
      words replace that notice when the reply arrives.
- [ ] Ask an arithmetic question, a technical question and a friendly everyday
      question. Each answer should address its specific question, with restrained
      character flavour and no recycled long paragraph. If this fails, run the
      [Ubuntu conversation check](ubuntu-server.md#repeated-or-irrelevant-replies).
- [ ] Type `For this test, my imaginary pet is a blue duck called Cogbert.`
      Then ask `What is my imaginary pet called?` Check recent conversation.
- [ ] With **Voice** off, a typed reply appears without speaker playback.
- [ ] On Ubuntu, run `.venv-server/bin/python -m marsi_local.conversation --check-english`.
      Both answers should be English. `[REPAIR]` may precede a corrected answer;
      a recovery notice must report `[FAILED]`, never a completed pass. In normal
      conversation, this case stays in character with the English vox-cog notice
      and optional speech, without displaying a technical language error.
- [ ] Long replies remain readable by scrolling the text area.
- [ ] Earlier human messages and Marsi replies remain visible, including after
      closing and reopening the display. OLDER TRANSMISSIONS loads an earlier
      page; LATEST returns to recent messages.
- [ ] Type `art`, `sermon`, `help` and `exit`. Commands perform their local
      action; `Tell me about art` remains a normal Qwen conversation.
- [ ] Escape changes fullscreen to a window; Ctrl+Q closes Marsi. Reopen him.
- [ ] After a full Pi boot, move the mouse over the archive, input field and
      buttons. Check that the reticle is visible and follows the mouse. Click
      Help and drag to select text in the input field. Check the manual launch
      too if its behaviour differs.
- [ ] Leave the Lite/X11 screen idle for at least 15 minutes with Marsi open.
      The display stays on. Check `DISPLAY=:0 xset q` from the same user's SSH
      session: screen-saver timeout is 0 and DPMS disabled or unavailable. When
      exiting normally to an existing X11 desktop, its prior settings return.

The model's answers vary. Separate conversational quality from whether a
request completed. Record how long a cold first reply and a second reply take;
there is no promised response time for the i5-4460.

## 2. Speaker and voice synthesis

- [ ] A short local tone test is audible through the intended speakers.
      Use the Pi guide for wired audio or the Bluetooth guide for the receiver.
- [ ] Enable **Voice**, type `Say a short hello.`, and hear the reply while its
      text appears. This checks Piper plus playback, without a microphone.
- [ ] Press **BLESS** with Voice on and hear the ritual line.
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
- [ ] Repeat using F8 to start, then F8 to finish. Holding F8 should not toggle
      recording repeatedly. The display must have keyboard focus.
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

- [ ] With Voice off, press **BLESS** several times, waiting for each result.
      Look for a blessing, salute, inspection or doodle. Selection is random;
      four clicks do not guarantee all four animations.
- [ ] Leave Idle rites on and the display idle during the daytime. An automatic
      ritual should appear after the configured 10–20 minute interval.
- [ ] Automatic rituals are silent with the default
      `MARSI_RITUAL_SPEECH=false`, even when Voice is on.
- [ ] Turn Idle rites off and leave the display idle; automatic rituals stop.
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
`MARSI_RITUAL_SPEECH=true`, leave Voice and Idle rites on, and restart. Restore all
normal timer, quiet-hour and speech settings when finished.

## 6. Connection loss and restart

- [ ] Close Marsi while idle or playing audio; the display exits and any active
      playback stops.
- [ ] On Ubuntu, run `systemctl --user stop marsi-server`. Wait for the Pi's
      link badge to show `Retry in` and `Connecting`. The character continues
      blinking and the loaded journal stays visible. Type a draft and press
      Send. The draft stays in the input field while the link is down.
- [ ] Open Marsi on the Pi while the service is stopped. The same status badge
      shows attempts from startup. Start the service on Ubuntu with
      `systemctl --user start marsi-server`. The display changes to `Online`
      and loads the journal. Send the draft manually and receive a reply.
- [ ] From the Pi or a second device on the trusted LAN or Wi-Fi, open
      `http://YOUR_SERVER_IP:8765/health` using the Ubuntu LAN address.
      Check for `"status": "ok"` with the
      [LAN health instructions](ubuntu-server.md#check-health-from-lan-or-wi-fi).
- [ ] If you enabled Ubuntu startup, reboot Ubuntu and verify the user service
      and a Pi conversation after it becomes ready.
- [ ] If you enabled Pi startup, reboot the Pi and verify its display. For
      Bluetooth, also verify receiver reconnection, output selection and playback.
      If audio fails, close Marsi and repeat the local audio check first.

## 7. Art, sermons and morning speech

- [ ] Type `art` twice. See original ASCII machine diagrams with real available
      numeric readings; unavailable Pi data is labelled as such. With Voice on,
      Marsi speaks a description rather than reading punctuation.
- [ ] Type `sermon`. See a short kind sermon framed by art; with Voice on, hear
      the corresponding words. Reopen Marsi and find both inscriptions again.
- [ ] Leave Ubuntu running over a day and check for one scheduled artwork.
      Schedules are preserved if the server restarts.
- [ ] Leave Ubuntu running for 2–3 days and find a scheduled tiny sermon.
- [ ] With Voice and Idle rites on, leave both machines and the audio receiver
      running before 07:00. Hear the morning greeting around 07:00, including
      during default quiet hours. It includes date and available machine data.
- [ ] Restart the display after an observance finishes speaking. Its local
      delivery marker should prevent the same greeting being spoken again.

Do not change the operating-system clock just to speed up these tests. Calendar
and restart logic has automated tests; long-running checks verify the actual
machines. See [behaviour](behaviour.md) for defaults and catch-up rules.

Keep results as hardware observations. Wake words, continuous listening, device
control, raster images, weather and news remain outside this checklist.
