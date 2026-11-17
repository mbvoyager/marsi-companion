# Marsi's reading tools

Marsi can explain measurements from the local climate archive. Internet research
is a separate, opt-in command. Both features use the Ollama model on Ubuntu and
work through the existing chat and Talk controls in the browser and on the Pi.

## Climate questions

Try `Wie warm ist es draußen?`, `What is the humidity inside?` or
`Show the indoor temperature over the last 24 hours.` Marsi replies in English.
The router recognizes current and historical climate questions in English and
German. Ask about a period of `3h`, `24h` or `7d` for historical statistics.

`climate_now` reads temperature, relative humidity, sensor names, indoor/outdoor
locations, measurement times and connection states from the same visible
sensors as the Climate tab. A stale reading is labeled with its last recorded
value. If there is no visible outdoor sensor, Marsi says so. `climate_summary`
uses the climate archive's existing time windows and computes min, max and the
sample mean from the raw readings in that window. It marks any missing series.
The chart's bucket averages remain available in the Climate tab.

The server makes those readings available to the model with their units and
timestamps. For missing data, stale data, reports too large for the small model's
context, or an unusable model answer, Marsi shows the server's formatted report.
Climate answers remain in the journal and are excluded from the model's rolling
exchange history, where they could be mistaken for new readings.

## Settings on Ubuntu

Edit the following keys in `~/marsi-companion/.env.server`. For existing keys,
edit the current line. Restart Marsi after saving with
`systemctl --user restart marsi-server`.

| Setting | Default | Effect |
| --- | --- | --- |
| `MARSI_CLIMATE_NOW` | `true` | Give the companion access to current climate readings |
| `MARSI_CLIMATE_SUMMARY` | `true` | Give the companion access to 3h, 24h and 7d summaries |
| `MARSI_WEB_SEARCH` | `false` | Allow explicitly requested search through SearXNG |
| `MARSI_WEB_FETCH` | `true` | Allow reading one search result in an authorized research turn |
| `MARSI_SEARXNG_PORT` | `8888` | Local SearXNG port on `127.0.0.1` |
| `MARSI_TOOL_CALLING` | `false` | Let Ollama propose validated tool calls |

The climate switches control the companion's tools. The Climate tab reads its
existing API. `MARSI_CLIMATE_CONFIG` must point to the active climate setup for
the companion to see its sensors. See [Climate setup](climate.md).

Clear climate questions use the deterministic router. With Ollama tool calling
enabled, the model can also ask for an enabled climate tool when the router
finds no clear match. An explicit research command always sets the search query
and uses one tool call. The default router reads the first result when enabled.
Ollama tool calling lets the model choose one of the results if it calls
`web_fetch` with a URL from that search. The server validates the name and exact
arguments and executes at most two tool calls for the entire answer. Invalid
batches are logged and discarded. At the limit or after a rejected choice, the
model can finish its reply with tool calling off.
See [Ollama's tool protocol](https://docs.ollama.com/capabilities/tool-calling).

## Internet research

Type `/research How do rain droplets form?`. To use the microphone, press Talk
and say **“Marsi research, how do rain droplets form?”** The command is
recognized in the Talk recording. Speech recognition is English.

The Pi and browser show live search, page-reading and answer-preparation phases
when they occur. A research reply carries an **Internet Research** label and a
list of source titles and domains. The search returns up to five results. If the
page cannot be fetched, Marsi can answer from the available snippets. If the
service is down or the sources are insufficient, Marsi reports that.

### Install SearXNG if you want research

This step is for the **Ubuntu server**. SearXNG queries search providers and
normalizes their results into JSON. The container reuses the Docker daemon
already used by Mosquitto and Zigbee2MQTT. As a starting budget, allow about
**300–500 MB of additional RAM** and **1 GB of disk space**, including the image
and its cache. Actual usage depends on the image and load. Direct installation
would require maintaining another Python environment and service. A hosted
search API would require sending the query to that service directly and might
need an account. The local container is the simplest fit for this setup.
[SearXNG container documentation](https://docs.searxng.org/admin/installation-docker.html)

1. Confirm Docker is active and port 8888 is free.

   ```bash
   systemctl is-active docker
   ss -ltn 'sport = :8888'
   ```

   Expect `active` and an empty listener table. If another program uses the
   port, choose a free one in the Docker mapping, the curl check and
   `MARSI_SEARXNG_PORT`.

2. Create the private configuration on a first installation. The configuration
   enables JSON and uses the Brave web engine, whose search request is a GET.
   Its secret is generated and written locally. [SearXNG settings](https://docs.searxng.org/admin/settings/settings.html),
   [Brave engine source](https://github.com/searxng/searxng/blob/master/searx/engines/brave.py).

   ```bash
   mkdir -p "$HOME/marsi-search/config" "$HOME/marsi-search/cache"
   cd "$HOME/marsi-search"
   (
     umask 077
     set -C
     cat > config/settings.yml <<EOF
   use_default_settings:
     engines:
       keep_only:
         - brave
   server:
     secret_key: "$(openssl rand -hex 32)"
     limiter: false
     public_instance: false
     image_proxy: false
     method: GET
   search:
     formats:
       - html
       - json
   engines:
     - name: brave
       disabled: false
   outgoing:
     request_timeout: 4.0
     max_request_timeout: 6.0
   EOF
   ) && test -s config/settings.yml && printf 'SearXNG configuration exists\n'
   ```

   Expect the confirmation. If the file already exists, open it for editing and
   keep its existing secret.

3. Pull and start the container. The inspected digest selects the downloaded
   image for reproducible restarts. Docker publishes SearXNG on Ubuntu's own
   loopback interface.

   ```bash
   cd "$HOME/marsi-search"
   sudo docker pull docker.io/searxng/searxng:latest
   searx_image="$(sudo docker image inspect docker.io/searxng/searxng:latest \
     --format '{{index .RepoDigests 0}}')"
   sudo docker run -d --name marsi-searxng --restart unless-stopped \
     -p 127.0.0.1:8888:8080 \
     --mount "type=bind,source=$PWD/config,target=/etc/searxng" \
     --mount "type=bind,source=$PWD/cache,target=/var/cache/searxng" \
     "$searx_image"
   sudo docker ps --filter name=marsi-searxng
   ```

   Expect `Up` and `127.0.0.1:8888->8080/tcp`. Check actual memory use with
   `sudo docker stats --no-stream marsi-searxng`. For a startup failure, inspect
   `sudo docker logs --tail 60 marsi-searxng` before proceeding.

4. Verify the search path and JSON format with a public test query. The command
   asks the configured upstream provider about rain. [SearXNG Search API](https://docs.searxng.org/dev/search_api.html)

   ```bash
   curl -fsS --max-time 10 -G http://127.0.0.1:8888/search \
     --data-urlencode 'q=How do rain droplets form?' \
     --data-urlencode 'format=json' |
     python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["results"]), "results"); print(d.get("unresponsive_engines", []))'
   ```

   Expect a positive result count. HTTP 403 calls for checking enabled formats.
   If the count is zero, look at `unresponsive_engines` and the container log
   for an upstream timeout or rate limit before enabling Marsi search.

5. Set `MARSI_WEB_SEARCH=true` in `~/marsi-companion/.env.server` and restart the
   user service.

   ```bash
   systemctl --user restart marsi-server
   systemctl --user is-active marsi-server
   ```

   Expect `active`. In the browser, send the test query with `/research`. Check
   for the phase and the final source labels. Update and restart the Pi client
   if it has older display code. Try the same command with the Pi's text input
   and microphone.

## Security and audit

- Search and page retrieval make HTTP GET requests. A search sends the explicit
  question. A page request sends its result URL and normal connection metadata.
  Search code receives no notes, dialogue history, microphone recording,
  tokens, climate readings or machine telemetry.
- Marsi accepts result pages over HTTP or HTTPS on standard ports. It checks
  every resolved address and connects directly to the checked address. Private,
  loopback, link-local and multicast addresses are rejected. Each of up to
  three redirects goes through the same validation. The original hostname is
  used to validate HTTPS. The search service is a separate, fixed loopback
  destination.
- A page download is capped at 2 MB, page text at 2,400 characters and each
  search snippet at 320 characters. Only plain text and HTML are accepted for
  pages. Search has up to 10 seconds and page retrieval up to 8 seconds, both
  within Marsi's configured answer deadline. The model gets isolated,
  labeled evidence after the tool phase. Its output cannot trigger another
  request.
- The tool whitelist contains climate reads and research reads. It exposes no
  shell, arbitrary file reads, forms, deletion, admin operations or Zigbee
  commands. The existing human-operated climate admin API is separate.
- The server logs the exact explicit search query locally. Sources and answers
  are displayed for the current session of the UI and are excluded from the
  server journal and long-term memory. Inspect queries on Ubuntu with
  `journalctl --user -u marsi-server -g 'Research query'`. The journal follows
  the machine's systemd retention settings.
- `MARSI_WEB_SEARCH=false` prevents both search and page retrieval. Inference
  uses a downloaded local Ollama model and an Ollama URL on loopback or a
  literal private LAN address. For a local-only Ollama service, set
  `OLLAMA_NO_CLOUD=1` in Ollama's own service environment and restart Ollama.
  The Marsi service uses Whisper from its local cache. The separate
  `marsi_local.speech --check-recognition` setup diagnostic can download
  missing Whisper files. [Ollama local mode](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features)

## Measure Ollama tool choice

On Ubuntu, where the model is already installed:

```bash
cd ~/marsi-companion
.venv-server/bin/python -m marsi_local.tool_check --runs 2
```

This exercises the native Ollama protocol with synthetic prompts and validates
the first response against the production schemas. It does not invoke tools or
read the conversation archive. The list covers current readings in German and
English, all three historical ranges, an ordinary question, requests for
unavailable capabilities, and selection from fake result URLs. The diagnostic
warms up the model and reports per-prompt time, exact matches and median latency.
Use the same diagnostic after changing the model or Ollama version.

On 2026-11-17, Ollama **0.35.1** with **Qwen3 1.7B**, Q4_K_M, selected the exact
tool and arguments in **12 of 18** trials. The test used one local CPU instance
with three threads on an Intel i7-8850H. The median selection time after warm-up
was **3.1 seconds**, with a range of **1.4–33.9 seconds**. The Ubuntu i5-4460 has
its own runtime characteristics.

| Prompt | Exact choices | What happened |
| --- | ---: | --- |
| Outdoor temperature in German | 0/2 | Answered without requesting climate data |
| Current humidity in English | 0/2 | Answered without requesting climate data |
| Indoor temperature range over 3h | 0/2 | Proposed invalid arguments, which validation rejected |
| Mean temperature over 24h in German | 2/2 | Selected `climate_summary` with `24h` |
| High and low temperature over 7d | 2/2 | Selected `climate_summary` with `7d` |
| Arithmetic, an unsolicited online search and a shell request | 6/6 | Returned no tool calls |
| Relevant page from two synthetic results | 2/2 | Selected the permitted `web_fetch` URL |

These are small synthetic samples of tool selection. The deterministic router
remains the default for this model and handles clear climate requests even
with Ollama tool calling enabled.

A separate run used the same model with two synthetic SQLite sensors. Marsi
answered the German outdoor question in English using the outdoor value of
8.25 °C. A research turn using simulated external sources produced a short
answer, all three progress phases and a citation.
