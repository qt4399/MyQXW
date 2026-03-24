#!/usr/bin/env python3
import argparse
import json
import shlex
import sys
import threading
import time
from dataclasses import dataclass
from typing import BinaryIO, Optional, Tuple

import cv2
import paramiko
from pynput import keyboard as pynput_keyboard
from Xlib import X, Xatom
from Xlib.display import Display as XDisplay

DEFAULT_DISPLAY_WIDTH = 1920
DEFAULT_DISPLAY_HEIGHT = 1080

MODIFIER_KEYS = {
    pynput_keyboard.Key.shift: "shift",
    pynput_keyboard.Key.shift_l: "shift",
    pynput_keyboard.Key.shift_r: "shift",
    pynput_keyboard.Key.ctrl: "ctrl",
    pynput_keyboard.Key.ctrl_l: "ctrl",
    pynput_keyboard.Key.ctrl_r: "ctrl",
    pynput_keyboard.Key.alt: "alt",
    pynput_keyboard.Key.alt_l: "alt",
    pynput_keyboard.Key.alt_r: "alt",
    pynput_keyboard.Key.cmd: "win",
    pynput_keyboard.Key.cmd_l: "win",
    pynput_keyboard.Key.cmd_r: "win",
}

SPECIAL_KEYS = {
    pynput_keyboard.Key.backspace: "backspace",
    pynput_keyboard.Key.tab: "tab",
    pynput_keyboard.Key.enter: "enter",
    pynput_keyboard.Key.esc: "esc",
    pynput_keyboard.Key.space: "space",
    pynput_keyboard.Key.delete: "delete",
    pynput_keyboard.Key.home: "home",
    pynput_keyboard.Key.end: "end",
    pynput_keyboard.Key.page_up: "pageup",
    pynput_keyboard.Key.page_down: "pagedown",
    pynput_keyboard.Key.up: "up",
    pynput_keyboard.Key.down: "down",
    pynput_keyboard.Key.left: "left",
    pynput_keyboard.Key.right: "right",
    pynput_keyboard.Key.insert: "insert",
    pynput_keyboard.Key.f1: "f1",
    pynput_keyboard.Key.f2: "f2",
    pynput_keyboard.Key.f3: "f3",
    pynput_keyboard.Key.f4: "f4",
    pynput_keyboard.Key.f5: "f5",
    pynput_keyboard.Key.f6: "f6",
    pynput_keyboard.Key.f7: "f7",
    pynput_keyboard.Key.f8: "f8",
    pynput_keyboard.Key.f9: "f9",
    pynput_keyboard.Key.f10: "f10",
    pynput_keyboard.Key.f11: "f11",
}

SHIFTED_CHAR_MAP = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
    "~": "`",
}

DIRECT_CHAR_MAP = {
    "-": "-",
    "=": "=",
    "[": "[",
    "]": "]",
    "\\": "\\",
    ";": ";",
    "'": "'",
    ",": ",",
    ".": ".",
    "/": "/",
    "`": "`",
}


def build_input_url(host: str, port: int) -> str:
    listen_host = "@" if host in ("", "0.0.0.0", "*") else host
    return f"udp://{listen_host}:{port}?fifo_size=5000000&overrun_nonfatal=1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Receive the remote desktop UDP stream and control the remote desktop over a persistent SSH channel."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Local listen host. Use 0.0.0.0 to listen on all interfaces.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Local UDP port to listen on.",
    )
    parser.add_argument(
        "--print-interval",
        type=float,
        default=1.0,
        help="Seconds between status lines.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display the received frames in a window.",
    )
    parser.add_argument(
        "--window-name",
        default="remote-screen",
        help="Window title used with --show.",
    )
    parser.add_argument(
        "--open-timeout",
        type=float,
        default=15.0,
        help="Seconds to wait for the stream to become readable.",
    )
    parser.add_argument(
        "--display-width",
        type=int,
        default=DEFAULT_DISPLAY_WIDTH,
        help="Display width used for the local preview window.",
    )
    parser.add_argument(
        "--display-height",
        type=int,
        default=DEFAULT_DISPLAY_HEIGHT,
        help="Display height used for the local preview window.",
    )
    parser.add_argument(
        "--remote-host",
        default="10.0.0.2",
        help="Remote SSH host used for control.",
    )
    parser.add_argument(
        "--remote-user",
        default="qintao",
        help="Remote SSH user used for control.",
    )
    parser.add_argument(
        "--remote-password",
        default=" ",
        help="Remote SSH password used for control.",
    )
    parser.add_argument(
        "--remote-script",
        default="/home/qintao/connect/read_screen_size.py",
        help="Remote script path that executes control events.",
    )
    parser.add_argument(
        "--ssh-timeout",
        type=float,
        default=5.0,
        help="Seconds to wait for SSH operations.",
    )
    return parser.parse_args()


@dataclass
class DisplayGeometry:
    content_width: int
    content_height: int
    offset_x: int
    offset_y: int


class WindowFocusChecker:
    def __init__(self, window_name: str) -> None:
        self.window_name = window_name
        self.lock = threading.Lock()
        self.display = XDisplay()
        self.root = self.display.screen().root
        self.active_window_atom = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        self.net_wm_name_atom = self.display.intern_atom("_NET_WM_NAME")
        self.utf8_atom = self.display.intern_atom("UTF8_STRING")

    def close(self) -> None:
        with self.lock:
            self.display.close()

    def is_active(self) -> bool:
        with self.lock:
            try:
                prop = self.root.get_full_property(self.active_window_atom, X.AnyPropertyType)
                if prop is None or not prop.value:
                    return False
                window = self.display.create_resource_object("window", int(prop.value[0]))
                window_name = self._get_window_name(window)
                if not window_name:
                    return False
                return self.window_name in window_name
            except Exception:
                return False

    def _get_window_name(self, window) -> str:
        prop = window.get_full_property(self.net_wm_name_atom, self.utf8_atom)
        if prop is not None and prop.value:
            value = prop.value
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore")
            return bytes(value).decode("utf-8", errors="ignore")

        prop = window.get_full_property(Xatom.WM_NAME, X.AnyPropertyType)
        if prop is not None and prop.value:
            value = prop.value
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="ignore")
            return bytes(value).decode("utf-8", errors="ignore")

        wm_name = window.get_wm_name()
        return wm_name or ""


class PersistentSSHRemoteController:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        script_path: str,
        timeout: float,
    ) -> None:
        self.host = host.strip()
        self.user = user
        self.password = password
        self.script_path = script_path
        self.timeout = timeout
        self.client: Optional[paramiko.SSHClient] = None
        self.channel = None
        self.stdin: Optional[BinaryIO] = None
        self.stdout: Optional[BinaryIO] = None
        self.stderr: Optional[BinaryIO] = None
        self.lock = threading.Lock()
        self.last_error_time = 0.0
        self.stderr_thread: Optional[threading.Thread] = None
        self.stdout_thread: Optional[threading.Thread] = None

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.user and self.script_path)

    def close(self) -> None:
        with self.lock:
            self._close_control_channel()
            if self.client is not None:
                self.client.close()
                self.client = None

    def ensure_ready(self) -> bool:
        if not self.enabled:
            return False

        with self.lock:
            if self._channel_alive():
                return True

            self._close_control_channel()
            if not self._ensure_client():
                return False
            return self._start_control_channel()

    def send_click(self, x_norm: float, y_norm: float, button: str, clicks: int = 1) -> bool:
        return self.send_event(
            {
                "type": "click",
                "x_norm": x_norm,
                "y_norm": y_norm,
                "button": button,
                "clicks": clicks,
            }
        )

    def send_key_down(self, key_name: str) -> bool:
        return self.send_event({"type": "key_down", "key_name": key_name})

    def send_key_up(self, key_name: str) -> bool:
        return self.send_event({"type": "key_up", "key_name": key_name})

    def send_key_tap(self, key_name: str, presses: int = 1) -> bool:
        return self.send_event(
            {
                "type": "key_tap",
                "key_name": key_name,
                "presses": presses,
            }
        )

    def send_text(self, text: str) -> bool:
        return self.send_event({"type": "text", "text": text})

    def send_event(self, payload: dict) -> bool:
        if not self.enabled:
            return False

        data = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        for _ in range(2):
            if not self.ensure_ready():
                return False
            with self.lock:
                try:
                    assert self.stdin is not None
                    self.stdin.write(data)
                    self.stdin.flush()
                    return True
                except Exception as exc:
                    self._log_error(f"remote control write failed: {exc}")
                    self._close_control_channel()
        return False

    def _ensure_client(self) -> bool:
        if self.client is not None:
            transport = self.client.get_transport()
            if transport is not None and transport.is_active():
                return True
            self.client.close()
            self.client = None

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self.host,
                username=self.user,
                password=self.password,
                timeout=self.timeout,
            )
            self.client = client
            print(f"remote ssh connected: {self.user}@{self.host}", flush=True)
            return True
        except Exception as exc:
            self._log_error(f"remote ssh connect failed: {exc}")
            self.client = None
            return False

    def _start_control_channel(self) -> bool:
        try:
            assert self.client is not None
            transport = self.client.get_transport()
            if transport is None:
                return False

            channel = transport.open_session(timeout=self.timeout)
            channel.exec_command(
                f"python3 {shlex.quote(self.script_path)} --control-stdio"
            )
            stdin = channel.makefile("wb")
            stdout = channel.makefile("rb")
            stderr = channel.makefile_stderr("rb")

            self.channel = channel
            self.stdin = stdin
            self.stdout = stdout
            self.stderr = stderr
            self.stdout_thread = threading.Thread(
                target=self._drain_stream,
                args=("stdout", stdout),
                daemon=True,
            )
            self.stderr_thread = threading.Thread(
                target=self._drain_stream,
                args=("stderr", stderr),
                daemon=True,
            )
            self.stdout_thread.start()
            self.stderr_thread.start()
            print("remote control channel ready", flush=True)
            return True
        except Exception as exc:
            self._log_error(f"remote control session failed: {exc}")
            self._close_control_channel()
            return False

    def _channel_alive(self) -> bool:
        return self.channel is not None and not self.channel.exit_status_ready()

    def _close_control_channel(self) -> None:
        for stream in (self.stdin, self.stdout, self.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        if self.channel is not None:
            try:
                self.channel.close()
            except Exception:
                pass
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.channel = None

    def _drain_stream(self, name: str, stream: BinaryIO) -> None:
        try:
            while True:
                raw = stream.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", errors="ignore").strip()
                if text:
                    target = sys.stderr if name == "stderr" else sys.stdout
                    print(f"remote {name}: {text}", file=target, flush=True)
        except Exception:
            return

    def _log_error(self, message: str) -> None:
        now = time.perf_counter()
        if now - self.last_error_time >= 1.0:
            print(message, file=sys.stderr, flush=True)
            self.last_error_time = now


class KeyboardForwarder:
    def __init__(
        self,
        controller: PersistentSSHRemoteController,
        focus_checker: WindowFocusChecker,
        state: dict,
    ) -> None:
        self.controller = controller
        self.focus_checker = focus_checker
        self.state = state
        self.listener: Optional[pynput_keyboard.Listener] = None
        self.active_modifiers = set()
        self.lock = threading.Lock()

    def start(self) -> None:
        self.listener = pynput_keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self.listener.start()

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

    def _on_press(self, key) -> None:
        modifier_name = MODIFIER_KEYS.get(key)
        if modifier_name is not None:
            if not self.focus_checker.is_active():
                return
            with self.lock:
                if modifier_name in self.active_modifiers:
                    return
                self.active_modifiers.add(modifier_name)
            self.controller.send_key_down(modifier_name)
            return

        if key == pynput_keyboard.Key.caps_lock:
            if self.focus_checker.is_active():
                self.controller.send_key_tap("capslock")
            return

        if not self.focus_checker.is_active():
            return

        if key == pynput_keyboard.Key.f12:
            self.state["should_exit"] = True
            return

        special_name = SPECIAL_KEYS.get(key)
        if special_name is not None:
            self.controller.send_key_tap(special_name)
            return

        char = getattr(key, "char", None)
        if char is None:
            return

        key_name = char_to_key_name(char)
        if key_name is not None:
            self.controller.send_key_tap(key_name)
        else:
            self.controller.send_text(char)

    def _on_release(self, key) -> None:
        modifier_name = MODIFIER_KEYS.get(key)
        if modifier_name is None:
            return

        with self.lock:
            if modifier_name not in self.active_modifiers:
                return
            self.active_modifiers.remove(modifier_name)

        self.controller.send_key_up(modifier_name)


def char_to_key_name(char: str) -> Optional[str]:
    if not char:
        return None
    if char == " ":
        return "space"
    if "a" <= char <= "z":
        return char
    if "A" <= char <= "Z":
        return char.lower()
    if "0" <= char <= "9":
        return char
    if char in SHIFTED_CHAR_MAP:
        return SHIFTED_CHAR_MAP[char]
    if char in DIRECT_CHAR_MAP:
        return DIRECT_CHAR_MAP[char]
    return None


def open_capture(url: str, timeout: float) -> cv2.VideoCapture:
    deadline = time.perf_counter() + timeout
    capture: Optional[cv2.VideoCapture] = None

    while time.perf_counter() < deadline:
        if capture is not None:
            capture.release()

        capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if capture.isOpened():
            return capture

        time.sleep(0.3)

    if capture is not None:
        capture.release()
    raise RuntimeError(f"Failed to open stream: {url}")


def compute_display_geometry(
    src_width: int,
    src_height: int,
    target_width: int,
    target_height: int,
) -> DisplayGeometry:
    scale = min(target_width / src_width, target_height / src_height)
    content_width = max(1, int(round(src_width * scale)))
    content_height = max(1, int(round(src_height * scale)))
    offset_x = (target_width - content_width) // 2
    offset_y = (target_height - content_height) // 2
    return DisplayGeometry(
        content_width=content_width,
        content_height=content_height,
        offset_x=offset_x,
        offset_y=offset_y,
    )


def build_display_frame(frame, target_width: int, target_height: int):
    src_height, src_width = frame.shape[:2]
    geometry = compute_display_geometry(src_width, src_height, target_width, target_height)

    resized = cv2.resize(
        frame,
        (geometry.content_width, geometry.content_height),
        interpolation=cv2.INTER_LINEAR,
    )

    canvas = cv2.copyMakeBorder(
        resized,
        geometry.offset_y,
        target_height - geometry.content_height - geometry.offset_y,
        geometry.offset_x,
        target_width - geometry.content_width - geometry.offset_x,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )
    return canvas, geometry


def map_display_to_normalized(
    x: int,
    y: int,
    geometry: Optional[DisplayGeometry],
) -> Optional[Tuple[float, float]]:
    if geometry is None:
        return None

    if x < geometry.offset_x or y < geometry.offset_y:
        return None
    if x >= geometry.offset_x + geometry.content_width:
        return None
    if y >= geometry.offset_y + geometry.content_height:
        return None

    local_x = x - geometry.offset_x
    local_y = y - geometry.offset_y
    x_norm = local_x / max(1, geometry.content_width - 1)
    y_norm = local_y / max(1, geometry.content_height - 1)
    x_norm = max(0.0, min(1.0, x_norm))
    y_norm = max(0.0, min(1.0, y_norm))
    return x_norm, y_norm


def make_mouse_callback(state: dict):
    def handle_mouse(event: int, x: int, y: int, flags: int, param) -> None:
        del flags, param

        geometry = state.get("geometry")
        controller: PersistentSSHRemoteController = state["controller"]
        point = map_display_to_normalized(x, y, geometry)
        if point is None:
            return

        x_norm, y_norm = point

        if event == cv2.EVENT_LBUTTONUP:
            if controller.send_click(x_norm, y_norm, "left", clicks=1):
                print(
                    f"remote left click: norm=({x_norm:.3f}, {y_norm:.3f})",
                    flush=True,
                )
        elif event == cv2.EVENT_RBUTTONUP:
            if controller.send_click(x_norm, y_norm, "right", clicks=1):
                print(
                    f"remote right click: norm=({x_norm:.3f}, {y_norm:.3f})",
                    flush=True,
                )
        elif event == cv2.EVENT_MBUTTONUP:
            if controller.send_click(x_norm, y_norm, "left", clicks=2):
                print(
                    f"remote double click: norm=({x_norm:.3f}, {y_norm:.3f})",
                    flush=True,
                )

    return handle_mouse


def main() -> int:
    args = parse_args()

    if args.port <= 0 or args.port > 65535:
        print("port must be between 1 and 65535", file=sys.stderr)
        return 1
    if args.print_interval <= 0:
        print("print-interval must be greater than 0", file=sys.stderr)
        return 1
    if args.open_timeout <= 0:
        print("open-timeout must be greater than 0", file=sys.stderr)
        return 1
    if args.display_width <= 0:
        print("display-width must be greater than 0", file=sys.stderr)
        return 1
    if args.display_height <= 0:
        print("display-height must be greater than 0", file=sys.stderr)
        return 1
    if args.ssh_timeout <= 0:
        print("ssh-timeout must be greater than 0", file=sys.stderr)
        return 1

    controller = PersistentSSHRemoteController(
        host=args.remote_host,
        user=args.remote_user,
        password=args.remote_password,
        script_path=args.remote_script,
        timeout=args.ssh_timeout,
    )

    focus_checker = None
    keyboard_forwarder = None
    if args.show and controller.enabled:
        focus_checker = WindowFocusChecker(args.window_name)

    url = build_input_url(args.host, args.port)
    print(f"listening: {url}", flush=True)
    if controller.enabled:
        print(
            "window controls: left=left click, right=right click, middle=double click, "
            "focused keyboard=remote input, CapsLock and Ctrl/Shift/Alt combos supported, "
            "F12=exit local preview",
            flush=True,
        )

    capture = None
    state = {
        "controller": controller,
        "geometry": None,
        "should_exit": False,
    }

    try:
        capture = open_capture(url, args.open_timeout)
        print("stream opened", flush=True)

        if controller.enabled:
            controller.ensure_ready()

        if args.show:
            cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(args.window_name, args.display_width, args.display_height)
            cv2.setMouseCallback(args.window_name, make_mouse_callback(state))

            if focus_checker is not None:
                keyboard_forwarder = KeyboardForwarder(
                    controller=controller,
                    focus_checker=focus_checker,
                    state=state,
                )
                keyboard_forwarder.start()

        last_print_time = time.perf_counter()
        last_fps_time = last_print_time
        frames_since_print = 0

        while True:
            if state["should_exit"]:
                break

            ok, frame = capture.read()
            if not ok:
                time.sleep(0.01)
                continue

            height, width = frame.shape[:2]
            frames_since_print += 1

            display_frame = None
            if args.show:
                display_frame, geometry = build_display_frame(
                    frame,
                    args.display_width,
                    args.display_height,
                )
                state["geometry"] = geometry

            now = time.perf_counter()
            if now - last_print_time >= args.print_interval:
                elapsed = now - last_fps_time
                fps_value = frames_since_print / elapsed if elapsed > 0 else 0.0
                control_status = "persistent-ssh" if controller.enabled else "off"
                print(
                    f"[{time.strftime('%H:%M:%S')}] "
                    f"frame={width}x{height} "
                    f"display={args.display_width}x{args.display_height} "
                    f"control={control_status} "
                    f"fps={fps_value:.2f}",
                    flush=True,
                )
                last_print_time = now
                last_fps_time = now
                frames_since_print = 0

            if args.show and display_frame is not None:
                cv2.imshow(args.window_name, display_frame)
                if cv2.getWindowProperty(args.window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
                cv2.waitKey(1)

    except KeyboardInterrupt:
        print("stopped", flush=True)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if keyboard_forwarder is not None:
            keyboard_forwarder.stop()
        if focus_checker is not None:
            focus_checker.close()
        controller.close()
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
