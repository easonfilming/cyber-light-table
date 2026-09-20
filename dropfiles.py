"""Windows 拖拽接收：从资源管理器把文件拖进窗口。

tkinter 原生不支持，得挂 shell32 的 `DragAcceptFiles`，
再子类化窗口过程收 `WM_DROPFILES`。

**这段单独放一个模块、全程 try/except** —— 失败了就静默不启用，
绝不能让拖拽把整个程序搞崩。64 位下有三处做错会直接崩进程：

1. 原型写错（`GetWindowLongW` 只有 32 位，得用 `...PtrW`；`CallWindowProcW`
   的句柄参数不声明 argtypes 会被截断）
2. `WNDPROC` 回调对象被 GC 收走 —— 所以下面用 `_keep_alive` 留一份引用
3. 回调里抛异常穿回 C —— 所以整个回调体包在 try/except 里，
   而且最后一定要 `CallWindowProcW` 把消息转下去

Tk 的 toplevel 有内外两层窗口，不确定哪层收 `WM_DROPFILES`，
所以两层都挂一遍，哪层生效算哪层。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
DRAGQUERYFILE_ALL = 0xFFFFFFFF

# 必须留一份引用：WNDPROC 对象被 GC 收走的话，消息一来就崩
_keep_alive: list = []


def available() -> bool:
    return hasattr(ctypes, "windll")


def enable(widget, on_files) -> bool:
    """给窗口挂上拖拽接收。成功返回 True；非 Windows 或出错返回 False。

    on_files(paths: list[str]) 在 Tk 主线程里被调用。
    """
    if not available():
        return False
    try:
        return _install(widget, on_files)
    except Exception:
        return False


def _install(widget, on_files) -> bool:
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32

    widget.update_idletasks()
    hwnd = int(widget.winfo_id())

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                                 ctypes.c_ulonglong, ctypes.c_longlong)

    is64 = ctypes.sizeof(ctypes.c_void_p) == 8
    get_long = user32.GetWindowLongPtrW if is64 else user32.GetWindowLongW
    set_long = user32.SetWindowLongPtrW if is64 else user32.SetWindowLongW
    get_long.restype = ctypes.c_void_p
    get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    set_long.restype = ctypes.c_void_p
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

    user32.GetParent.restype = ctypes.c_void_p
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.CallWindowProcW.restype = ctypes.c_longlong
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint,
                                       ctypes.c_ulonglong, ctypes.c_longlong]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]

    targets = [hwnd]
    parent = user32.GetParent(hwnd)
    if parent and int(parent) != hwnd:
        targets.append(int(parent))

    installed = False
    for target in targets:
        try:
            old = get_long(target, GWLP_WNDPROC)
            if not old:
                continue

            def make_proc(old_proc):
                def proc(h, msg, wparam, lparam):
                    try:
                        if msg == WM_DROPFILES:
                            paths = _read_drop(wparam)
                            shell32.DragFinish(ctypes.c_void_p(wparam))
                            if paths:
                                widget.after(0, _dispatch, widget, on_files, paths)
                            return 0
                    except Exception:
                        pass
                    # 一定要转下去，不然窗口就不响应消息了
                    return user32.CallWindowProcW(old_proc, h, msg, wparam, lparam)
                return proc

            cb = WNDPROC(make_proc(old))
            if set_long(target, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p)):
                _keep_alive.append(cb)
                shell32.DragAcceptFiles(wintypes.HWND(target), True)
                installed = True
        except Exception:
            continue
    return installed


def _dispatch(widget, on_files, paths):
    """在 Tk 事件循环里执行回调，兜住所有异常。"""
    try:
        on_files(paths)
    except Exception:
        pass


def _read_drop(hdrop) -> list[str]:
    """从 HDROP 里取出拖进来的文件路径。"""
    shell32 = ctypes.windll.shell32
    shell32.DragQueryFileW.restype = ctypes.c_uint
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_void_p, ctypes.c_uint]

    handle = ctypes.c_void_p(hdrop)
    n = int(shell32.DragQueryFileW(handle, DRAGQUERYFILE_ALL, None, 0))
    out = []
    for i in range(max(0, n)):
        need = int(shell32.DragQueryFileW(handle, i, None, 0))
        buf = ctypes.create_unicode_buffer(need + 1)
        shell32.DragQueryFileW(handle, i, ctypes.cast(buf, ctypes.c_void_p), need + 1)
        if buf.value:
            out.append(buf.value)
    return out
