#!/usr/bin/python3
"""README 스크린샷을 예시 데이터로 그린다. 화면에 창을 띄우지 않고 실제 계정 정보도 쓰지 않는다."""
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cairo

from agent_usage import providers, widget  # GTK 3 버전을 먼저 고정한다.
from gi.repository import Gdk, GLib, Gtk

OUT = ROOT / "docs" / "screenshots"
NOW = providers.now()


def window(label, used, hours):
    return {"label": label, "used": float(used), "reset_at": NOW + timedelta(hours=hours)}


ACCOUNTS = [
    {"provider": "codex", "id": "system", "label": "System default", "source": "system"},
    {"provider": "codex", "id": "work", "label": "work@example.com", "source": "own"},
    {"provider": "claude", "id": "system", "label": "System default", "source": "system"},
    {"provider": "antigravity", "id": "system", "label": "System default", "source": "system"},
]
REPORTS = {
    ("codex", "system"): {"status": "ok", "plan": "team", "windows": [window("5h", 64, 2.2), window("Weekly", 38, 110)],
                          "image": window("Images · 24h", 21, 15),
                          "reset_credits": {"count": 3, "expires": [NOW + timedelta(days=days, hours=4) for days in (4, 7, 11)]}},
    ("codex", "work"): {"status": "ok", "plan": "plus", "windows": [window("5h", 12, 4.6), window("Weekly", 27, 70)],
                        "reset_credits": {"count": 0, "expires": []}},
    ("claude", "system"): {"status": "ok", "plan": "Max 20x", "windows": [window("5h", 18, 3.1), window("Weekly", 76, 94)]},
    ("antigravity", "system"): {"status": "ok", "plan": None, "windows": [window("Gemini · 5h", 41, 2.9), window("Gemini · Weekly", 23, 150),
                                                                          window("Claude and GPT · 5h", 0, 4.9), window("Claude and GPT · Weekly", 5, 151)]},
}


def background(width, height):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    context = cairo.Context(surface)
    gradient = cairo.LinearGradient(0, 0, width, height)
    gradient.add_color_stop_rgb(0, 0.42, 0.66, 0.85)
    gradient.add_color_stop_rgb(0.55, 0.13, 0.55, 0.85)
    gradient.add_color_stop_rgb(1, 0.05, 0.25, 0.72)
    context.set_source(gradient)
    context.paint()
    return surface, context


def snapshot(widget_to_draw, width):
    offscreen = Gtk.OffscreenWindow()
    offscreen.set_visual(offscreen.get_screen().get_rgba_visual())
    offscreen.add(widget_to_draw)
    widget_to_draw.set_size_request(width, -1)
    offscreen.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    return offscreen.get_pixbuf()


def main():
    widget.Bubble.show_all = lambda self: None
    widget.App.refresh = lambda self, *_args: True
    app = widget.App()
    for indicator in app.indicators.values():
        indicator.set_status(widget.AyatanaAppIndicator3.IndicatorStatus.PASSIVE)
    app.accounts, app.reports = ACCOUNTS, REPORTS
    OUT.mkdir(parents=True, exist_ok=True)

    app.window.remove(app.body)
    app.window.get_visible = lambda: True
    app.place = lambda: None
    app.expanded = {"codex"}
    app.ticket_lists = {("codex", "system")}
    app.render()
    panel = snapshot(app.body, 440)
    surface, context = background(panel.get_width() + 80, panel.get_height() + 80)
    Gdk.cairo_set_source_pixbuf(context, panel, 40, 40)
    context.paint()
    surface.write_to_png(str(OUT / "panel.png"))

    bubble_center = (5600, 900)
    app.bubble.center = lambda: bubble_center
    app.workarea_at = lambda *_args: SimpleNamespace(x=3840, y=40, width=1920, height=1040)
    app.fan.progress = 1.0
    size = 2 * widget.Fan.HALF
    fan = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    app.fan.draw(None, cairo.Context(fan))
    bubble = cairo.ImageSurface(cairo.FORMAT_ARGB32, widget.Bubble.SIZE, widget.Bubble.SIZE)
    widget.draw_orb(cairo.Context(bubble), widget.Bubble.SIZE, 0, widget.load_orb(widget.Bubble.SIZE))
    surface, context = background(size, 250)
    context.set_source_surface(fan, 0, -20)
    context.paint()
    context.set_source_surface(bubble, widget.Fan.HALF - widget.Bubble.SIZE / 2, widget.Fan.HALF - widget.Bubble.SIZE / 2 - 20)
    context.paint()
    surface.write_to_png(str(OUT / "fan.png"))


if __name__ == "__main__":
    GLib.idle_add(lambda: main() or Gtk.main_quit())
    Gtk.main()
