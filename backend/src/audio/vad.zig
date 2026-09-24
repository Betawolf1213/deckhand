const std = @import("std");

// Energy (RMS) VAD for 16 kHz mono i16; onset/tail timed in ms so WASAPI block sizes don't matter.

pub const Config = struct {
    sample_rate: u32 = 16_000,
    // RMS threshold on normalised [-1, 1] amplitude (0.01 ≈ -40 dBFS); raise in noisy rooms.
    energy_threshold: f32 = 0.008,
    // Continuous above-threshold audio needed to start an utterance.
    onset_ms: u32 = 60,
    // Silence duration after speech that ends the utterance.
    tail_silence_ms: u32 = 450,
    // Hard cap so a stuck-open VAD (noise, music) flushes quickly.
    max_utterance_ms: u32 = 4_000,
    // Startup period used only to learn the room's noise floor.
    calibration_ms: u32 = 300,
    // Speech must be this many times louder (RMS) than the learned noise floor.
    noise_ratio: f32 = 3.0,
};

pub const Event = union(enum) {
    none,
    speech_start,
    utterance: []const i16,
};

pub const Vad = struct {
    cfg: Config,
    state: State = .idle,
    buffer: std.ArrayList(i16),
    above_ms_streak: u32 = 0,
    silence_ms: u32 = 0,
    // Learned background RMS. Kept across reset() so it survives utterances.
    noise_floor: f32 = 0,
    calibrated_ms: u32 = 0,

    const State = enum { idle, speaking };

    pub fn init(allocator: std.mem.Allocator, cfg: Config) Vad {
        return .{
            .cfg = cfg,
            .buffer = std.ArrayList(i16).init(allocator),
        };
    }

    pub fn deinit(self: *Vad) void {
        self.buffer.deinit();
    }

    /// Forget the learned noise floor (e.g. after switching microphones).
    pub fn recalibrate(self: *Vad) void {
        self.reset();
        self.noise_floor = 0;
        self.calibrated_ms = 0;
    }

    pub fn reset(self: *Vad) void {
        self.state = .idle;
        self.buffer.clearRetainingCapacity();
        self.above_ms_streak = 0;
        self.silence_ms = 0;
    }

    // Feed a block; the returned `utterance` borrows the internal buffer until the next feed().
    pub fn feed(self: *Vad, block: []const i16) !Event {
        if (block.len == 0) return .none;
        const block_ms: u32 = @intCast((block.len * 1000) / self.cfg.sample_rate);
        const energy = rmsNormalised(block);

        // Learn the room's noise floor before listening for speech.
        if (self.calibrated_ms < self.cfg.calibration_ms) {
            self.calibrated_ms += block_ms;
            self.noise_floor = if (self.noise_floor == 0) energy else self.noise_floor * 0.8 + energy * 0.2;
            return .none;
        }

        // Speech must clear both the absolute minimum and the noise floor by a margin.
        const threshold = @max(self.cfg.energy_threshold, self.noise_floor * self.cfg.noise_ratio);
        const above = energy > threshold;

        // Track the noise floor while idle and quiet: fall fast, rise slowly.
        if (self.state == .idle and !above) {
            const alpha: f32 = if (energy < self.noise_floor) 0.2 else 0.02;
            self.noise_floor = self.noise_floor * (1.0 - alpha) + energy * alpha;
        }

        switch (self.state) {
            .idle => {
                if (above) {
                    self.above_ms_streak += block_ms;
                    if (self.above_ms_streak >= self.cfg.onset_ms) {
                        self.state = .speaking;
                        self.above_ms_streak = 0;
                        self.silence_ms = 0;
                        try self.buffer.appendSlice(block);
                        return .speech_start;
                    }
                } else {
                    self.above_ms_streak = 0;
                }
                return .none;
            },
            .speaking => {
                try self.buffer.appendSlice(block);
                if (above) {
                    self.silence_ms = 0;
                } else {
                    self.silence_ms += block_ms;
                }

                const utterance_ms: u32 = @intCast((self.buffer.items.len * 1000) / self.cfg.sample_rate);
                const ended_silence = self.silence_ms >= self.cfg.tail_silence_ms;
                const ended_cap = utterance_ms >= self.cfg.max_utterance_ms;
                if (ended_silence or ended_cap) {
                    const slice = self.buffer.items;
                    self.state = .idle;
                    self.silence_ms = 0;
                    self.above_ms_streak = 0;
                    return .{ .utterance = slice };
                }
                return .none;
            },
        }
    }
};

pub fn rmsNormalised(samples: []const i16) f32 {
    if (samples.len == 0) return 0;
    var acc: f64 = 0;
    for (samples) |s| {
        const f: f64 = @as(f64, @floatFromInt(s)) / 32768.0;
        acc += f * f;
    }
    const mean = acc / @as(f64, @floatFromInt(samples.len));
    return @floatCast(@sqrt(mean));
}

// ---- tests ----

test "silent block reports low energy" {
    var buf = [_]i16{0} ** 320;
    try std.testing.expect(rmsNormalised(&buf) < 0.001);
}

test "loud block above threshold" {
    var buf: [320]i16 = undefined;
    for (&buf, 0..) |*s, i| {
        const t: f32 = @as(f32, @floatFromInt(i)) / 320.0;
        s.* = @intFromFloat(@sin(t * 100.0) * 16000.0);
    }
    try std.testing.expect(rmsNormalised(&buf) > 0.01);
}

test "vad state machine detects utterance" {
    var vad = Vad.init(std.testing.allocator, .{
        .sample_rate = 16000,
        .energy_threshold = 0.01,
        .onset_ms = 40,
        .tail_silence_ms = 60,
        .calibration_ms = 0,
    });
    defer vad.deinit();

    var silent = [_]i16{0} ** 320; // 20 ms
    var loud: [320]i16 = undefined;
    for (&loud) |*s| s.* = 10_000;

    try std.testing.expectEqual(@as(Event, .none), try vad.feed(&silent));

    _ = try vad.feed(&loud);
    const started = try vad.feed(&loud);
    try std.testing.expect(started == .speech_start);

    _ = try vad.feed(&loud);

    _ = try vad.feed(&silent);
    _ = try vad.feed(&silent);
    const ended = try vad.feed(&silent);
    try std.testing.expect(ended == .utterance);
    try std.testing.expect(ended.utterance.len > 0);
}

fn noiseBlock(rng: std.Random, sigma: f32, out: []i16) void {
    for (out) |*s| s.* = @intFromFloat(std.math.clamp(rng.floatNorm(f32) * sigma * 32768.0, -32767.0, 32767.0));
}

test "steady background noise above the fixed threshold does not trigger speech" {
    // Mirrors a real Focusrite noise floor: RMS ~0.02, well above the 0.008 default.
    var vad = Vad.init(std.testing.allocator, .{});
    defer vad.deinit();
    var prng = std.Random.DefaultPrng.init(42);
    var blk: [160]i16 = undefined; // 10 ms at 16 kHz
    var i: usize = 0;
    while (i < 300) : (i += 1) { // 3 s
        noiseBlock(prng.random(), 0.02, &blk);
        const evt = try vad.feed(&blk);
        try std.testing.expect(evt == .none);
    }
}

test "speech over background noise starts and ends promptly" {
    var vad = Vad.init(std.testing.allocator, .{});
    defer vad.deinit();
    var prng = std.Random.DefaultPrng.init(7);
    var blk: [160]i16 = undefined;
    var started = false;
    var ended_at: ?usize = null;
    var i: usize = 0;
    while (i < 250) : (i += 1) { // 1 s noise, 0.6 s speech, 0.9 s noise
        const speaking = i >= 100 and i < 160;
        noiseBlock(prng.random(), if (speaking) 0.2 else 0.02, &blk);
        switch (try vad.feed(&blk)) {
            .speech_start => started = true,
            .utterance => {
                ended_at = i;
                vad.reset();
            },
            .none => {},
        }
    }
    try std.testing.expect(started);
    // Utterance must end within ~0.7 s of the speech stopping (tail silence is 450 ms).
    try std.testing.expect(ended_at != null);
    try std.testing.expect(ended_at.? >= 160 and ended_at.? < 230);
}

test "continuous speech is cut at the 4 s cap" {
    var vad = Vad.init(std.testing.allocator, .{ .calibration_ms = 0 });
    defer vad.deinit();
    try std.testing.expectEqual(@as(u32, 4_000), vad.cfg.max_utterance_ms);
    var loud: [160]i16 = undefined; // 10 ms
    for (&loud) |*s| s.* = 12_000;
    var i: usize = 0;
    var cut_len: ?usize = null;
    while (i < 600) : (i += 1) { // 6 s of non-stop "speech"
        const evt = try vad.feed(&loud);
        if (evt == .utterance) {
            cut_len = evt.utterance.len;
            break;
        }
    }
    try std.testing.expect(cut_len != null);
    const ms = cut_len.? * 1000 / 16_000;
    try std.testing.expect(ms >= 4_000 and ms < 4_100);
}

test "recalibrate forgets the noise floor" {
    var vad = Vad.init(std.testing.allocator, .{});
    defer vad.deinit();
    var blk = [_]i16{500} ** 160;
    for (0..40) |_| _ = try vad.feed(&blk);
    try std.testing.expect(vad.noise_floor > 0);
    vad.recalibrate();
    try std.testing.expectEqual(@as(f32, 0), vad.noise_floor);
    try std.testing.expectEqual(@as(u32, 0), vad.calibrated_ms);
}
