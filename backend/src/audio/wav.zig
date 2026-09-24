const std = @import("std");

// Minimal 16-bit mono PCM WAV writer for --dump-audio (inspect VAD chunks).

pub const WriteError = error{FileError} || std.fs.File.WriteError || std.fs.File.OpenError;

pub fn writeI16Mono(path: []const u8, samples: []const i16, sample_rate: u32) WriteError!void {
    var file = try std.fs.cwd().createFile(path, .{ .truncate = true });
    defer file.close();

    const data_bytes: u32 = @intCast(samples.len * @sizeOf(i16));
    const fmt_chunk_size: u32 = 16;
    const riff_size: u32 = 4 + (8 + fmt_chunk_size) + (8 + data_bytes);

    var w = file.writer();

    try w.writeAll("RIFF");
    try w.writeInt(u32, riff_size, .little);
    try w.writeAll("WAVE");

    try w.writeAll("fmt ");
    try w.writeInt(u32, fmt_chunk_size, .little);
    try w.writeInt(u16, 1, .little);            // PCM
    try w.writeInt(u16, 1, .little);            // mono
    try w.writeInt(u32, sample_rate, .little);
    try w.writeInt(u32, sample_rate * 2, .little); // avg bytes/sec
    try w.writeInt(u16, 2, .little);            // block align
    try w.writeInt(u16, 16, .little);           // bits/sample

    try w.writeAll("data");
    try w.writeInt(u32, data_bytes, .little);
    try w.writeAll(std.mem.sliceAsBytes(samples));
}

test "writes header + samples of correct size" {
    const tmp = "test_out.wav";
    defer std.fs.cwd().deleteFile(tmp) catch {};

    var samples: [1600]i16 = undefined; // 100 ms @ 16 kHz
    for (&samples, 0..) |*s, i| s.* = @intCast(i % 32000);
    try writeI16Mono(tmp, &samples, 16000);

    const f = try std.fs.cwd().openFile(tmp, .{});
    defer f.close();
    const stat = try f.stat();
    // Header 44 + samples * 2
    try std.testing.expectEqual(@as(u64, 44 + 1600 * 2), stat.size);
}

pub const ReadError = error{ NotWav, UnsupportedWav } || std.mem.Allocator.Error;

pub const Pcm = struct {
    sample_rate: u32,
    samples: []i16, // mono (channels are averaged)

    pub fn deinit(self: *Pcm, a: std.mem.Allocator) void {
        a.free(self.samples);
    }
};

/// Parse a 16-bit PCM RIFF/WAV file image. Multi-channel audio is mixed to mono.
pub fn parseI16(a: std.mem.Allocator, bytes: []const u8) ReadError!Pcm {
    if (bytes.len < 12 or !std.mem.eql(u8, bytes[0..4], "RIFF") or !std.mem.eql(u8, bytes[8..12], "WAVE")) return error.NotWav;
    var pos: usize = 12;
    var channels: u16 = 0;
    var rate: u32 = 0;
    var bits: u16 = 0;
    var fmt_tag: u16 = 0;
    while (pos + 8 <= bytes.len) {
        const id = bytes[pos .. pos + 4];
        const size = std.mem.readInt(u32, bytes[pos + 4 ..][0..4], .little);
        const body_start = pos + 8;
        const body_end = @min(bytes.len, body_start + size);
        const body = bytes[body_start..body_end];
        if (std.mem.eql(u8, id, "fmt ")) {
            if (body.len < 16) return error.NotWav;
            fmt_tag = std.mem.readInt(u16, body[0..2], .little);
            channels = std.mem.readInt(u16, body[2..4], .little);
            rate = std.mem.readInt(u32, body[4..8], .little);
            bits = std.mem.readInt(u16, body[14..16], .little);
        } else if (std.mem.eql(u8, id, "data")) {
            if ((fmt_tag != 1 and fmt_tag != 0xFFFE) or bits != 16 or channels == 0) return error.UnsupportedWav;
            const frames = body.len / (2 * @as(usize, channels));
            const out = try a.alloc(i16, frames);
            for (out, 0..) |*o, f| {
                var acc: i32 = 0;
                for (0..channels) |c| {
                    const off = (f * channels + c) * 2;
                    acc += std.mem.readInt(i16, body[off..][0..2], .little);
                }
                o.* = @intCast(@divTrunc(acc, @as(i32, channels)));
            }
            return .{ .sample_rate = rate, .samples = out };
        }
        pos = body_start + size + (size & 1); // chunks are word-aligned
    }
    return error.NotWav;
}

test "parseI16 round-trips writeI16Mono output" {
    const tmp = "test_roundtrip.wav";
    defer std.fs.cwd().deleteFile(tmp) catch {};
    const src = [_]i16{ 0, 1000, -1000, 32767, -32768 };
    try writeI16Mono(tmp, &src, 16000);
    const bytes = try std.fs.cwd().readFileAlloc(std.testing.allocator, tmp, 1 << 20);
    defer std.testing.allocator.free(bytes);
    var pcm = try parseI16(std.testing.allocator, bytes);
    defer pcm.deinit(std.testing.allocator);
    try std.testing.expectEqual(@as(u32, 16000), pcm.sample_rate);
    try std.testing.expectEqualSlices(i16, &src, pcm.samples);
}

test "parseI16 rejects non-wav" {
    try std.testing.expectError(error.NotWav, parseI16(std.testing.allocator, "hello world, not a wave"));
}
