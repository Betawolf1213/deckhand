const std = @import("std");
const vk_map = @import("vk_map.zig");

pub const Side = enum { unspecified, left, right };

pub const Modifier = struct {
    active: bool = false,
    side: Side = .unspecified,
};

pub const Chord = struct {
    ctrl: Modifier = .{},
    alt: Modifier = .{},
    shift: Modifier = .{},
    base_vk: u16,
};

pub const ParseError = error{
    Empty,
    NoBaseKey,
    MultipleBaseKeys,
    UnknownKey,
} || std.mem.Allocator.Error;

// Parses "left ctrl+f8", "shift+alt+n", "n": '+'-separated, optional sides, exactly one base key.
pub fn parse(input: []const u8) ParseError!Chord {
    return parseImpl(input, true);
}

/// Like parse() for keys held during a click ("left alt"); base key optional (base_vk = 0).
pub fn parseHeld(input: []const u8) ParseError!Chord {
    return parseImpl(input, false);
}

fn parseImpl(input: []const u8, require_base: bool) ParseError!Chord {
    if (trim(input).len == 0) return ParseError.Empty;

    var chord: Chord = .{ .base_vk = 0 };
    var found_base = false;

    var it = std.mem.splitScalar(u8, input, '+');
    while (it.next()) |raw| {
        const tok = trim(raw);
        if (tok.len == 0) continue;

        if (asModifier(tok)) |mod_result| {
            switch (mod_result.which) {
                .ctrl => chord.ctrl = .{ .active = true, .side = mod_result.side },
                .alt => chord.alt = .{ .active = true, .side = mod_result.side },
                .shift => chord.shift = .{ .active = true, .side = mod_result.side },
            }
            continue;
        }

        const vk = vk_map.lookup(tok) catch return ParseError.UnknownKey;
        if (found_base) return ParseError.MultipleBaseKeys;
        chord.base_vk = vk;
        found_base = true;
    }

    if (!found_base and require_base) return ParseError.NoBaseKey;
    return chord;
}

const Which = enum { ctrl, alt, shift };
const ModResult = struct { which: Which, side: Side };

fn asModifier(tok: []const u8) ?ModResult {
    var buf: [24]u8 = undefined;
    if (tok.len > buf.len) return null;
    const lower = std.ascii.lowerString(&buf, tok);

    if (eq(lower, "ctrl") or eq(lower, "control")) return .{ .which = .ctrl, .side = .unspecified };
    if (eq(lower, "alt") or eq(lower, "menu")) return .{ .which = .alt, .side = .unspecified };
    if (eq(lower, "shift")) return .{ .which = .shift, .side = .unspecified };

    if (eq(lower, "left ctrl") or eq(lower, "left control") or eq(lower, "lctrl")) return .{ .which = .ctrl, .side = .left };
    if (eq(lower, "right ctrl") or eq(lower, "right control") or eq(lower, "rctrl")) return .{ .which = .ctrl, .side = .right };
    if (eq(lower, "left alt") or eq(lower, "lalt")) return .{ .which = .alt, .side = .left };
    if (eq(lower, "right alt") or eq(lower, "ralt")) return .{ .which = .alt, .side = .right };
    if (eq(lower, "left shift") or eq(lower, "lshift")) return .{ .which = .shift, .side = .left };
    if (eq(lower, "right shift") or eq(lower, "rshift")) return .{ .which = .shift, .side = .right };
    return null;
}

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn trim(s: []const u8) []const u8 {
    return std.mem.trim(u8, s, " \t\r\n");
}

test "plain base key" {
    const c = try parse("n");
    try std.testing.expectEqual(@as(u16, 0x4E), c.base_vk);
    try std.testing.expect(!c.ctrl.active and !c.alt.active and !c.shift.active);
}

test "sided modifier + base" {
    const c = try parse("left ctrl+f8");
    try std.testing.expectEqual(vk_map.VK.LCONTROL, blk: {
        try std.testing.expect(c.ctrl.active);
        try std.testing.expectEqual(Side.left, c.ctrl.side);
        break :blk vk_map.VK.LCONTROL;
    });
    try std.testing.expectEqual(@as(u16, 0x77), c.base_vk); // F8
}

test "multiple modifiers" {
    const c = try parse("shift+alt+n");
    try std.testing.expect(c.shift.active and c.alt.active and !c.ctrl.active);
    try std.testing.expectEqual(Side.unspecified, c.shift.side);
    try std.testing.expectEqual(@as(u16, 0x4E), c.base_vk);
}

test "whitespace tolerated" {
    const c = try parse(" ctrl + shift + a ");
    try std.testing.expect(c.ctrl.active and c.shift.active);
    try std.testing.expectEqual(@as(u16, 0x41), c.base_vk);
}

test "rejects missing base" {
    try std.testing.expectError(ParseError.NoBaseKey, parse("ctrl+shift"));
}

test "rejects two base keys" {
    try std.testing.expectError(ParseError.MultipleBaseKeys, parse("a+b"));
}

test "rejects empty" {
    try std.testing.expectError(ParseError.Empty, parse(""));
}

test "parseHeld accepts modifier-only strings" {
    const c = try parseHeld("left alt");
    try std.testing.expect(c.alt.active);
    try std.testing.expectEqual(Side.left, c.alt.side);
    try std.testing.expectEqual(@as(u16, 0), c.base_vk);
    const c2 = try parseHeld("ctrl+shift");
    try std.testing.expect(c2.ctrl.active and c2.shift.active);
    const c3 = try parseHeld("left alt+x");
    try std.testing.expectEqual(@as(u16, 0x58), c3.base_vk);
    try std.testing.expectError(ParseError.Empty, parseHeld("  "));
    try std.testing.expectError(ParseError.UnknownKey, parseHeld("left alt+bogus"));
}
