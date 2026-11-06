// Converts mic audio to 16-bit PCM chunks of 20 ms (320 samples at 16 kHz) for Deepgram Flux.
class MicCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buf = new Int16Array(320);
        this.n = 0;
    }

    process(inputs) {
        const channel = inputs[0][0];
        if (channel) {
            for (let i = 0; i < channel.length; i++) {
                const s = Math.max(-1, Math.min(1, channel[i]));
                this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
                if (this.n === this.buf.length) {
                    this.port.postMessage(this.buf.buffer, [this.buf.buffer]);
                    this.buf = new Int16Array(320);
                    this.n = 0;
                }
            }
        }
        return true;
    }
}

registerProcessor('mic-capture', MicCapture);
