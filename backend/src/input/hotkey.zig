const std = @import("std");
const windows = std.os.windows;
const modifiers = @import("modifiers.zig");

// Windows message + hotkey API — self-contained decls (no @cImport).

pub const MOD_ALT: u32 = 0x0001;
pub const MOD_CONTROL: u32 = 0x0002;
pub const MOD_SHIFT: u32 = 0x0004;
pub const MOD_WIN: u32 = 0x0008;
pub const MOD_NOREPEAT: u32 = 0x4000;

pub const WM_HOTKEY: u32 = 0x0312;
pub const WM_QUIT: u32 = 0x0012;
pub const WM_APP: u32 = 0x8000;

pub const POINT = extern struct { x: i32, y: i32 };
pub const MSG = extern struct {
    hwnd: ?windows.HWND,
    message: u32,
    wParam: usize,
    lParam: isize,
    time: u32,
    pt: POINT,
    lPrivate: u32,
};

extern "user32" fn RegisterHotKey(
    hWnd: ?windows.HWND,
    id: c_int,
    fsModifiers: c_uint,
    vk: c_uint,
) callconv(windows.WINAPI) windows.BOOL;

extern "user32" fn UnregisterHotKey(hWnd: ?windows.HWND, id: c_int) callconv(windows.WINAPI) windows.BOOL;

extern "user32" fn GetMessageW(
    lpMsg: *MSG,
    hWnd: ?windows.HWND,
    wMsgFilterMin: c_uint,
    wMsgFilterMax: c_uint,
) callconv(windows.WINAPI) c_int;

extern "user32" fn PostThreadMessageW(
    idThread: windows.DWORD,
    Msg: c_uint,
    wParam: usize,
    lParam: isize,
) callconv(windows.WINAPI) windows.BOOL;

extern "kernel32" fn GetCurrentThreadId() callconv(windows.WINAPI) windows.DWORD;

extern "user32" fn PeekMessageW(
    lpMsg: *MSG,
    hWnd: ?windows.HWND,
    wMsgFilterMin: c_uint,
    wMsgFilterMax: c_uint,
    wRemoveMsg: c_uint,
) callconv(windows.WINAPI) windows.BOOL;

const PM_NOREMOVE: c_uint = 0x0000;
const WM_USER: c_uint = 0x0400;

pub const ERROR_HOTKEY_ALREADY_REGISTERED: u32 = 1409;

// ---- Public API ----

pub const Callback = *const fn (user_data: ?*anyopaque) void;

pub const RegisterError = error{ RegisterFailed, AlreadyRegistered, ThreadSpawnFailed };

/// Short user-facing text for hotkey_status.error.
pub fn errorText(err: RegisterError) []const u8 {
    return switch (err) {
        error.AlreadyRegistered => "already in use",
        error.RegisterFailed => "registration failed",
        error.ThreadSpawnFailed => "could not start hotkey thread",
    };
}

fn classifyWin32Error(code: u32) RegisterError {
    return if (code == ERROR_HOTKEY_ALREADY_REGISTERED) error.AlreadyRegistered else error.RegisterFailed;
}

// RegisterHotKey(NULL) is per-thread, so each Handle owns a pump thread; rebind: stop(), spawn().
pub const Handle = struct {
    allocator: std.mem.Allocator,
    thread: std.Thread,
    tid: std.atomic.Value(windows.DWORD),
    id: c_int,
    done: std.atomic.Value(bool),
    ctx: *ThreadCtx,

    /// Unregister, join the thread and free the handle.
    pub fn stop(self: *Handle) void {
        self.done.store(true, .release);
        // Retry anyway: a lost WM_QUIT would make join() hang forever.
        var tries: u32 = 0;
        while (PostThreadMessageW(self.tid.load(.acquire), WM_QUIT, 0, 0) == 0 and tries < 200) : (tries += 1) {
            std.time.sleep(5 * std.time.ns_per_ms);
        }
        self.thread.join();
        const a = self.allocator;
        a.destroy(self.ctx);
        a.destroy(self);
    }
};

fn chordToMods(chord: modifiers.Chord) u32 {
    var m: u32 = MOD_NOREPEAT;
    if (chord.ctrl.active) m |= MOD_CONTROL;
    if (chord.alt.active) m |= MOD_ALT;
    if (chord.shift.active) m |= MOD_SHIFT;
    return m;
}

const ThreadCtx = struct {
    chord: modifiers.Chord,
    callback: Callback,
    user: ?*anyopaque,
    handle: *Handle,
    ready: std.atomic.Value(bool),
    register_ok: std.atomic.Value(bool),
    last_error: std.atomic.Value(u32),
};

pub fn spawn(
    allocator: std.mem.Allocator,
    chord: modifiers.Chord,
    callback: Callback,
    user_data: ?*anyopaque,
) RegisterError!*Handle {
    const handle = allocator.create(Handle) catch return RegisterError.ThreadSpawnFailed;
    const ctx = allocator.create(ThreadCtx) catch {
        allocator.destroy(handle);
        return RegisterError.ThreadSpawnFailed;
    };
    handle.* = .{
        .allocator = allocator,
        .thread = undefined,
        .tid = std.atomic.Value(windows.DWORD).init(0),
        .id = 1,
        .done = std.atomic.Value(bool).init(false),
        .ctx = ctx,
    };
    ctx.* = .{
        .chord = chord,
        .callback = callback,
        .user = user_data,
        .handle = handle,
        .ready = std.atomic.Value(bool).init(false),
        .register_ok = std.atomic.Value(bool).init(false),
        .last_error = std.atomic.Value(u32).init(0),
    };

    handle.thread = std.Thread.spawn(.{}, threadMain, .{ctx}) catch {
        allocator.destroy(ctx);
        allocator.destroy(handle);
        return RegisterError.ThreadSpawnFailed;
    };

    // Wait until the thread has called RegisterHotKey so success/failure is reported synchronously.
    while (!ctx.ready.load(.acquire)) {
        std.time.sleep(200 * std.time.ns_per_us);
    }
    if (!ctx.register_ok.load(.acquire)) {
        const code = ctx.last_error.load(.acquire);
        handle.thread.join(); // thread returns right after a failed register
        allocator.destroy(ctx);
        allocator.destroy(handle);
        return classifyWin32Error(code);
    }
    return handle;
}

fn threadMain(ctx: *ThreadCtx) void {
    var msg: MSG = std.mem.zeroes(MSG);
    // Create the queue first: PostThreadMessage(WM_QUIT) fails on a thread without one.
    _ = PeekMessageW(&msg, null, WM_USER, WM_USER, PM_NOREMOVE);
    ctx.handle.tid.store(GetCurrentThreadId(), .release);

    const ok = RegisterHotKey(
        null,
        ctx.handle.id,
        chordToMods(ctx.chord),
        @intCast(ctx.chord.base_vk),
    );
    if (ok == 0) ctx.last_error.store(@intFromEnum(windows.kernel32.GetLastError()), .release);
    ctx.register_ok.store(ok != 0, .release);
    ctx.ready.store(true, .release);

    if (ok == 0) return;
    defer _ = UnregisterHotKey(null, ctx.handle.id);

    while (!ctx.handle.done.load(.acquire)) {
        const r = GetMessageW(&msg, null, 0, 0);
        if (r <= 0) break; // WM_QUIT or error
        if (msg.message == WM_HOTKEY) {
            ctx.callback(ctx.user);
        }
    }
}

// ---- tests ---- (hotkey needs a live pump; modifiers.zig and vk_map.zig cover parsing/lookup)

test "chord to MOD flags" {
    const c1 = try modifiers.parse("ctrl+shift+a");
    const m1 = chordToMods(c1);
    try std.testing.expect((m1 & MOD_CONTROL) != 0);
    try std.testing.expect((m1 & MOD_SHIFT) != 0);
    try std.testing.expect((m1 & MOD_ALT) == 0);
    try std.testing.expect((m1 & MOD_NOREPEAT) != 0);

    const c2 = try modifiers.parse("alt+f12");
    const m2 = chordToMods(c2);
    try std.testing.expect((m2 & MOD_ALT) != 0);
    try std.testing.expect((m2 & MOD_CONTROL) == 0);
}

test "win32 error 1409 maps to 'already in use'" {
    try std.testing.expectEqual(RegisterError.AlreadyRegistered, classifyWin32Error(1409));
    try std.testing.expectEqual(RegisterError.RegisterFailed, classifyWin32Error(87));
    try std.testing.expectEqualStrings("already in use", errorText(classifyWin32Error(1409)));
    try std.testing.expectEqualStrings("registration failed", errorText(classifyWin32Error(5)));
}
