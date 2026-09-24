const std = @import("std");

// Loads command files v1/v2 (docs/COMMANDS.md); only `phrases` feeds the grammar, extras ignored.

pub const DEFAULT_COMMANDS_PATH = "config/commands.json";
pub const DEFAULT_COMMANDS_FALLBACK = "config/commands.default.json";

/// `config/commands.json` when present (written by the GUI), else the shipped default.
pub fn pickCommandsFile() []const u8 {
    if (std.fs.cwd().access(DEFAULT_COMMANDS_PATH, .{})) |_| {
        return DEFAULT_COMMANDS_PATH;
    } else |_| {
        return DEFAULT_COMMANDS_FALLBACK;
    }
}

pub const SystemOp = enum { stop_listening, stop_speaking, say_random };

pub const Action = union(enum) {
    tap: struct { keys: []const u8 },
    hold: struct { keys: []const u8, duration_ms: u32 },
    press: struct { keys: []const u8 },
    release: struct { keys: []const u8 },
    // `keys` (optional): modifiers held down around the click, e.g. "left alt".
    mouse: struct { button: []const u8, kind: []const u8, keys: ?[]const u8 = null },
    scroll: struct { direction: []const u8, amount: i32 },
    system: struct { op: SystemOp, responses: []const []const u8 = &.{} },
};

pub const Command = struct {
    id: []const u8,
    phrases: []const []const u8,
    action: Action,
    tts_ack: ?[]const u8 = null,
};

/// True for the one action that is still honoured while the echo guard is up.
pub fn isStopSpeaking(action: Action) bool {
    return action == .system and action.system.op == .stop_speaking;
}

/// One random entry of `responses`, or null when there are none.
pub fn pickResponse(responses: []const []const u8, random: std.Random) ?[]const u8 {
    if (responses.len == 0) return null;
    return responses[random.uintLessThan(usize, responses.len)];
}

pub const CommandSet = struct {
    version: u32,
    commands: []Command,
    // Arena-owned parse tree: every slice in `commands` lives here, so deinit is one free.
    parsed: std.json.Parsed(std.json.Value),
    allocator: std.mem.Allocator,

    pub fn deinit(self: *CommandSet) void {
        self.parsed.deinit();
    }

    /// Number of enabled phrases across all commands (what the grammar gets).
    pub fn phraseCount(self: *const CommandSet) usize {
        var n: usize = 0;
        for (self.commands) |c| n += c.phrases.len;
        return n;
    }
};

pub const LoadError = error{
    InvalidFormat,
    UnsupportedVersion,
    UnknownActionType,
    UnknownSystemOp,
    MissingField,
} || std.mem.Allocator.Error || std.json.ParseError(std.json.Scanner) || std.fs.File.OpenError || std.fs.File.ReadError;

/// Optional diagnostics: which command made loading fail.
pub const Diag = struct {
    index: ?usize = null,
    id_buf: [64]u8 = undefined,
    id_len: usize = 0,

    pub fn id(self: *const Diag) []const u8 {
        return self.id_buf[0..self.id_len];
    }
};

pub fn loadFromFile(allocator: std.mem.Allocator, path: []const u8) LoadError!CommandSet {
    return loadFromFileDiag(allocator, path, null);
}

pub fn loadFromFileDiag(allocator: std.mem.Allocator, path: []const u8, diag: ?*Diag) LoadError!CommandSet {
    var file = try std.fs.cwd().openFile(path, .{});
    defer file.close();
    const source = try file.readToEndAlloc(allocator, 16 * 1024 * 1024);
    defer allocator.free(source);
    return loadFromSliceDiag(allocator, source, diag);
}

pub fn loadFromSlice(allocator: std.mem.Allocator, source: []const u8) LoadError!CommandSet {
    return loadFromSliceDiag(allocator, source, null);
}

pub fn loadFromSliceDiag(allocator: std.mem.Allocator, source: []const u8, diag: ?*Diag) LoadError!CommandSet {
    var parsed = try std.json.parseFromSlice(std.json.Value, allocator, source, .{});
    errdefer parsed.deinit();
    const arena = parsed.arena.allocator();

    if (parsed.value != .object) return LoadError.InvalidFormat;
    const root = parsed.value.object;

    const ver = root.get("version") orelse return LoadError.MissingField;
    if (ver != .integer or (ver.integer != 1 and ver.integer != 2)) return LoadError.UnsupportedVersion;

    const cmds_json = root.get("commands") orelse return LoadError.MissingField;
    if (cmds_json != .array) return LoadError.InvalidFormat;

    const commands = try arena.alloc(Command, cmds_json.array.items.len);
    for (cmds_json.array.items, 0..) |item, i| {
        errdefer if (diag) |d| noteFailure(d, i, item);
        if (item != .object) return LoadError.InvalidFormat;
        commands[i] = try parseCommand(arena, item.object);
    }

    return .{
        .version = @intCast(ver.integer),
        .commands = commands,
        .parsed = parsed,
        .allocator = allocator,
    };
}

fn noteFailure(d: *Diag, index: usize, item: std.json.Value) void {
    d.index = index;
    d.id_len = 0;
    if (item != .object) return;
    const v = item.object.get("id") orelse return;
    if (v != .string) return;
    const n = @min(v.string.len, d.id_buf.len);
    @memcpy(d.id_buf[0..n], v.string[0..n]);
    d.id_len = n;
}

fn parseCommand(arena: std.mem.Allocator, obj: std.json.ObjectMap) LoadError!Command {
    const id = try requireString(obj, "id");

    // Missing `phrases` is treated like an empty list (never matched).
    const phrases = if (obj.get("phrases")) |v| try stringArray(arena, v) else &[_][]const u8{};

    const action_v = obj.get("action") orelse return LoadError.MissingField;
    if (action_v != .object) return LoadError.InvalidFormat;
    const action = try parseAction(arena, action_v.object);

    const tts_ack: ?[]const u8 = if (obj.get("tts_ack")) |v|
        (if (v == .string and v.string.len > 0) v.string else null)
    else
        null;

    return .{
        .id = id,
        .phrases = phrases,
        .action = action,
        .tts_ack = tts_ack,
    };
}

fn stringArray(arena: std.mem.Allocator, v: std.json.Value) LoadError![]const []const u8 {
    if (v != .array) return LoadError.InvalidFormat;
    const out = try arena.alloc([]const u8, v.array.items.len);
    var n: usize = 0;
    for (v.array.items) |p| {
        if (p != .string) return LoadError.InvalidFormat;
        // Blank phrases would put "" into the Vosk grammar; skip them.
        if (std.mem.trim(u8, p.string, " \t\r\n").len == 0) continue;
        out[n] = p.string;
        n += 1;
    }
    return out[0..n];
}

fn parseAction(arena: std.mem.Allocator, obj: std.json.ObjectMap) LoadError!Action {
    const type_v = obj.get("type") orelse return LoadError.MissingField;
    if (type_v != .string) return LoadError.InvalidFormat;
    const t = type_v.string;

    if (std.mem.eql(u8, t, "tap")) {
        return .{ .tap = .{ .keys = try requireString(obj, "keys") } };
    } else if (std.mem.eql(u8, t, "hold")) {
        const dur = obj.get("duration_ms") orelse return LoadError.MissingField;
        if (dur != .integer or dur.integer < 0 or dur.integer > 600_000) return LoadError.InvalidFormat;
        return .{ .hold = .{
            .keys = try requireString(obj, "keys"),
            .duration_ms = @intCast(dur.integer),
        } };
    } else if (std.mem.eql(u8, t, "press")) {
        return .{ .press = .{ .keys = try requireString(obj, "keys") } };
    } else if (std.mem.eql(u8, t, "release")) {
        return .{ .release = .{ .keys = try requireString(obj, "keys") } };
    } else if (std.mem.eql(u8, t, "mouse")) {
        const keys: ?[]const u8 = if (obj.get("keys")) |k| blk: {
            if (k == .null) break :blk null;
            if (k != .string) return LoadError.InvalidFormat;
            break :blk if (std.mem.trim(u8, k.string, " ").len == 0) null else k.string;
        } else null;
        return .{ .mouse = .{
            .button = try requireString(obj, "button"),
            .kind = try requireString(obj, "kind"),
            .keys = keys,
        } };
    } else if (std.mem.eql(u8, t, "scroll")) {
        const amt = obj.get("amount") orelse return LoadError.MissingField;
        if (amt != .integer or amt.integer < 0 or amt.integer > 1000) return LoadError.InvalidFormat;
        return .{ .scroll = .{
            .direction = try requireString(obj, "direction"),
            .amount = @intCast(amt.integer),
        } };
    } else if (std.mem.eql(u8, t, "system")) {
        const op_s = try requireString(obj, "op");
        const op = std.meta.stringToEnum(SystemOp, op_s) orelse return LoadError.UnknownSystemOp;
        const responses = if (obj.get("responses")) |v| try stringArray(arena, v) else &[_][]const u8{};
        return .{ .system = .{ .op = op, .responses = responses } };
    }
    return LoadError.UnknownActionType;
}

fn requireString(obj: std.json.ObjectMap, key: []const u8) LoadError![]const u8 {
    const v = obj.get(key) orelse return LoadError.MissingField;
    if (v != .string) return LoadError.InvalidFormat;
    return v.string;
}

test "parse minimal command set" {
    const src =
        \\{ "version": 1, "commands": [
        \\  { "id": "landing_gear", "phrases": ["landing gear","gear"], "action": {"type":"tap","keys":"n"} },
        \\  { "id": "boost", "phrases": ["boost"], "action": {"type":"hold","keys":"left shift","duration_ms":250}, "tts_ack":"boost" }
        \\]}
    ;
    var set = try loadFromSlice(std.testing.allocator, src);
    defer set.deinit();

    try std.testing.expectEqual(@as(u32, 1), set.version);
    try std.testing.expectEqual(@as(usize, 2), set.commands.len);
    try std.testing.expectEqualStrings("landing_gear", set.commands[0].id);
    try std.testing.expectEqualStrings("gear", set.commands[0].phrases[1]);
    try std.testing.expect(set.commands[0].action == .tap);
    try std.testing.expectEqualStrings("n", set.commands[0].action.tap.keys);
    try std.testing.expect(set.commands[1].action == .hold);
    try std.testing.expectEqual(@as(u32, 250), set.commands[1].action.hold.duration_ms);
    try std.testing.expectEqualStrings("boost", set.commands[1].tts_ack.?);
}

test "reject unknown action type" {
    const src =
        \\{ "version": 1, "commands": [
        \\  { "id": "x", "phrases": ["x"], "action": {"type":"beam","keys":"x"} }
        \\]}
    ;
    const res = loadFromSlice(std.testing.allocator, src);
    try std.testing.expectError(LoadError.UnknownActionType, res);
}

test "reject unsupported version" {
    const src =
        \\{ "version": 3, "commands": [] }
    ;
    const res = loadFromSlice(std.testing.allocator, src);
    try std.testing.expectError(LoadError.UnsupportedVersion, res);
}

test "mouse and scroll" {
    const src =
        \\{ "version": 1, "commands": [
        \\  { "id":"fire","phrases":["fire"],"action":{"type":"mouse","button":"left","kind":"click"} },
        \\  { "id":"wheel","phrases":["scroll up"],"action":{"type":"scroll","direction":"up","amount":3} }
        \\]}
    ;
    var set = try loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    try std.testing.expect(set.commands[0].action == .mouse);
    try std.testing.expectEqualStrings("left", set.commands[0].action.mouse.button);
    try std.testing.expect(set.commands[0].action.mouse.keys == null);
    try std.testing.expect(set.commands[1].action == .scroll);
    try std.testing.expectEqual(@as(i32, 3), set.commands[1].action.scroll.amount);
}

test "v2 file: unknown fields ignored, only enabled phrases kept" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id": "landing_gear", "label": "Landing Gear", "category": "Landing & ATC",
        \\    "phrases": ["landing gear", "gear"], "disabled_phrases": ["gear up"], "custom": false,
        \\    "action": {"type":"tap","keys":"n"}, "tts_ack": "gear", "future_field": {"x": 1} }
        \\]}
    ;
    var set = try loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    try std.testing.expectEqual(@as(u32, 2), set.version);
    try std.testing.expectEqual(@as(usize, 2), set.commands[0].phrases.len);
    for (set.commands[0].phrases) |p| try std.testing.expect(!std.mem.eql(u8, p, "gear up"));
    try std.testing.expectEqual(@as(usize, 2), set.phraseCount());
}

test "v2 command with zero phrases is kept" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id": "muted", "phrases": [], "disabled_phrases": ["mute"], "action": {"type":"tap","keys":"m"} },
        \\  { "id": "nophrases", "action": {"type":"tap","keys":"k"} }
        \\]}
    ;
    var set = try loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    try std.testing.expectEqual(@as(usize, 2), set.commands.len);
    try std.testing.expectEqual(@as(usize, 0), set.commands[0].phrases.len);
    try std.testing.expectEqual(@as(usize, 0), set.commands[1].phrases.len);
    try std.testing.expectEqual(@as(usize, 0), set.phraseCount());
}

test "system actions parse with op and responses" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id": "voice_off", "phrases": ["computer off"], "action": {"type":"system","op":"stop_listening"}, "tts_ack": "Voice protocol offline." },
        \\  { "id": "stop_talking", "phrases": ["robot shut up"], "action": {"type":"system","op":"stop_speaking"} },
        \\  { "id": "thanks_computer", "phrases": ["thanks computer"], "action": {"type":"system","op":"say_random","responses":["Any time.","You're welcome, pilot."]} }
        \\]}
    ;
    var set = try loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    try std.testing.expectEqual(SystemOp.stop_listening, set.commands[0].action.system.op);
    try std.testing.expectEqual(@as(usize, 0), set.commands[0].action.system.responses.len);
    try std.testing.expect(isStopSpeaking(set.commands[1].action));
    try std.testing.expect(!isStopSpeaking(set.commands[0].action));
    try std.testing.expectEqual(SystemOp.say_random, set.commands[2].action.system.op);
    try std.testing.expectEqualStrings("You're welcome, pilot.", set.commands[2].action.system.responses[1]);
}

test "unknown system op is rejected with diagnostics" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id": "ok", "phrases": ["a"], "action": {"type":"tap","keys":"a"} },
        \\  { "id": "bad_one", "phrases": ["b"], "action": {"type":"system","op":"self_destruct"} }
        \\]}
    ;
    var diag = Diag{};
    try std.testing.expectError(LoadError.UnknownSystemOp, loadFromSliceDiag(std.testing.allocator, src, &diag));
    try std.testing.expectEqual(@as(?usize, 1), diag.index);
    try std.testing.expectEqualStrings("bad_one", diag.id());
}

test "mouse action with held modifier keys" {
    const src =
        \\{ "version": 2, "commands": [
        \\  { "id": "zoom", "phrases": ["zoom"], "action": {"type":"mouse","button":"right","kind":"click","keys":"left alt"} }
        \\]}
    ;
    var set = try loadFromSlice(std.testing.allocator, src);
    defer set.deinit();
    try std.testing.expectEqualStrings("left alt", set.commands[0].action.mouse.keys.?);
}

test "pickResponse returns null for empty and an element otherwise" {
    var prng = std.Random.DefaultPrng.init(1);
    const r = prng.random();
    try std.testing.expect(pickResponse(&.{}, r) == null);
    const one = [_][]const u8{"only"};
    try std.testing.expectEqualStrings("only", pickResponse(&one, r).?);
    const many = [_][]const u8{ "a", "b", "c" };
    var seen = [_]bool{ false, false, false };
    for (0..200) |_| {
        const p = pickResponse(&many, r).?;
        seen[p[0] - 'a'] = true;
    }
    try std.testing.expect(seen[0] and seen[1] and seen[2]);
}
