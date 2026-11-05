# Climate sensors on Ubuntu

The SONOFF coordinator receives the Aqara radio reports. Zigbee2MQTT publishes
them to Mosquitto, and the Marsi server records selected sensor topics in SQLite.
Docker runs the two Zigbee services on Ubuntu. Marsi continues to run from its
existing server environment.

## 1. Recognise the coordinator and install Docker

Plug the dongle into Ubuntu and run `ls -l /dev/serial/by-id/`. Keep the full path
for the device. It follows the dongle even if Ubuntu assigns a different tty
number. The **ZBDongle-P** uses `zstack`. The **ZBDongle-E** uses `ember` and needs
its own adapter settings. [Zigbee2MQTT adapter settings](https://www.zigbee2mqtt.io/guide/configuration/adapter-settings.html)

On Ubuntu 26.04, Docker Engine and Compose are available as `docker.io` and
`docker-compose-v2`. They take a few hundred MB of disk space. The pinned
container images include the broker and Zigbee2MQTT's Node.js runtime. For
Zigbee2MQTT, budget about 1 GB of additional disk space and a few hundred MB of
RAM. [Docker image guide](https://www.zigbee2mqtt.io/guide/installation/02_docker.html)

```bash
sudo apt update
sudo apt install docker.io docker-compose-v2
systemctl is-active docker
sudo docker version --format '{{.Server.Version}}'
sudo docker compose version
```

Expect `active` and two version numbers. The following steps use
`~/marsi-climate` as a private directory outside the checkout. The coordinator
backup and broker credentials belong there.

## 2. Start Mosquitto

For a fresh setup, create the directory and its broker configuration.

```bash
mkdir -m 700 ~/marsi-climate && cd ~/marsi-climate && mkdir -m 755 mosquitto
cat > compose.yaml <<'EOF'
services:
  mosquitto:
    image: eclipse-mosquitto:2.1.2-alpine
    restart: unless-stopped
    ports:
      - "127.0.0.1:1883:1883"
    volumes:
      - ./mosquitto:/mosquitto/config:ro
      - mosquitto-data:/mosquitto/data

volumes:
  mosquitto-data:
EOF
cat > mosquitto/mosquitto.conf <<'EOF'
listener 1883
allow_anonymous false
plugin /usr/lib/mosquitto_password_file.so
plugin_opt_password_file /mosquitto/config/passwd
persistence true
persistence_location /mosquitto/data/
log_dest stdout
EOF
```

Create the broker account once. `-c` creates the password file, so use it only
for the initial setup. Enter a dedicated MQTT password and keep it for the next
steps. [Mosquitto password tool](https://mosquitto.org/man/mosquitto_passwd-1.html)

```bash
sudo docker compose run --rm --no-deps \
  -v "$PWD/mosquitto:/setup" mosquitto sh -ec '
    mosquitto_passwd -c /setup/passwd marsi
    chown 1883:1883 /setup/passwd
    chmod 600 /setup/passwd
  '
sudo docker compose up -d mosquitto
sudo docker compose ps
```

Mosquitto should be `Up` and publish `127.0.0.1:1883->1883/tcp`. The host port
is local to Ubuntu. Services in the Compose project use `mosquitto:1883` on
their shared network. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)

## 3. Start Zigbee2MQTT

In `~/marsi-climate`, make the `zigbee2mqtt` directory with
`mkdir -m 700 zigbee2mqtt`. Save this as `compose.override.yaml` beside
`compose.yaml`, substituting the full path from step 1 for the host device path.
Compose loads both files automatically.

```yaml
services:
  zigbee2mqtt:
    image: ghcr.io/koenkk/zigbee2mqtt:2.14.3
    restart: unless-stopped
    depends_on:
      - mosquitto
    devices:
      - "/dev/serial/by-id/REPLACE_WITH_DEVICE_PATH:/dev/ttyUSB0"
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ./zigbee2mqtt:/app/data
    environment:
      TZ: Europe/Berlin
```

Save this as `zigbee2mqtt/configuration.yaml` for a fresh ZBDongle-P setup. The
running service replaces `GENERATE` with the new network identifiers and key.
Keep its data directory when updating or restarting so the sensors stay paired.
`cache_state: false` passes through individual updates. `last_seen` gives them
explicit timestamps.

```yaml
version: 5
mqtt:
  server: mqtt://mosquitto:1883
  base_topic: zigbee2mqtt
  user: marsi
  password: '!secret.yaml mqtt_password'
serial:
  port: /dev/ttyUSB0
  adapter: zstack
frontend:
  enabled: true
advanced:
  network_key: GENERATE
  pan_id: GENERATE
  ext_pan_id: GENERATE
  last_seen: ISO_8601
  cache_state: false
  enable_external_js: false
```

Save the same MQTT password in the local Zigbee2MQTT secret file. The input is
hidden. [Zigbee2MQTT secret file](https://www.zigbee2mqtt.io/guide/configuration/mqtt.html#specifying-mqtt-server-user-password-and-network-key-in-a-different-file)

```bash
(
  umask 077
  python3 - <<'PY'
from getpass import getpass
import json
from pathlib import Path

password = getpass("MQTT password for marsi: ")
if not password:
    raise SystemExit("Enter the MQTT password you chose in step 2.")
Path("zigbee2mqtt/secret.yaml").write_text(
    f"mqtt_password: {json.dumps(password, ensure_ascii=False)}\n",
    encoding="utf-8",
)
PY
)
sudo docker compose config --quiet
sudo docker compose up -d zigbee2mqtt
```

After about 30 seconds, run `sudo docker compose ps -a` and
`sudo docker compose logs --tail=40 zigbee2mqtt`. Both containers should be `Up`.
Look for `Connected to MQTT server` and `Zigbee2MQTT started!`. If startup fails,
use the first error in the logs to distinguish adapter access from broker login.

## 4. Pair and verify the first sensor

Keep the sensor near the coordinator. Remove the battery tab if present.
On Ubuntu, run the command below and enter the same MQTT password. It opens the
coordinator for 120 seconds and reads events and sensor reports from Mosquitto.
[Zigbee2MQTT permit-join command](https://www.zigbee2mqtt.io/guide/usage/mqtt_topics_and_messages.html#zigbee2mqtt-bridge-request-permit-join)

```bash
sudo docker run --rm -it --network host --tmpfs /tmp --entrypoint sh \
  eclipse-mosquitto:2.1.2-alpine -ec '
    umask 077
    printf "MQTT password: "
    read -rs mqtt_pass
    printf "\n"
    printf "%s\n" "-h 127.0.0.1" "-u marsi" "-P $mqtt_pass" > /tmp/mqtt.conf
    unset mqtt_pass
    reply=$(mosquitto_rr -o /tmp/mqtt.conf -V mqttv311 -q 1 -W 10 \
      -t zigbee2mqtt/bridge/request/permit_join \
      -e zigbee2mqtt/bridge/response/permit_join \
      -m "{\"time\":120,\"device\":\"coordinator\"}")
    printf "%s\n" "$reply"
    printf "%s\n" "$reply" | grep -q "\"status\":\"ok\""
    printf "Joining open. Pair the sensor now.\n"
    mosquitto_sub -o /tmp/mqtt.conf -v -W 150 \
      -t zigbee2mqtt/bridge/event -t "zigbee2mqtt/+"
  '
```

When the prompt says `Joining open`, hold the WSDCGQ11LM button for about five
seconds and release it as soon as the blue LED blinks. Look for `device_interview`
with `status` set to `successful`, then `temperature` and `humidity` reports.
The sensor can send these in separate messages. Copy the topic suffix after
`zigbee2mqtt/` for your local configuration. The test can be stopped with Ctrl+C
once both values appear. [Aqara WSDCGQ11LM pairing](https://www.zigbee2mqtt.io/devices/WSDCGQ11LM.html#pairing)

## 5. Archive readings in Marsi

In the Marsi checkout on Ubuntu, install the small Paho MQTT client in the
existing server virtual environment. It is a Python library used by the server
to subscribe and reconnect. [Paho MQTT 2.1.0](https://pypi.org/project/paho-mqtt/2.1.0/)

```bash
cd ~/marsi-companion
.venv-server/bin/python -m pip install -r requirements-climate.txt
cp -i config/climate.example.json ~/marsi-climate/marsi.json
nano ~/marsi-climate/marsi.json
```

Replace `REPLACE_WITH_DEVICE_TOPIC` with the exact suffix you saw in step 4.
Sensor IDs use letters, numbers, underscores or hyphens. Set `name` and
`location` (`indoor` or `outdoor`). `color` is an optional `#RRGGBB` value.
Additional sensors are entries in the same `sensors` object. Keep their keys
stable so their history follows them when you change a display name.

Write the password for the Marsi MQTT client. The file is relative to `marsi.json`
and only needs to be readable by the Ubuntu user who runs `marsi-server`.

```bash
(
  umask 077
  .venv-server/bin/python - <<'PY'
from getpass import getpass
from pathlib import Path

password = getpass("MQTT password for marsi: ")
if not password:
    raise SystemExit("Enter the MQTT password you chose in step 2.")
(Path.home() / "marsi-climate" / "marsi-mqtt-password").write_text(password + "\n", encoding="utf-8")
PY
)
```

Add this line to your existing `.env.server` and save it.

```dotenv
MARSI_CLIMATE_CONFIG=~/marsi-climate/marsi.json
```

Restart the server to apply the configuration and check its log.

```bash
systemctl --user restart marsi-server
journalctl --user -u marsi-server -n 30 --no-pager
```

`Climate MQTT subscribed to 1 sensor topic(s)` confirms the broker subscription
for one sensor. After the sensor sends fresh readings, read back the database
from the same checkout.

```bash
.venv-server/bin/python -m marsi_local.climate --check
```

The diagnostic prints the latest stored value and UTC timestamp for each
metric. A sleeping battery sensor can take a while to report again. Battery and
link quality are recorded when present. Each metric keeps its own timestamp in
`climate_readings` inside the existing companion database. Replayed retained
snapshots are skipped and repeated writes for the same sensor, metric and
millisecond use one row. An update without `last_seen` uses the arrival time.
The archive records reports that reach Marsi while its subscriber is running.

## Read the archive over Marsi's API

The climate routes use the existing Marsi server address and bearer token.
Timestamps are Unix milliseconds in UTC. All routes are read-only.

| GET route | Response |
| --- | --- |
| `/v1/climate/now` | One entry per configured sensor with its name, location, optional color and latest values with individual timestamps |
| `/v1/climate/history?range=3h` | Individual temperature and humidity samples from the last three hours |
| `/v1/climate/history?range=24h` | Temperature and humidity means in five-minute buckets |
| `/v1/climate/history?range=7d` | Temperature and humidity means in thirty-minute buckets |
| `/v1/climate/events` | Server-sent `climate` events with the current snapshot |

The `now` response includes `last_measurement_ms` for the most recent
temperature or humidity reading and `last_report_ms` for the newest archived
report of any kind. A sensor is `waiting` before its first temperature or
humidity reading, `fresh` for two hours from the latest measurement and then
`stale`. Battery and link quality have their own timestamps.

Each history series is an array of `[time_ms, value]` pairs. The server averages
each sensor and metric separately inside UTC-aligned buckets. `bucket_ms` is
zero for raw samples. Buckets without measurements are absent.

The event stream sends an initial snapshot, followed by updates after readings
are committed or freshness changes. It sends a keepalive comment during idle
periods. Use the `Authorization` header on the stream request as on the JSON
routes. [Server-sent events format](https://html.spec.whatwg.org/multipage/server-sent-events.html)

From the Ubuntu checkout, use this check after starting the updated server.
It reads the bearer token from the local environment and prints only the sensor
name and state, history counts, and the first event line.

```bash
.venv-server/bin/python - <<'PY'
from urllib.request import Request

from marsi_local.client import Client
from marsi_local.config import ServerConfig, load_env

load_env(".env.server")
api = Client("http://127.0.0.1:8765", token=ServerConfig.from_env().token, timeout=5)
current = api.request("/v1/climate/now", method="GET")
for sensor in current["sensors"]:
    print(sensor["name"], sensor["status"], ", ".join(sensor["readings"]))
for period in ("3h", "24h", "7d"):
    history = api.request(f"/v1/climate/history?range={period}", method="GET")
    count = sum(len(points) for sensor in history["sensors"] for points in sensor["series"].values())
    print(period, "points", count, "bucket_ms", history["bucket_ms"])
request = Request(api.url + "/v1/climate/events", headers={"Authorization": "Bearer " + api.token})
with api.http.open(request, timeout=5) as stream:
    print("Live", stream.readline().decode().strip())
PY
```

`Live event: climate` confirms the stream opened and sent its initial snapshot.
The history point count reflects the actual time window and can be zero after
the sensor has been quiet.

## Open the Klima tab on the Pi

Update the Pi checkout to the version with the climate display and restart the
graphical session. A Pi with Marsi autostart enabled can reboot into the new
display. See the [Pi setup guide](raspberry-pi.md) for the usual start commands.

Choose **KLIMA** above the journal. **Jetzt** shows the temperature, relative
humidity and time of the latest measurement. **AUSSEN** identifies an outdoor
sensor and **SIGNAL ALT** marks a stale climate reading. In **3 h**, **24 h** and
**7 Tage**, the temperature and humidity use separate plots with a shared time
axis. Sensor names, colors and line patterns identify the traces. Wide gaps in
the archive appear as breaks in a trace. A lone sample appears as a dot.

The tab opens a live stream using the Pi's existing Marsi URL and token. New
measurements update the view as they arrive. **LINK PAUSE** indicates the feed
will retry. **CHAT** returns to the journal and **F8** opens it for voice input.

## Open Marsi in a browser on the LAN

Update the Ubuntu checkout to the version with the web interface and restart
`marsi-server`. The same process serves the browser assets, JSON API and live
climate stream. The existing systemd service listens on all IPv4 interfaces
on port `8765`.

```bash
cd ~/marsi-companion
systemctl --user restart marsi-server
curl -fsS http://127.0.0.1:8765/health
hostname -I
```

Use the Ubuntu LAN IPv4 address that the Pi connects to. With the phone on
the same Wi-Fi, open `http://UBUNTU-LAN-IP:8765/` in its browser. Enter the
same Marsi token as on the Pi. The default journal session is `pi`. Use the
value of `MARSI_SESSION` if you chose a different name on the Pi. Browser
tabs remember their login for the tab's session. **LOCK** or `exit` seals it.

Choose **KLIMA** to view the cards, history and live updates. In a history
view, tap a graph to inspect the nearest samples, or use the left and right
arrow keys when a graph is focused. Tap a sensor in the legend to hide or show
its trace. **CHAT** uses the shared journal, supports the same typed commands,
and shows readings from Ubuntu and the Pi. Enable **Voice** for spoken
replies. Use the audio player's Play control if the browser waits for a tap.
Scheduled entries are visible in the journal. Browser playback depends on
the page being open and the browser's media permission.

Keep ports `8765` and `8766` within the trusted LAN. Use the subnet-scoped
firewall rules in the [Ubuntu guide](ubuntu-server.md) if UFW is active and
keep router port forwarding disabled for both ports.

### Enable the browser microphone with local HTTPS

The browser can capture microphone audio from a trusted HTTPS origin. The
optional TLS listener uses the same Marsi process and journal. It defaults to
port `8766`, alongside the existing `8765` listener. It uses Python's built-in
TLS support. OpenSSL is used here to create a local certificate authority and
a server certificate. [Browser microphone requirements](https://www.w3.org/TR/mediacapture-streams/)

Check `openssl version` on Ubuntu first. For a fresh TLS setup, create a
private directory and enter the server's LAN IPv4 address when asked. The
certificate identifies that address, so use the address that the phone will
open. [OpenSSL certificate tool](https://docs.openssl.org/3.5/man1/openssl-req/)

```bash
mkdir -m 700 ~/marsi-climate/tls && cd ~/marsi-climate/tls
```

```bash
(
  set -eu
  umask 077
  read -r -p 'Ubuntu LAN IPv4 address: ' marsi_ip
  python3 -c 'import ipaddress, sys; ipaddress.IPv4Address(sys.argv[1])' "$marsi_ip"

  openssl req -x509 -newkey rsa:3072 -noenc -sha256 -days 3650 \
    -subj '/CN=Marsi LAN Root' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' \
    -keyout marsi-ca.key -out marsi-ca.crt

  openssl req -new -newkey rsa:2048 -noenc -sha256 \
    -subj '/CN=Marsi LAN' -keyout marsi.key -out marsi.csr

  cat > marsi-tls.ext <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$marsi_ip
EOF

  openssl x509 -req -in marsi.csr -CA marsi-ca.crt -CAkey marsi-ca.key \
    -CAcreateserial -days 180 -sha256 -extfile marsi-tls.ext -out marsi.crt
  openssl verify -CAfile marsi-ca.crt -purpose sslserver -verify_ip "$marsi_ip" marsi.crt
)
```

Expect `marsi.crt: OK`. Keep the signing key `marsi-ca.key` and server key
`marsi.key` private. The public `marsi-ca.crt` is the file to transfer to a
phone or computer you control so it can verify the server certificate. Renew
the server certificate before it expires with the same CA to retain the
phone's trust settings.

Add these lines to the existing `.env.server` in `~/marsi-companion`.

```dotenv
MARSI_WEB_TLS_CERT=~/marsi-climate/tls/marsi.crt
MARSI_WEB_TLS_KEY=~/marsi-climate/tls/marsi.key
MARSI_WEB_HTTPS_PORT=8766
```

Restart `marsi-server` and check that its journal includes
`Marsi browser HTTPS listening on 0.0.0.0:8766`. On Ubuntu, substitute the
same IPv4 address as in the certificate and verify HTTPS with the public CA.
[OpenSSL certificate verification](https://docs.openssl.org/3.5/man1/openssl-verify/)

```bash
systemctl --user restart marsi-server
journalctl --user -u marsi-server -n 15 --no-pager
curl --cacert ~/marsi-climate/tls/marsi-ca.crt https://UBUNTU-LAN-IP:8766/health
```

On iOS, install the CA profile and enable trust for it in **Settings →
General → About → Certificate Trust Settings**. On Android, look for
**Install a certificate → CA certificate** in the device's security and
credential settings. Select the public `marsi-ca.crt` file. Menu wording can
vary by device. [Apple certificate trust](https://support.apple.com/102390), [Android certificate settings](https://support.google.com/pixelphone/answer/2844832)

Open `https://UBUNTU-LAN-IP:8766/` on the trusted device and unlock the
archive. Choose **CHAT**, press **TALK** or **F8**, and grant microphone
permission. Press **FINISH** to send the recording, or let the recording
finish after 15 seconds. The browser sends a complete WAV in memory. Marsi
stores the recognised conversation in the same journal as typed turns.

## Simulate more sensors

Add entries to the `sensors` object in your local `marsi.json`, such as these two.

```json
{
  "sim-workbench": {"name": "Simulated workbench", "location": "indoor", "color": "#a68b5c"},
  "sim-exterior": {"name": "Simulated exterior", "location": "outdoor", "color": "#9fbf97"}
}
```

Restart `marsi-server` to pick up the new topic subscriptions. Once the log
confirms the subscriptions, run the simulator from the Marsi checkout. It
sends one batch to every configured `sim-` sensor through the same broker and
storage path. For a continuous test, add `--interval 15` and use Ctrl+C to stop.

```bash
.venv-server/bin/python -m marsi_local.climate --simulate
.venv-server/bin/python -m marsi_local.climate --check
```
