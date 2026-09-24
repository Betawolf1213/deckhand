const std = @import("std");

// Windows virtual-key codes (winuser.h); names match the Python upstream `_VK_NAMES` keybinds.

pub const VK = struct {
    pub const BACK: u16 = 0x08;
    pub const TAB: u16 = 0x09;
    pub const CLEAR: u16 = 0x0C;
    pub const RETURN: u16 = 0x0D;
    pub const SHIFT: u16 = 0x10;
    pub const CONTROL: u16 = 0x11;
    pub const MENU: u16 = 0x12; // Alt
    pub const PAUSE: u16 = 0x13;
    pub const CAPITAL: u16 = 0x14;
    pub const ESCAPE: u16 = 0x1B;
    pub const SPACE: u16 = 0x20;
    pub const PRIOR: u16 = 0x21;
    pub const NEXT: u16 = 0x22;
    pub const END: u16 = 0x23;
    pub const HOME: u16 = 0x24;
    pub const LEFT: u16 = 0x25;
    pub const UP: u16 = 0x26;
    pub const RIGHT: u16 = 0x27;
    pub const DOWN: u16 = 0x28;
    pub const SNAPSHOT: u16 = 0x2C;
    pub const INSERT: u16 = 0x2D;
    pub const DELETE: u16 = 0x2E;
    pub const LWIN: u16 = 0x5B;
    pub const RWIN: u16 = 0x5C;
    pub const NUMPAD0: u16 = 0x60;
    pub const MULTIPLY: u16 = 0x6A;
    pub const ADD: u16 = 0x6B;
    pub const SEPARATOR: u16 = 0x6C;
    pub const SUBTRACT: u16 = 0x6D;
    pub const DECIMAL: u16 = 0x6E;
    pub const DIVIDE: u16 = 0x6F;
    pub const LSHIFT: u16 = 0xA0;
    pub const RSHIFT: u16 = 0xA1;
    pub const LCONTROL: u16 = 0xA2;
    pub const RCONTROL: u16 = 0xA3;
    pub const LMENU: u16 = 0xA4;
    pub const RMENU: u16 = 0xA5;
    pub const OEM_1: u16 = 0xBA; // ;:
    pub const OEM_PLUS: u16 = 0xBB;
    pub const OEM_COMMA: u16 = 0xBC;
    pub const OEM_MINUS: u16 = 0xBD;
    pub const OEM_PERIOD: u16 = 0xBE;
    pub const OEM_2: u16 = 0xBF; // /?
    pub const OEM_3: u16 = 0xC0; // `~
    pub const OEM_4: u16 = 0xDB; // [{
    pub const OEM_5: u16 = 0xDC; // \|
    pub const OEM_6: u16 = 0xDD; // ]}
    pub const OEM_7: u16 = 0xDE; // '"
};

pub const LookupError = error{UnknownKey};

// Case-insensitive key name (letters, digits, F-keys, specials, punctuation) -> VK or UnknownKey.
pub fn lookup(name: []const u8) LookupError!u16 {
    var buf: [32]u8 = undefined;
    if (name.len == 0 or name.len > buf.len) return LookupError.UnknownKey;
    const lower = std.ascii.lowerString(&buf, name);

    // Single alphabetic character A–Z.
    if (lower.len == 1 and lower[0] >= 'a' and lower[0] <= 'z') {
        return @as(u16, @intCast(0x41 + (lower[0] - 'a')));
    }
    // Single digit 0–9.
    if (lower.len == 1 and lower[0] >= '0' and lower[0] <= '9') {
        return @as(u16, @intCast(0x30 + (lower[0] - '0')));
    }
    // Function keys f1..f24.
    if ((lower.len == 2 or lower.len == 3) and lower[0] == 'f') {
        const n = std.fmt.parseInt(u8, lower[1..], 10) catch return LookupError.UnknownKey;
        if (n >= 1 and n <= 24) return @as(u16, 0x6F) + @as(u16, n);
    }
    // Numpad NN
    if (std.mem.startsWith(u8, lower, "numpad") and lower.len == 7) {
        const d = lower[6];
        if (d >= '0' and d <= '9') return VK.NUMPAD0 + @as(u16, d - '0');
    }
    if (std.mem.startsWith(u8, lower, "kp_")) {
        const rest = lower[3..];
        if (std.mem.eql(u8, rest, "multiply")) return VK.MULTIPLY;
        if (std.mem.eql(u8, rest, "add")) return VK.ADD;
        if (std.mem.eql(u8, rest, "subtract")) return VK.SUBTRACT;
        if (std.mem.eql(u8, rest, "divide")) return VK.DIVIDE;
        if (std.mem.eql(u8, rest, "decimal")) return VK.DECIMAL;
    }

    const named = [_]struct { []const u8, u16 }{
        .{ "backspace", VK.BACK },       .{ "back", VK.BACK },
        .{ "tab", VK.TAB },
        .{ "clear", VK.CLEAR },
        .{ "enter", VK.RETURN },         .{ "return", VK.RETURN },
        .{ "shift", VK.SHIFT },          .{ "ctrl", VK.CONTROL },
        .{ "control", VK.CONTROL },      .{ "alt", VK.MENU },
        .{ "pause", VK.PAUSE },          .{ "capslock", VK.CAPITAL },
        .{ "escape", VK.ESCAPE },        .{ "esc", VK.ESCAPE },
        .{ "space", VK.SPACE },          .{ "spacebar", VK.SPACE },
        .{ "pageup", VK.PRIOR },         .{ "page up", VK.PRIOR },
        .{ "pagedown", VK.NEXT },        .{ "page down", VK.NEXT },
        .{ "end", VK.END },              .{ "home", VK.HOME },
        .{ "left", VK.LEFT },            .{ "up", VK.UP },
        .{ "right", VK.RIGHT },          .{ "down", VK.DOWN },
        .{ "printscreen", VK.SNAPSHOT }, .{ "print_screen", VK.SNAPSHOT },
        .{ "insert", VK.INSERT },        .{ "delete", VK.DELETE },
        .{ "del", VK.DELETE },
        .{ "lwin", VK.LWIN },            .{ "rwin", VK.RWIN },
        .{ "windows", VK.LWIN },         .{ "win", VK.LWIN },
        .{ "left shift", VK.LSHIFT },    .{ "right shift", VK.RSHIFT },
        .{ "left ctrl", VK.LCONTROL },   .{ "right ctrl", VK.RCONTROL },
        .{ "left control", VK.LCONTROL }, .{ "right control", VK.RCONTROL },
        .{ "left alt", VK.LMENU },       .{ "right alt", VK.RMENU },
        .{ "semicolon", VK.OEM_1 },      .{ ";", VK.OEM_1 },
        .{ "plus", VK.OEM_PLUS },        .{ "=", VK.OEM_PLUS },
        .{ "comma", VK.OEM_COMMA },      .{ ",", VK.OEM_COMMA },
        .{ "minus", VK.OEM_MINUS },      .{ "-", VK.OEM_MINUS },
        .{ "period", VK.OEM_PERIOD },    .{ ".", VK.OEM_PERIOD },
        .{ "slash", VK.OEM_2 },          .{ "/", VK.OEM_2 },
        .{ "backtick", VK.OEM_3 },       .{ "`", VK.OEM_3 },      .{ "grave", VK.OEM_3 },
        .{ "lbracket", VK.OEM_4 },       .{ "[", VK.OEM_4 },
        .{ "backslash", VK.OEM_5 },      .{ "\\", VK.OEM_5 },
        .{ "rbracket", VK.OEM_6 },       .{ "]", VK.OEM_6 },
        .{ "apostrophe", VK.OEM_7 },     .{ "'", VK.OEM_7 },      .{ "quote", VK.OEM_7 },
    };
    for (named) |entry| {
        if (std.mem.eql(u8, entry[0], lower)) return entry[1];
    }
    return LookupError.UnknownKey;
}

test "letters and digits" {
    try std.testing.expectEqual(@as(u16, 0x41), try lookup("A"));
    try std.testing.expectEqual(@as(u16, 0x41), try lookup("a"));
    try std.testing.expectEqual(@as(u16, 0x5A), try lookup("z"));
    try std.testing.expectEqual(@as(u16, 0x30), try lookup("0"));
    try std.testing.expectEqual(@as(u16, 0x39), try lookup("9"));
}

test "function keys" {
    try std.testing.expectEqual(@as(u16, 0x70), try lookup("f1"));
    try std.testing.expectEqual(@as(u16, 0x87), try lookup("f24"));
    try std.testing.expectError(LookupError.UnknownKey, lookup("f0"));
    try std.testing.expectError(LookupError.UnknownKey, lookup("f25"));
}

test "named" {
    try std.testing.expectEqual(VK.ESCAPE, try lookup("escape"));
    try std.testing.expectEqual(VK.ESCAPE, try lookup("ESC"));
    try std.testing.expectEqual(VK.SPACE, try lookup("Space"));
    try std.testing.expectEqual(VK.LSHIFT, try lookup("left shift"));
    try std.testing.expectEqual(VK.OEM_5, try lookup("backslash"));
    try std.testing.expectEqual(VK.SNAPSHOT, try lookup("print_screen"));
    try std.testing.expectEqual(VK.NUMPAD0 + 5, try lookup("numpad5"));
}

test "unknown" {
    try std.testing.expectError(LookupError.UnknownKey, lookup("floop"));
    try std.testing.expectError(LookupError.UnknownKey, lookup(""));
}
