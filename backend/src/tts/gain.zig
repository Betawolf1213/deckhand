const std = @import("std");

// Normalise TTS peak to near full scale, apply user volume, soft-limit boosts instead of clipping.

pub const TARGET_PEAK: f32 = 0.89; // ~ -1 dBFS
pub const MAX_VOLUME_PCT: u32 = 300;
// Limiter knee sits at the target, so 0..100% is untouched; only boosts are limited.
const KNEE: f32 = 0.9;

pub fn applyVolume(samples: []i16, volume_pct: u32) void {
    const peak = peakOf(samples);
    if (peak == 0) return;
    const vol: f32 = @as(f32, @floatFromInt(@min(volume_pct, MAX_VOLUME_PCT))) / 100.0;
    const gain: f32 = (TARGET_PEAK / (@as(f32, @floatFromInt(peak)) / 32767.0)) * vol;
    for (samples) |*s| {
        const x = (@as(f32, @floatFromInt(s.*)) / 32767.0) * gain;
        s.* = @intFromFloat(@round(std.math.clamp(softLimit(x), -1.0, 1.0) * 32767.0));
    }
}

pub fn softLimit(x: f32) f32 {
    const a = @abs(x);
    if (a <= KNEE) return x;
    const room = 1.0 - KNEE;
    const y = KNEE + room * std.math.tanh((a - KNEE) / room);
    return if (x < 0) -y else y;
}

pub fn buildWav(allocator: std.mem.Allocator, samples: []const i16, sample_rate: u32) ![]u8 {
    const data_len: u32 = @intCast(samples.len * 2);
    const out = try allocator.alloc(u8, 44 + data_len);
    @memcpy(out[0..4], "RIFF");
    std.mem.writeInt(u32, out[4..8], 36 + data_len, .little);
    @memcpy(out[8..12], "WAVE");
    @memcpy(out[12..16], "fmt ");
    std.mem.writeInt(u32, out[16..20], 16, .little); // fmt chunk size
    std.mem.writeInt(u16, out[20..22], 1, .little); // PCM
    std.mem.writeInt(u16, out[22..24], 1, .little); // mono
    std.mem.writeInt(u32, out[24..28], sample_rate, .little);
    std.mem.writeInt(u32, out[28..32], sample_rate * 2, .little); // byte rate
    std.mem.writeInt(u16, out[32..34], 2, .little); // block align
    std.mem.writeInt(u16, out[34..36], 16, .little); // bits
    @memcpy(out[36..40], "data");
    std.mem.writeInt(u32, out[40..44], data_len, .little);
    for (samples, 0..) |s, i| std.mem.writeInt(i16, out[44 + i * 2 ..][0..2], s, .little);
    return out;
}

/// Returns the PCM payload if `bytes` is a RIFF/WAVE file, otherwise `bytes`.
pub fn pcmPayload(bytes: []const u8) []const u8 {
    if (bytes.len < 12 or !std.mem.eql(u8, bytes[0..4], "RIFF") or !std.mem.eql(u8, bytes[8..12], "WAVE")) return bytes;
    var off: usize = 12;
    while (off + 8 <= bytes.len) {
        const size = std.mem.readInt(u32, bytes[off + 4 ..][0..4], .little);
        const body = off + 8;
        if (std.mem.eql(u8, bytes[off..][0..4], "data")) return bytes[body..@min(bytes.len, body + size)];
        off = body + size + (size & 1);
    }
    return bytes[0..0];
}

fn peakOf(samples: []const i16) i32 {
    var p: i32 = 0;
    for (samples) |s| p = @max(p, @as(i32, if (s < 0) -@as(i32, s) else s));
    return p;
}

// ---- tests ----

test "100% volume normalises quiet speech up to the target peak" {
    var s = [_]i16{ 0, 3000, -6000, 2000 }; // peak ~ -15 dBFS
    applyVolume(&s, 100);
    const want: i32 = @intFromFloat(TARGET_PEAK * 32767.0);
    try std.testing.expect(@abs(peakOf(&s) - want) <= 2);
    try std.testing.expect(s[2] < 0); // polarity kept
}

test "50% volume is half of the normalised level" {
    var s = [_]i16{ 0, 3000, -6000, 2000 };
    applyVolume(&s, 50);
    const want: i32 = @intFromFloat(TARGET_PEAK * 32767.0 * 0.5);
    try std.testing.expect(@abs(peakOf(&s) - want) <= 2);
}

test "boost above 100% is louder but never clips" {
    var a = [_]i16{ 0, 1000, -6000, 3000, 500 };
    var b = a;
    var c = a;
    applyVolume(&a, 100);
    applyVolume(&b, 200);
    applyVolume(&c, MAX_VOLUME_PCT);
    try std.testing.expectEqual(@as(u32, 300), MAX_VOLUME_PCT);
    try std.testing.expect(peakOf(&b) <= 32767);
    try std.testing.expect(peakOf(&c) <= 32767);
    // Quieter samples gain noticeably more at 200%, and more again at 300%.
    try std.testing.expect(@abs(@as(i32, b[1])) > @abs(@as(i32, a[1])) * 3 / 2);
    try std.testing.expect(@abs(@as(i32, c[1])) > @abs(@as(i32, b[1])));
}

test "silence stays silent and 0% mutes" {
    var z = [_]i16{ 0, 0, 0 };
    applyVolume(&z, 150);
    try std.testing.expectEqualSlices(i16, &.{ 0, 0, 0 }, &z);
    var m = [_]i16{ 100, -200, 300 };
    applyVolume(&m, 0);
    try std.testing.expectEqualSlices(i16, &.{ 0, 0, 0 }, &m);
}

test "soft limiter is identity below the knee and bounded above it" {
    try std.testing.expectApproxEqAbs(@as(f32, 0.5), softLimit(0.5), 1e-6);
    try std.testing.expectApproxEqAbs(@as(f32, -0.7), softLimit(-0.7), 1e-6);
    try std.testing.expect(softLimit(5.0) <= 1.0);
    try std.testing.expect(softLimit(-5.0) >= -1.0);
    try std.testing.expect(softLimit(1.2) > softLimit(1.0)); // monotonic
}

test "buildWav writes a playable 16-bit mono RIFF header" {
    const s = [_]i16{ 1, -1, 2 };
    const wav = try buildWav(std.testing.allocator, &s, 22050);
    defer std.testing.allocator.free(wav);
    try std.testing.expectEqual(@as(usize, 44 + 6), wav.len);
    try std.testing.expectEqualStrings("RIFF", wav[0..4]);
    try std.testing.expectEqualStrings("WAVE", wav[8..12]);
    try std.testing.expectEqual(@as(u32, 22050), std.mem.readInt(u32, wav[24..28], .little));
    try std.testing.expectEqual(@as(u16, 16), std.mem.readInt(u16, wav[34..36], .little));
    try std.testing.expectEqual(@as(u32, 6), std.mem.readInt(u32, wav[40..44], .little));
    try std.testing.expectEqualSlices(u8, pcmPayload(wav), wav[44..]);
}
