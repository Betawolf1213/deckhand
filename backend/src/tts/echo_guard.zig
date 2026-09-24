const std = @import("std");

// Ignore the mic while our TTS is queued/playing (+TAIL_MS latency/echo) so acks can't re-fire.
pub const EchoGuard = struct {
    until_ms: std.atomic.Value(i64) = std.atomic.Value(i64).init(0),

    pub const TAIL_MS: i64 = 500;
    pub const PENDING_MS: i64 = 5000;

    pub fn holdPending(self: *EchoGuard, now_ms: i64) void {
        // Never shortens: an ack queued during playback keeps the mic muted.
        _ = self.until_ms.fetchMax(now_ms + PENDING_MS, .acq_rel);
    }

    pub fn playing(self: *EchoGuard, now_ms: i64, duration_ms: i64) void {
        // Duration is now known, so replace the provisional pending hold.
        self.until_ms.store(now_ms + duration_ms + TAIL_MS, .release);
    }

    pub fn release(self: *EchoGuard, now_ms: i64) void {
        self.until_ms.store(now_ms + TAIL_MS, .release);
    }

    pub fn active(self: *const EchoGuard, now_ms: i64) bool {
        return now_ms < self.until_ms.load(.acquire);
    }
};

test "guard is off until something is spoken" {
    var g = EchoGuard{};
    try std.testing.expect(!g.active(1000));
}

test "queued speech mutes the mic immediately" {
    var g = EchoGuard{};
    g.holdPending(1000);
    try std.testing.expect(g.active(1000));
    try std.testing.expect(g.active(1000 + EchoGuard.PENDING_MS - 1));
}

test "playback mutes for its duration plus the tail, then unmutes" {
    var g = EchoGuard{};
    g.holdPending(1000);
    g.playing(1200, 600); // audio ends at 1800, tail to 2300
    try std.testing.expect(g.active(1799));
    try std.testing.expect(g.active(1800 + EchoGuard.TAIL_MS - 1));
    try std.testing.expect(!g.active(1800 + EchoGuard.TAIL_MS));
}

test "failed speech releases after only the tail" {
    var g = EchoGuard{};
    g.holdPending(1000);
    g.release(1100);
    try std.testing.expect(g.active(1100 + EchoGuard.TAIL_MS - 1));
    try std.testing.expect(!g.active(1100 + EchoGuard.TAIL_MS));
}

test "a new queued ack during playback keeps the mic muted" {
    var g = EchoGuard{};
    g.playing(1000, 300); // until 1800
    g.holdPending(1500); // next ack queued before the first finished
    try std.testing.expect(g.active(1800 + 100));
}
