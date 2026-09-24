const std = @import("std");
const gain = @import("../tts/gain.zig");

// Inbound messages from the Python GUI to the Zig backend.
pub const Inbound = union(enum) {
    reload_grammar,
    reload_config,
    set_listening: struct { enabled: bool },
    set_tts_enabled: struct { enabled: bool },
    // Voice token id (full registry path); "" means the Windows default voice.
    set_tts_voice: struct { id: []const u8 },
    // 0..300 percent (100 = normalised; above 100 is boosted through a soft limiter).
    set_tts_volume: struct { volume: u32 },
    // -10..10, 0 = normal speed.
    set_tts_rate: struct { rate: i32 },
    // Speak arbitrary text (GUI "Test voice"); ignores the TTS on/off toggle.
    speak_text: struct { text: []const u8 },
    trigger_command: struct { id: []const u8 },
    // Stop current speech immediately and drop anything queued.
    stop_speaking,
    list_audio_devices,
    // WASAPI endpoint id; "" = Windows default capture device.
    set_audio_device: struct { id: []const u8 },
    // Enumerate active render endpoints for TTS output selection.
    list_tts_output_devices,
    // WASAPI render endpoint id ("" = default eConsole); no-op under --tts-legacy.
    set_tts_output_device: struct { id: []const u8 },
    // e.g. "ctrl+shift+f12"; "" disables the hotkey.
    set_hotkey: struct { chord: []const u8 },
    // Dedicated stop-speaking hotkey; fires tts.stopSpeaking() bypassing the echo guard.
    set_stop_hotkey: struct { chord: []const u8 },
    ping,
    unknown: []const u8,

    pub fn parse(parsed: std.json.Value) Inbound {
        if (parsed != .object) return .{ .unknown = "not-an-object" };
        const obj = parsed.object;
        const type_v = obj.get("type") orelse return .{ .unknown = "missing-type" };
        if (type_v != .string) return .{ .unknown = "type-not-string" };
        const t = type_v.string;

        if (eq(t, "reload_grammar")) return .reload_grammar;
        if (eq(t, "reload_config")) return .reload_config;
        if (eq(t, "ping")) return .ping;
        if (eq(t, "stop_speaking")) return .stop_speaking;
        if (eq(t, "list_audio_devices")) return .list_audio_devices;
        if (eq(t, "set_audio_device")) {
            const id = obj.get("id") orelse return .{ .unknown = "missing-id" };
            if (id != .string) return .{ .unknown = "id-not-string" };
            return .{ .set_audio_device = .{ .id = id.string } };
        }
        if (eq(t, "list_tts_output_devices")) return .list_tts_output_devices;
        if (eq(t, "set_tts_output_device")) {
            const id = obj.get("id") orelse return .{ .unknown = "missing-id" };
            if (id != .string) return .{ .unknown = "id-not-string" };
            return .{ .set_tts_output_device = .{ .id = id.string } };
        }
        if (eq(t, "set_hotkey")) {
            const c = obj.get("chord") orelse return .{ .unknown = "missing-chord" };
            if (c != .string) return .{ .unknown = "chord-not-string" };
            return .{ .set_hotkey = .{ .chord = c.string } };
        }
        if (eq(t, "set_stop_hotkey")) {
            const c = obj.get("chord") orelse return .{ .unknown = "missing-chord" };
            if (c != .string) return .{ .unknown = "chord-not-string" };
            return .{ .set_stop_hotkey = .{ .chord = c.string } };
        }
        if (eq(t, "set_listening")) {
            const en = obj.get("enabled") orelse return .{ .unknown = "missing-enabled" };
            return .{ .set_listening = .{ .enabled = boolOf(en) } };
        }
        if (eq(t, "set_tts_enabled")) {
            const en = obj.get("enabled") orelse return .{ .unknown = "missing-enabled" };
            return .{ .set_tts_enabled = .{ .enabled = boolOf(en) } };
        }
        if (eq(t, "trigger_command")) {
            const id = obj.get("id") orelse return .{ .unknown = "missing-id" };
            if (id != .string) return .{ .unknown = "id-not-string" };
            return .{ .trigger_command = .{ .id = id.string } };
        }
        if (eq(t, "set_tts_voice")) {
            const id = obj.get("id") orelse return .{ .unknown = "missing-id" };
            if (id != .string) return .{ .unknown = "id-not-string" };
            return .{ .set_tts_voice = .{ .id = id.string } };
        }
        if (eq(t, "set_tts_volume")) {
            const v = obj.get("volume") orelse return .{ .unknown = "missing-volume" };
            return .{ .set_tts_volume = .{ .volume = @intCast(std.math.clamp(intOf(v), 0, gain.MAX_VOLUME_PCT)) } };
        }
        if (eq(t, "set_tts_rate")) {
            const v = obj.get("rate") orelse return .{ .unknown = "missing-rate" };
            return .{ .set_tts_rate = .{ .rate = @intCast(std.math.clamp(intOf(v), -10, 10)) } };
        }
        if (eq(t, "speak_text")) {
            const s = obj.get("text") orelse return .{ .unknown = "missing-text" };
            if (s != .string) return .{ .unknown = "text-not-string" };
            return .{ .speak_text = .{ .text = s.string } };
        }
        return .{ .unknown = t };
    }
};

fn intOf(v: std.json.Value) i64 {
    return switch (v) {
        .integer => |i| i,
        .float => |f| if (std.math.isFinite(f)) @intFromFloat(std.math.clamp(@round(f), -1e9, 1e9)) else 0,
        else => 0,
    };
}

pub const AudioDevice = struct { id: []const u8, name: []const u8, is_default: bool };

// Backend -> GUI messages, serialized as compact JSON lines.
pub const Outbound = union(enum) {
    status: struct { listening: bool, elevated: bool, engine: []const u8 },
    mic_ready: struct { sample_rate: u32, channels: u16, device_id: []const u8 = "", device_name: []const u8 = "" },
    audio_level: struct { peak: f32 },
    transcript_partial: struct { text: []const u8 },
    transcript_final: struct { text: []const u8, confidence: f32 },
    command_fired: struct { id: []const u8 },
    no_match: struct { text: []const u8 },
    // Free-form transcript starting with a question lead; no command fired.
    question: struct { text: []const u8 },
    // Informational: a system command was performed (op = SystemOp tag name).
    system_action: struct { op: []const u8, id: []const u8 },
    audio_devices: struct { devices: []const AudioDevice, current_id: []const u8 },
    // Render endpoint list + currently-selected id. `mode` is "wasapi" or "legacy".
    tts_output_devices: struct { devices: []const AudioDevice, current_id: []const u8, mode: []const u8 },
    // Acknowledges a set_tts_output_device request; `err` "" when ok.
    tts_output_device: struct { id: []const u8, name: []const u8, ok: bool, err: []const u8 },
    // `err` is serialized as "error" ("" when ok).
    hotkey_status: struct { chord: []const u8, ok: bool, err: []const u8 },
    // Same shape as hotkey_status but for the dedicated stop-speaking hotkey.
    stop_hotkey_status: struct { chord: []const u8, ok: bool, err: []const u8 },
    config_reloaded: struct { commands: usize, phrases: usize, path: []const u8 },
    log: struct { level: []const u8, msg: []const u8 },
    pong,

    pub fn write(self: Outbound, writer: anytype) !void {
        try writer.writeByte('{');
        switch (self) {
            .status => |s| {
                try writer.print(
                    "\"type\":\"status\",\"listening\":{s},\"elevated\":{s},\"engine\":",
                    .{ boolStr(s.listening), boolStr(s.elevated) },
                );
                try writeString(writer, s.engine);
            },
            .mic_ready => |s| {
                try writer.print("\"type\":\"mic_ready\",\"sample_rate\":{},\"channels\":{},\"device_id\":", .{ s.sample_rate, s.channels });
                try writeString(writer, s.device_id);
                try writer.writeAll(",\"device_name\":");
                try writeString(writer, s.device_name);
            },
            .audio_level => |s| {
                try writer.print("\"type\":\"audio_level\",\"peak\":{d:.4}", .{s.peak});
            },
            .transcript_partial => |s| {
                try writer.writeAll("\"type\":\"transcript_partial\",\"text\":");
                try writeString(writer, s.text);
            },
            .transcript_final => |s| {
                try writer.writeAll("\"type\":\"transcript_final\",\"text\":");
                try writeString(writer, s.text);
                try writer.print(",\"confidence\":{d:.3}", .{s.confidence});
            },
            .command_fired => |s| {
                try writer.writeAll("\"type\":\"command_fired\",\"id\":");
                try writeString(writer, s.id);
            },
            .no_match => |s| {
                try writer.writeAll("\"type\":\"no_match\",\"text\":");
                try writeString(writer, s.text);
            },
            .log => |s| {
                try writer.writeAll("\"type\":\"log\",\"level\":");
                try writeString(writer, s.level);
                try writer.writeAll(",\"msg\":");
                try writeString(writer, s.msg);
            },
            .pong => try writer.writeAll("\"type\":\"pong\""),
            .question => |s| {
                try writer.writeAll("\"type\":\"question\",\"text\":");
                try writeString(writer, s.text);
            },
            .system_action => |s| {
                try writer.writeAll("\"type\":\"system_action\",\"op\":");
                try writeString(writer, s.op);
                try writer.writeAll(",\"id\":");
                try writeString(writer, s.id);
            },
            .audio_devices => |s| {
                try writer.writeAll("\"type\":\"audio_devices\",\"devices\":[");
                for (s.devices, 0..) |d, i| {
                    if (i > 0) try writer.writeByte(',');
                    try writer.writeAll("{\"id\":");
                    try writeString(writer, d.id);
                    try writer.writeAll(",\"name\":");
                    try writeString(writer, d.name);
                    try writer.print(",\"is_default\":{s}}}", .{boolStr(d.is_default)});
                }
                try writer.writeAll("],\"current_id\":");
                try writeString(writer, s.current_id);
            },
            .tts_output_devices => |s| {
                try writer.writeAll("\"type\":\"tts_output_devices\",\"devices\":[");
                for (s.devices, 0..) |d, i| {
                    if (i > 0) try writer.writeByte(',');
                    try writer.writeAll("{\"id\":");
                    try writeString(writer, d.id);
                    try writer.writeAll(",\"name\":");
                    try writeString(writer, d.name);
                    try writer.print(",\"is_default\":{s}}}", .{boolStr(d.is_default)});
                }
                try writer.writeAll("],\"current_id\":");
                try writeString(writer, s.current_id);
                try writer.writeAll(",\"mode\":");
                try writeString(writer, s.mode);
            },
            .tts_output_device => |s| {
                try writer.writeAll("\"type\":\"tts_output_device\",\"id\":");
                try writeString(writer, s.id);
                try writer.writeAll(",\"name\":");
                try writeString(writer, s.name);
                try writer.print(",\"ok\":{s},\"error\":", .{boolStr(s.ok)});
                try writeString(writer, s.err);
            },
            .hotkey_status => |s| {
                try writer.writeAll("\"type\":\"hotkey_status\",\"chord\":");
                try writeString(writer, s.chord);
                try writer.print(",\"ok\":{s},\"error\":", .{boolStr(s.ok)});
                try writeString(writer, s.err);
            },
            .stop_hotkey_status => |s| {
                try writer.writeAll("\"type\":\"stop_hotkey_status\",\"chord\":");
                try writeString(writer, s.chord);
                try writer.print(",\"ok\":{s},\"error\":", .{boolStr(s.ok)});
                try writeString(writer, s.err);
            },
            .config_reloaded => |s| {
                try writer.print("\"type\":\"config_reloaded\",\"commands\":{d},\"phrases\":{d},\"path\":", .{ s.commands, s.phrases });
                try writeString(writer, s.path);
            },
        }
        try writer.writeAll("}\n");
    }
};

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn boolOf(v: std.json.Value) bool {
    return switch (v) {
        .bool => |b| b,
        .integer => |i| i != 0,
        else => false,
    };
}

fn boolStr(b: bool) []const u8 {
    return if (b) "true" else "false";
}

fn writeString(writer: anytype, s: []const u8) !void {
    try writer.writeByte('"');
    for (s) |c| switch (c) {
        '"' => try writer.writeAll("\\\""),
        '\\' => try writer.writeAll("\\\\"),
        '\n' => try writer.writeAll("\\n"),
        '\r' => try writer.writeAll("\\r"),
        '\t' => try writer.writeAll("\\t"),
        0x00...0x08, 0x0B, 0x0C, 0x0E...0x1F => try writer.print("\\u{x:0>4}", .{c}),
        else => try writer.writeByte(c),
    };
    try writer.writeByte('"');
}

// ---- tests ----

test "outbound mic_ready and audio_level serialize" {
    var buf: std.ArrayList(u8) = .init(std.testing.allocator);
    defer buf.deinit();
    const mic_msg = Outbound{ .mic_ready = .{ .sample_rate = 48000, .channels = 1 } };
    try mic_msg.write(buf.writer());
    try std.testing.expectEqualStrings("{\"type\":\"mic_ready\",\"sample_rate\":48000,\"channels\":1,\"device_id\":\"\",\"device_name\":\"\"}\n", buf.items);
    buf.clearRetainingCapacity();
    const level_msg = Outbound{ .audio_level = .{ .peak = 0.5 } };
    try level_msg.write(buf.writer());
    try std.testing.expectEqualStrings("{\"type\":\"audio_level\",\"peak\":0.5000}\n", buf.items);
}

test "outbound status serializes" {
    var buf: std.ArrayList(u8) = .init(std.testing.allocator);
    defer buf.deinit();
    const msg = Outbound{ .status = .{ .listening = true, .elevated = false, .engine = "vosk" } };
    try msg.write(buf.writer());
    try std.testing.expectEqualStrings(
        "{\"type\":\"status\",\"listening\":true,\"elevated\":false,\"engine\":\"vosk\"}\n",
        buf.items,
    );
}

test "outbound transcript_final formats confidence" {
    var buf: std.ArrayList(u8) = .init(std.testing.allocator);
    defer buf.deinit();
    const msg = Outbound{ .transcript_final = .{ .text = "landing gear", .confidence = 0.94 } };
    try msg.write(buf.writer());
    try std.testing.expect(std.mem.indexOf(u8, buf.items, "\"text\":\"landing gear\"") != null);
    try std.testing.expect(std.mem.indexOf(u8, buf.items, "\"confidence\":0.940") != null);
}

test "inbound parse trigger_command" {
    const src = "{\"type\":\"trigger_command\",\"id\":\"landing_gear\"}";
    var parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, src, .{});
    defer parsed.deinit();
    const msg = Inbound.parse(parsed.value);
    try std.testing.expect(msg == .trigger_command);
    try std.testing.expectEqualStrings("landing_gear", msg.trigger_command.id);
}

test "inbound parse set_listening" {
    const src = "{\"type\":\"set_listening\",\"enabled\":true}";
    var parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, src, .{});
    defer parsed.deinit();
    const msg = Inbound.parse(parsed.value);
    try std.testing.expect(msg == .set_listening);
    try std.testing.expect(msg.set_listening.enabled);
}

test "inbound unknown type returns tagged unknown" {
    const src = "{\"type\":\"floop\"}";
    var parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, src, .{});
    defer parsed.deinit();
    const msg = Inbound.parse(parsed.value);
    try std.testing.expect(msg == .unknown);
}

fn parseStr(src: []const u8) !std.json.Parsed(std.json.Value) {
    return std.json.parseFromSlice(std.json.Value, std.testing.allocator, src, .{});
}

test "inbound parse TTS voice, volume, rate and speak_text" {
    var p1 = try parseStr("{\"type\":\"set_tts_voice\",\"id\":\"HKEY_LOCAL_MACHINE\\\\SOFTWARE\\\\Microsoft\\\\Speech\\\\Voices\\\\Tokens\\\\TTS_MS_EN-US_ZIRA_11.0\"}");
    defer p1.deinit();
    const v = Inbound.parse(p1.value);
    try std.testing.expect(v == .set_tts_voice);
    try std.testing.expect(std.mem.endsWith(u8, v.set_tts_voice.id, "TTS_MS_EN-US_ZIRA_11.0"));

    var p2 = try parseStr("{\"type\":\"set_tts_volume\",\"volume\":150}");
    defer p2.deinit();
    const vol = Inbound.parse(p2.value);
    try std.testing.expect(vol == .set_tts_volume);
    try std.testing.expectEqual(@as(u32, 150), vol.set_tts_volume.volume);

    var p3 = try parseStr("{\"type\":\"set_tts_rate\",\"rate\":-3}");
    defer p3.deinit();
    const r = Inbound.parse(p3.value);
    try std.testing.expect(r == .set_tts_rate);
    try std.testing.expectEqual(@as(i32, -3), r.set_tts_rate.rate);

    var p4 = try parseStr("{\"type\":\"speak_text\",\"text\":\"voice check\"}");
    defer p4.deinit();
    const s = Inbound.parse(p4.value);
    try std.testing.expect(s == .speak_text);
    try std.testing.expectEqualStrings("voice check", s.speak_text.text);
}

test "inbound TTS values are clamped to safe ranges" {
    var p1 = try parseStr("{\"type\":\"set_tts_volume\",\"volume\":9999}");
    defer p1.deinit();
    try std.testing.expectEqual(@as(u32, 300), Inbound.parse(p1.value).set_tts_volume.volume);
    var p2 = try parseStr("{\"type\":\"set_tts_volume\",\"volume\":-5}");
    defer p2.deinit();
    try std.testing.expectEqual(@as(u32, 0), Inbound.parse(p2.value).set_tts_volume.volume);
    var p3 = try parseStr("{\"type\":\"set_tts_rate\",\"rate\":42}");
    defer p3.deinit();
    try std.testing.expectEqual(@as(i32, 10), Inbound.parse(p3.value).set_tts_rate.rate);
}

test "inbound parse v2 messages" {
    var p1 = try parseStr("{\"type\":\"stop_speaking\"}");
    defer p1.deinit();
    try std.testing.expect(Inbound.parse(p1.value) == .stop_speaking);

    var p2 = try parseStr("{\"type\":\"list_audio_devices\"}");
    defer p2.deinit();
    try std.testing.expect(Inbound.parse(p2.value) == .list_audio_devices);

    var p3 = try parseStr("{\"type\":\"set_audio_device\",\"id\":\"{0.0.1.00000000}.{5a3c-\\\\-x}\"}");
    defer p3.deinit();
    const d = Inbound.parse(p3.value);
    try std.testing.expect(d == .set_audio_device);
    try std.testing.expectEqualStrings("{0.0.1.00000000}.{5a3c-\\-x}", d.set_audio_device.id);

    var p4 = try parseStr("{\"type\":\"set_audio_device\",\"id\":\"\"}");
    defer p4.deinit();
    try std.testing.expectEqualStrings("", Inbound.parse(p4.value).set_audio_device.id);

    var p5 = try parseStr("{\"type\":\"set_hotkey\",\"chord\":\"alt+f10\",\"extra\":1}");
    defer p5.deinit();
    const h = Inbound.parse(p5.value);
    try std.testing.expect(h == .set_hotkey);
    try std.testing.expectEqualStrings("alt+f10", h.set_hotkey.chord);

    var p6 = try parseStr("{\"type\":\"set_hotkey\"}");
    defer p6.deinit();
    try std.testing.expect(Inbound.parse(p6.value) == .unknown);

    var p7 = try parseStr("{\"type\":\"reload_config\"}");
    defer p7.deinit();
    try std.testing.expect(Inbound.parse(p7.value) == .reload_config);
}

fn expectWrites(msg: Outbound, expected: []const u8) !void {
    var buf: std.ArrayList(u8) = .init(std.testing.allocator);
    defer buf.deinit();
    try msg.write(buf.writer());
    try std.testing.expectEqualStrings(expected, buf.items);
    // Every message must be valid JSON on its own line.
    var parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, buf.items, .{});
    parsed.deinit();
}

test "outbound mic_ready carries device id and name (escaped)" {
    try expectWrites(.{ .mic_ready = .{
        .sample_rate = 48000,
        .channels = 2,
        .device_id = "{0.0.1.00000000}.{abc}",
        .device_name = "Analogue 1 + 2 (Focusrite \"USB\" Audio) \\ \u{e9}",
    } }, "{\"type\":\"mic_ready\",\"sample_rate\":48000,\"channels\":2,\"device_id\":\"{0.0.1.00000000}.{abc}\",\"device_name\":\"Analogue 1 + 2 (Focusrite \\\"USB\\\" Audio) \\\\ \u{e9}\"}\n");
}

test "outbound question and system_action" {
    try expectWrites(.{ .question = .{ .text = "what is \"quantanium\"\n" } }, "{\"type\":\"question\",\"text\":\"what is \\\"quantanium\\\"\\n\"}\n");
    try expectWrites(.{ .system_action = .{ .op = "say_random", .id = "thanks_computer" } }, "{\"type\":\"system_action\",\"op\":\"say_random\",\"id\":\"thanks_computer\"}\n");
}

test "outbound audio_devices list" {
    const devs = [_]AudioDevice{
        .{ .id = "{a}", .name = "Mic \"A\"", .is_default = true },
        .{ .id = "{b}\\x", .name = "Headset", .is_default = false },
    };
    try expectWrites(.{ .audio_devices = .{ .devices = &devs, .current_id = "" } }, "{\"type\":\"audio_devices\",\"devices\":[{\"id\":\"{a}\",\"name\":\"Mic \\\"A\\\"\",\"is_default\":true},{\"id\":\"{b}\\\\x\",\"name\":\"Headset\",\"is_default\":false}],\"current_id\":\"\"}\n");
    try expectWrites(.{ .audio_devices = .{ .devices = &.{}, .current_id = "{a}" } }, "{\"type\":\"audio_devices\",\"devices\":[],\"current_id\":\"{a}\"}\n");
}

test "outbound hotkey_status and config_reloaded" {
    try expectWrites(.{ .hotkey_status = .{ .chord = "ctrl+shift+f12", .ok = true, .err = "" } }, "{\"type\":\"hotkey_status\",\"chord\":\"ctrl+shift+f12\",\"ok\":true,\"error\":\"\"}\n");
    try expectWrites(.{ .hotkey_status = .{ .chord = "f8", .ok = false, .err = "already in use" } }, "{\"type\":\"hotkey_status\",\"chord\":\"f8\",\"ok\":false,\"error\":\"already in use\"}\n");
    try expectWrites(.{ .config_reloaded = .{ .commands = 58, .phrases = 140, .path = "config\\commands.json" } }, "{\"type\":\"config_reloaded\",\"commands\":58,\"phrases\":140,\"path\":\"config\\\\commands.json\"}\n");
}
