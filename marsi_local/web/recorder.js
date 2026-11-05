class MarsiRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(4096);
    this.used = 0;
    this.remaining = Math.floor(sampleRate * 15);
    this.active = true;
    this.port.onmessage = event => {
      if (event.data === "finish") this.finish();
    };
  }

  flush() {
    if (!this.used) return;
    const samples = this.buffer.slice(0, this.used);
    this.port.postMessage(samples, [samples.buffer]);
    this.used = 0;
  }

  finish() {
    if (!this.active) return;
    this.flush();
    this.active = false;
    this.port.postMessage("done");
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!this.active || !channel) return this.active;
    const count = Math.min(this.remaining, channel.length);
    for (let i = 0; i < count; i++) {
      this.buffer[this.used++] = channel[i];
      if (this.used === this.buffer.length) this.flush();
    }
    this.remaining -= count;
    if (!this.remaining) this.finish();
    return this.active;
  }
}

registerProcessor("marsi-recorder", MarsiRecorder);
