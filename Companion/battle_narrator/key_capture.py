"""Foreground-scoped keyboard capture for the settings menu (Windows).

**Why this is not `hotkeys.WindowsForegroundHotkey`.** Every other hotkey in
this project is a chord with a mandatory modifier -- `parse_hotkey` refuses a
bare key outright -- and is read by polling `GetAsyncKeyState`. Polling
observes; it cannot stop Dolphin from acting on the same press. That is fine
for `ctrl+g`, which Dolphin does nothing with. It is not fine here. Read from
the project owner's own Dolphin configuration:

    Hotkeys.ini    Load State/Load State Slot 1 = F1
    GCPadNew.ini   Main Stick Up/Down/Left/Right = UP/DOWN/LEFT/RIGHT
                   D-Pad/Right = H
                   Buttons/Start = RETURN

So a polled settings menu on those keys would load a save state every time it
opened, walk the player around while they moved through the list, and press
Start on the way out. The keys have to be taken away from the game, not
merely noticed, which is what `WH_KEYBOARD_LL` is for: the hook sees each
event before the foreground application does and can consume it.

**Scope, kept as narrow as the feature allows.** A global keyboard hook is a
serious thing to install, so:

- Only the keys in the policy are ever consumed. Everything else is passed
  straight on, untouched, in the same call.
- Nothing at all is consumed unless Dolphin owns foreground focus -- the same
  rule every other hotkey in this project already follows. Alt-tab away and
  the keyboard behaves exactly as if this module did not exist.
- Outside the menu, exactly ONE key is consumed: the key that opens it. The
  arrows, H, Enter and Escape are consumed only while the menu is actually
  open, so ordinary play is unaffected.
- `--no-settings-menu` disables the whole thing, hook included.

**Threading.** A low-level hook is called on the thread that installed it,
and that thread must be pumping messages; Windows silently removes a hook
whose callback does not return within `LowLevelHooksTimeout` (300 ms by
default). The narrator's poll loop sleeps up to half a second between ticks
and does memory reads and pathfinding in between, so the hook gets its own
dedicated thread that does nothing but pump. The callback itself only
classifies the key and appends to a deque; every decision that could be slow
(speech, reading game memory) happens later, on the poll thread, when
`poll()` drains it.
"""
import ctypes
from ctypes import wintypes
import threading
from collections import deque


WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
LLKHF_INJECTED = 0x10

VK_BACK = 0x08
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_H = 0x48
VK_F1 = 0x70

MENU_KEYS = frozenset({
    VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT, VK_H, VK_RETURN, VK_SPACE,
    VK_ESCAPE, VK_HOME, VK_END,
})
"""Consumed only while the menu is open. Space and Enter both activate,
Home and End jump to the ends of the list."""

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KeyEvent:
    """One key-down the companion took for itself."""

    __slots__ = ("vk", "shift", "ctrl", "alt")

    def __init__(self, vk, shift=False, ctrl=False, alt=False):
        self.vk = vk
        self.shift = shift
        self.ctrl = ctrl
        self.alt = alt

    def __eq__(self, other):
        return (
            isinstance(other, KeyEvent)
            and (self.vk, self.shift, self.ctrl, self.alt)
            == (other.vk, other.shift, other.ctrl, other.alt)
        )

    def __repr__(self):
        flags = "".join(
            name for name, held in
            (("shift", self.shift), ("ctrl", self.ctrl), ("alt", self.alt))
            if held
        )
        return f"KeyEvent(vk=0x{self.vk:02X}{'+' + flags if flags else ''})"


class MenuKeyPolicy:
    """Which keys belong to the companion, and when.

    Separated from the hook so the rule -- the part with the actual
    consequences for the player's game -- is testable without installing
    anything."""

    def __init__(self, open_key=VK_F1, menu_keys=MENU_KEYS):
        self.open_key = open_key
        self.menu_keys = frozenset(menu_keys)

    def owns(self, vk, menu_open):
        if vk == self.open_key:
            return True
        return bool(menu_open) and vk in self.menu_keys


class LowLevelKeyCapture:
    """Installs the hook, decides swallow-or-pass, and queues what it took.

    `foreground` is a zero-argument callable returning whether Dolphin owns
    focus (in production `hotkeys.WindowsForegroundProcess().is_active`).
    `user32`/`kernel32` are injectable so the classification logic can be
    tested without Windows in the loop.
    """

    def __init__(self, policy=None, foreground=None, logger=None,
                 user32=None, kernel32=None):
        self.policy = policy or MenuKeyPolicy()
        self.foreground = foreground or (lambda: True)
        self.logger = logger
        self.user32 = user32 if user32 is not None else ctypes.windll.user32
        self.kernel32 = (
            kernel32 if kernel32 is not None else ctypes.windll.kernel32)
        self.menu_open = False
        self.events = deque()
        self.installed = False
        self._hook = None
        self._proc = None
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()

    # -- classification (runs on the hook thread) ----------------------

    def _held(self, vk):
        return bool(self.user32.GetAsyncKeyState(vk) & 0x8000)

    def _handle(self, vk, message):
        """True to swallow the event. Called for every key on the machine,
        so the cheap check comes first and the foreground lookup only
        happens for a key we might actually want."""
        if not self.policy.owns(vk, self.menu_open):
            return False
        if not self.foreground():
            return False
        if message in (WM_KEYDOWN, WM_SYSKEYDOWN):
            self.events.append(KeyEvent(
                vk,
                shift=self._held(VK_SHIFT),
                ctrl=self._held(VK_CONTROL),
                alt=self._held(VK_MENU),
            ))
        # The key-up is swallowed too. Letting it through on its own leaves
        # DirectInput holding a key it never saw pressed, which is how a
        # swallowed arrow would turn into a stuck walk.
        return True

    def _callback(self, code, wparam, lparam):
        if code == HC_ACTION:
            try:
                info = ctypes.cast(
                    lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if self._handle(info.vkCode, wparam):
                    return 1
            except Exception as exc:
                # Nothing may escape into the Windows hook chain: an
                # exception here would leave the player's keyboard behaving
                # unpredictably in a way nothing in this project could catch.
                self._log("warning", "KEY CAPTURE callback failed: %s", exc)
        return self.user32.CallNextHookEx(None, code, wparam, lparam)

    # -- lifetime ------------------------------------------------------

    def start(self, timeout=5.0):
        """Install the hook on its own thread. Returns whether it took."""
        if self._thread is not None:
            return self.installed
        self._configure_prototypes()
        self._thread = threading.Thread(
            target=self._pump, name="settings-key-capture", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.installed

    def _configure_prototypes(self):
        """Explicit signatures. Without them ctypes truncates the 64-bit
        handles and pointers these calls traffic in, and the failure looks
        like a hook that installs and then never fires."""
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        self.user32.CallNextHookEx.restype = LRESULT
        self.user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self.user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self.user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint,
            ctypes.c_uint]
        self.user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]

    def _pump(self):
        self._thread_id = self.kernel32.GetCurrentThreadId()
        # The bound HOOKPROC is kept on the instance: if it were only a
        # local, Python would collect it while Windows still held its
        # address, and the first keypress would land in freed memory.
        self._proc = HOOKPROC(self._callback)
        self._hook = self.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, None, 0)
        self.installed = bool(self._hook)
        if not self.installed:
            self._log(
                "error",
                "KEY CAPTURE could not install the keyboard hook (error %s); "
                "the settings menu is unavailable this session",
                ctypes.get_last_error() if hasattr(ctypes, "get_last_error")
                else "unknown")
        self._ready.set()
        if not self.installed:
            return
        self._log("info", "KEY CAPTURE installed on thread %s", self._thread_id)
        message = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))
        self.user32.UnhookWindowsHookEx(self._hook)
        self.installed = False
        self._log("info", "KEY CAPTURE removed")

    def stop(self, timeout=2.0):
        if self._thread is None or self._thread_id is None:
            return
        self.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout)
        self._thread = None

    # -- consumption (runs on the poll thread) -------------------------

    def poll(self):
        """Drain and return everything captured since the last call.

        `deque.popleft` is atomic, so no lock is needed between this and the
        hook thread's `append`."""
        drained = []
        while True:
            try:
                drained.append(self.events.popleft())
            except IndexError:
                return drained

    def discard(self):
        self.events.clear()

    def _log(self, level, message, *args):
        if self.logger is not None:
            getattr(self.logger, level)(message, *args)
