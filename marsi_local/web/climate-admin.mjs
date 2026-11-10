const $ = id => document.getElementById("admin-" + id);
const clock = new Intl.DateTimeFormat("en-GB", {dateStyle: "medium", timeStyle: "medium"});

function node(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text;
  return element;
}

function options(select, items, preferred = select.value) {
  select.replaceChildren(...items.map(([value, label]) => {
    const option = node("option", label);
    option.value = value;
    return option;
  }));
  if (items.some(([value]) => value === preferred)) select.value = preferred;
}

export class ClimateAdminView {
  constructor(request) {
    this.request = request;
    this.session = null;
    this.revision = 0;
    this.entries = new Map();
    this.sensors = new Map();
    this.form("login", () => this.unlock());
    this.form("editor", () => this.save());
    this.form("readings", () => this.read(0, this.filtersFromForm()));
    $("lock").addEventListener("click", () => { this.close(); this.open(); });
    $("pair-open").addEventListener("click", () => this.pair(true));
    $("pair-close").addEventListener("click", () => this.pair(false));
    $("refresh").addEventListener("click", () => this.refresh());
    $("sensor").addEventListener("change", () => this.fillEditor());
    $("show").addEventListener("click", () => this.save(true));
    $("hide").addEventListener("click", () => this.preview({action: "hide", id: this.selected()?.sensor?.id}));
    $("unpair").addEventListener("click", () => this.preview({action: "unpair", id: this.selected()?.sensor?.id}));
    $("delete").addEventListener("click", () => this.preview({action: "delete", filters: this.filtersFromForm()}));
    $("previous").addEventListener("click", () => this.read(this.previousOffset, this.readFilters));
    $("next").addEventListener("click", () => this.read(this.nextOffset, this.readFilters));
    $("cancel").addEventListener("click", () => $("dialog").close());
    $("confirm").addEventListener("click", () => this.confirm());
    $("dialog").addEventListener("close", () => { this.pending = null; });
  }

  form(id, action) {
    $(id).addEventListener("submit", event => { event.preventDefault(); action(); });
  }

  notice(message, error = false) {
    $("notice").textContent = message;
    $("notice").dataset.error = error;
  }

  open() {
    if (!$("controls").hidden) return;
    this.notice("Enter the separate climate admin token.");
    $("token").focus();
  }

  close() {
    this.session?.abort();
    this.session = null;
    this.token = "";
    this.busy = this.polling = false;
    this.pending = null;
    this.readFilters = this.previousOffset = this.nextOffset = null;
    clearInterval(this.poll);
    if ($("dialog").open) $("dialog").close();
    $("login").hidden = false;
    $("lock").hidden = $("controls").hidden = $("editor").hidden = $("reading-results").hidden = true;
    $("login").reset();
    $("editor").reset();
    $("readings").reset();
    for (const id of ["sensor", "filter-sensor", "reading-rows", "preview"]) $(id).replaceChildren();
    this.entries.clear();
    this.sensors.clear();
    this.notice("");
  }

  async run(operation, {quiet = false} = {}) {
    const session = this.session;
    if (!session || this.busy || (quiet && this.polling)) return;
    const revision = quiet ? this.revision : ++this.revision;
    if (quiet) this.polling = true;
    else {
      this.busy = true;
      this.notice("[ ARCHIVE ] Working ...");
    }
    const send = async (route, body) => {
      const result = await this.request("/v1/climate/admin/" + route, {
        method: body === undefined ? "GET" : "POST", body, signal: session.signal,
        headers: {"X-Marsi-Admin-Token": this.token},
      });
      if (session.signal.aborted || revision !== this.revision) throw new Error("Administration view changed");
      return result;
    };
    try {
      await operation(send);
    } catch (error) {
      if (session.signal.aborted || revision !== this.revision) return;
      if (error.status === 401 || error.status === 403) {
        this.close();
        this.notice(error.message, true);
      } else if (!quiet) this.notice(error.message, true);
    } finally {
      if (this.session === session) {
        if (quiet) this.polling = false;
        else this.busy = false;
      }
    }
  }

  unlock() {
    if (this.busy) return;
    this.token = $("token").value.trim();
    $("token").value = "";
    this.session = new AbortController();
    this.run(async send => {
      this.renderStatus(await send("status"));
      $("login").hidden = true;
      $("controls").hidden = $("lock").hidden = false;
      this.notice("[ KEEPER ACCESS ] Administration open.");
      this.poll = setInterval(() => this.refresh(true), 3000);
    });
  }

  refresh(quiet = false) {
    return this.run(async send => {
      this.renderStatus(await send("status"));
      if (!quiet) this.notice("Device list refreshed.");
    }, {quiet});
  }

  pair(open) {
    return this.run(async send => {
      this.renderStatus(await send("pairing", {open}));
      this.notice(open ? "Pairing is open for 120 seconds." : "Pairing is closed.");
    });
  }

  selected() { return this.entries.get($("sensor").value); }

  renderStatus(status, savedId) {
    const previous = $("sensor").value;
    const sensors = status.sensors;
    this.sensors = new Map(sensors.map(sensor => [sensor.id, sensor]));
    this.entries = new Map([
      ...sensors.map(sensor => ["sensor/" + sensor.id, {sensor, label: sensor.name +
        (sensor.detached ? " [ZIGBEE REMOVED]" : sensor.hidden ? " [HIDDEN]" : "")}]),
      ...status.discoveries.map(device => ["device/" + device.ieee_address,
        {device, label: `Discovered / ${device.topic}${device.model ? " / " + device.model : ""}`}]),
    ]);
    options($("sensor"), this.entries.size ? [...this.entries].map(([key, entry]) => [key, entry.label])
      : [["", "No registered or discovered devices"]], savedId ? "sensor/" + savedId : previous);
    options($("filter-sensor"), [["", "All sensors"], ...sensors.map(sensor => [sensor.id, sensor.name])]);
    if (savedId || previous !== $("sensor").value) this.fillEditor();
    else this.editorActions();

    const remaining = status.pairing_until_ms == null ? 0 : Math.max(0, Math.ceil((status.pairing_until_ms - Date.now()) / 1000));
    const {mqtt, zigbee2mqtt} = status.services;
    const online = mqtt === "online" && zigbee2mqtt === "online";
    $("pair-open").disabled = $("pair-close").disabled = !online;
    $("pair-status").textContent = `MQTT ${mqtt.toUpperCase()} / ZIGBEE2MQTT ${zigbee2mqtt.toUpperCase()}. ` +
      (remaining ? `Marsi pairing window: ${remaining} s left.` : "Marsi pairing window closed.");
  }

  fillEditor() {
    const selected = this.selected();
    $("name").value = selected?.sensor?.name ?? selected?.device?.topic?.slice(0, 80) ?? "";
    $("room").value = selected?.sensor?.room ?? "";
    $("location").value = selected?.sensor?.location ?? "indoor";
    $("use-color").checked = Boolean(selected?.sensor?.color);
    $("color").value = selected?.sensor?.color ?? "#9fbf97";
    this.editorActions();
  }

  editorActions() {
    const selected = this.selected();
    const sensor = selected?.sensor;
    $("editor").hidden = !selected;
    $("save").textContent = selected?.device ? "Adopt sensor" : "Save sensor";
    $("show").hidden = !sensor?.hidden || sensor.detached;
    $("hide").hidden = !sensor || sensor.hidden || sensor.detached;
    $("unpair").hidden = !sensor?.can_unpair;
  }

  save(show = false) {
    const selected = this.selected();
    if (!selected || !$("editor").reportValidity()) return;
    const payload = {
      ...(selected.device ? {device_id: selected.device.ieee_address} : {id: selected.sensor.id}),
      name: $("name").value, room: $("room").value, location: $("location").value,
      color: $("use-color").checked ? $("color").value : null, show,
    };
    return this.run(async send => {
      const result = await send("sensors", payload);
      this.renderStatus(result, result.saved_id);
      this.notice(selected.device ? "Sensor adopted. Readings appear as the sensor reports." : "Sensor saved.");
    });
  }

  filtersFromForm() {
    const filters = {};
    if ($("filter-sensor").value) filters.sensor_id = $("filter-sensor").value;
    if ($("from").value) filters.from_ms = new Date($("from").value).getTime();
    if ($("to").value) filters.to_ms = new Date($("to").value).getTime();
    return filters;
  }

  sensorName(id) { return this.sensors.get(id)?.name ?? id; }

  read(offset, filters) {
    return this.run(async send => {
      const result = await send("readings", {filters, offset});
      this.readFilters = filters;
      this.previousOffset = result.previous_offset;
      this.nextOffset = result.next_offset;
      const rows = result.rows.map(reading => {
        const row = document.createElement("tr");
        for (const field of [clock.format(reading.observed_ms), this.sensorName(reading.sensor_id), reading.metric, reading.value]) {
          row.append(node("td", field));
        }
        const action = document.createElement("td");
        const button = node("button", "Preview deletion");
        button.type = "button";
        const {value, ...key} = reading;
        button.addEventListener("click", () => this.preview({action: "delete", filters: key}));
        action.append(button);
        row.append(action);
        return row;
      });
      $("reading-rows").replaceChildren(...rows);
      $("reading-results").hidden = false;
      $("previous").disabled = this.previousOffset == null;
      $("next").disabled = this.nextOffset == null;
      this.notice(rows.length ? `${rows.length} readings on this page.` : "No matching readings.");
    });
  }

  preview(payload) {
    return this.run(async send => {
      const result = await send("preview", payload);
      this.pending = result;
      const {scope, action, count} = result;
      if (action === "delete") {
        const sensor = scope.sensor_id ? this.sensorName(scope.sensor_id) : "All sensors";
        const details = scope.observed_ms == null ? [
          scope.from_ms == null ? "" : "From " + clock.format(scope.from_ms),
          scope.to_ms == null ? "" : "Before " + clock.format(scope.to_ms),
        ].filter(Boolean).join(" / ") : `${scope.metric} at ${clock.format(scope.observed_ms)}`;
        $("preview").textContent = `Delete ${count} reading${count === 1 ? "" : "s"} from the live archive.\n${sensor}${details ? " / " + details : ""}\nMarsi will create a database backup first.`;
        $("confirm").textContent = "Confirm deletion";
      } else {
        const verb = action === "hide" ? "Hide in Marsi" : "Remove from Zigbee";
        $("preview").textContent = `${verb}: ${result.sensor_name}.\n${count} existing readings will stay in the archive.\nMarsi will create a database backup first.`;
        $("confirm").textContent = action === "hide" ? "Confirm hide" : "Confirm Zigbee removal";
      }
      this.notice("Review the selection before confirming.");
      $("dialog").showModal();
    });
  }

  confirm() {
    if (!this.pending) return;
    const preview = this.pending;
    this.pending = null;
    $("dialog").close();
    return this.run(async send => {
      const result = await send("confirm", {preview_id: preview.preview_id, confirm: true});
      $("reading-results").hidden = true;
      $("reading-rows").replaceChildren();
      const action = result.action === "delete" ? `Deleted ${result.readings_deleted} reading(s).` : "Sensor updated.";
      this.notice(`${action} Backup ${result.backup}`);
      if (result.status) this.renderStatus(result.status);
    });
  }
}
