const std = @import("std");
const config = @import("config.zig");
const modifiers = @import("input/modifiers.zig");
const sendinput = @import("input/sendinput.zig");

// Performs keyboard/mouse/scroll actions; `system` actions belong to the listener and are rejected.

pub const Error = error{ UnknownMouseButton, UnknownMouseKind, SystemActionNotInput } ||
    sendinput.SendError;

pub fn parseMouseButton(s: []const u8) ?sendinput.MouseButton {
    return std.meta.stringToEnum(sendinput.MouseButton, s);
}

pub fn parseMouseKind(s: []const u8) ?sendinput.MouseKind {
    return std.meta.stringToEnum(sendinput.MouseKind, s);
}

pub fn perform(allocator: std.mem.Allocator, action: config.Action) Error!void {
    switch (action) {
        .tap => |a| try sendinput.tap(allocator, try modifiers.parse(a.keys)),
        .hold => |a| try sendinput.hold(allocator, try modifiers.parse(a.keys), a.duration_ms),
        .press => |a| try sendinput.pressChord(allocator, try modifiers.parse(a.keys)),
        .release => |a| try sendinput.releaseChord(allocator, try modifiers.parse(a.keys)),
        .mouse => |a| {
            const btn = parseMouseButton(a.button) orelse return error.UnknownMouseButton;
            const kind = parseMouseKind(a.kind) orelse return error.UnknownMouseKind;
            if (a.keys) |k| {
                try sendinput.mouseWithKeys(allocator, try modifiers.parseHeld(k), btn, kind);
            } else {
                try sendinput.mouse(btn, kind);
            }
        },
        .scroll => |a| try sendinput.scroll(if (std.mem.eql(u8, a.direction, "up")) .up else .down, @intCast(a.amount)),
        .system => return error.SystemActionNotInput,
    }
}

test "mouse button and kind names" {
    try std.testing.expectEqual(sendinput.MouseButton.right, parseMouseButton("right").?);
    try std.testing.expectEqual(sendinput.MouseButton.x2, parseMouseButton("x2").?);
    try std.testing.expect(parseMouseButton("wheel") == null);
    try std.testing.expectEqual(sendinput.MouseKind.double, parseMouseKind("double").?);
    try std.testing.expect(parseMouseKind("triple") == null);
}

test "system actions are not input" {
    try std.testing.expectError(error.SystemActionNotInput, perform(std.testing.allocator, .{ .system = .{ .op = .stop_speaking } }));
}
