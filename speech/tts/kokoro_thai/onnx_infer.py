"""ONNX Runtime inference for the Thai student — the CPU serving path.

thoughts/cpu-inference-serving.md benchmarked the runtimes against Kokoro's
English weights: ORT fp16 is the fastest CPU option, int8 dynamic quantization
is ~2.5x *slower* (this LSTM/Conv graph has no fast int8 kernel), and load
capacity comes from going wide — many small workers — not fat. This module is
that path for our fine-tuned student, which the study never covered.

`onnx_export.build` writes three graphs, split at the two places KModel.forward
leaves the tensor world:

    prosody.onnx   input_ids, style_dur, speed   -> pred_dur, d, t_en
    (host)         repeat_interleave -> gather en/asr
    curves.onnx    en, style_dur                 -> f0_curve, n_curve
    (host)         harmonic source + STFT        -> har
    decoder.onnx   asr, f0_curve, n_curve, style_acou, har -> audio

The first split retires the dense (n_tokens x n_frames) alignment matrix
KModel.forward materializes: `d.transpose(-1,-2) @ pred_aln_trg` selects each
column of `d` once, so it is a gather, and that is what happens here.

The second split exists for precision, not shape. SineGen accumulates phase to
~1.4e5 radians over a chunk, where float32 spacing is ~8e-3 — so a 1e-7
relative difference in the resampling ahead of it lands as a ~0.03 rad error
in sin(), and ONNX Runtime's Resize does not round bit-identically to torch's
interpolate. Computed in float64 here, the same phase is exact to ~1e-11 rad.
It costs ~2% of a chunk's compute and it is the difference between a faithful
excitation and an audibly noisy one.

SineGen's noise likewise comes from numpy seeded by the caller rather than
torch's global RNG, which ORT cannot seed per request. Same seed still means
same audio; the waveform differs from the torch path's at equal seed because
the RNG differs.

This module deliberately imports neither torch nor kokoro: an ORT worker needs
numpy, onnxruntime and the G2P, and never loads the checkpoint.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PRECISIONS = ("fp32", "fp16")
# fp32 by default, against the expectation set by the study: fp16 measured both
# slower and audibly worse on this student. The conversion has to keep fp32 at
# the boundary, and the Cast nodes that adds cost more than halved weights save
# on a graph of many small conv ops; quality suffers because the vocoder's
# `exp` overflows fp16 and the iSTFT's 1e-11 envelope floor underflows it.
DEFAULT_PRECISIONS = ("fp32",)
GRAPH_NAMES = ("prosody", "curves", "decoder")
MANIFEST_NAME = "onnx_manifest.json"
STYLES_NAME = "styles.npz"

# SineGen / iSTFTNet constants. Asserted against the checkpoint at export time
# (onnx_export._source_config), so a retuned vocoder cannot silently drift.
HARMONICS = 9              # 8 overtones + the fundamental
UPSAMPLE_SCALE = 300       # prod(upsample_rates) * gen_istft_hop_size
SAMPLES_PER_FRAME = 600    # audio samples per predicted duration unit, 24 kHz
SAMPLE_RATE = 24000
VOICED_THRESHOLD = 10.0
SINE_AMP = 0.1
NOISE_STD = 0.003
N_FFT = 20
HOP = 5

DEFAULT_SEED = 1234


@dataclass
class OnnxStudent:
    """The serving-side counterpart of infer.Student."""
    prosody: Any        # ort.InferenceSession
    curves: Any         # ort.InferenceSession
    decoder: Any        # ort.InferenceSession
    vocab: dict
    g2p: Any
    source_weight: np.ndarray   # SourceModuleHnNSF.l_linear, applied on the host
    source_bias: np.ndarray
    window: np.ndarray          # the STFT's analysis window
    precision: str = "fp16"


def load_onnx(model_dir: str | Path, g2p=None, intra_threads: int = 1,
              precision: str = "fp16") -> OnnxStudent:
    """Open the sessions from a bundle written by onnx_export.build.

    `intra_threads` is per session and should stay small: the study found
    per-request latency saturates around 5 threads, and that N workers x 2
    threads beats one worker x 2N threads by ~40%. Size the worker pool, not
    this.
    """
    import onnxruntime as ort

    model_dir = Path(model_dir)
    manifest = json.loads((model_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    if precision not in manifest["precisions"]:
        raise FileNotFoundError(
            f"{model_dir} has no {precision} graphs (exported: {manifest['precisions']})")

    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_threads
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    sessions = [
        ort.InferenceSession(str(model_dir / f"{name}_{precision}.onnx"),
                             sess_options=options, providers=["CPUExecutionProvider"])
        for name in GRAPH_NAMES
    ]
    if g2p is None:
        from .g2p import ThaiG2P

        g2p = ThaiG2P()
    source = np.load(model_dir / manifest["source_params"])
    return OnnxStudent(
        prosody=sessions[0], curves=sessions[1], decoder=sessions[2],
        vocab=manifest["vocab"], g2p=g2p,
        source_weight=source["weight"], source_bias=source["bias"],
        window=source["window"], precision=precision)


def load_styles(model_dir: str | Path) -> dict[int, np.ndarray]:
    """The per-speaker ref_s vectors, precomputed at export time.

    The style encoders are the only other thing serving needed torch for, so
    baking these in is what lets a worker run without the checkpoint.
    """
    with np.load(Path(model_dir) / STYLES_NAME) as data:
        return {int(k): data[k].astype(np.float32).reshape(1, 256) for k in data.files}


def synth(student: OnnxStudent, text: str, ref_s, speed: float = 1.0,
          seed: int = DEFAULT_SEED) -> np.ndarray:
    """Thai text -> 24 kHz waveform (float32 numpy). Mirrors infer.synth."""
    return synth_phonemes(student, student.g2p.phonemize(text), ref_s, speed, seed)


def synth_phonemes(student: OnnxStudent, phonemes: str, ref_s, speed: float = 1.0,
                   seed: int = DEFAULT_SEED) -> np.ndarray:
    """Same, from phonemes already computed — the API path counts tokens while
    chunking, so it has them and need not phonemize twice."""
    ids = [i for i in (student.vocab.get(p) for p in phonemes) if i is not None]
    if not ids:
        return np.zeros(0, dtype=np.float32)

    ref_s = np.asarray(ref_s, dtype=np.float32).reshape(1, 256)
    style_dur, style_acou = ref_s[:, 128:], ref_s[:, :128]

    pred_dur, d, t_en = student.prosody.run(None, {
        "input_ids": np.array([[0, *ids, 0]], dtype=np.int64),
        "style_dur": style_dur,
        "speed": np.array([speed], dtype=np.float32),
    })

    # The alignment KModel.forward builds as a matrix, as the gather it is.
    index = np.repeat(np.arange(pred_dur.shape[0], dtype=np.int64), pred_dur)
    en = np.ascontiguousarray(d.transpose(0, 2, 1)[:, :, index])
    asr = np.ascontiguousarray(t_en[:, :, index])

    f0_curve, n_curve = student.curves.run(None, {"en": en, "style_dur": style_dur})
    har = harmonic_source(student, f0_curve, seed)
    audio, = student.decoder.run(None, {
        "asr": asr, "f0_curve": f0_curve, "n_curve": n_curve,
        "style_acou": style_acou, "har": har,
    })
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def harmonic_source(student: OnnxStudent, f0_curve: np.ndarray, seed: int) -> np.ndarray:
    """SineGen + SourceModuleHnNSF + the analysis STFT, in float64.

    A line-for-line mirror of kokoro.istftnet, with two changes: the phase runs
    in float64 (see the module docstring), and the noise is drawn from `seed`
    rather than torch's global RNG.
    """
    rng = np.random.default_rng(seed)
    f0 = np.repeat(np.asarray(f0_curve, dtype=np.float64), UPSAMPLE_SCALE, axis=1)[..., None]
    n_samples = f0.shape[1]

    rad = f0 * np.arange(1, HARMONICS + 1, dtype=np.float64) / SAMPLE_RATE
    rad -= np.floor(rad)                       # SineGen's `% 1`, sign of the divisor
    rand_ini = rng.random((1, HARMONICS))
    rand_ini[:, 0] = 0.0                       # the fundamental keeps its phase
    rad[:, 0, :] += rand_ini

    # Phase accumulates at F0 rate — down, cumulate, back up — or a long chunk's
    # sine drifts out of tune. This is SineGen's own round trip, not ours.
    phase = np.cumsum(_resample(rad, 1 / UPSAMPLE_SCALE), axis=1) * 2 * np.pi
    phase = _resample(phase * UPSAMPLE_SCALE, UPSAMPLE_SCALE)

    voiced = (f0 > VOICED_THRESHOLD).astype(np.float64)
    amplitude = voiced * NOISE_STD + (1 - voiced) * SINE_AMP / 3
    noise = rng.standard_normal((1, n_samples, HARMONICS))
    waves = np.sin(phase) * SINE_AMP * voiced + amplitude * noise

    merged = np.tanh(waves @ student.source_weight.T + student.source_bias)
    return _stft(merged[0, :, 0].astype(np.float32), student.window)


def _resample(x: np.ndarray, scale: float) -> np.ndarray:
    """Linear resampling along axis 1, matching F.interpolate(align_corners=False).

    Source coordinates are half-pixel — (j + 0.5) / scale - 0.5 — and clamped
    to the input range at both edges, which is what torch does and what makes
    the first and last half-block constant.
    """
    length = x.shape[1]
    out_length = int(length * scale)
    source = (np.arange(out_length, dtype=np.float64) + 0.5) / scale - 0.5
    np.clip(source, 0, length - 1, out=source)
    lower = np.floor(source).astype(np.int64)
    upper = np.minimum(lower + 1, length - 1)
    weight = (source - lower)[None, :, None]
    return x[:, lower] * (1 - weight) + x[:, upper] * weight


def _stft(audio: np.ndarray, window: np.ndarray) -> np.ndarray:
    """The generator's `cat([har_spec, har_phase])`, as torch.stft computes it:
    centred with reflect padding, one-sided, unnormalized."""
    padded = np.pad(audio, N_FFT // 2, mode="reflect")
    n_frames = (len(padded) - N_FFT) // HOP + 1
    frames = np.lib.stride_tricks.as_strided(
        padded, (n_frames, N_FFT), (padded.strides[0] * HOP, padded.strides[0]))
    spectrum = np.fft.rfft(frames * window, axis=1).T[None]
    return np.concatenate([np.abs(spectrum), np.angle(spectrum)],
                          axis=1).astype(np.float32)


def count_tokens(student: OnnxStudent, phonemes: str) -> int:
    return sum(1 for p in phonemes if p in student.vocab)
