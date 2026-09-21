from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, "/opt/gsplat/examples")

from gsplat.strategy import DefaultStrategy
from simple_trainer import Config, main as train_main

PROFILES = {
    "preview": {
        "data_factor": 4,
        "max_steps": 3000,
    },
    "standard": {
        "data_factor": 2,
        "max_steps": 7000,
    },
    "high": {
        "data_factor": 2,
        "max_steps": 15000,
    },
}


def run(data_dir: Path, result_dir: Path, profile_name: str) -> None:
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA is unavailable. Start the gsplat compose profile on a host "
            "with an NVIDIA GPU and NVIDIA Container Toolkit."
        )

    profile = PROFILES[profile_name]
    steps = profile["max_steps"]

    cfg = Config(
        disable_viewer=True,
        data_type="colmap",
        data_dir=str(data_dir),
        data_factor=profile["data_factor"],
        result_dir=str(result_dir),
        test_every=8,
        max_steps=steps,
        eval_steps=[],
        save_steps=[steps],
        save_ply=True,
        ply_steps=[steps],
        disable_video=True,
        packed=True,
        cache_images=False,
        strategy=DefaultStrategy(verbose=True),
    )
    train_main(0, 0, 1, cfg)


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    args = parser.parse_args()
    run(args.data_dir.resolve(), args.result_dir.resolve(), args.profile)


if __name__ == "__main__":
    cli()
