const std = @import("std");
const builtin = @import("builtin");
const elevation = @import("elevation.zig");
const config = @import("config.zig");
const codegen = @import("grammar/codegen.zig");
const modifiers = @import("input/modifiers.zig");
const sendinput = @import("input/sendinput.zig");
const hotkey = @import("input/hotkey.zig");
const wasapi = @import("audio/wasapi.zig");
const vad_mod = @import("audio/vad.zig");
const wav = @import("audio/wav.zig");
const sapi5 = @import("tts/sapi5.zig");
const protocol = @import("ipc/protocol.zig");
const pipe_server = @import("ipc/pipe_server.zig");
const dispatch = @import("dispatch.zig");
const listen_mod = @import("listen.zig");
const actions = @import("actions.zig");

const VERSION = "2.0.0";


pub fn main() !void {
    var gpa: std.heap.GeneralPurposeAllocator(.{}) = .{};
    defer _ = gpa.deinit();
    const allocator = gpa.allocator();

    const stdout = std.io.getStdOut().writer();

    try stdout.print("Deckhand backend v{s}\n", .{VERSION});
    try stdout.print("Zig {s} — target {s}-{s}\n", .{
        builtin.zig_version_string,
        @tagName(builtin.os.tag),
        @tagName(builtin.cpu.arch),
    });

    var elevated: bool = false;
    if (builtin.os.tag == .windows) {
        elevated = elevation.isElevated() catch |err| blk: {
            try stdout.print("elevation check failed: {s}\n", .{@errorName(err)});
            break :blk false;
        };
        try stdout.print("elevated: {}\n", .{elevated});
    } else {
        try stdout.writeAll("(non-Windows build; elevation check skipped)\n");
    }

    var args = try std.process.argsWithAllocator(allocator);
    defer args.deinit();
    _ = args.next();

    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--version")) return;

        if (std.mem.eql(u8, arg, "--check-elevation")) {
            std.process.exit(if (elevated) 0 else 1);
        }

        if (std.mem.eql(u8, arg, "--regen-grammar")) {
            try regenGrammar(allocator, stdout);
            return;
        }

        if (std.mem.eql(u8, arg, "--list-commands")) {
            try listCommands(allocator, stdout);
            return;
        }

        if (std.mem.eql(u8, arg, "--fire")) {
            const id = args.next() orelse {
                try stdout.writeAll("--fire requires <command_id>\n");
                std.process.exit(2);
            };
            try fireCommand(allocator, stdout, id);
            return;
        }

        if (std.mem.eql(u8, arg, "--hotkey")) {
            const chord_str = args.next() orelse {
                try stdout.writeAll("--hotkey requires <chord>, e.g. \"ctrl+shift+f12\"\n");
                std.process.exit(2);
            };
            try hotkeyDemo(allocator, stdout, chord_str);
            return;
        }

        if (std.mem.eql(u8, arg, "--dump-audio")) {
            const secs_str = args.next() orelse {
                try stdout.writeAll("--dump-audio requires <seconds>\n");
                std.process.exit(2);
            };
            const secs = std.fmt.parseInt(u32, secs_str, 10) catch {
                try stdout.writeAll("bad --dump-audio duration\n");
                std.process.exit(2);
            };
            try dumpAudio(allocator, stdout, secs);
            return;
        }

        if (std.mem.eql(u8, arg, "--say")) {
            const text = args.next() orelse {
                try stdout.writeAll("--say requires <text>\n");
                std.process.exit(2);
            };
            var say = SayOpts{};
            while (args.next()) |opt| {
                if (std.mem.eql(u8, opt, "--voice")) {
                    say.voice = args.next() orelse "";
                } else if (std.mem.eql(u8, opt, "--volume")) {
                    say.volume = std.fmt.parseInt(u32, args.next() orelse "100", 10) catch 100;
                } else if (std.mem.eql(u8, opt, "--rate")) {
                    say.rate = std.fmt.parseInt(i32, args.next() orelse "0", 10) catch 0;
                }
            }
            try sayDemo(allocator, stdout, text, say);
            return;
        }

        if (std.mem.eql(u8, arg, "--ipc-only")) {
            try ipcOnly(allocator, stdout, elevated);
            return;
        }

        if (std.mem.eql(u8, arg, "--decode-wav")) {
            try decodeWavCmd(allocator, stdout, &args);
            return;
        }

        if (std.mem.eql(u8, arg, "--listen")) {
            try listenMode(allocator, stdout, &args);
            return;
        }

        if (std.mem.eql(u8, arg, "--help") or std.mem.eql(u8, arg, "-h")) {
            try printHelp(stdout);
            return;
        }
    }

    try stdout.writeAll("\nNo action specified. Try --help.\n");
}

fn printHelp(out: anytype) !void {
    try out.writeAll(
        \\
        \\Usage: deckhand.exe [flags]
        \\
        \\  --version           print version and exit
        \\  --check-elevation   exit 0 if elevated, 1 if not
        \\  --regen-grammar     regenerate generated/commands.{gbnf,jsgf} from commands.json
        \\  --list-commands     list all loaded command IDs and phrases
        \\  --fire <id>         send the SendInput sequence for command <id>
        \\  --hotkey <chord>    register hotkey (e.g. "ctrl+shift+f12") and print when pressed
        \\  --dump-audio <sec>  capture from default mic for <sec>s, dump VAD-detected chunks to dump_NNN.wav
        \\  --say <text>        speak <text> via SAPI5 and exit. Options (after text):
        \\                        --voice <token id>  e.g. HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_EN-US_ZIRA_11.0
        \\                        --volume <0-300>    percent; 100 = normalised, >100 = boosted
        \\                        --rate <-10..10>    speaking speed
        \\  --ipc-only          start the named-pipe server (\\.\pipe\deckhand) without audio/recognizer
        \\  --listen            full voice loop (audio → Vosk → SendInput). Options:
        \\                        --hotkey <chord>   toggle listening with hotkey (starts paused)
        \\                        --stop-hotkey <chord> chord that fires stopSpeaking (e.g. "ctrl+shift+f11")
        \\                        --ipc              also start the named-pipe server
        \\                        --no-tts           disable SAPI5 acknowledgement
        \\                        --model <path>     Vosk model dir (default models\vosk-model-small-en-us)
        \\                        --grammar <path>   Vosk grammar JSON (default generated\commands.vosk.json)
        \\                        --device <id>      WASAPI capture endpoint id (default: Windows default mic)
        \\                        --tts-legacy       route TTS to PlaySoundW (Windows default device) instead of WASAPI render
        \\                        --tts-output <id>  WASAPI render endpoint id for TTS (default: Windows default speaker)
        \\                        --replay-wav <wav> (test) feed a 16 kHz WAV through the voice path once
        \\                                           a pipe client connects; repeatable
        \\  --decode-wav <wav>... decode 16 kHz 16-bit WAVs with the grammar and free-form
        \\                      recognizers; prints text, match, question verdict and latency
        \\  --help              this message
        \\
    );
}

fn regenGrammar(allocator: std.mem.Allocator, out: anytype) !void {
    const path = config.pickCommandsFile();
    try out.print("Loading commands from {s}\n", .{path});

    var set = config.loadFromFile(allocator, path) catch |err| {
        try out.print("failed to load {s}: {s}\n", .{ path, @errorName(err) });
        return err;
    };
    defer set.deinit();

    try out.print("Loaded {d} commands. Writing grammars...\n", .{set.commands.len});
    try codegen.writeAll(allocator, &set, codegen.default_output);
    try out.print("  wrote {s}\n", .{codegen.default_output.gbnf});
    try out.print("  wrote {s}\n", .{codegen.default_output.vosk_json});
}

fn listCommands(allocator: std.mem.Allocator, out: anytype) !void {
    const path = config.pickCommandsFile();
    var set = try config.loadFromFile(allocator, path);
    defer set.deinit();

    try out.print("Loaded {d} commands from {s}\n\n", .{ set.commands.len, path });
    for (set.commands) |cmd| {
        try out.print("  {s}\n    phrases: ", .{cmd.id});
        for (cmd.phrases, 0..) |p, i| {
            if (i > 0) try out.writeAll(", ");
            try out.print("\"{s}\"", .{p});
        }
        try out.writeByte('\n');
        try out.print("    action:  {s}", .{@tagName(cmd.action)});
        switch (cmd.action) {
            .tap => |a| try out.print(" {s}\n", .{a.keys}),
            .hold => |a| try out.print(" {s} ({d}ms)\n", .{ a.keys, a.duration_ms }),
            .press => |a| try out.print(" {s}\n", .{a.keys}),
            .release => |a| try out.print(" {s}\n", .{a.keys}),
            .mouse => |a| if (a.keys) |k|
                try out.print(" {s} {s} holding {s}\n", .{ a.button, a.kind, k })
            else
                try out.print(" {s} {s}\n", .{ a.button, a.kind }),
            .scroll => |a| try out.print(" {s} x{d}\n", .{ a.direction, a.amount }),
            .system => |a| try out.print(" {s} ({d} responses)\n", .{ @tagName(a.op), a.responses.len }),
        }
    }
}

fn fireCommand(allocator: std.mem.Allocator, out: anytype, id: []const u8) !void {
    if (builtin.os.tag != .windows) {
        try out.writeAll("SendInput requires Windows.\n");
        return;
    }
    const path = config.pickCommandsFile();
    var set = try config.loadFromFile(allocator, path);
    defer set.deinit();

    for (set.commands) |cmd| {
        if (!std.mem.eql(u8, cmd.id, id)) continue;
        if (cmd.action == .system) {
            try out.print("{s} is a system action ({s}); it only runs inside --listen.\n", .{ cmd.id, @tagName(cmd.action.system.op) });
            return;
        }
        try out.print("Firing {s} in 2 seconds — focus target window now.\n", .{cmd.id});
        std.time.sleep(2 * std.time.ns_per_s);
        try actions.perform(allocator, cmd.action);
        try out.writeAll("Done.\n");
        return;
    }
    try out.print("Command id not found: {s}\n", .{id});
    std.process.exit(1);
}

fn hotkeyDemo(allocator: std.mem.Allocator, out: anytype, chord_str: []const u8) !void {
    if (builtin.os.tag != .windows) {
        try out.writeAll("Hotkeys require Windows.\n");
        return;
    }
    const chord = try modifiers.parse(chord_str);
    try out.print("Registering hotkey: {s}. Press it a few times; Ctrl-C to exit.\n", .{chord_str});

    var counter: u32 = 0;
    const handle = hotkey.spawn(allocator, chord, &onHotkey, &counter) catch |err| {
        try out.print("hotkey registration failed: {s} (is another app already bound to this chord?)\n", .{@errorName(err)});
        return;
    };
    _ = handle;

    // Sleep in a loop; the hotkey callback runs on its own thread.
    while (true) std.time.sleep(1 * std.time.ns_per_s);
}

const DumpCtx = struct {
    vad: *vad_mod.Vad,
    chunk_idx: u32 = 0,
    out: std.fs.File.Writer,
};

fn dumpAudio(allocator: std.mem.Allocator, out: anytype, seconds: u32) !void {
    if (builtin.os.tag != .windows) {
        try out.writeAll("Audio capture requires Windows.\n");
        return;
    }

    var cap = wasapi.Capture.open(null) catch |err| {
        try out.print("failed to open capture device: {s}\n", .{@errorName(err)});
        return;
    };
    defer cap.close();

    try out.print(
        "Capture format: {d} Hz, {d} ch, {s} — resampling to 16 kHz mono i16 for VAD.\n",
        .{ cap.format.sample_rate, cap.format.channels, if (cap.format.is_float) "float32" else "int16" },
    );

    var vad = vad_mod.Vad.init(allocator, .{});
    defer vad.deinit();

    var ctx = DumpCtx{ .vad = &vad, .out = out };

    try cap.start();
    defer cap.stop();

    try out.print("Recording for {d}s. Speak now.\n", .{seconds});

    const start_ms = std.time.milliTimestamp();
    const end_ms = start_ms + @as(i64, seconds) * 1000;

    var resample_buf: [8192]i16 = undefined;
    while (std.time.milliTimestamp() < end_ms) {
        _ = cap.poll(&resample_buf, dumpCallback, &ctx) catch |err| {
            try out.print("poll error: {s}\n", .{@errorName(err)});
            break;
        };
        std.time.sleep(10 * std.time.ns_per_ms);
    }

    try out.print("Done. Emitted {d} chunk(s).\n", .{ctx.chunk_idx});
}

fn dumpCallback(samples: []const i16, user: ?*anyopaque) void {
    const ctx: *DumpCtx = @ptrCast(@alignCast(user.?));
    const evt = ctx.vad.feed(samples) catch return;
    switch (evt) {
        .none => {},
        .speech_start => {
            ctx.out.writeAll("[speech start]\n") catch {};
        },
        .utterance => |buf| {
            ctx.chunk_idx += 1;
            var name_buf: [64]u8 = undefined;
            const name = std.fmt.bufPrint(&name_buf, "dump_{d:0>3}.wav", .{ctx.chunk_idx}) catch return;
            wav.writeI16Mono(name, buf, wasapi.TARGET_SAMPLE_RATE) catch |err| {
                ctx.out.print("wav write failed: {s}\n", .{@errorName(err)}) catch {};
                return;
            };
            ctx.out.print("[utterance {d}: {d} samples → {s}]\n", .{ ctx.chunk_idx, buf.len, name }) catch {};
            ctx.vad.reset();
        },
    }
}

fn listenMode(allocator: std.mem.Allocator, out: anytype, args: *std.process.ArgIterator) !void {
    var replay = std.ArrayList([]const u8).init(allocator);
    defer replay.deinit();
    var opts = listen_mod.Options{
        .commands_path = config.pickCommandsFile(),
        .vosk_model_path = "models/vosk-model-small-en-us",
        .vosk_grammar_path = "generated/commands.vosk.json",
        .hotkey_chord = null,
        .ipc = false,
        .tts_enabled = true,
    };
    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--hotkey")) {
            opts.hotkey_chord = args.next() orelse return error.MissingArg;
        } else if (std.mem.eql(u8, arg, "--stop-hotkey")) {
            opts.stop_hotkey_chord = args.next() orelse return error.MissingArg;
        } else if (std.mem.eql(u8, arg, "--ipc")) {
            opts.ipc = true;
        } else if (std.mem.eql(u8, arg, "--no-tts")) {
            opts.tts_enabled = false;
        } else if (std.mem.eql(u8, arg, "--model")) {
            const p = args.next() orelse return error.MissingArg;
            opts.vosk_model_path = try allocator.dupeZ(u8, p);
        } else if (std.mem.eql(u8, arg, "--grammar")) {
            const p = args.next() orelse return error.MissingArg;
            opts.vosk_grammar_path = try allocator.dupeZ(u8, p);
        } else if (std.mem.eql(u8, arg, "--device")) {
            opts.device_id = args.next() orelse return error.MissingArg;
        } else if (std.mem.eql(u8, arg, "--tts-legacy")) {
            // Use legacy PlaySoundW TTS (default output) instead of the WASAPI render path.
            opts.tts_use_wasapi = false;
        } else if (std.mem.eql(u8, arg, "--tts-output")) {
            opts.tts_output_id = args.next() orelse return error.MissingArg;
        } else if (std.mem.eql(u8, arg, "--replay-wav")) {
            try replay.append(args.next() orelse return error.MissingArg);
        }
    }
    opts.replay_wavs = replay.items;
    try listen_mod.run(allocator, out, opts);
}

fn decodeWavCmd(allocator: std.mem.Allocator, out: anytype, args: *std.process.ArgIterator) !void {
    var model: [:0]const u8 = "models/vosk-model-small-en-us";
    var paths = std.ArrayList([]const u8).init(allocator);
    defer paths.deinit();
    while (args.next()) |arg| {
        if (std.mem.eql(u8, arg, "--model")) {
            model = args.next() orelse return error.MissingArg;
        } else {
            try paths.append(arg);
        }
    }
    if (paths.items.len == 0) {
        try out.writeAll("--decode-wav requires at least one .wav path\n");
        std.process.exit(2);
    }
    try listen_mod.decodeWav(allocator, out, model, config.pickCommandsFile(), paths.items);
}

const SayOpts = struct {
    voice: ?[]const u8 = null,
    volume: u32 = 100,
    rate: i32 = 0,
};

fn sayDemo(allocator: std.mem.Allocator, out: anytype, text: []const u8, say: SayOpts) !void {
    if (builtin.os.tag != .windows) {
        try out.writeAll("SAPI5 requires Windows.\n");
        return;
    }
    const tts = sapi5.Tts.create(allocator, .{ .play_sync = true }) catch |err| {
        try out.print("TTS init failed: {s}\n", .{@errorName(err)});
        return;
    };
    defer tts.destroy();
    tts.setVolume(say.volume);
    tts.setRate(say.rate);
    if (say.voice) |v| {
        try tts.setVoice(v);
        _ = tts.waitIdle(10_000);
        const hr = tts.last_voice_hr.load(.acquire);
        try out.print("voice hr=0x{x:0>8} ({s})\n", .{ hr, if (hr == 0) "ok" else "FAILED" });
    }
    try tts.speakForce(text);
    if (!tts.waitIdle(30_000)) try out.writeAll("TTS timed out\n");
    const samples = tts.last_samples.load(.acquire);
    const pin = tts.last_peak_in.load(.acquire);
    const pout = tts.last_peak_out.load(.acquire);
    try out.print("rendered {d} samples ({d} ms) | peak {d:.1} -> {d:.1} dBFS | loudness (RMS) {d:.1} -> {d:.1} dBFS at volume {d}%\n", .{
        samples,
        samples * 1000 / sapi5.RENDER_RATE,
        dbfs(pin),
        dbfs(pout),
        dbfs(tts.last_rms_in.load(.acquire)),
        dbfs(tts.last_rms_out.load(.acquire)),
        say.volume,
    });
}

fn dbfs(peak: u32) f64 {
    if (peak == 0) return -120.0;
    return 20.0 * std.math.log10(@as(f64, @floatFromInt(peak)) / 32767.0);
}

const IpcCtx = struct {
    server: *pipe_server.Server,
    elevated: bool,
    listening: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
    tts_enabled: std.atomic.Value(bool) = std.atomic.Value(bool).init(true),
    out: std.fs.File.Writer,
};

fn ipcOnly(allocator: std.mem.Allocator, out: anytype, elevated: bool) !void {
    if (builtin.os.tag != .windows) {
        try out.writeAll("Named pipes require Windows.\n");
        return;
    }

    var server = pipe_server.Server.init(allocator, onIpcMessage, undefined);
    defer server.deinit();

    var ctx = IpcCtx{
        .server = &server,
        .elevated = elevated,
        .out = out,
    };
    server.handler_user = &ctx;

    try server.start();
    defer server.stop();

    try out.writeAll("IPC server listening at \\\\.\\pipe\\deckhand. Ctrl-C to exit.\n");

    // Periodically send a status message so a fresh GUI sees state immediately.
    while (true) {
        std.time.sleep(2 * std.time.ns_per_s);
        server.send(.{ .status = .{
            .listening = ctx.listening.load(.acquire),
            .elevated = ctx.elevated,
            .engine = "none",
        } }) catch {};
    }
}

fn onIpcMessage(msg: protocol.Inbound, user: ?*anyopaque) void {
    const ctx: *IpcCtx = @ptrCast(@alignCast(user.?));
    switch (msg) {
        .ping => ctx.server.send(.pong) catch {},
        .set_listening => |s| {
            ctx.listening.store(s.enabled, .release);
            ctx.server.send(.{ .log = .{ .level = "info", .msg = if (s.enabled) "listening on" else "listening off" } }) catch {};
        },
        .set_tts_enabled => |s| {
            ctx.tts_enabled.store(s.enabled, .release);
        },
        .set_tts_voice, .set_tts_volume, .set_tts_rate, .speak_text, .stop_speaking, .list_tts_output_devices, .set_tts_output_device => {
            ctx.server.send(.{ .log = .{ .level = "info", .msg = "TTS settings need --listen mode" } }) catch {};
        },
        .list_audio_devices, .set_audio_device, .set_hotkey, .set_stop_hotkey => {
            ctx.server.send(.{ .log = .{ .level = "info", .msg = "audio device / hotkey control needs --listen mode" } }) catch {};
        },
        .reload_grammar, .reload_config => {
            ctx.server.send(.{ .log = .{ .level = "info", .msg = "reload requested (stub)" } }) catch {};
        },
        .trigger_command => |s| {
            ctx.server.send(.{ .command_fired = .{ .id = s.id } }) catch {};
        },
        .unknown => |t| {
            ctx.out.print("ipc: unknown message type: {s}\n", .{t}) catch {};
            ctx.server.send(.{ .log = .{ .level = "warn", .msg = "unknown message type" } }) catch {};
        },
    }
}

fn onHotkey(user: ?*anyopaque) void {
    if (user) |p| {
        const counter: *u32 = @ptrCast(@alignCast(p));
        counter.* += 1;
        std.debug.print("hotkey pressed ({d})\n", .{counter.*});
    }
}

test {
    _ = @import("elevation.zig");
    _ = @import("config.zig");
    _ = @import("grammar/codegen.zig");
    _ = @import("input/vk_map.zig");
    _ = @import("input/modifiers.zig");
    _ = @import("input/sendinput.zig");
    _ = @import("input/hotkey.zig");
    _ = @import("audio/com.zig");
    _ = @import("audio/wasapi.zig");
    _ = @import("audio/vad.zig");
    _ = @import("audio/wav.zig");
    _ = @import("tts/sapi5.zig");
    _ = @import("tts/gain.zig");
    _ = @import("tts/echo_guard.zig");
    _ = @import("tts/wasapi_out.zig");
    _ = @import("ipc/protocol.zig");
    _ = @import("ipc/pipe_server.zig");
    _ = @import("dispatch.zig");
    _ = @import("cooldown.zig");
    _ = @import("question.zig");
    _ = @import("requests.zig");
    _ = @import("actions.zig");
    _ = @import("listen.zig");
}

test "smoke" {
    try std.testing.expect(VERSION.len > 0);
}
