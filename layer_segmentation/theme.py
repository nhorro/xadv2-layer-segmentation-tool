"""Shared dark Tk theme for the workspace and layer editor windows."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


DARK_COLORS = {
    "background": "#1e1f22",
    "panel": "#2b2d31",
    "field": "#232428",
    "foreground": "#e6e6e6",
    "muted": "#aeb3bd",
    "accent": "#4f8cff",
    "selection": "#365880",
    "border": "#3b3e45",
}


def apply_dark_theme(window: tk.Misc) -> None:
    """Apply the same dark palette used by xadv2-animated-sprite."""
    colors = DARK_COLORS
    window.configure(background=colors["background"])
    window.option_add("*background", colors["background"])
    window.option_add("*foreground", colors["foreground"])
    window.option_add("*selectBackground", colors["selection"])
    window.option_add("*selectForeground", colors["foreground"])
    window.option_add("*insertBackground", colors["foreground"])
    window.option_add("*TCombobox*Listbox.background", colors["field"])
    window.option_add("*TCombobox*Listbox.foreground", colors["foreground"])

    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure(".", background=colors["panel"], foreground=colors["foreground"])
    style.configure("TFrame", background=colors["background"])
    style.configure(
        "TLabelframe",
        background=colors["background"],
        bordercolor=colors["border"],
    )
    style.configure(
        "TLabelframe.Label",
        background=colors["background"],
        foreground=colors["foreground"],
    )
    style.configure("TLabel", background=colors["background"], foreground=colors["foreground"])
    style.configure(
        "TButton",
        background=colors["panel"],
        foreground=colors["foreground"],
        bordercolor=colors["border"],
        focuscolor=colors["accent"],
        padding=5,
    )
    style.map(
        "TButton",
        background=[("active", colors["selection"]), ("disabled", colors["background"])],
        foreground=[("disabled", colors["muted"])],
    )

    for widget_style in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(
            widget_style,
            fieldbackground=colors["field"],
            foreground=colors["foreground"],
            background=colors["panel"],
            bordercolor=colors["border"],
            arrowcolor=colors["foreground"],
            insertcolor=colors["foreground"],
        )
        style.map(
            widget_style,
            fieldbackground=[
                ("readonly", colors["field"]),
                ("disabled", colors["background"]),
            ],
            foreground=[
                ("readonly", colors["foreground"]),
                ("disabled", colors["muted"]),
            ],
        )

    for widget_style in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            widget_style,
            background=colors["background"],
            foreground=colors["foreground"],
        )
        style.map(
            widget_style,
            background=[("active", colors["background"])],
            foreground=[("disabled", colors["muted"])],
        )

    style.configure(
        "TScale",
        background=colors["background"],
        troughcolor=colors["field"],
        bordercolor=colors["border"],
    )
    style.configure(
        "TScrollbar",
        background=colors["panel"],
        troughcolor=colors["field"],
        bordercolor=colors["border"],
        arrowcolor=colors["foreground"],
    )
    style.map("TScrollbar", background=[("active", colors["selection"])])
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=colors["field"],
        background=colors["accent"],
        bordercolor=colors["border"],
        lightcolor=colors["accent"],
        darkcolor=colors["accent"],
    )
