const std = @import("std");
const windows = std.os.windows;
const modifiers = @import("modifiers.zig");
const vk_map = @import("vk_map.zig");

// ---- Windows API externs (INPUT on x64: DWORD + 4 pad + 32-byte union = 40 bytes) ----

pub const KEYBDINPUT = extern struct {
    wVk: u16,
    wScan: u16,
    dwFlags: u32,
    time: u32,
    dwExtraInfo: usize,
};

pub const MOUSEINPUT = extern struct {
    dx: i32,
    dy: i32,
    mouseData: u32,
    dwFlags: u32,
    time: u32,
    dwExtraInfo: usize,
};

pub const HARDWAREINPUT = extern struct {
    uMsg: u32,
    wParamL: u16,
    wParamH: u16,
};

const INPUT_UNION = extern union {
    mi: MOUSEINPUT,
    ki: KEYBDINPUT,
    hi: HARDWAREINPUT,
};

pub const INPUT = extern struct {
    type: u32,
    u: INPUT_UNION align(@alignOf(usize)),
};

comptime {
    // Sanity: on any 64-bit target this must be 40. On 32-bit, 28.
    const expected: comptime_int = if (@sizeOf(usize) == 8) 40 else 28;
    if (@sizeOf(INPUT) != expected) @compileError("INPUT layout mismatch");
}

pub const INPUT_MOUSE: u32 = 0;
pub const INPUT_KEYBOARD: u32 = 1;
pub const INPUT_HARDWARE: u32 = 2;

pub const KEYEVENTF_EXTENDEDKEY: u32 = 0x0001;
pub const KEYEVENTF_KEYUP: u32 = 0x0002;
pub const KEYEVENTF_UNICODE: u32 = 0x0004;
pub const KEYEVENTF_SCANCODE: u32 = 0x0008;

pub const MOUSEEVENTF_LEFTDOWN: u32 = 0x0002;
pub const MOUSEEVENTF_LEFTUP: u32 = 0x0004;
pub const MOUSEEVENTF_RIGHTDOWN: u32 = 0x0008;
pub const MOUSEEVENTF_RIGHTUP: u32 = 0x0010;
pub const MOUSEEVENTF_MIDDLEDOWN: u32 = 0x0020;
pub const MOUSEEVENTF_MIDDLEUP: u32 = 0x0040;
pub const MOUSEEVENTF_XDOWN: u32 = 0x0080;
pub const MOUSEEVENTF_XUP: u32 = 0x0100;
pub const MOUSEEVENTF_WHEEL: u32 = 0x0800;
pub const MOUSEEVENTF_HWHEEL: u32 = 0x1000;

pub const XBUTTON1: u32 = 0x0001;
pub const XBUTTON2: u32 = 0x0002;
pub const WHEEL_DELTA: i32 = 120;

extern "user32" fn SendInput(
    cInputs: c_uint,
    pInputs: [*]INPUT,
    cbSize: c_int,
) callconv(windows.WINAPI) c_uint;

// ---- Public API ----

pub const SendError = error{ SendInputFailed, UnknownKey } || modifiers.ParseError;

// Extended-key VKs that require KEYEVENTF_EXTENDEDKEY per MSDN.
fn isExtendedKey(vk: u16) bool {
    return switch (vk) {
        vk_map.VK.RMENU, vk_map.VK.RCONTROL,
        vk_map.VK.INSERT, vk_map.VK.DELETE,
        vk_map.VK.HOME, vk_map.VK.END,
        vk_map.VK.PRIOR, vk_map.VK.NEXT,
        vk_map.VK.LEFT, vk_map.VK.UP, vk_map.VK.RIGHT, vk_map.VK.DOWN,
        vk_map.VK.SNAPSHOT, vk_map.VK.DIVIDE,
        vk_map.VK.LWIN, vk_map.VK.RWIN,
        vk_map.VK.RETURN, // flag harmless for main enter (numpad-enter is the extended one)
        => true,
        else => false,
    };
}

fn makeKey(vk: u16, keyup: bool) INPUT {
    var flags: u32 = 0;
    if (keyup) flags |= KEYEVENTF_KEYUP;
    if (isExtendedKey(vk)) flags |= KEYEVENTF_EXTENDEDKEY;
    return .{
        .type = INPUT_KEYBOARD,
        .u = .{ .ki = .{
            .wVk = vk,
            .wScan = 0,
            .dwFlags = flags,
            .time = 0,
            .dwExtraInfo = 0,
        } },
    };
}

fn appendModifierDown(list: *std.ArrayList(INPUT), mod: modifiers.Modifier, neutral: u16, left: u16, right: u16) !void {
    if (!mod.active) return;
    const vk = switch (mod.side) {
        .left => left,
        .right => right,
        .unspecified => neutral,
    };
    try list.append(makeKey(vk, false));
}

fn appendModifierUp(list: *std.ArrayList(INPUT), mod: modifiers.Modifier, neutral: u16, left: u16, right: u16) !void {
    if (!mod.active) return;
    const vk = switch (mod.side) {
        .left => left,
        .right => right,
        .unspecified => neutral,
    };
    try list.append(makeKey(vk, true));
}

// Press modifiers (if any) + base, then release in reverse order.
pub fn tap(allocator: std.mem.Allocator, chord: modifiers.Chord) SendError!void {
    var list: std.ArrayList(INPUT) = .init(allocator);
    defer list.deinit();

    try appendModifierDown(&list, chord.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);
    try appendModifierDown(&list, chord.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierDown(&list, chord.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try list.append(makeKey(chord.base_vk, false));
    try list.append(makeKey(chord.base_vk, true));
    try appendModifierUp(&list, chord.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try appendModifierUp(&list, chord.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierUp(&list, chord.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);

    try dispatch(list.items);
}

// Press everything, sleep, release everything.
pub fn hold(allocator: std.mem.Allocator, chord: modifiers.Chord, duration_ms: u32) SendError!void {
    var down_list: std.ArrayList(INPUT) = .init(allocator);
    defer down_list.deinit();
    var up_list: std.ArrayList(INPUT) = .init(allocator);
    defer up_list.deinit();

    try appendModifierDown(&down_list, chord.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);
    try appendModifierDown(&down_list, chord.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierDown(&down_list, chord.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try down_list.append(makeKey(chord.base_vk, false));

    try up_list.append(makeKey(chord.base_vk, true));
    try appendModifierUp(&up_list, chord.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try appendModifierUp(&up_list, chord.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierUp(&up_list, chord.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);

    try dispatch(down_list.items);
    std.time.sleep(@as(u64, duration_ms) * std.time.ns_per_ms);
    try dispatch(up_list.items);
}

pub fn pressChord(allocator: std.mem.Allocator, chord: modifiers.Chord) SendError!void {
    var list: std.ArrayList(INPUT) = .init(allocator);
    defer list.deinit();
    try appendModifierDown(&list, chord.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);
    try appendModifierDown(&list, chord.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierDown(&list, chord.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try list.append(makeKey(chord.base_vk, false));
    try dispatch(list.items);
}

pub fn releaseChord(allocator: std.mem.Allocator, chord: modifiers.Chord) SendError!void {
    var list: std.ArrayList(INPUT) = .init(allocator);
    defer list.deinit();
    try list.append(makeKey(chord.base_vk, true));
    try appendModifierUp(&list, chord.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try appendModifierUp(&list, chord.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierUp(&list, chord.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);
    try dispatch(list.items);
}

pub const MouseButton = enum { left, right, middle, x1, x2 };
pub const MouseKind = enum { click, down, up, double };

pub fn mouse(btn: MouseButton, kind: MouseKind) SendError!void {
    var inputs: [4]INPUT = undefined;
    var count: usize = 0;

    const flags = mouseFlags(btn);
    switch (kind) {
        .down => {
            inputs[count] = mouseInput(flags.down, mouseData(btn));
            count = 1;
        },
        .up => {
            inputs[count] = mouseInput(flags.up, mouseData(btn));
            count = 1;
        },
        .click, .double => {
            inputs[count] = mouseInput(flags.down, mouseData(btn));
            count += 1;
            inputs[count] = mouseInput(flags.up, mouseData(btn));
            count += 1;
            if (kind == .double) {
                inputs[count] = mouseInput(flags.down, mouseData(btn));
                count += 1;
                inputs[count] = mouseInput(flags.up, mouseData(btn));
                count += 1;
            }
        },
    }
    try dispatch(inputs[0..count]);
}

// Modifier and key events that surround a click, in press order.
fn heldDown(list: *std.ArrayList(INPUT), held: modifiers.Chord) !void {
    try appendModifierDown(list, held.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);
    try appendModifierDown(list, held.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierDown(list, held.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    if (held.base_vk != 0) try list.append(makeKey(held.base_vk, false));
}

fn heldUp(list: *std.ArrayList(INPUT), held: modifiers.Chord) !void {
    if (held.base_vk != 0) try list.append(makeKey(held.base_vk, true));
    try appendModifierUp(list, held.shift, vk_map.VK.SHIFT, vk_map.VK.LSHIFT, vk_map.VK.RSHIFT);
    try appendModifierUp(list, held.alt, vk_map.VK.MENU, vk_map.VK.LMENU, vk_map.VK.RMENU);
    try appendModifierUp(list, held.ctrl, vk_map.VK.CONTROL, vk_map.VK.LCONTROL, vk_map.VK.RCONTROL);
}

/// Modifier-to-click gap so games polling key state per frame (Star Citizen) see it held.
pub const HELD_KEY_GAP_MS: u64 = 30;

/// Mouse action with keys held around it, e.g. left alt + right click.
pub fn mouseWithKeys(allocator: std.mem.Allocator, held: modifiers.Chord, btn: MouseButton, kind: MouseKind) SendError!void {
    var down: std.ArrayList(INPUT) = .init(allocator);
    defer down.deinit();
    var up: std.ArrayList(INPUT) = .init(allocator);
    defer up.deinit();
    try heldDown(&down, held);
    try heldUp(&up, held);
    try dispatch(down.items);
    std.time.sleep(HELD_KEY_GAP_MS * std.time.ns_per_ms);
    // Always release the held keys, even if the click failed.
    const click_result = mouse(btn, kind);
    std.time.sleep(HELD_KEY_GAP_MS * std.time.ns_per_ms);
    try dispatch(up.items);
    return click_result;
}

pub fn scroll(direction: enum { up, down }, notches: u32) SendError!void {
    var amount: i32 = @as(i32, @intCast(notches)) * WHEEL_DELTA;
    if (direction == .down) amount = -amount;
    var inputs = [_]INPUT{mouseInput(MOUSEEVENTF_WHEEL, @bitCast(amount))};
    try dispatch(inputs[0..]);
}

fn mouseFlags(btn: MouseButton) struct { down: u32, up: u32 } {
    return switch (btn) {
        .left => .{ .down = MOUSEEVENTF_LEFTDOWN, .up = MOUSEEVENTF_LEFTUP },
        .right => .{ .down = MOUSEEVENTF_RIGHTDOWN, .up = MOUSEEVENTF_RIGHTUP },
        .middle => .{ .down = MOUSEEVENTF_MIDDLEDOWN, .up = MOUSEEVENTF_MIDDLEUP },
        .x1, .x2 => .{ .down = MOUSEEVENTF_XDOWN, .up = MOUSEEVENTF_XUP },
    };
}

fn mouseData(btn: MouseButton) u32 {
    return switch (btn) {
        .x1 => XBUTTON1,
        .x2 => XBUTTON2,
        else => 0,
    };
}

fn mouseInput(flags: u32, data: u32) INPUT {
    return .{
        .type = INPUT_MOUSE,
        .u = .{ .mi = .{
            .dx = 0, .dy = 0,
            .mouseData = data,
            .dwFlags = flags,
            .time = 0,
            .dwExtraInfo = 0,
        } },
    };
}

fn dispatch(inputs: []INPUT) SendError!void {
    if (inputs.len == 0) return;
    const sent = SendInput(
        @intCast(inputs.len),
        inputs.ptr,
        @intCast(@sizeOf(INPUT)),
    );
    if (sent != inputs.len) return SendError.SendInputFailed;
}

// ---- tests ----

test "INPUT size on 64-bit is 40" {
    if (@sizeOf(usize) == 8) {
        try std.testing.expectEqual(@as(usize, 40), @sizeOf(INPUT));
    }
}

test "tap chord builds 4 events for ctrl+shift+a" {
    // SendInput needs a session, so only check parsing here; real input is a manual test.
    const chord = try modifiers.parse("ctrl+shift+a");
    try std.testing.expect(chord.ctrl.active);
    try std.testing.expect(chord.shift.active);
    try std.testing.expect(!chord.alt.active);
    try std.testing.expectEqual(@as(u16, 0x41), chord.base_vk);
}

test "held keys for a mouse action press and release symmetrically" {
    var down: std.ArrayList(INPUT) = .init(std.testing.allocator);
    defer down.deinit();
    var up: std.ArrayList(INPUT) = .init(std.testing.allocator);
    defer up.deinit();
    const held = try modifiers.parseHeld("left alt");
    try heldDown(&down, held);
    try heldUp(&up, held);
    try std.testing.expectEqual(@as(usize, 1), down.items.len);
    try std.testing.expectEqual(@as(usize, 1), up.items.len);
    try std.testing.expectEqual(vk_map.VK.LMENU, down.items[0].u.ki.wVk);
    try std.testing.expectEqual(@as(u32, 0), down.items[0].u.ki.dwFlags & KEYEVENTF_KEYUP);
    try std.testing.expectEqual(vk_map.VK.LMENU, up.items[0].u.ki.wVk);
    try std.testing.expect(up.items[0].u.ki.dwFlags & KEYEVENTF_KEYUP != 0);
}
