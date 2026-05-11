// AudioWorklet that captures mic input, downsamples to 16 kHz mono Int16,
// and posts ArrayBuffers to the main thread for WS send.
//
// Buffers are emitted every ~40 ms (640 samples @ 16 kHz).

class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const opts = (options && options.processorOptions) || {}
    this.targetRate = opts.targetRate || 16000
    this.frameSamples = opts.frameSamples || 640 // 40 ms @ 16 kHz
    this.inRate = sampleRate
    this.ratio = this.inRate / this.targetRate
    this.outBuf = new Int16Array(this.frameSamples)
    this.outIdx = 0
    this.resampleAcc = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true
    const channel = input[0]
    if (!channel) return true

    // Linear-decimation resample to targetRate
    for (let i = 0; i < channel.length; i++) {
      this.resampleAcc += 1
      if (this.resampleAcc >= this.ratio) {
        this.resampleAcc -= this.ratio
        let s = channel[i]
        if (s > 1) s = 1
        else if (s < -1) s = -1
        this.outBuf[this.outIdx++] = (s * 0x7fff) | 0
        if (this.outIdx >= this.frameSamples) {
          // Copy then post — outBuf gets reused
          const out = new Int16Array(this.outBuf)
          this.port.postMessage(out.buffer, [out.buffer])
          this.outIdx = 0
        }
      }
    }
    return true
  }
}

registerProcessor('pcm-capture', PCMCaptureProcessor)
