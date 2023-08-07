from collections import defaultdict
from pathlib import Path

import click
import librosa
import numpy as np
import torch
import torchaudio
from torchmetrics.functional.audio.pesq import perceptual_evaluation_speech_quality
from tqdm import tqdm

from fish_vocoder.data.transforms.spectrogram import LinearSpectrogram


def pesq_nb(target, preds, sr):
    target = torchaudio.functional.resample(target, orig_freq=sr, new_freq=8000)
    preds = torchaudio.functional.resample(preds, orig_freq=sr, new_freq=8000)

    return perceptual_evaluation_speech_quality(preds, target, 8000, "nb").item()


def pesq_wb(target, preds, sr):
    target = torchaudio.functional.resample(target, orig_freq=sr, new_freq=16000)
    preds = torchaudio.functional.resample(preds, orig_freq=sr, new_freq=16000)

    return perceptual_evaluation_speech_quality(preds, target, 16000, "wb").item()


def spec_difference(spec, target, preds):
    target = spec(target[None])
    preds = spec(preds[None])

    target = torch.log(torch.clamp(target, min=1e-5))
    preds = torch.log(torch.clamp(preds, min=1e-5))

    return torch.mean(torch.abs(target - preds)).item()


@click.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=True, file_okay=False))
@click.argument(
    "generated", type=click.Path(exists=True, dir_okay=True, file_okay=False)
)
def main(source, generated):
    source = Path(source)
    generated = Path(generated)

    assert source.is_dir()
    assert generated.is_dir()

    source_files = sorted(list(source.rglob("*.wav")))
    scores = defaultdict(list)
    bar = tqdm(source_files)

    mel_spec = LinearSpectrogram(2048, 2048, 512, center=False)

    for idx, source_file in enumerate(tqdm(source_files)):
        generated_file = generated / source_file.relative_to(source)

        if not generated_file.exists():
            generated_file = generated_file.with_suffix(".flac")

        if not generated_file.exists():
            print(f"{generated_file} does not exist")
            continue

        source_audio, sr = librosa.load(source_file, sr=24000)
        generated_audio, _ = librosa.load(generated_file, sr=24000)

        min_len = min(len(source_audio), len(generated_audio))
        assert max(len(source_audio) - min_len, len(generated_audio) - min_len) < 1000

        source_audio = source_audio[:min_len]
        generated_audio = generated_audio[:min_len]

        source_audio = torch.from_numpy(source_audio)
        generated_audio = torch.from_numpy(generated_audio)

        try:
            scores["pesq_nb"].append(pesq_nb(source_audio, generated_audio, sr))
            scores["pesq_wb"].append(pesq_wb(source_audio, generated_audio, sr))
            scores["spec_diff"].append(
                spec_difference(mel_spec, source_audio, generated_audio)
            )
        except Exception:
            print(f"Error processing {source_file}")
            continue

        if idx % 10 == 0:
            all_metrics = [f"{k}: {np.mean(v):.2f}" for k, v in scores.items()]
            bar.set_description(", ".join(all_metrics))

    print("Average scores:")
    for k, v in scores.items():
        print(f"    {k}: {np.mean(v):.2f}")


if __name__ == "__main__":
    main()
