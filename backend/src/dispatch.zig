const std = @import("std");
const config = @import("config.zig");

// Case/space-insensitive: exact phrase wins, else longest contained phrase (>= 3 chars), else null.
pub fn matchCommand(commands: []const config.Command, text: []const u8, scratch: []u8) ?usize {
    const norm = normalise(text, scratch);
    if (norm.len == 0) return null;

    // Exact match pass.
    for (commands, 0..) |cmd, i| {
        for (cmd.phrases) |phrase| {
            var pbuf: [128]u8 = undefined;
            const pn = normalise(phrase, &pbuf);
            if (pn.len > 0 and std.mem.eql(u8, pn, norm)) return i;
        }
    }

    // Substring match pass.
    var best_idx: ?usize = null;
    var best_len: usize = 0;
    for (commands, 0..) |cmd, i| {
        for (cmd.phrases) |phrase| {
            var pbuf: [128]u8 = undefined;
            const pn = normalise(phrase, &pbuf);
            if (pn.len < 3) continue;
            if (std.mem.indexOf(u8, norm, pn) != null and pn.len > best_len) {
                best_idx = i;
                best_len = pn.len;
            }
        }
    }
    return best_idx;
}

/// Exact-phrase match only, so a command like "show cargo" is not taken as a question.
pub fn matchExact(commands: []const config.Command, text: []const u8) ?usize {
    var tbuf: [256]u8 = undefined;
    const norm = normalise(text, &tbuf);
    if (norm.len == 0) return null;
    for (commands, 0..) |cmd, i| {
        for (cmd.phrases) |phrase| {
            var pbuf: [128]u8 = undefined;
            const pn = normalise(phrase, &pbuf);
            if (pn.len > 0 and std.mem.eql(u8, pn, norm)) return i;
        }
    }
    return null;
}

// Lowercase, collapse whitespace, drop non-alphanumerics.
fn normalise(s: []const u8, buf: []u8) []const u8 {
    var out_i: usize = 0;
    var last_space = true;
    for (s) |c| {
        if (out_i >= buf.len) break;
        if (std.ascii.isAlphanumeric(c) or c == '\'') {
            buf[out_i] = std.ascii.toLower(c);
            out_i += 1;
            last_space = false;
        } else if (c == ' ' or c == '-' or c == '_' or c == '\t') {
            if (!last_space and out_i < buf.len) {
                buf[out_i] = ' ';
                out_i += 1;
                last_space = true;
            }
        }
    }
    // Trim trailing space.
    while (out_i > 0 and buf[out_i - 1] == ' ') out_i -= 1;
    return buf[0..out_i];
}

// ---- tests ----

test "exact match" {
    const src =
        \\{ "version": 1, "commands": [
        \\  { "id":"a","phrases":["landing gear","gear"],"action":{"type":"tap","keys":"n"} },
        \\  { "id":"b","phrases":["fire"],"action":{"type":"tap","keys":"f"} }
        \\]}
    ;
    var set = try config.loadFromSlice(std.testing.allocator, src);
    defer set.deinit();

    var scratch: [128]u8 = undefined;
    try std.testing.expectEqual(@as(?usize, 0), matchCommand(set.commands, "landing gear", &scratch));
    try std.testing.expectEqual(@as(?usize, 0), matchCommand(set.commands, "  Landing   Gear ", &scratch));
    try std.testing.expectEqual(@as(?usize, 1), matchCommand(set.commands, "fire", &scratch));
}

test "substring match" {
    const src =
        \\{ "version": 1, "commands": [
        \\  { "id":"a","phrases":["landing gear"],"action":{"type":"tap","keys":"n"} }
        \\]}
    ;
    var set = try config.loadFromSlice(std.testing.allocator, src);
    defer set.deinit();

    var scratch: [128]u8 = undefined;
    try std.testing.expectEqual(@as(?usize, 0), matchCommand(set.commands, "landing gear please", &scratch));
}

test "no match" {
    const src =
        \\{ "version": 1, "commands": [
        \\  { "id":"a","phrases":["landing gear"],"action":{"type":"tap","keys":"n"} }
        \\]}
    ;
    var set = try config.loadFromSlice(std.testing.allocator, src);
    defer set.deinit();

    var scratch: [128]u8 = undefined;
    try std.testing.expectEqual(@as(?usize, null), matchCommand(set.commands, "quantum drive", &scratch));
    try std.testing.expectEqual(@as(?usize, null), matchCommand(set.commands, "", &scratch));
}

test "matchExact only accepts whole-phrase matches" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id":"cargo","phrases":["show cargo"],"action":{"type":"tap","keys":"f4"} },
        \\  { "id":"off","phrases":[],"disabled_phrases":["show map"],"action":{"type":"tap","keys":"m"} }
        \\]}
    ;
    var set = try config.loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    try std.testing.expectEqual(@as(?usize, 0), matchExact(set.commands, "Show  Cargo"));
    try std.testing.expectEqual(@as(?usize, null), matchExact(set.commands, "show cargo prices"));
    try std.testing.expectEqual(@as(?usize, null), matchExact(set.commands, "show map"));
    try std.testing.expectEqual(@as(?usize, null), matchExact(set.commands, ""));
}

test "commands with zero phrases never match" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id":"off","phrases":[],"disabled_phrases":["landing gear"],"action":{"type":"tap","keys":"n"} }
        \\]}
    ;
    var set = try config.loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    var scratch: [128]u8 = undefined;
    try std.testing.expectEqual(@as(?usize, null), matchCommand(set.commands, "landing gear", &scratch));
}
