#!/usr/bin/env python3
"""Detect the supplied retry banner and click its retry button every 10 seconds."""

from __future__ import annotations

import ctypes
import time
from datetime import datetime
from ctypes import wintypes
from pathlib import Path

import cv2
import mss
import numpy as np
from PIL import Image
try:
    import uiautomation as automation
except ImportError:
    automation = None


INTERVAL_SECONDS = 10.0
LEFT_MATCH_THRESHOLD = 0.95
BUTTON_MATCH_THRESHOLD = 0.80
CLICK_OFFSET_X = 711
CLICK_OFFSET_Y = 30
LEFT_MATCH_WIDTH = 630
BUTTON_REGION = (630, 8, 754, 53)
UIA_RETRY_NAMES = {"重试", "重试按钮", "retry", "retry button"}
TIMED_TEMPLATE_PATH = Path(__file__).with_name("retry_template_timed.png")
TIMED_LEFT_WIDTH = 620
TIMED_BUTTON_REGION = (630, 10, 745, 65)
TIMED_BUTTON_MIN_BLUE_PIXELS = 100
TEMPLATE_PATH = Path(__file__).with_name("retry_template.png")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\CodexAutoRetryClicker"
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
MONITOR_DEFAULTTONULL = 0
BI_RGB = 0
BI_BITFIELDS = 3


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def _window_process_name(hwnd: int) -> str:
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
    if not process:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return Path(buffer.value).name.casefold()
        return ""
    finally:
        kernel32.CloseHandle(process)


def find_chatgpt_window() -> tuple[int, dict[str, int]] | None:
    """Find a visible ChatGPT window, including a minimized one."""
    matches: list[tuple[int, int, str, int, int, int]] = []
    foreground = user32.GetForegroundWindow()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def enum_callback(hwnd: int, _: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, len(title))
        title_text = title.value.casefold()
        process_name = _window_process_name(hwnd)
        if "chatgpt" in title_text or process_name.startswith("chatgpt"):
            window_rect = wintypes.RECT()
            area = 0
            if user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
                area = max(0, window_rect.right - window_rect.left) * max(
                    0, window_rect.bottom - window_rect.top
                )
            matches.append(
                (
                    hwnd,
                    user32.GetWindowThreadProcessId(hwnd, None),
                    title.value,
                    int(process_name.startswith("chatgpt")),
                    int(hwnd == foreground),
                    area,
                )
            )
        return True

    user32.EnumWindows(enum_callback, 0)
    if not matches:
        return None

    # Prefer the ChatGPT desktop process, then the active matching window,
    # then the largest remaining window. This avoids selecting a stale
    # background browser window when several ChatGPT-like windows exist.
    hwnd = max(matches, key=lambda item: (item[3], item[4], item[5]))[0]
    if user32.IsIconic(hwnd):
        return hwnd, {"left": 0, "top": 0, "width": 0, "height": 0}

    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    top_left = wintypes.POINT(rect.left, rect.top)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return hwnd, {
        "left": top_left.x,
        "top": top_left.y,
        "width": width,
        "height": height,
    }


def make_dpi_aware() -> None:
    """Keep screenshot pixels and Win32 screen coordinates in the same scale."""
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


class StatusLog:
    """Collapse consecutive identical scan messages while retaining last time."""

    def __init__(self) -> None:
        self.message: str | None = None
        self.first_time: str | None = None
        self.last_time: str | None = None
        self.count = 0
        self.ellipsis_shown = False

    def write(self, message: str, timestamp: str) -> None:
        if message != self.message:
            self.flush()
            self.message = message
            self.first_time = timestamp
            self.last_time = timestamp
            self.count = 1
            self.ellipsis_shown = False
            print(f"[{timestamp}] {message}", flush=True)
            return

        self.last_time = timestamp
        self.count += 1
        if not self.ellipsis_shown:
            print("    ...", flush=True)
            self.ellipsis_shown = True

    def flush(self) -> None:
        if self.message is not None and self.count > 1:
            print(f"    （以上状态最后一次：{self.last_time}）", flush=True)
        self.message = None
        self.first_time = None
        self.last_time = None
        self.count = 0
        self.ellipsis_shown = False


def show(message: str) -> None:
    """Write one immediately visible console line."""
    print(message, flush=True)


def acquire_single_instance() -> int | None:
    """Keep one process running globally on this Windows machine."""
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise OSError("无法创建单实例锁")
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def post_background_click(hwnd: int, x: int, y: int) -> bool:
    """Send a click to ChatGPT's window without using the foreground window."""
    lparam = (y << 16) | (x & 0xFFFF)
    moved = user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    pressed = user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    released = user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    return bool(moved and pressed and released)


def restore_foreground_window(hwnd: int) -> None:
    """Return focus to the window the user was working in before the click."""
    if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return
    user32.SetForegroundWindow(hwnd)


def is_fully_covered(hwnd: int, foreground: int) -> bool:
    """Return whether the foreground window covers ChatGPT's whole client area."""
    if not foreground or foreground == hwnd:
        return False
    if not user32.IsZoomed(foreground):
        return False
    client_rect = wintypes.RECT()
    foreground_rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
        return False
    top_left = wintypes.POINT(client_rect.left, client_rect.top)
    bottom_right = wintypes.POINT(client_rect.right, client_rect.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        return False
    if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        return False
    if not user32.GetWindowRect(foreground, ctypes.byref(foreground_rect)):
        return False
    chatgpt_center = wintypes.POINT(
        (top_left.x + bottom_right.x) // 2,
        (top_left.y + bottom_right.y) // 2,
    )
    foreground_center = wintypes.POINT(
        (foreground_rect.left + foreground_rect.right) // 2,
        (foreground_rect.top + foreground_rect.bottom) // 2,
    )
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    chatgpt_monitor = user32.MonitorFromPoint(chatgpt_center, MONITOR_DEFAULTTONULL)
    foreground_monitor = user32.MonitorFromPoint(foreground_center, MONITOR_DEFAULTTONULL)
    if not chatgpt_monitor or chatgpt_monitor != foreground_monitor:
        return False
    return (
        foreground_rect.left <= top_left.x
        and foreground_rect.top <= top_left.y
        and foreground_rect.right >= bottom_right.x
        and foreground_rect.bottom >= bottom_right.y
    )


def move_click_restore(x: int, y: int) -> None:
    """Fallback for applications that ignore background mouse messages."""
    cursor = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(cursor)):
        raise OSError("GetCursorPos failed")
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    user32.SetCursorPos(cursor.x, cursor.y)


def capture_window_content(hwnd: int, client: dict[str, int]) -> np.ndarray | None:
    """Capture a window's own client content, including when it is covered."""
    width, height = client["width"], client["height"]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32 = ctypes.windll.gdi32
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    user32.PrintWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    screen_dc = user32.GetDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not screen_dc or not memory_dc or not bitmap:
        if memory_dc:
            ctypes.windll.gdi32.DeleteDC(memory_dc)
        if screen_dc:
            user32.ReleaseDC(hwnd, screen_dc)
        return None

    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        rendered = user32.PrintWindow(
            hwnd,
            memory_dc,
            PW_CLIENTONLY | PW_RENDERFULLCONTENT,
        )
        if not rendered:
            return None

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        pixels = np.empty((height, width, 4), dtype=np.uint8)
        copied = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            pixels.ctypes.data,
            ctypes.byref(info),
            0,
        )
        if copied != height:
            return None
        return pixels[:, :, :3].copy()
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, screen_dc)


def find_retry_control(hwnd: int) -> object | None:
    """Find a real ChatGPT retry button, even when its window is covered."""
    if automation is None:
        return None
    try:
        root = automation.ControlFromHandle(hwnd)
    except Exception:
        # UIA can lose the Chromium provider between scans.  Treat that as a
        # transient miss instead of terminating the whole polling process.
        return None
    stack = [root]
    while stack:
        control = stack.pop()
        try:
            # Both properties perform a COM round-trip.  Either can fail when
            # a renderer destroys the element while we are inspecting it.
            control_type = control.ControlTypeName
            name = control.Name or ""
            normalized_name = name.strip().casefold()
            # Do not use a substring check here: a link named
            # ``retry_clicker.py`` was previously mistaken for the button.
            is_retry_label = normalized_name in UIA_RETRY_NAMES
            # Chromium may keep detached/stale retry nodes in the UIA tree.
            # Ignore controls that are hidden, disabled, or have no screen
            # rectangle; they are not actionable buttons on the page.
            is_visible_and_actionable = True
            try:
                is_visible_and_actionable = bool(control.IsEnabled) and not bool(
                    control.IsOffscreen
                )
                rectangle = control.BoundingRectangle
                is_visible_and_actionable = is_visible_and_actionable and (
                    rectangle.right > rectangle.left
                    and rectangle.bottom > rectangle.top
                )
            except Exception:
                is_visible_and_actionable = False
            if (
                control_type == "ButtonControl"
                and is_retry_label
                and is_visible_and_actionable
            ):
                return control
            stack.extend(control.GetChildren())
        except Exception:
            # A single stale element must not abort traversal of the rest of
            # the tree.  The next polling cycle will obtain fresh elements.
            continue
    return None


def invoke_retry_control(control: object) -> str | None:
    """Invoke a UIA retry control, returning its label when successful."""
    try:
        name = control.Name or "重试"
        control.GetInvokePattern().Invoke()
        return name
    except Exception:
        return None


def activate_and_invoke_retry(hwnd: int) -> str | None:
    """Temporarily activate ChatGPT so Chromium exposes its button to UIA."""
    previous_foreground = user32.GetForegroundWindow()
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    try:
        control = find_retry_control(hwnd)
        if control is None:
            return None
        return invoke_retry_control(control)
    finally:
        restore_foreground_window(previous_foreground)


def load_template() -> np.ndarray:
    if not TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")
    with Image.open(TEMPLATE_PATH) as image:
        rgb = np.asarray(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"Template not found: {path}")
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def find_banner(
    screen: np.ndarray,
    template: np.ndarray,
    timed_template: np.ndarray | None = None,
) -> tuple[int, int, int, int] | None:
    # Match the stable left message/icon area first, then independently verify
    # the complete button region.  Both checks must agree on the same origin.
    left_template = template[:, :LEFT_MATCH_WIDTH]
    if screen.shape[0] >= left_template.shape[0] and screen.shape[1] >= left_template.shape[1]:
        left_result = cv2.matchTemplate(screen, left_template, cv2.TM_CCOEFF_NORMED)
        _, left_score, _, location = cv2.minMaxLoc(left_result)
        if left_score >= LEFT_MATCH_THRESHOLD:
            x, y = location
            left, top, right, bottom = BUTTON_REGION
            if y + bottom <= screen.shape[0] and x + right <= screen.shape[1]:
                button_area = screen[y + top:y + bottom, x + left:x + right]
                button_template = template[top:bottom, left:right]
                button_score = cv2.matchTemplate(
                    button_area, button_template, cv2.TM_CCOEFF_NORMED
                )[0, 0]
                if button_score >= BUTTON_MATCH_THRESHOLD:
                    return x, y, CLICK_OFFSET_X, CLICK_OFFSET_Y

    if timed_template is None:
        return None
    timed_left = timed_template[:, :TIMED_LEFT_WIDTH]
    if screen.shape[0] < timed_left.shape[0] or screen.shape[1] < timed_left.shape[1]:
        return None
    timed_result = cv2.matchTemplate(screen, timed_left, cv2.TM_CCOEFF_NORMED)
    _, timed_score, _, timed_location = cv2.minMaxLoc(timed_result)
    if timed_score < LEFT_MATCH_THRESHOLD:
        return None

    timed_x, timed_y = timed_location
    left, top, right, bottom = TIMED_BUTTON_REGION
    if timed_y + bottom > screen.shape[0] or timed_x + right > screen.shape[1]:
        return None
    button_area = screen[timed_y + top:timed_y + bottom, timed_x + left:timed_x + right]
    blue_pixels = (
        (button_area[:, :, 0] > button_area[:, :, 2] + 10)
        & (button_area[:, :, 0] > button_area[:, :, 1] + 5)
    ).sum()
    if blue_pixels < TIMED_BUTTON_MIN_BLUE_PIXELS:
        return None
    return timed_x, timed_y, 688, 37


def main() -> None:
    make_dpi_aware()
    template = load_template()
    timed_template = load_image(TIMED_TEMPLATE_PATH) if TIMED_TEMPLATE_PATH.is_file() else None
    show("╔══════════════════════════════════════════╗")
    show("║        ChatGPT 重试按钮自动点击器        ║")
    show("╚══════════════════════════════════════════╝")
    show(
        f"检测间隔：{INTERVAL_SECONDS:.0f} 秒   |   左侧阈值：{LEFT_MATCH_THRESHOLD:.0%}   "
        f"|   按钮阈值：{BUTTON_MATCH_THRESHOLD:.0%}"
    )
    show("点击方式：优先后台点击，不占用鼠标")
    show("运行中……按 Ctrl+C 停止\n")

    status_log = StatusLog()
    # mss 10.x exposes the screenshotter as the lowercase ``mss``
    # constructor (the old ``MSS`` name is no longer exported).
    with mss.mss() as capture:
        try:
            scan_number = 0
            while True:
                started = time.monotonic()
                scan_number += 1
                now = datetime.now().strftime("%H:%M:%S")
                target = find_chatgpt_window()
                if target is None:
                    status_log.write("未发现 ChatGPT 窗口，跳过", now)
                    time.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - started)))
                    continue

                hwnd, client = target
                if client["width"] <= 0 or client["height"] <= 0:
                    status_log.write("ChatGPT 已最小化，暂停识别，等待窗口恢复", now)
                    time.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - started)))
                    continue

                retry_control = find_retry_control(hwnd)
                if retry_control is not None:
                    previous_foreground = user32.GetForegroundWindow()
                    retry_name = invoke_retry_control(retry_control)
                    restore_foreground_window(previous_foreground)
                    if retry_name is not None:
                        status_log.write(
                            f"发现重试按钮“{retry_name}”，已直接调用 ✓（窗口被遮挡也可用）",
                            now,
                        )
                        time.sleep(0.4)
                        time.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - started)))
                        continue
                    # The UIA node was stale or detached. Continue with the
                    # visual detector instead of reporting a false button.

                foreground = user32.GetForegroundWindow()
                if is_fully_covered(hwnd, foreground):
                    try:
                        retry_name = activate_and_invoke_retry(hwnd)
                    except Exception:
                        # Window activation/UIA providers can disappear while
                        # Chromium is navigating; resume normal polling next
                        # cycle rather than terminating the process.
                        retry_name = None
                    if retry_name is not None:
                        status_log.write(
                            f"发现重试按钮“{retry_name}”，已临时激活点击并恢复原窗口 ✓",
                            now,
                        )
                    else:
                        status_log.write("ChatGPT 被全屏窗口遮挡且未找到按钮，暂停截图识别", now)
                    time.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - started)))
                    continue

                frame = capture_window_content(hwnd, client)
                capture_mode = "窗口内容"
                if frame is None:
                    frame = np.asarray(capture.grab(client))[:, :, :3]
                    capture_mode = "屏幕区域（兜底）"
                match = find_banner(frame, template, timed_template)
                if match is not None:
                    x = client["left"] + match[0] + match[2]
                    y = client["top"] + match[1] + match[3]
                    click_x = match[0] + match[2]
                    click_y = match[1] + match[3]
                    previous_foreground = user32.GetForegroundWindow()
                    if post_background_click(hwnd, click_x, click_y):
                        restore_foreground_window(previous_foreground)
                        status_log.write(f"发现重试按钮，已后台点击 ✓（{capture_mode}）", now)
                    else:
                        move_click_restore(x, y)
                        restore_foreground_window(previous_foreground)
                        status_log.write(
                            f"发现重试按钮，已移动鼠标点击并恢复 ✓（{capture_mode}）",
                            now,
                        )
                    time.sleep(0.4)
                else:
                    status_log.write("未发现完整重试提示，跳过", now)

                time.sleep(max(0.0, INTERVAL_SECONDS - (time.monotonic() - started)))
        finally:
            status_log.flush()


if __name__ == "__main__":
    instance_handle = None
    try:
        instance_handle = acquire_single_instance()
        if instance_handle is None:
            show("已有一个自动重试工具正在运行，本次启动已退出。")
            raise SystemExit(0)
        main()
    except KeyboardInterrupt:
        show("\n已停止。")
    except Exception as error:
        show(f"\n程序异常：{error}")
        raise
    finally:
        if instance_handle:
            kernel32.CloseHandle(instance_handle)
