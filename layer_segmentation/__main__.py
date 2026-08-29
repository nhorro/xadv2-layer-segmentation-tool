if __package__:
    from .cli import main
else:
    # ``python layer_segmentation`` executes this file outside package context.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from layer_segmentation.cli import main

raise SystemExit(main())
