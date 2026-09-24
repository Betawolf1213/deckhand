const std = @import("std");

// Voice-only per-id cooldown (WINDOW_MS, docs/IPC.md rule 4); keys copied so reloads are safe.

pub const WINDOW_MS: i64 = 1500;

pub const Cooldown = struct {
    allocator: std.mem.Allocator,
    window_ms: i64 = WINDOW_MS,
    last_fired: std.StringHashMapUnmanaged(i64) = .{},

    pub fn init(allocator: std.mem.Allocator) Cooldown {
        return .{ .allocator = allocator };
    }

    pub fn deinit(self: *Cooldown) void {
        var it = self.last_fired.keyIterator();
        while (it.next()) |k| self.allocator.free(k.*);
        self.last_fired.deinit(self.allocator);
    }

    /// True if `id` may fire at `now_ms` (records it); a suppressed try does not extend the window.
    pub fn tryFire(self: *Cooldown, id: []const u8, now_ms: i64) bool {
        if (self.last_fired.getPtr(id)) |last| {
            if (now_ms - last.* < self.window_ms) return false;
            last.* = now_ms;
            return true;
        }
        // Out of memory only loses the cooldown, never the command.
        const key = self.allocator.dupe(u8, id) catch return true;
        self.last_fired.put(self.allocator, key, now_ms) catch {
            self.allocator.free(key);
        };
        return true;
    }
};

test "first firing is allowed" {
    var c = Cooldown.init(std.testing.allocator);
    defer c.deinit();
    try std.testing.expect(c.tryFire("landing_gear", 10_000));
}

test "same id within the window is suppressed, allowed at the boundary" {
    var c = Cooldown.init(std.testing.allocator);
    defer c.deinit();
    try std.testing.expect(c.tryFire("landing_gear", 10_000));
    try std.testing.expect(!c.tryFire("landing_gear", 10_001));
    try std.testing.expect(!c.tryFire("landing_gear", 10_000 + WINDOW_MS - 1));
    try std.testing.expect(c.tryFire("landing_gear", 10_000 + WINDOW_MS));
}

test "suppressed attempts do not extend the window" {
    var c = Cooldown.init(std.testing.allocator);
    defer c.deinit();
    try std.testing.expect(c.tryFire("boost", 0));
    try std.testing.expect(!c.tryFire("boost", 1000));
    try std.testing.expect(c.tryFire("boost", 1500));
}

test "different ids are independent" {
    var c = Cooldown.init(std.testing.allocator);
    defer c.deinit();
    try std.testing.expect(c.tryFire("a", 0));
    try std.testing.expect(c.tryFire("b", 10));
    try std.testing.expect(!c.tryFire("a", 20));
    try std.testing.expect(!c.tryFire("b", 30));
}

test "keys are copied (caller buffer may change)" {
    var c = Cooldown.init(std.testing.allocator);
    defer c.deinit();
    var buf = "gear".*;
    try std.testing.expect(c.tryFire(&buf, 0));
    buf[0] = 'b';
    try std.testing.expect(!c.tryFire("gear", 100));
}
