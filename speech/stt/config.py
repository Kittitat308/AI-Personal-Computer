from pathlib import Path


STT_DIR = Path(__file__).resolve().parent
MODEL_DIR = STT_DIR / "zipformer"

ENCODER_PATH = MODEL_DIR / "encoder-epoch-12-avg-5.int8.onnx"
DECODER_PATH = MODEL_DIR / "decoder-epoch-12-avg-5.onnx"
JOINER_PATH = MODEL_DIR / "joiner-epoch-12-avg-5.int8.onnx"
TOKENS_PATH = MODEL_DIR / "tokens.txt"

SAMPLE_RATE = 16_000
FEATURE_DIM = 80
NUM_THREADS = 2
CHANNELS = 1
