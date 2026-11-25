import math
import signal

import cairo
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import AyatanaAppIndicator3, Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo

from . import accounts, providers
from .i18n import LANGUAGE, t

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
REFRESH_SECONDS = 300
SLIDE_SECONDS = 0.18
FAN_SECONDS = 0.28
BACKOFF_START = 300
BACKOFF_MAX = 1800
NAMES = {"codex": "Codex", "claude": "Claude", "antigravity": "Antigravity"}
ICONS = {"codex": "openai", "claude": "claude-color", "antigravity": "antigravity-color"}
CSS = b"""
.panel { background: #1f1f1f; color: #e8e8e8; border: 1px solid #3a3a3a; border-radius: 10px; font-size: 13px; }
.manager { background: #1f1f1f; color: #e8e8e8; }
.title { font-weight: 700; font-size: 14px; }
.muted { color: #9a9a9a; }
.small { font-size: 12px; }
.tiny { font-size: 11px; }
.percent { font-weight: 600; }
.flat { background: transparent; border: 0; box-shadow: none; color: #d0d0d0; padding: 4px 6px; border-radius: 6px; }
.flat:hover, .row:hover { background: #2c2c2c; }
.row { border-radius: 8px; }
.selected { background: #2c2c2c; }
.card { background: #161616; border-radius: 10px; padding: 12px 14px; }
.pill { background: #2a2a2a; border: 1px solid #444; color: #e8e8e8; border-radius: 8px; padding: 4px 12px; box-shadow: none; }
.separator { background: #333333; min-height: 1px; }
.warning { color: #f5a524; }
entry { background: #161616; color: #e8e8e8; border: 1px solid #3a3a3a; }
"""


def used_color(used):
    return (0.94, 0.27, 0.27) if used >= 90 else (0.96, 0.62, 0.04) if used >= 70 else (0.13, 0.77, 0.37)


def countdown(moment, compact=False):
    if moment is None:
        return ""
    seconds = int((moment - providers.now()).total_seconds())
    if seconds <= 0:
        return t("초기화됨")
    days, hours, minutes = seconds // 86400, seconds % 86400 // 3600, seconds % 3600 // 60
    if compact or LANGUAGE == "en":
        parts = [f"{days}d", f"{hours}h"] if days else [f"{hours}h", f"{minutes}m"] if hours else [f"{minutes}m"]
    else:
        parts = [f"{days}일", f"{hours}시간"] if days else [f"{hours}시간", f"{minutes}분"] if hours else [f"{minutes}분"]
    return " ".join(parts)


def plan_label(plan):
    # Codex 는 "self_serve_business_prolite" 같은 소문자 식별자를, Claude 는 이미 표시용 이름을 준다.
    return plan.removeprefix("self_serve_").replace("_", " ").title() if plan and plan.islower() else plan


def status_text(report):
    return {"expired": t("로그인 만료"), "limited": t("대기")}.get(report["status"], t("오류"))


def with_backoff(previous, fetched, backoff, now):
    """429 를 받은 계정은 5분부터 두 배씩(최대 30분) 쉬고, 그동안 마지막 정상값을 보여 준다.
    backoff 는 (다시 조회할 시각, 대기 초) 또는 None 이다. (보여 줄 보고, 새 backoff) 를 돌려준다."""
    if fetched["status"] != "limited":
        return fetched, None
    seconds = min(BACKOFF_MAX, backoff[1] * 2) if backoff else BACKOFF_START
    shown = previous if previous and previous["status"] == "ok" else fetched
    return shown, (now + seconds, seconds)


def headline(report):
    return max(report["windows"], key=lambda window: window["used"]) if report.get("windows") else None


def icon(provider, size):
    return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(str(ASSET_DIR / f"{ICONS[provider]}.svg"), size, size))


def label(text, *classes, xalign=0.0, expand=False):
    widget = Gtk.Label(label=text, xalign=xalign)
    widget.set_hexpand(expand)
    widget.set_ellipsize(Pango.EllipsizeMode.END)
    for name in classes:
        widget.get_style_context().add_class(name)
    return widget


class Bar(Gtk.DrawingArea):
    def __init__(self, used, width=-1, height=6, gray=False):
        super().__init__()
        self.used = used
        self.gray = gray
        self.set_size_request(width, height)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(width < 0)
        self.connect("draw", self.draw)

    def draw(self, _widget, context):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        radius = height / 2

        def rounded(length):
            context.new_sub_path()
            context.arc(radius, radius, radius, 1.5708, 4.7124)
            context.arc(max(radius, length - radius), radius, radius, 4.7124, 1.5708)
            context.close_path()

        context.set_source_rgb(0.22, 0.22, 0.22)
        rounded(width)
        context.fill()
        if self.used > 0:
            context.set_source_rgb(*((0.56, 0.56, 0.58) if self.gray else used_color(self.used)))
            rounded(max(height, width * self.used / 100))
            context.fill()


class Tickets(Gtk.DrawingArea):
    """리셋권 개수만큼(최대 3장) 겹친 티켓 그림."""

    WIDTH, HEIGHT = 30, 18

    def __init__(self, count):
        super().__init__()
        self.count = count
        self.set_size_request(self.WIDTH + 2 * 5 + 2, self.HEIGHT + 2 * 3 + 2)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self.draw)

    def ticket(self, context, x, y):
        width, height, notch, radius = self.WIDTH, self.HEIGHT, 3.5, 3
        context.new_path()
        context.move_to(x + radius, y)
        context.line_to(x + width - radius, y)
        context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        context.arc_negative(x + width, y + height / 2, notch, -math.pi / 2, math.pi / 2)
        context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        context.line_to(x + radius, y + height)
        context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        context.arc_negative(x, y + height / 2, notch, math.pi / 2, -math.pi / 2)
        context.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        context.close_path()

    def draw(self, _widget, context):
        shown = max(1, min(3, self.count))
        for index in range(shown):
            # 뒤 티켓일수록 오른쪽 위로 밀리고 어둡다. 맨 앞 티켓이 마지막에 그려진다.
            depth = shown - 1 - index
            x, y = 1 + depth * 5, 1 + (2 - depth) * 3 - (3 - shown) * 3
            self.ticket(context, x, y)
            if self.count == 0:
                context.set_source_rgba(1, 1, 1, 0.15)
            else:
                shade = 1 - depth * 0.22
                context.set_source_rgb(0.98 * shade, 0.74 * shade, 0.18 * shade)
            context.fill_preserve()
            context.set_source_rgba(0, 0, 0, 0.35)
            context.set_line_width(1)
            context.stroke()
            if depth == 0:
                context.set_dash([2, 2])
                context.move_to(x + self.WIDTH * 0.68, y + 3)
                context.line_to(x + self.WIDTH * 0.68, y + self.HEIGHT - 3)
                context.set_source_rgba(0, 0, 0, 0.4 if self.count else 0.2)
                context.stroke()
                context.set_dash([])


def clickable(child, callback, *classes, horizontal=14, vertical=11):
    # EventBox 는 CSS padding 을 그리지 않아서 안쪽 위젯 여백으로 준다.
    child.set_margin_start(horizontal)
    child.set_margin_end(horizontal)
    child.set_margin_top(vertical)
    child.set_margin_bottom(vertical)
    box = Gtk.EventBox()
    box.add(child)
    for name in ("row", *classes):
        box.get_style_context().add_class(name)
    box.connect("button-release-event", lambda *_args: callback())
    return box


def panel_origin(anchor, size, area):
    """패널 왼쪽 위 좌표. anchor 는 동그라미 (x, y, 너비, 높이), 없으면 작업 영역 오른쪽 위다."""
    area_x, area_y, area_width, area_height = area
    width, height = size
    if anchor is None:
        return area_x + area_width - width - 12, area_y + 8
    bubble_x, bubble_y, bubble_width, bubble_height = anchor
    x = bubble_x - width - 8 if bubble_x - width - 8 >= area_x else bubble_x + bubble_width + 8
    y = bubble_y + bubble_height - height if bubble_y + bubble_height / 2 > area_y + area_height / 2 else bubble_y
    return min(max(x, area_x), area_x + area_width - width), max(min(y, area_y + area_height - height - 8), area_y + 8)


class Bubble(Gtk.Window):
    SIZE = 56

    def __init__(self, app):
        super().__init__(type=Gtk.WindowType.TOPLEVEL, title="agent-usage-bubble")
        self.app = app
        self.set_decorated(False)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        # 누를 때 포커스를 가져가면 열린 패널이 focus-out 으로 먼저 닫혀서 다시 열려 버린다.
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_visual(self.get_screen().get_rgba_visual())
        self.set_app_paintable(True)
        self.set_default_size(self.SIZE, self.SIZE)
        self.set_size_request(self.SIZE, self.SIZE)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.pressed = None
        self.connect("draw", self.draw)
        self.connect("button-press-event", self.press)
        self.connect("motion-notify-event", self.motion)
        self.connect("button-release-event", self.release)
        self.connect("configure-event", self.moved)
        self.menu = self.make_menu()
        saved = app.state.get("bubble")
        if not saved:
            area = Gdk.Display.get_default().get_primary_monitor().get_workarea()
            saved = (area.x + area.width - self.SIZE - 24, area.y + area.height - self.SIZE - 24)
        # 끄는 중에는 get_position 이 늦게 갱신돼서 configure-event 좌표를 따로 들고 있는다.
        self.position = tuple(saved)
        self.move(*saved)
        self.show_all()

    def draw(self, _widget, context):
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        center = self.SIZE / 2
        context.arc(center, center, center - 2, 0, 6.2832)
        context.set_source_rgb(0.12, 0.12, 0.12)
        context.fill_preserve()
        context.set_source_rgba(1, 1, 1, 0.18)
        context.set_line_width(1.5)
        context.stroke()
        # 네 갈래 반짝이 모양 AI 아이콘
        for scale, dx, dy in ((11, 0, 0), (4.5, 9, -9)):
            x, y = center + dx, center + dy
            context.move_to(x, y - scale)
            for to_x, to_y, end_x, end_y in ((x, y, x + scale, y), (x, y, x, y + scale), (x, y, x - scale, y), (x, y, x, y - scale)):
                context.curve_to(to_x, to_y, to_x, to_y, end_x, end_y)
            context.close_path()
        context.set_source_rgb(0.95, 0.95, 0.95)
        context.fill()

    def press(self, _widget, event):
        if event.button == 1:
            self.pressed = (event.x_root, event.y_root, event.time)
        elif event.button == 3:
            self.menu.popup_at_pointer(event)

    def motion(self, _widget, event):
        if self.pressed and abs(event.x_root - self.pressed[0]) + abs(event.y_root - self.pressed[1]) > 6:
            self.pressed = None
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), event.time)

    def release(self, _widget, event):
        if self.pressed and event.button == 1:
            self.pressed = None
            self.app.toggle_from_bubble()

    def moved(self, _widget, event):
        # 다른 창이 앞으로 올 때도 configure-event 가 와서, 위치가 실제로 바뀐 경우만 처리한다.
        if (event.x, event.y) == self.position:
            return
        self.position = (event.x, event.y)
        # 펼친 부채꼴과 동그라미에 붙여 연 패널이 함께 따라온다.
        if self.app.fan.opened:
            self.app.fan.follow()
        self.app.follow_anchor()
        position = [event.x, event.y]
        if self.app.state.get("bubble") != position:
            self.app.state["bubble"] = position
            GLib.timeout_add(500, lambda: accounts.save_state(self.app.state) or False)

    def anchor(self):
        x, y = self.position
        return x, y, self.SIZE, self.SIZE

    def center(self):
        x, y = self.position
        return x + self.SIZE / 2, y + self.SIZE / 2

    def make_menu(self):
        menu = Gtk.Menu()
        for text, callback in ((t("전체 보기"), lambda: self.app.show_all_agents()), (t("계정 연결"), lambda: self.app.open_manager()),
                               (t("새로고침"), lambda: self.app.refresh()), (t("종료"), Gtk.main_quit)):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _item, callback=callback: callback())
            menu.append(item)
        menu.show_all()
        return menu


def fan_angles(bubble_center, area, radius=118, item=(32, 62, 22), count=3, spread=55):
    """부채꼴 항목 각도(라디안, 수학 좌표). 위(아래쪽이 좁으면 아래)로 펼치고, 항목이 작업 영역 밖으로
    나가면 화면 가운데 쪽으로 필요한 만큼만 돌린다. item 은 (반너비, 위 여유, 아래 여유)다."""
    x, y = bubble_center
    area_x, area_y, area_width, area_height = area
    half_width, above, below = item
    vertical = math.pi / 2 if y - area_y > radius + above else -math.pi / 2
    toward = math.atan2(y - (area_y + area_height / 2), (area_x + area_width / 2) - x)
    turn = math.atan2(math.sin(toward - vertical), math.cos(toward - vertical))

    def spread_from(base):
        return [base + math.radians((count // 2 - index) * spread) for index in range(count)]

    def fits(angles):
        for angle in angles:
            item_x, item_y = x + radius * math.cos(angle), y - radius * math.sin(angle)
            if item_x - half_width < area_x or item_x + half_width > area_x + area_width:
                return False
            if item_y - above < area_y or item_y + below > area_y + area_height:
                return False
        return True

    for step in range(21):
        angles = spread_from(vertical + turn * step / 20)
        if fits(angles):
            return angles
    return spread_from(toward)


class Fan(Gtk.Window):
    RADIUS = 118
    DISC = 22
    HALF = 210
    PILL = (64, 34)

    def __init__(self, app):
        # POPUP 은 창 관리자가 위치를 화면 안으로 끌어당기지 않아서 구석에서도 중심이 어긋나지 않는다.
        super().__init__(type=Gtk.WindowType.POPUP)
        self.app = app
        self.set_visual(self.get_screen().get_rgba_visual())
        self.set_app_paintable(True)
        self.set_size_request(2 * self.HALF, 2 * self.HALF)
        self.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.progress = 0.0
        self.motion = 0
        self.opened = False
        self.icons = {}
        self.connect("draw", self.draw)
        self.connect("button-release-event", self.release)

    def positions(self, progress=1.0):
        center_x, center_y = self.app.bubble.center()
        area = self.app.workarea_at(center_x, center_y)
        angles = fan_angles((center_x, center_y), (area.x, area.y, area.width, area.height), self.RADIUS,
                            (self.PILL[0] / 2, self.DISC + self.PILL[1] + 6, self.DISC), len(NAMES))
        result = {}
        for index, (provider, angle) in enumerate(zip(NAMES, angles)):
            # 항목마다 조금씩 늦게 나오게 한다.
            local = min(1.0, max(0.0, progress * 1.3 - index * 0.15))
            eased = 1 - (1 - local) ** 3
            result[provider] = (self.HALF + self.RADIUS * eased * math.cos(angle), self.HALF - self.RADIUS * eased * math.sin(angle), eased)
        return result

    def hit_rect(self, x, y):
        width, height = self.PILL
        return int(x - width / 2), int(y - self.DISC - height - 6), width, height + 6 + 2 * self.DISC

    def open(self):
        self.show_all()
        self.follow()
        self.opened = True
        self.animate(True)

    def follow(self):
        center_x, center_y = self.app.bubble.center()
        self.move(int(center_x - self.HALF), int(center_y - self.HALF))
        region = cairo.Region([cairo.RectangleInt(*self.hit_rect(x, y)) for x, y, _ in self.positions().values()])
        self.input_shape_combine_region(region)
        self.queue_draw()

    def close(self):
        if self.opened:
            self.opened = False
            self.animate(False)

    def animate(self, opening):
        self.motion += 1
        motion, started, start = self.motion, GLib.get_monotonic_time(), self.progress

        def step():
            if motion != self.motion:
                return False
            elapsed = (GLib.get_monotonic_time() - started) / (FAN_SECONDS * 1e6)
            self.progress = min(1.0, start + elapsed) if opening else max(0.0, start - elapsed)
            self.queue_draw()
            if 0 < self.progress < 1:
                return True
            if not opening:
                self.hide()
            return False

        GLib.timeout_add(16, step)

    def icon(self, provider, scale):
        if (provider, scale) not in self.icons:
            self.icons[(provider, scale)] = GdkPixbuf.Pixbuf.new_from_file_at_size(str(ASSET_DIR / f"{ICONS[provider]}.svg"), 20 * scale, 20 * scale)
        return self.icons[(provider, scale)]

    def text(self, context, x, y, value, font, rgba):
        layout = PangoCairo.create_layout(context)
        # 투명 창에서 서브픽셀 글자 다듬기를 쓰면 글자 가장자리에 색이 번진다.
        options = cairo.FontOptions()
        options.set_antialias(cairo.ANTIALIAS_GRAY)
        PangoCairo.context_set_font_options(layout.get_context(), options)
        layout.context_changed()
        layout.set_font_description(Pango.FontDescription(font))
        layout.set_text(value, -1)
        width, _ = layout.get_pixel_size()
        context.move_to(x - width / 2, y)
        context.set_source_rgba(*rgba)
        PangoCairo.show_layout(context, layout)

    def draw(self, _widget, context):
        context.set_operator(cairo.OPERATOR_SOURCE)
        context.set_source_rgba(0, 0, 0, 0)
        context.paint()
        context.set_operator(cairo.OPERATOR_OVER)
        scale = self.get_scale_factor()
        for provider, (x, y, shown) in self.positions(self.progress).items():
            if shown <= 0:
                continue
            context.push_group()
            used, reset = self.app.fan_values(provider)
            # 글자를 그린 뒤 남은 현재 점에서 arc 가 선을 이어 그리지 않게 경로를 비운다.
            context.new_path()
            context.arc(x, y, self.DISC, 0, 2 * math.pi)
            context.set_source_rgb(0.12, 0.12, 0.12)
            context.fill_preserve()
            context.set_source_rgba(1, 1, 1, 0.18)
            context.set_line_width(1.2)
            context.stroke()
            context.set_line_width(3)
            context.arc(x, y, self.DISC - 3, 0, 2 * math.pi)
            context.set_source_rgba(1, 1, 1, 0.1)
            context.stroke()
            if used is not None:
                context.arc(x, y, self.DISC - 3, -math.pi / 2, -math.pi / 2 + 2 * math.pi * used / 100)
                context.set_source_rgb(*used_color(used))
                context.stroke()
            context.save()
            context.translate(x - 10, y - 10)
            context.scale(1 / scale, 1 / scale)
            Gdk.cairo_set_source_pixbuf(context, self.icon(provider, scale), 0, 0)
            context.paint()
            context.restore()
            width, height = self.PILL
            left, top = x - width / 2, y - self.DISC - height - 6
            context.new_sub_path()
            for corner_x, corner_y, angle in ((left + width - 8, top + 8, -math.pi / 2), (left + width - 8, top + height - 8, 0),
                                              (left + 8, top + height - 8, math.pi / 2), (left + 8, top + 8, math.pi)):
                context.arc(corner_x, corner_y, 8, angle, angle + math.pi / 2)
            context.close_path()
            context.set_source_rgba(0.08, 0.08, 0.08, 0.85)
            context.fill()
            self.text(context, x, top + 3, f"{round(used)}%" if used is not None else reset, "Sans Bold 9.5", (1, 1, 1, 1))
            if used is not None:
                self.text(context, x, top + 18, reset, "Sans 7.5", (0.7, 0.7, 0.7, 1))
            context.pop_group_to_source()
            context.paint_with_alpha(shown)

    def item_anchor(self, provider):
        # 끄는 중에는 get_position 이 늦어서 동그라미 중심에서 계산한다.
        center_x, center_y = self.app.bubble.center()
        x, y, _ = self.positions()[provider]
        return center_x - self.HALF + x - self.DISC, center_y - self.HALF + y - self.DISC, 2 * self.DISC, 2 * self.DISC

    def release(self, _widget, event):
        for provider, (x, y, _) in self.positions().items():
            left, top, width, height = self.hit_rect(x, y)
            if left <= event.x <= left + width and top <= event.y <= top + height:
                self.app.open_agent(provider)


class App:
    def __init__(self):
        self.state = accounts.load_state()
        self.accounts = []
        self.reports = {}
        self.backoff = {}
        self.ticket_lists = set()
        self.loading = False
        self.sort_by_usage = True
        self.expanded = set()
        self.logins = []
        self.focused = False
        self.error = None
        self.indicators = {provider: self.make_indicator(provider) for provider in NAMES}
        self.window = self.make_window()
        self.anchor = None
        self.anchor_source = None
        self.target = (0, 0)
        self.closing = False
        self.motion = 0
        self.fan = Fan(self)
        self.bubble = Bubble(self)
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self.refresh)
        GLib.timeout_add_seconds(60, self.update_indicators)

    # 데이터

    def key(self, account):
        return account["provider"], account["id"]

    def provider_accounts(self, provider):
        return [account for account in self.accounts if account["provider"] == provider]

    def selected(self, provider):
        items = self.provider_accounts(provider)
        chosen = self.state["selected"].get(provider)
        return next((account for account in items if account["id"] == chosen), items[0] if items else None)

    def refresh(self, *_args):
        if self.loading:
            return True
        self.loading = True
        self.render()
        threading.Thread(target=self.collect, daemon=True).start()
        return True

    def fetch_politely(self, account, now):
        key = self.key(account)
        backoff = self.backoff.get(key)
        previous = self.reports.get(key)
        if backoff and now < backoff[0]:
            return previous or {"status": "limited", "error": t("대기"), "windows": []}
        report, self.backoff[key] = with_backoff(previous, providers.fetch(account), backoff, now)
        return report

    def collect(self):
        try:
            found = accounts.list_accounts(self.state)
            now = time.monotonic()
            with ThreadPoolExecutor(max_workers=6) as pool:
                reports = dict(zip(map(self.key, found), pool.map(lambda account: self.fetch_politely(account, now), found)))
        except Exception as error:
            GLib.idle_add(self.finish, None, None, str(error))
            return
        GLib.idle_add(self.finish, found, reports, None)

    def finish(self, found, reports, error):
        self.loading = False
        if error:
            self.error = error
        else:
            self.error = None
            self.accounts, self.reports = found, reports
        self.render()
        return False

    # 상단바

    def make_indicator(self, provider):
        indicator = AyatanaAppIndicator3.Indicator.new(f"agent-usage-{provider}", ICONS[provider], AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        indicator.set_icon_theme_path(str(ASSET_DIR))
        indicator.set_icon_full(ICONS[provider], NAMES[provider])
        indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        for text, callback in ((t("사용량 열기"), self.show_panel), (t("새로고침"), self.refresh), (t("종료"), Gtk.main_quit)):
            item = Gtk.MenuItem(label=text)
            item.connect("activate", callback)
            menu.append(item)
        menu.show_all()
        indicator.set_menu(menu)
        indicator.set_secondary_activate_target(menu.get_children()[0])
        return indicator

    def indicator_text(self, provider):
        account = self.selected(provider)
        report = self.reports.get(self.key(account)) if account else None
        if report is None:
            return "···"
        if report["status"] != "ok":
            return status_text(report)
        # 상단바는 트레이 아이콘이 많으면 라벨을 잘라서 사용률만 둔다. 남은 시간은 패널에서 보인다.
        return f"{round(headline(report)['used'])}%"

    # 패널

    def make_window(self):
        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL, title=t("사용량"))
        window.set_decorated(False)
        window.set_keep_above(True)
        window.set_skip_taskbar_hint(True)
        window.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        window.set_default_size(440, -1)
        visual = window.get_screen().get_rgba_visual()
        if visual:
            window.set_visual(visual)
            window.set_app_paintable(True)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        window.connect("delete-event", lambda *_args: self.close_panel() or True)
        window.connect("key-press-event", lambda _w, event: event.keyval == Gdk.KEY_Escape and self.close_panel())
        # 포커스를 한 번도 받지 못한 채 숨기면 창이 뜨자마자 사라진다.
        window.connect("focus-in-event", lambda *_args: setattr(self, "focused", True))
        # 동그라미로 연 패널은 다른 곳을 눌러도 열어 둔다. 동그라미나 Esc 로 닫는다.
        window.connect("focus-out-event", lambda *_args: self.focused and not self.logins and self.anchor is None and self.close_panel())
        window.connect("hide", lambda *_args: setattr(self, "focused", False))
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.body.get_style_context().add_class("panel")
        window.add(self.body)
        return window

    def workarea(self):
        return self.workarea_at(*self.anchor[:2]) if self.anchor else Gdk.Display.get_default().get_primary_monitor().get_workarea()

    def workarea_at(self, x, y):
        return Gdk.Display.get_default().get_monitor_at_point(int(x), int(y)).get_workarea()

    def show_panel(self, *_args, source=None):
        """source 는 패널을 붙일 사각형을 돌려주는 함수다. 없으면 상단바 아래(작업 영역 오른쪽 위)에 연다."""
        if self.window.get_visible() and not self.closing:
            if source:
                self.anchor_source, self.anchor = source, source()
            self.render()
            self.window.present()
            return
        self.anchor_source = source
        self.anchor = source() if source else None
        self.window.set_opacity(0)
        self.window.show_all()
        self.render()
        self.window.present()
        self.slide(opening=True)

    def close_panel(self):
        if self.window.get_visible() and not self.closing:
            self.slide(opening=False)

    def toggle_from_bubble(self):
        if self.fan.opened:
            self.fan.close()
            self.close_panel()
        else:
            self.fan.open()

    def show_all_agents(self):
        self.expanded = set(NAMES)
        self.show_panel(source=self.bubble.anchor)

    def open_agent(self, provider):
        if self.window.get_visible() and not self.closing and self.expanded == {provider}:
            self.close_panel()
            return
        self.expanded = {provider}
        self.show_panel(source=lambda: self.fan.item_anchor(provider))

    def follow_anchor(self):
        if self.anchor_source and self.window.get_visible() and not self.closing:
            self.anchor = self.anchor_source()
            self.place()

    def fan_values(self, provider):
        account = self.selected(provider)
        report = self.reports.get(self.key(account)) if account else None
        if report is None:
            return None, "···"
        if report["status"] != "ok":
            return None, status_text(report)
        top = headline(report)
        return top["used"], countdown(top["reset_at"], compact=True)

    def slide(self, opening):
        # 투명도와 위치를 함께 바꿔 동그라미(또는 상단바) 쪽에서 밀려 나오는 것처럼 보이게 한다.
        self.closing = not opening
        self.motion += 1
        motion, started = self.motion, GLib.get_monotonic_time()
        x, y = self.target
        if self.anchor is None:
            offset_x, offset_y = 0, -14
        else:
            offset_x, offset_y = (18 if self.anchor[0] > x else -18), 0

        def step():
            if motion != self.motion:
                return False
            progress = min(1.0, (GLib.get_monotonic_time() - started) / (SLIDE_SECONDS * 1e6))
            eased = 1 - (1 - progress) ** 3
            shown = eased if opening else 1 - eased
            self.window.set_opacity(shown)
            self.window.move(round(x + offset_x * (1 - shown)), round(y + offset_y * (1 - shown)))
            if progress < 1:
                return True
            if not opening:
                self.window.hide()
                self.window.set_opacity(1)
                self.closing = False
            return False

        step()
        GLib.timeout_add(16, step)

    def place(self):
        area = self.workarea()
        size = (self.window.get_size()[0], self.body.get_preferred_height()[1])
        self.target = panel_origin(self.anchor, size, (area.x, area.y, area.width, area.height))
        if not self.closing:
            self.window.move(*self.target)

    def update_indicators(self):
        self.fan.queue_draw()
        for provider in NAMES:
            self.indicators[provider].set_label(self.indicator_text(provider), "")
        return True

    def render(self, *_args):
        # GLib.idle_add 로도 불린다. True 를 돌려주면 끝없이 다시 그려 클릭이 먹지 않는다.
        self.update_indicators()
        if not self.window.get_visible():
            return False
        for child in self.body.get_children():
            self.body.remove(child)
        header = self.header()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if self.error:
            message = label(self.error, "warning", "small")
            message.set_margin_start(14)
            content.pack_start(message, False, False, 4)
        for session in self.logins:
            content.pack_start(self.login_block(session), False, False, 0)
        for provider in self.ordered_providers():
            content.pack_start(self.provider_section(provider), False, False, 0)
        footer = Gtk.Box(margin_bottom=8)
        # 작업 영역보다 긴 창은 GNOME 이 다른 모니터로 밀어내서, 넘치는 목록은 스크롤로 넣는다.
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        scroller.add(content)
        self.body.pack_start(header, False, False, 0)
        self.body.pack_start(scroller, True, True, 0)
        self.body.pack_start(footer, False, False, 0)
        self.body.show_all()
        # 창에 붙은 뒤에 재야 CSS 글꼴·여백이 반영된 높이가 나온다.
        fixed = sum(part.get_preferred_height()[1] for part in (header, footer))
        limit = max(200, self.workarea().height - 16 - fixed - 2)
        # 창은 최소 높이로 줄어들어서, 내용 높이(화면 한도까지)를 최소값으로 준다.
        scroller.set_min_content_height(min(content.get_preferred_height()[1], limit))
        scroller.set_max_content_height(limit)
        self.window.resize(440, 1)
        self.place()
        return False

    def ordered_providers(self):
        providers_list = list(NAMES)
        if not self.sort_by_usage:
            return sorted(providers_list, key=lambda provider: NAMES[provider])

        def used(provider):
            account = self.selected(provider)
            report = self.reports.get(self.key(account)) if account else None
            top = headline(report) if report and report["status"] == "ok" else None
            return top["used"] if top else -1

        return sorted(providers_list, key=used, reverse=True)

    def separator(self):
        line = Gtk.Box()
        line.get_style_context().add_class("separator")
        return line

    def icon_button(self, name, tooltip, callback):
        button = Gtk.Button.new_from_icon_name(name, Gtk.IconSize.BUTTON)
        button.get_style_context().add_class("flat")
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_args: callback())
        return button

    def header(self):
        top = Gtk.Box(spacing=4, margin=14)
        top.pack_start(label(t("사용량"), "title"), False, False, 0)
        top.pack_start(label("· " + t("모든 에이전트"), "muted"), False, False, 0)
        refresh = self.icon_button("view-refresh-symbolic", t("새로고침"), self.refresh)
        refresh.set_sensitive(not self.loading)
        top.pack_start(refresh, False, False, 0)
        top.pack_start(self.icon_button("emblem-system-symbolic", t("계정 관리"), self.open_manager), False, False, 0)
        sort = Gtk.Button(label=(t("사용량") if self.sort_by_usage else t("이름")) + "  ⇅")
        sort.get_style_context().add_class("flat")
        sort.connect("clicked", lambda *_args: self.toggle("sort_by_usage"))
        top.pack_end(sort, False, False, 0)
        all_open = self.expanded >= set(NAMES)
        top.pack_end(self.icon_button("pan-up-symbolic" if all_open else "pan-down-symbolic", t("모두 접기") if all_open else t("모두 펼치기"),
                                      lambda: self.set_detailed(not all_open)), False, False, 0)
        return top

    def set_detailed(self, detailed):
        self.expanded = set(NAMES) if detailed else set()
        GLib.idle_add(self.render)

    def toggle(self, name):
        setattr(self, name, not getattr(self, name))
        GLib.idle_add(self.render)

    def provider_section(self, provider):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        account = self.selected(provider)
        report = self.reports.get(self.key(account)) if account else None
        expanded = provider in self.expanded
        row = Gtk.Box(spacing=10)
        row.pack_start(icon(provider, 22), False, False, 0)
        name = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        name.pack_start(label(NAMES[provider]), False, False, 0)
        if report and report.get("plan"):
            name.pack_start(label(plan_label(report["plan"]), "muted", "tiny"), False, False, 0)
        row.pack_start(name, True, True, 0)
        if report is None:
            row.pack_start(label("···", "muted"), False, False, 0)
        elif report["status"] != "ok":
            row.pack_start(label(status_text(report), "muted"), False, False, 0)
        else:
            top = headline(report)
            row.pack_start(label(countdown(top["reset_at"]), "muted", "small", xalign=1.0), False, False, 0)
            row.pack_start(Bar(top["used"], width=46, height=5, gray=True), False, False, 0)
            percent = label(f"{round(top['used'])}%", "percent", xalign=1.0)
            percent.set_width_chars(5)
            row.pack_start(percent, False, False, 0)
        row.pack_end(Gtk.Image.new_from_icon_name("pan-down-symbolic" if expanded else "pan-end-symbolic", Gtk.IconSize.MENU), False, False, 0)
        section.pack_start(clickable(row, lambda: self.toggle_provider(provider), *(["selected"] if expanded else [])), False, False, 0)
        section.set_margin_start(6)
        section.set_margin_end(6)
        if expanded and account:
            section.pack_start(self.detail(provider, account, report), False, False, 0)
        return section

    def toggle_provider(self, provider):
        self.expanded ^= {provider}
        GLib.idle_add(self.render)

    def detail(self, provider, account, report):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=14, margin_end=14, margin_top=6, margin_bottom=8)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card")
        card.pack_start(label(account["label"], "title"), False, False, 0)
        if report is None:
            card.pack_start(label(t("불러오는 중…"), "muted"), False, False, 0)
        elif report["status"] != "ok":
            card.pack_start(label(report["error"], "warning"), False, False, 0)
            if account["source"] != "orca":
                again = Gtk.Button(label=t("다시 로그인"))
                again.get_style_context().add_class("pill")
                again.set_halign(Gtk.Align.START)
                again.connect("clicked", lambda *_args: self.login(lambda: accounts.relogin(account)))
                card.pack_start(again, False, False, 0)
        else:
            for window in [*report["windows"], *([report["image"]] if report.get("image") else [])]:
                card.pack_start(self.window_meter(window), False, False, 0)
            if report.get("image_error"):
                card.pack_start(label(t("이미지 한도: {v0}", v0=report["image_error"]), "muted", "small"), False, False, 0)
            if provider == "codex":
                card.pack_start(self.reset_credits(account, report["reset_credits"]), False, False, 0)
        box.pack_start(card, False, False, 0)
        box.pack_start(self.account_list(provider, account), False, False, 0)
        return box

    def window_meter(self, window):
        meter = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        line = Gtk.Box(spacing=6)
        reset = countdown(window["reset_at"])
        line.pack_start(label(window["label"], "percent"), False, False, 0)
        if reset:
            line.pack_start(label("· " + (reset if reset == t("초기화됨") else t("{v0} 후 초기화", v0=reset)), "muted", "small"), False, False, 0)
        line.pack_end(label(f"{round(window['used'])}%", "percent"), False, False, 0)
        meter.pack_start(line, False, False, 0)
        meter.pack_start(Bar(window["used"]), False, False, 0)
        return meter

    def reset_credits(self, account, credits):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row = Gtk.Box(spacing=8)
        tickets = Gtk.Box(spacing=6)
        tickets.set_tooltip_text(t("속도 제한 재설정 {v0}회 사용 가능", v0=credits["count"]))
        tickets.pack_start(Tickets(credits["count"]), False, False, 0)
        tickets.pack_start(label(f"×{credits['count']}", "title" if credits["count"] else "muted"), False, False, 0)
        opened = self.key(account) in self.ticket_lists
        if credits["expires"]:
            tickets.pack_start(Gtk.Image.new_from_icon_name("pan-up-symbolic" if opened else "pan-down-symbolic", Gtk.IconSize.MENU), False, False, 0)
            text = clickable(tickets, lambda: self.toggle_tickets(account), horizontal=4, vertical=2)
            text.set_halign(Gtk.Align.START)
        else:
            text = tickets
        row.pack_start(text, True, True, 0)
        if credits["count"]:
            button = Gtk.Button(label=t("지금 재설정"))
            button.get_style_context().add_class("pill")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", lambda *_args: self.consume(account))
            row.pack_end(button, False, False, 0)
        box.pack_start(row, False, False, 0)
        if opened:
            for index, expiry in enumerate(credits["expires"], 1):
                line = Gtk.Box(spacing=8, margin_start=6)
                line.pack_start(label(f"{index}", "muted", "tiny"), False, False, 0)
                line.pack_start(label(expiry.astimezone().strftime("%m-%d %H:%M"), "small"), False, False, 0)
                line.pack_end(label(t("{v0} 후 만료됨", v0=countdown(expiry, compact=True)), "muted", "tiny"), False, False, 0)
                box.pack_start(line, False, False, 0)
        return box

    def toggle_tickets(self, account):
        self.ticket_lists ^= {self.key(account)}
        GLib.idle_add(self.render)

    def consume(self, account):
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True, message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
                                   text=t("리셋권 1회를 사용해 Codex 사용량을 초기화할까요?"))
        dialog.format_secondary_text(t("{v0} · 되돌릴 수 없습니다.", v0=account["label"]))
        dialog.add_button(t("취소"), Gtk.ResponseType.CANCEL)
        dialog.add_button(t("리셋권 사용"), Gtk.ResponseType.ACCEPT).get_style_context().add_class("destructive-action")
        # 엔터·스페이스로 바로 통과되지 않게 기본 선택은 취소다.
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).grab_focus()
        answer = dialog.run()
        dialog.destroy()
        if answer != Gtk.ResponseType.ACCEPT:
            return

        def work():
            try:
                code = providers.consume_reset_credit(account)
            except Exception as error:
                code = str(error)
            GLib.idle_add(self.notify, t("재설정 결과: {v0}", v0=code))
            GLib.idle_add(lambda: self.refresh() and False)

        threading.Thread(target=work, daemon=True).start()

    def notify(self, text):
        self.error = text
        self.render()
        return False

    def account_list(self, provider, chosen):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head = Gtk.Box(margin_start=4, margin_end=4)
        head.pack_start(label(t("계정"), "muted", "small"), True, True, 0)
        head.pack_end(label(t("사용량"), "muted", "small"), False, False, 0)
        box.pack_start(head, False, False, 0)
        for account in self.provider_accounts(provider):
            report = self.reports.get(self.key(account))
            row = Gtk.Box(spacing=10)
            mark = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
            mark.set_opacity(1 if account is chosen else 0)
            row.pack_start(mark, False, False, 0)
            row.pack_start(label(account["label"], expand=True), True, True, 0)
            if report and report["status"] == "ok":
                top = headline(report)
                row.pack_start(Bar(top["used"], width=48, height=5), False, False, 0)
                row.pack_start(label(f"{round(top['used'])}%", xalign=1.0), False, False, 0)
            elif report:
                row.pack_start(label(status_text(report), "muted", "small"), False, False, 0)
            box.pack_start(clickable(row, lambda account=account: self.select(provider, account), *(["selected"] if account is chosen else []), horizontal=8, vertical=7), False, False, 0)
        return box

    def select(self, provider, account):
        self.state["selected"][provider] = account["id"]
        accounts.save_state(self.state)
        GLib.idle_add(self.render)

    # 계정 관리

    def login(self, start):
        try:
            session = start()
        except Exception as error:
            self.notify(str(error))
            return
        self.logins.append(session)
        threading.Thread(target=self.watch_login, args=(session,), daemon=True).start()
        self.show_panel()

    def watch_login(self, session):
        session.read(lambda: GLib.idle_add(self.render))  # read 는 로그인 주소를 처음 찾았을 때만 부른다
        GLib.idle_add(self.login_finished, session)

    def login_finished(self, session):
        self.logins.remove(session)
        done, last = session.result()
        self.error = None if done else t("{v0} 로그인 실패: {v1}", v0=NAMES[session.provider], v1=last)
        self.refresh()
        return False

    def login_block(self, session):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=14, margin_end=14, margin_bottom=8)
        box.get_style_context().add_class("card")
        head = Gtk.Box(spacing=8)
        head.pack_start(icon(session.provider, 18), False, False, 0)
        head.pack_start(label(t("{v0} 로그인 중 · {v1}", v0=NAMES[session.provider], v1=session.label), "percent", expand=True), True, True, 0)
        box.pack_start(head, False, False, 0)
        code_row = Gtk.Box(spacing=6)
        code = Gtk.Entry(placeholder_text=t("인증 코드"))
        code_row.pack_start(code, True, True, 0)
        send = Gtk.Button(label=t("보내기"))
        send.get_style_context().add_class("pill")
        send.connect("clicked", lambda *_args: code.get_text().strip() and session.send_code(code.get_text().strip()))
        code.connect("activate", lambda *_args: send.clicked())
        code_row.pack_start(send, False, False, 0)
        box.pack_start(code_row, False, False, 0)
        actions = Gtk.Box(spacing=6)
        if session.url:
            again = Gtk.Button(label=t("로그인 페이지 다시 열기"))
            again.get_style_context().add_class("pill")
            again.connect("clicked", lambda *_args: Gtk.show_uri_on_window(self.window, session.url, Gdk.CURRENT_TIME))
            actions.pack_start(again, False, False, 0)
        cancel = Gtk.Button(label=t("취소"))
        cancel.get_style_context().add_class("pill")
        cancel.connect("clicked", lambda *_args: session.cancel())
        actions.pack_end(cancel, False, False, 0)
        box.pack_start(actions, False, False, 0)
        return box

    def open_manager(self):
        self.close_panel()
        manager = Gtk.Window(title=t("계정 관리"))
        manager.set_default_size(480, -1)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        for provider in NAMES:
            head = Gtk.Box(spacing=8)
            head.pack_start(icon(provider, 18), False, False, 0)
            head.pack_start(label(NAMES[provider], "title"), True, True, 0)
            outer.pack_start(head, False, False, 0)
            for account in self.provider_accounts(provider):
                outer.pack_start(self.manager_row(manager, account), False, False, 0)
            add = Gtk.Box(spacing=8)
            name = Gtk.Entry(placeholder_text=t("새 계정 이름(선택)"))
            add.pack_start(name, True, True, 0)
            button = Gtk.Button(label=t("계정 추가"))
            button.get_style_context().add_class("pill")
            button.connect("clicked", lambda _button, provider=provider, name=name: self.add_account(manager, provider, name.get_text().strip()))
            add.pack_start(button, False, False, 0)
            outer.pack_start(add, False, False, 0)
            outer.pack_start(self.separator(), False, False, 0)
        frame = Gtk.Box()
        frame.get_style_context().add_class("manager")
        frame.pack_start(outer, True, True, 0)
        manager.add(frame)
        manager.show_all()

    def manager_row(self, manager, account):
        row = Gtk.Box(spacing=8)
        if account["source"] == "own":
            name = Gtk.Entry(text=account["label"])
            row.pack_start(name, True, True, 0)
            save = Gtk.Button(label=t("이름 저장"))
            save.get_style_context().add_class("pill")
            save.connect("clicked", lambda *_args: (accounts.rename_account(self.state, account["id"], name.get_text().strip()), self.refresh()))
            row.pack_start(save, False, False, 0)
        else:
            source = t("시스템") if account["source"] == "system" else "Orca"
            row.pack_start(label(f"{account['label']}  ·  {source}", expand=True), True, True, 0)
        if account["source"] != "orca":
            again = Gtk.Button(label=t("다시 로그인"))
            again.get_style_context().add_class("pill")
            again.connect("clicked", lambda *_args: self.login(lambda: accounts.relogin(account)))
            row.pack_start(again, False, False, 0)
        if account["source"] == "own":
            remove = Gtk.Button(label=t("삭제"))
            remove.get_style_context().add_class("pill")
            remove.connect("clicked", lambda *_args: self.remove_account(manager, account))
            row.pack_start(remove, False, False, 0)
        return row

    def add_account(self, manager, provider, name):
        manager.destroy()
        self.login(lambda: accounts.add_account(self.state, provider, name))

    def remove_account(self, manager, account):
        dialog = Gtk.MessageDialog(transient_for=manager, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=t("이 계정과 로그인 정보를 지울까요?"))
        dialog.format_secondary_text(account["label"])
        answer = dialog.run()
        dialog.destroy()
        if answer == Gtk.ResponseType.OK:
            accounts.remove_account(self.state, account["id"])
            manager.destroy()
            self.refresh()


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = App()
    if "--open" in __import__("sys").argv:
        app.show_panel()
    Gtk.main()
