from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="layer-segmentation",
        description="Open the XADV2 multilayer-background authoring application",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("workspace"),
        help="Directory containing scene projects (default: ./workspace)",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="SAM inference device (default: auto)",
    )
    parser.add_argument(
        "--model",
        choices=("tiny", "small", "base_plus", "large"),
        default="small",
        help="SAM2.1 model used for newly created scenes (default: small)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from .workspace import main as run_workspace

        return run_workspace(args.workspace, args.device, args.model)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
