# Cogitator before / after

These captures use synthetic conversations and sensor/machine readings. No live
tokens, personal journal, device serials or private network addresses are shown.
The web's test banner explicitly identifies the data as synthetic.

The earlier web comes from revision `2f203dc`; the earlier Pi was captured before
the redesign. Tk captures render the actual off-screen widget layout and cached
canvas items, including wrapped text. They are development captures on Windows,
not evidence of physical Pi speed. Web captures use a real headless Firefox;
the phone content is constrained to 375 px. Verify touch, smoothness and sound
on the Pi 3 B+ and a physical phone using [the release checks](../../docs/cogitator.md).

## Journal and climate

| Surface | Before | After |
| --- | --- | --- |
| Pi 800 × 480 | [Before](before/terminal-800x480.png) | [After](after/terminal-800x480.png) |
| Pi 480 × 320 | [Before](before/terminal-480x320.png) | [After](after/terminal-480x320.png) |
| Web desktop | [Before](before/web-desktop.png) | [After](after/web-desktop.png) |
| Web phone, Climate | [Before](before/web-phone.png) | [After](after/web-phone.png) |

Four-sensor curves: [desktop](after/web-desktop-history.png),
[phone](after/web-phone-history.png). Each line has its sensor's colour, shape
marker and distinct dash pattern.

The isolated [before portrait](before/marsi-effigy.png) and
[after portrait](after/marsi-effigy.png) have identical pixels in the compared
idle pose. New interlude lens/gaze modes are additional reactions.

## Interludes

| Scene | Pi 800 × 480 | Pi 480 × 320 |
| --- | --- | --- |
| Auspex | [View](after/pi-auspex-800x480.png) | [View](after/pi-auspex-480x320.png) |
| Vox | [View](after/pi-vox-800x480.png) | [View](after/pi-vox-480x320.png) |
| Servitor | [View](after/pi-servitor-800x480.png) | [View](after/pi-servitor-480x320.png) |
| Hololith | [View](after/pi-hololith-800x480.png) | [View](after/pi-hololith-480x320.png) |
| Codex | [View](after/pi-codex-800x480.png) | [View](after/pi-codex-480x320.png) |
| Noosphere | [View](after/pi-noosphere-800x480.png) | [View](after/pi-noosphere-480x320.png) |

| Scene | Web desktop | Web phone |
| --- | --- | --- |
| Auspex | [View](after/web-desktop-auspex.png) | [View](after/web-phone-auspex.png) |
| Vox | [View](after/web-desktop-vox.png) | [View](after/web-phone-vox.png) |
| Servitor | [View](after/web-desktop-servitor.png) | [View](after/web-phone-servitor.png) |

Both renderers are tested with the same six JSON packets in
`tests/fixtures/interludes.json`. Browser tests additionally open all six scenes,
check overflow and observe the moving block-cursor text reveal.
