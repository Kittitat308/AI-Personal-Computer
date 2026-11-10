# Wayu-Paxa-TTS-Edge

The speech model in this folder and the Thai frontend in `../kokoro_thai/` come from
**Wayu-Paxa-TTS-Edge** by Wayu Research (https://huggingface.co/wayu-ai/wayu-paxa-tts-edge).

- Code: Apache-2.0
- Model weights and voices (`voice-*.bin`, `*.onnx`): **CC-BY-NC-4.0, non-commercial use only**

The three ONNX graphs (`prosody_fp32.onnx`, `curves_fp32.onnx`, `decoder_fp32.onnx`,
about 317 MB) are not stored in git. Copy them into this folder before turning speech on.
