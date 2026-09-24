const std = @import("std");
const builtin = @import("builtin");
const build_options = @import("build_options");

const config = @import("config.zig");
const codegen = @import("grammar/codegen.zig");
const modifiers = @import("input/modifiers.zig");
const hotkey = @import("input/hotkey.zig");
const wasapi = @import("audio/wasapi.zig");
const vad_mod = @import("audio/vad.zig");
const wav = @import("audio/wav.zig");
const sapi5 = @import("tts/sapi5.zig");
const wasapi_out = @import("tts/wasapi_out.zig");
const protocol = @import("ipc/protocol.zig");
const pipe_server = @import("ipc/pipe_server.zig");
const dispatch = @import("dispatch.zig");
const actions = @import("actions.zig");
const cooldown_mod = @import("cooldown.zig");
const question = @import("question.zig");
const requests_mod = @import("requests.zig");
const recognizer = @import("recognizer/recognizer.zig");
// No-op Vosk stub keeps this file type-checking without Vosk; run() bails out early then.
const vosk = if (build_options.with_vosk) @import("recognizer/vosk.zig") else struct {
    pub const Model = struct {
        pub fn load(_: [:0]const u8, _: bool) recognizer.Error!Model {
            return recognizer.Error.InitFailed;
        }
        pub fn deinit(_: *Model) void {}
    };
    pub const Recognizer = struct {
        pub fn initGrammar(_: std.mem.Allocator, _: Model, _: []const u8) recognizer.Error!Recognizer {
            return recognizer.Error.InitFailed;
        }
        pub fn initGrammarFile(_: std.mem.Allocator, _: Model, _: [:0]const u8) recognizer.Error!Recognizer {
            return recognizer.Error.InitFailed;
        }
        pub fn initFree(_: std.mem.Allocator, _: Model) recognizer.Error!Recognizer {
            return recognizer.Error.InitFailed;
        }
        pub fn deinit(_: *Recognizer) void {}
        pub fn decode(_: *Recognizer, _: []const i16) recognizer.Error!recognizer.Result {
            return recognizer.Error.RecognizeFailed;
        }
        pub fn accept(_: *Recognizer, _: []const i16) void {}
        pub fn finish(_: *Recognizer) recognizer.Error!recognizer.Result {
            return recognizer.Error.RecognizeFailed;
        }
        pub fn abort(_: *Recognizer) void {}
    };
};

pub const Options = struct {
    commands_path: []const u8,
    vosk_model_path: [:0]const u8,
    vosk_grammar_path: [:0]const u8,
    hotkey_chord: ?[]const u8 = null,
    // Stop-speaking hotkey; bypasses the echo guard, which swallows voice "stop" over speakers.
    stop_hotkey_chord: ?[]const u8 = null,
    // WASAPI endpoint id; null / "" = Windows default capture device.
    device_id: ?[]const u8 = null,
    ipc: bool = false,
    tts_enabled: bool = true,
    // TTS engine: true = WASAPI on `tts_output_id`, false = legacy PlaySoundW (`--tts-legacy`).
    tts_use_wasapi: bool = true,
    // Initial WASAPI output device id ("" = default); ignored when tts_use_wasapi is false.
    tts_output_id: []const u8 = "",
    // --replay-wav: real-time 16 kHz WAVs replace the mic once a client connects (or after 20 s).
    replay_wavs: []const []const u8 = &.{},
};

pub const PREROLL_SAMPLES = 4000; // 250 ms @ 16 kHz

/// Fixed ring of the most recent samples.
pub const Preroll = struct {
    buf: [PREROLL_SAMPLES]i16 = undefined,
    len: usize = 0,
    head: usize = 0, // next write position

    pub fn push(self: *Preroll, samples: []const i16) void {
        for (samples) |x| {
            self.buf[self.head] = x;
            self.head = (self.head + 1) % PREROLL_SAMPLES;
            if (self.len < PREROLL_SAMPLES) self.len += 1;
        }
    }

    /// Oldest-first contents as (up to) two slices.
    pub fn slices(self: *const Preroll) [2][]const i16 {
        const start = (self.head + PREROLL_SAMPLES - self.len) % PREROLL_SAMPLES;
        if (start + self.len <= PREROLL_SAMPLES) return .{ self.buf[start .. start + self.len], &.{} };
        return .{ self.buf[start..], self.buf[0..self.head] };
    }

    pub fn clear(self: *Preroll) void {
        self.len = 0;
        self.head = 0;
    }
};

test "preroll keeps the newest samples oldest-first" {
    var p = Preroll{};
    var chunk: [3000]i16 = undefined;
    for (&chunk, 0..) |*x, i| x.* = @intCast(i);
    p.push(&chunk);
    var s = p.slices();
    try std.testing.expectEqual(@as(usize, 3000), s[0].len + s[1].len);
    try std.testing.expectEqual(@as(i16, 0), s[0][0]);
    for (&chunk, 0..) |*x, i| x.* = @intCast(3000 + i);
    p.push(&chunk); // 6000 pushed, ring holds 2000..5999
    s = p.slices();
    try std.testing.expectEqual(@as(usize, PREROLL_SAMPLES), s[0].len + s[1].len);
    try std.testing.expectEqual(@as(i16, 2000), s[0][0]);
    const last = if (s[1].len > 0) s[1][s[1].len - 1] else s[0][s[0].len - 1];
    try std.testing.expectEqual(@as(i16, 5999), last);
    p.clear();
    try std.testing.expectEqual(@as(usize, 0), p.slices()[0].len);
}

pub const Error = error{ VoskDisabled, VoskInitFailed, AudioOpenFailed, GrammarMissing } || std.mem.Allocator.Error;

// Snapshot of the open microphone, readable from the pipe thread (ping).
const MicInfo = struct {
    sample_rate: u32 = 0,
    channels: u16 = 0,
    id_buf: [512]u8 = undefined,
    id_len: usize = 0,
    name_buf: [256]u8 = undefined,
    name_len: usize = 0,
    // What the GUI asked for ("" = follow the Windows default).
    sel_buf: [512]u8 = undefined,
    sel_len: usize = 0,
};

const HotkeyInfo = struct {
    chord_buf: [64]u8 = undefined,
    chord_len: usize = 0,
    ok: bool = true,
    err: []const u8 = "",
};

fn copyInto(buf: []u8, s: []const u8) usize {
    const n = @min(buf.len, s.len);
    @memcpy(buf[0..n], s[0..n]);
    return n;
}

// Threads: main = audio/VAD/recognizers/Requests, pipe = ipcHandler; set_lock guards CommandSet.
const Runner = struct {
    allocator: std.mem.Allocator,
    out: std.fs.File.Writer,
    opts: Options,

    set_lock: std.Thread.RwLock = .{},
    set: config.CommandSet,
    set_path: []const u8,

    model: vosk.Model,
    grammar_rec: vosk.Recognizer,
    free_rec: ?vosk.Recognizer,

    capture: wasapi.Capture,
    vad: vad_mod.Vad,
    tts: ?*sapi5.Tts,
    server: ?*pipe_server.Server,
    hotkey_handle: ?*hotkey.Handle,
    stop_hotkey_handle: ?*hotkey.Handle,

    state_mutex: std.Thread.Mutex = .{},
    mic: MicInfo = .{},
    hk: HotkeyInfo = .{},
    stop_hk: HotkeyInfo = .{},

    requests: requests_mod.Requests,
    cooldown: cooldown_mod.Cooldown,

    listening: std.atomic.Value(bool),
    tts_enabled: std.atomic.Value(bool),
    stopping: std.atomic.Value(bool),
    last_audio_level_ms: i64 = 0,
    // The current VAD segment overlapped our own speech (echo guard).
    utt_guarded: bool = false,
    replay_next_ns: i128 = 0,
    // Idle-audio pre-roll: VAD triggers late and clips soft onsets ("what" -> "that").
    preroll: Preroll = .{},

    fn emitAudioLevel(self: *Runner, samples: []const i16) void {
        const now = std.time.milliTimestamp();
        if (now - self.last_audio_level_ms < 50) return;
        self.last_audio_level_ms = now;
        var peak: u16 = 0;
        for (samples) |sample| peak = @max(peak, @abs(sample));
        self.sendEvent(.{ .audio_level = .{ .peak = @as(f32, @floatFromInt(peak)) / 32768.0 } });
    }

    fn toggleListening(self: *Runner) void {
        const prev = self.listening.load(.acquire);
        self.listening.store(!prev, .release);
        self.emitStatus();
    }

    fn setListening(self: *Runner, on: bool) void {
        self.listening.store(on, .release);
        self.emitStatus();
    }

    fn setTts(self: *Runner, on: bool) void {
        self.tts_enabled.store(on, .release);
        if (self.tts) |t| t.setEnabled(on);
    }

    fn emitTtsOutputDevices(self: *Runner) void {
        // Pipe thread — safe to allocate + enumerate here.
        const mode: []const u8 = if (self.opts.tts_use_wasapi) "wasapi" else "legacy";
        var current_buf: [512]u8 = undefined;
        var current: []const u8 = current_buf[0..0];
        if (self.tts) |t| current = t.getOutputDevice(&current_buf);

        const devices = wasapi_out.listRenderDevices(self.allocator) catch |err| {
            self.log("warn", "list render devices failed: {s}", .{@errorName(err)});
            self.sendEvent(.{ .tts_output_devices = .{
                .devices = &.{},
                .current_id = current,
                .mode = mode,
            } });
            return;
        };
        defer wasapi.freeDeviceList(self.allocator, devices);
        // Reshape []DeviceInfo -> []AudioDevice for the protocol (same shape).
        var proto = self.allocator.alloc(protocol.AudioDevice, devices.len) catch {
            self.log("warn", "list render devices: out of memory", .{});
            return;
        };
        defer self.allocator.free(proto);
        for (devices, 0..) |d, i| {
            proto[i] = .{ .id = d.id, .name = d.name, .is_default = d.is_default };
        }
        self.sendEvent(.{ .tts_output_devices = .{
            .devices = proto,
            .current_id = current,
            .mode = mode,
        } });
    }

    fn applyTtsOutputDevice(self: *Runner, id: []const u8) void {
        if (!self.opts.tts_use_wasapi) {
            self.sendEvent(.{ .tts_output_device = .{
                .id = id,
                .name = "",
                .ok = false,
                .err = "backend running with --tts-legacy; WASAPI output device selection is disabled",
            } });
            return;
        }
        const t = self.tts orelse {
            self.sendEvent(.{ .tts_output_device = .{
                .id = id,
                .name = "",
                .ok = false,
                .err = "TTS unavailable",
            } });
            return;
        };
        // Reject unknown ids before storing: they'd ack ok, then break every playPcm (NoDevice).
        var name_buf: [256]u8 = undefined;
        var name: []const u8 = name_buf[0..0];
        if (id.len > 0) {
            const devices = wasapi_out.listRenderDevices(self.allocator) catch |err| {
                self.sendEvent(.{ .tts_output_device = .{ .id = id, .name = "", .ok = false, .err = @errorName(err) } });
                return;
            };
            defer wasapi.freeDeviceList(self.allocator, devices);
            const d = wasapi_out.findDevice(devices, id) orelse {
                self.sendEvent(.{ .tts_output_device = .{ .id = id, .name = "", .ok = false, .err = "NoDevice" } });
                return;
            };
            const n = @min(d.name.len, name_buf.len);
            @memcpy(name_buf[0..n], d.name[0..n]);
            name = name_buf[0..n];
        }
        t.setOutputDevice(id) catch |err| {
            self.sendEvent(.{ .tts_output_device = .{ .id = id, .name = "", .ok = false, .err = @errorName(err) } });
            return;
        };
        self.sendEvent(.{ .tts_output_device = .{
            .id = id,
            .name = name,
            .ok = true,
            .err = "",
        } });
    }

    fn speakAck(self: *Runner, cmd_id: []const u8, ack: []const u8) void {
        if (self.tts) |t| {
            t.speak(ack) catch |err| {
                self.out.print("TTS ack failed for {s}: {s}\n", .{ cmd_id, @errorName(err) }) catch {};
                self.sendEvent(.{ .log = .{ .level = "warn", .msg = "TTS acknowledgement failed (see backend log)" } });
            };
        } else {
            self.sendEvent(.{ .log = .{ .level = "warn", .msg = "TTS unavailable: SAPI voice failed to initialise" } });
        }
    }

    fn emitStatus(self: *Runner) void {
        self.sendEvent(.{ .status = .{
            .listening = self.listening.load(.acquire),
            .elevated = true,
            .engine = "vosk",
        } });
    }

    fn sendEvent(self: *Runner, msg: protocol.Outbound) void {
        if (self.server) |s| s.send(msg) catch {};
    }

    fn log(self: *Runner, level: []const u8, comptime fmt: []const u8, args: anytype) void {
        var buf: [512]u8 = undefined;
        const msg = std.fmt.bufPrint(&buf, fmt, args) catch fmt;
        self.out.print("[{s}] {s}\n", .{ level, msg }) catch {};
        self.sendEvent(.{ .log = .{ .level = level, .msg = msg } });
    }

    fn emitMicReady(self: *Runner) void {
        self.state_mutex.lock();
        defer self.state_mutex.unlock();
        self.sendEvent(.{ .mic_ready = .{
            .sample_rate = self.mic.sample_rate,
            .channels = self.mic.channels,
            .device_id = self.mic.id_buf[0..self.mic.id_len],
            .device_name = self.mic.name_buf[0..self.mic.name_len],
        } });
    }

    fn emitHotkeyStatus(self: *Runner) void {
        self.state_mutex.lock();
        defer self.state_mutex.unlock();
        self.sendEvent(.{ .hotkey_status = .{
            .chord = self.hk.chord_buf[0..self.hk.chord_len],
            .ok = self.hk.ok,
            .err = self.hk.err,
        } });
    }

    fn emitStopHotkeyStatus(self: *Runner) void {
        self.state_mutex.lock();
        defer self.state_mutex.unlock();
        self.sendEvent(.{ .stop_hotkey_status = .{
            .chord = self.stop_hk.chord_buf[0..self.stop_hk.chord_len],
            .ok = self.stop_hk.ok,
            .err = self.stop_hk.err,
        } });
    }

    fn recordMic(self: *Runner, selection: []const u8) void {
        self.state_mutex.lock();
        defer self.state_mutex.unlock();
        self.mic.sample_rate = self.capture.format.sample_rate;
        self.mic.channels = self.capture.format.channels;
        self.mic.id_len = copyInto(&self.mic.id_buf, self.capture.deviceId());
        self.mic.name_len = copyInto(&self.mic.name_buf, self.capture.deviceName());
        self.mic.sel_len = copyInto(&self.mic.sel_buf, selection);
    }

    // ---- main-thread request handlers ----

    fn processRequests(self: *Runner) void {
        var b = self.requests.take();
        defer b.deinit(self.allocator);
        if (b.isEmpty()) return;
        if (b.reload) self.reloadConfig();
        if (b.device) |id| self.switchDevice(id);
        if (b.list_devices) self.sendDeviceList();
        if (b.hotkey) |c| self.applyHotkey(c);
        if (b.stop_hotkey) |c| self.applyStopHotkey(c);
    }

    fn reloadConfig(self: *Runner) void {
        const path = config.pickCommandsFile();
        var diag = config.Diag{};
        var new_set = config.loadFromFileDiag(self.allocator, path, &diag) catch |err| {
            if (diag.index) |i| {
                self.log("error", "reload failed: {s} in command #{d} '{s}' of {s}; previous config kept", .{ @errorName(err), i, diag.id(), path });
            } else {
                self.log("error", "reload failed: {s} ({s}); previous config kept", .{ @errorName(err), path });
            }
            return;
        };

        var grammar = std.ArrayList(u8).init(self.allocator);
        defer grammar.deinit();
        codegen.writeVoskJson(grammar.writer(), new_set.commands) catch {
            new_set.deinit();
            self.log("error", "reload failed: out of memory building grammar; previous config kept", .{});
            return;
        };
        const t0 = std.time.milliTimestamp();
        const new_rec = vosk.Recognizer.initGrammar(self.allocator, self.model, grammar.items) catch |err| {
            new_set.deinit();
            self.log("error", "reload failed: grammar recognizer: {s}; previous config kept", .{@errorName(err)});
            return;
        };
        const build_ms = std.time.milliTimestamp() - t0;
        // Keep generated/ in sync for tooling (--regen-grammar parity); not fatal.
        codegen.writeAll(self.allocator, &new_set, codegen.default_output) catch |err| {
            self.out.print("warn: could not write generated grammar files: {s}\n", .{@errorName(err)}) catch {};
        };

        self.set_lock.lock();
        var old_set = self.set;
        self.set = new_set;
        self.set_path = path;
        self.set_lock.unlock();
        old_set.deinit();

        self.grammar_rec.deinit();
        self.grammar_rec = new_rec;
        self.vad.reset();
        self.utt_guarded = false;

        const n_cmds = self.set.commands.len;
        const n_phrases = self.set.phraseCount();
        self.out.print("config reloaded from {s}: {d} commands, {d} phrases (grammar built in {d} ms)\n", .{ path, n_cmds, n_phrases, build_ms }) catch {};
        self.sendEvent(.{ .config_reloaded = .{ .commands = n_cmds, .phrases = n_phrases, .path = path } });
    }

    fn switchDevice(self: *Runner, id: []const u8) void {
        var new_cap = wasapi.Capture.open(if (id.len == 0) null else id) catch |err| {
            self.log("error", "audio device open failed ({s}): {s}; keeping current microphone", .{ if (id.len == 0) "Windows default" else id, @errorName(err) });
            return;
        };
        new_cap.start() catch |err| {
            new_cap.close();
            self.log("error", "audio device start failed: {s}; keeping current microphone", .{@errorName(err)});
            return;
        };
        self.capture.stop();
        self.capture.close();
        self.capture = new_cap;
        // New mic, new noise floor.
        self.vad.recalibrate();
        self.utt_guarded = false;
        self.recordMic(id);
        self.out.print("audio device -> {s} [{s}] {d} Hz {d} ch\n", .{ self.capture.deviceName(), self.capture.deviceId(), self.capture.format.sample_rate, self.capture.format.channels }) catch {};
        self.emitMicReady();
    }

    fn sendDeviceList(self: *Runner) void {
        const list = wasapi.listCaptureDevices(self.allocator) catch |err| {
            self.log("error", "listing audio devices failed: {s}", .{@errorName(err)});
            return;
        };
        defer wasapi.freeDeviceList(self.allocator, list);
        const devs = self.allocator.alloc(protocol.AudioDevice, list.len) catch return;
        defer self.allocator.free(devs);
        for (list, devs) |d, *o| o.* = .{ .id = d.id, .name = d.name, .is_default = d.is_default };
        self.state_mutex.lock();
        defer self.state_mutex.unlock();
        self.sendEvent(.{ .audio_devices = .{ .devices = devs, .current_id = self.mic.sel_buf[0..self.mic.sel_len] } });
    }

    fn applyHotkey(self: *Runner, chord_raw: []const u8) void {
        const chord = std.mem.trim(u8, chord_raw, " \t");
        if (self.hotkey_handle) |h| {
            h.stop();
            self.hotkey_handle = null;
        }
        var ok = true;
        var err_text: []const u8 = "";
        if (chord.len > 0) {
            if (modifiers.parse(chord)) |c| {
                if (hotkey.spawn(self.allocator, c, onHotkeyToggle, self)) |h| {
                    self.hotkey_handle = h;
                } else |e| {
                    ok = false;
                    err_text = hotkey.errorText(e);
                }
            } else |_| {
                ok = false;
                err_text = "invalid chord";
            }
        }
        {
            self.state_mutex.lock();
            defer self.state_mutex.unlock();
            self.hk.chord_len = copyInto(&self.hk.chord_buf, chord);
            self.hk.ok = ok;
            self.hk.err = err_text;
        }
        if (chord.len == 0) {
            self.out.writeAll("hotkey disabled\n") catch {};
        } else if (ok) {
            self.out.print("Hotkey to toggle listening: {s}\n", .{chord}) catch {};
        } else {
            // Non-fatal: the GUI's Listening toggle still works.
            self.out.print("hotkey {s} registration failed (continuing without): {s}\n", .{ chord, err_text }) catch {};
        }
        self.emitHotkeyStatus();
    }

    fn applyStopHotkey(self: *Runner, chord_raw: []const u8) void {
        const chord = std.mem.trim(u8, chord_raw, " \t");
        if (self.stop_hotkey_handle) |h| {
            h.stop();
            self.stop_hotkey_handle = null;
        }
        var ok = true;
        var err_text: []const u8 = "";
        if (chord.len > 0) {
            if (modifiers.parse(chord)) |c| {
                if (hotkey.spawn(self.allocator, c, onStopHotkey, self)) |h| {
                    self.stop_hotkey_handle = h;
                } else |e| {
                    ok = false;
                    err_text = hotkey.errorText(e);
                }
            } else |_| {
                ok = false;
                err_text = "invalid chord";
            }
        }
        {
            self.state_mutex.lock();
            defer self.state_mutex.unlock();
            self.stop_hk.chord_len = copyInto(&self.stop_hk.chord_buf, chord);
            self.stop_hk.ok = ok;
            self.stop_hk.err = err_text;
        }
        if (chord.len == 0) {
            self.out.writeAll("stop-speaking hotkey disabled\n") catch {};
        } else if (ok) {
            self.out.print("Hotkey to stop speaking: {s}\n", .{chord}) catch {};
        } else {
            self.out.print("stop-speaking hotkey {s} registration failed (continuing without): {s}\n", .{ chord, err_text }) catch {};
        }
        self.emitStopHotkeyStatus();
    }

    // ---- recognition ----

    fn replay(self: *Runner, paths: []const []const u8) void {
        const silence = [_]i16{0} ** 160;
        self.replay_next_ns = std.time.nanoTimestamp();
        // Let the VAD calibrate on digital silence first.
        for (0..40) |_| self.replayBlock(&silence);
        for (paths) |path| {
            const bytes = std.fs.cwd().readFileAlloc(self.allocator, path, 64 << 20) catch |err| {
                self.log("error", "replay: cannot read {s}: {s}", .{ path, @errorName(err) });
                continue;
            };
            defer self.allocator.free(bytes);
            var pcm = wav.parseI16(self.allocator, bytes) catch |err| {
                self.log("error", "replay: {s}: {s}", .{ path, @errorName(err) });
                continue;
            };
            defer pcm.deinit(self.allocator);
            self.log("info", "replay: {s}", .{std.fs.path.basename(path)});
            var off: usize = 0;
            while (off < pcm.samples.len) : (off += 160) self.replayBlock(pcm.samples[off..@min(off + 160, pcm.samples.len)]);
            for (0..70) |_| self.replayBlock(&silence); // 700 ms: ends the utterance
        }
        self.log("info", "replay: done", .{});
    }

    fn replayBlock(self: *Runner, blk: []const i16) void {
        audioCallback(blk, self);
        self.processRequests();
        // Pace by deadline (Windows sleep is ~15.6 ms) so guard/cooldown timing is realistic.
        self.replay_next_ns += @divTrunc(@as(i128, @intCast(blk.len)) * std.time.ns_per_s, wasapi.TARGET_SAMPLE_RATE);
        const now = std.time.nanoTimestamp();
        if (self.replay_next_ns > now) std.time.sleep(@intCast(self.replay_next_ns - now));
    }

    // Stream both recognizers during speech so only the final flush remains (vosk.zig accept()).
    fn streamBegin(self: *Runner) void {
        self.grammar_rec.abort();
        if (self.free_rec) |*fr| fr.abort();
    }

    fn streamFeed(self: *Runner, samples: []const i16) void {
        self.grammar_rec.accept(samples);
        // Free-form decoding is skipped while our own speech is audible.
        if (!self.utt_guarded) {
            if (self.free_rec) |*fr| fr.accept(samples);
        }
    }

    fn onUtterance(self: *Runner, audio_ms: usize, guarded: bool) void {
        if (!build_options.with_vosk) return;
        if (guarded) {
            if (self.free_rec) |*fr| fr.abort();
            return self.onGuardedUtterance();
        }

        const t0 = std.time.nanoTimestamp();
        const g = self.grammar_rec.finish() catch return;
        const t1 = std.time.nanoTimestamp();
        var free_text: []const u8 = "";
        if (self.free_rec) |*fr| {
            if (fr.finish()) |f| free_text = f.text else |_| {}
        }
        const t2 = std.time.nanoTimestamp();
        self.out.print("utterance {d} ms: grammar flush {d} ms \"{s}\" | free-form flush {d} ms \"{s}\"\n", .{
            audio_ms,
            @divTrunc(t1 - t0, std.time.ns_per_ms),
            g.text,
            @divTrunc(t2 - t1, std.time.ns_per_ms),
            free_text,
        }) catch {};

        self.set_lock.lockShared();
        defer self.set_lock.unlockShared();

        // Question: fire nothing, unless it's an exact command phrase ("show cargo").
        if (question.startsWithLead(free_text) and dispatch.matchExact(self.set.commands, free_text) == null) {
            self.sendEvent(.{ .transcript_final = .{ .text = free_text, .confidence = 0.95 } });
            self.sendEvent(.{ .question = .{ .text = free_text } });
            return;
        }

        if (g.text.len == 0) return;
        self.sendEvent(.{ .transcript_final = .{ .text = g.text, .confidence = g.confidence } });

        var scratch: [256]u8 = undefined;
        const match_idx = dispatch.matchCommand(self.set.commands, g.text, &scratch) orelse {
            self.sendEvent(.{ .no_match = .{ .text = g.text } });
            return;
        };
        const cmd = self.set.commands[match_idx];
        if (!self.cooldown.tryFire(cmd.id, std.time.milliTimestamp())) {
            self.log("info", "cooldown: {s} ignored (fired < {d} ms ago)", .{ cmd.id, cooldown_mod.WINDOW_MS });
            return;
        }
        self.fire(cmd);
    }

    // While our own TTS is audible only a stop_speaking command may act.
    fn onGuardedUtterance(self: *Runner) void {
        const g = self.grammar_rec.finish() catch return;
        if (g.text.len == 0) return;
        self.set_lock.lockShared();
        defer self.set_lock.unlockShared();
        var scratch: [256]u8 = undefined;
        const idx = dispatch.matchCommand(self.set.commands, g.text, &scratch) orelse return;
        const cmd = self.set.commands[idx];
        if (!config.isStopSpeaking(cmd.action)) return;
        if (!self.cooldown.tryFire(cmd.id, std.time.milliTimestamp())) return;
        self.sendEvent(.{ .transcript_final = .{ .text = g.text, .confidence = g.confidence } });
        self.fire(cmd);
    }

    /// Perform a command. Caller holds `set_lock` (shared is enough).
    fn fire(self: *Runner, cmd: config.Command) void {
        switch (cmd.action) {
            .system => |sys| self.fireSystem(cmd, sys.op, sys.responses),
            else => {
                actions.perform(self.allocator, cmd.action) catch |err| {
                    self.log("warn", "command {s} failed: {s}", .{ cmd.id, @errorName(err) });
                    return;
                };
                self.sendEvent(.{ .command_fired = .{ .id = cmd.id } });
                if (cmd.tts_ack) |ack| self.speakAck(cmd.id, ack);
            },
        }
    }

    fn fireSystem(self: *Runner, cmd: config.Command, op: config.SystemOp, responses: []const []const u8) void {
        self.sendEvent(.{ .command_fired = .{ .id = cmd.id } });
        switch (op) {
            .stop_listening => {
                self.setListening(false);
                if (cmd.tts_ack) |ack| self.speakAck(cmd.id, ack);
            },
            .stop_speaking => if (self.tts) |t| t.stopSpeaking(),
            .say_random => {
                if (config.pickResponse(responses, std.crypto.random) orelse cmd.tts_ack) |text| self.speakAck(cmd.id, text);
            },
        }
        self.sendEvent(.{ .system_action = .{ .op = @tagName(op), .id = cmd.id } });
    }
};

// TTS worker events (voice changed / failed) are forwarded to the GUI log.
fn onTtsEvent(user: ?*anyopaque, level: []const u8, msg: []const u8) void {
    const runner: *Runner = @ptrCast(@alignCast(user.?));
    runner.sendEvent(.{ .log = .{ .level = level, .msg = msg } });
}

pub fn run(allocator: std.mem.Allocator, out: std.fs.File.Writer, opts: Options) !void {
    if (builtin.os.tag != .windows) return error.AudioOpenFailed;
    if (!build_options.with_vosk) {
        try out.writeAll(
            "Listen mode requires Vosk. Rebuild after running scripts\\fetch_models.ps1,\n" ++
                "or pass -Dvosk=true if the DLL is manually placed at vendor\\vosk-api\\libvosk.dll.\n",
        );
        return Error.VoskDisabled;
    }

    var runner = Runner{
        .allocator = allocator,
        .out = out,
        .opts = opts,
        .set = undefined,
        .set_path = opts.commands_path,
        .model = undefined,
        .grammar_rec = undefined,
        .free_rec = null,
        .capture = undefined,
        .vad = vad_mod.Vad.init(allocator, .{}),
        .tts = null,
        .server = null,
        .hotkey_handle = null,
        .stop_hotkey_handle = null,
        .requests = requests_mod.Requests.init(allocator),
        .cooldown = cooldown_mod.Cooldown.init(allocator),
        .listening = std.atomic.Value(bool).init(opts.hotkey_chord == null),
        .tts_enabled = std.atomic.Value(bool).init(opts.tts_enabled),
        .stopping = std.atomic.Value(bool).init(false),
    };
    defer runner.vad.deinit();
    defer runner.requests.deinit();
    defer runner.cooldown.deinit();

    try out.print("Loading commands from {s}\n", .{opts.commands_path});
    runner.set = try config.loadFromFile(allocator, opts.commands_path);
    // Deinit whatever set is current at exit (reload swaps it).
    defer runner.set.deinit();
    try out.print("  {d} commands, {d} phrases\n", .{ runner.set.commands.len, runner.set.phraseCount() });

    try out.writeAll("Regenerating grammars → generated/\n");
    try codegen.writeAll(allocator, &runner.set, codegen.default_output);

    try out.print("Opening Vosk model at {s}\n", .{opts.vosk_model_path});
    runner.model = vosk.Model.load(opts.vosk_model_path, true) catch return Error.VoskInitFailed;
    defer runner.model.deinit();
    runner.grammar_rec = vosk.Recognizer.initGrammarFile(allocator, runner.model, opts.vosk_grammar_path) catch return Error.VoskInitFailed;
    defer runner.grammar_rec.deinit();
    // Free-form recognizer on the same model, for question detection.
    runner.free_rec = vosk.Recognizer.initFree(allocator, runner.model) catch |err| blk: {
        try out.print("free-form recognizer init failed (questions disabled): {s}\n", .{@errorName(err)});
        break :blk null;
    };
    defer if (runner.free_rec) |*r| r.deinit();

    try out.writeAll("Opening audio capture...\n");
    var selection: []const u8 = opts.device_id orelse "";
    runner.capture = wasapi.Capture.open(opts.device_id) catch |err| blk: {
        if (selection.len == 0) return Error.AudioOpenFailed;
        try out.print("  device {s} failed ({s}); falling back to the Windows default\n", .{ selection, @errorName(err) });
        selection = "";
        break :blk wasapi.Capture.open(null) catch return Error.AudioOpenFailed;
    };
    defer runner.capture.close();
    runner.recordMic(selection);
    try out.print("  {s} [{s}]\n  {d} Hz, {d} ch, {d}-bit {s}\n", .{
        runner.capture.deviceName(),
        runner.capture.deviceId(),
        runner.capture.format.sample_rate,
        runner.capture.format.channels,
        runner.capture.format.bits_per_sample,
        if (runner.capture.format.is_float) "float" else "int",
    });

    var server_storage: pipe_server.Server = undefined;
    if (opts.ipc) {
        server_storage = pipe_server.Server.init(allocator, ipcHandler, &runner);
        runner.server = &server_storage;
    }
    defer if (opts.ipc) server_storage.deinit();

    // Create the TTS worker unless --no-tts so the GUI can enable it later; the flag gates acks.
    if (opts.tts_enabled) {
        runner.tts = sapi5.Tts.create(allocator, .{
            .use_wasapi = opts.tts_use_wasapi,
            .on_event = onTtsEvent,
            .event_user = &runner,
        }) catch |err| blk: {
            try out.print("TTS init failed (continuing without): {s}\n", .{@errorName(err)});
            break :blk null;
        };
        if (runner.tts) |t| {
            if (opts.tts_output_id.len > 0) {
                t.setOutputDevice(opts.tts_output_id) catch |err| {
                    try out.print("TTS output device set failed: {s}\n", .{@errorName(err)});
                };
            }
        }
    }
    defer if (runner.tts) |t| t.destroy();

    if (opts.ipc) {
        try server_storage.start();
        try out.writeAll("IPC listening at \\\\.\\pipe\\deckhand\n");
        runner.emitMicReady();
        runner.emitStatus();
    }
    defer if (opts.ipc) server_storage.stop();

    // Registration failure is non-fatal and reported via hotkey_status.
    runner.applyHotkey(opts.hotkey_chord orelse "");
    defer if (runner.hotkey_handle) |h| h.stop();
    runner.applyStopHotkey(opts.stop_hotkey_chord orelse "");
    defer if (runner.stop_hotkey_handle) |h| h.stop();

    try runner.capture.start();
    // Stops whichever capture is current at exit (set_audio_device swaps it).
    defer runner.capture.stop();

    runner.emitStatus();
    try out.writeAll("Ready. Ctrl-C to exit.\n");

    var poll_buf: [8192]i16 = undefined;
    const started_ms = std.time.milliTimestamp();
    var connected_ms: ?i64 = null;
    var replay_done = opts.replay_wavs.len == 0;
    while (!runner.stopping.load(.acquire)) {
        runner.processRequests();
        if (!replay_done) {
            const now = std.time.milliTimestamp();
            if (connected_ms == null and runner.server != null and runner.server.?.connected.load(.acquire)) connected_ms = now;
            if ((connected_ms != null and now - connected_ms.? > 1500) or now - started_ms > 20_000) {
                replay_done = true;
                runner.replay(opts.replay_wavs);
            }
        }
        // Poll even while paused so the GUI meter shows the mic receiving audio.
        _ = runner.capture.poll(&poll_buf, audioCallback, &runner) catch |err| {
            runner.log("error", "audio poll error: {s}", .{@errorName(err)});
            break;
        };
        std.time.sleep(10 * std.time.ns_per_ms);
    }
}

fn audioCallback(samples: []const i16, user: ?*anyopaque) void {
    const runner: *Runner = @ptrCast(@alignCast(user.?));
    runner.emitAudioLevel(samples);
    if (!runner.listening.load(.acquire)) return;
    // Echo guard: while TTS is queued/playing, utterances may only fire system/stop_speaking.
    const guard_now = if (runner.tts) |t| t.guard.active(std.time.milliTimestamp()) else false;
    if (guard_now) runner.utt_guarded = true;
    const evt = runner.vad.feed(samples) catch return;
    switch (evt) {
        .none => {
            if (runner.vad.state == .speaking) {
                runner.streamFeed(samples);
            } else {
                runner.preroll.push(samples);
                if (!guard_now) runner.utt_guarded = false;
            }
        },
        .speech_start => {
            // VAD buffer starts at this block; recognizers also get the 250 ms pre-roll.
            runner.streamBegin();
            for (runner.preroll.slices()) |pre| runner.streamFeed(pre);
            runner.preroll.clear();
            runner.streamFeed(samples);
            if (!runner.utt_guarded) runner.sendEvent(.{ .transcript_partial = .{ .text = "(speech detected)" } });
        },
        .utterance => |buf| {
            runner.streamFeed(samples);
            const guarded = runner.utt_guarded;
            runner.onUtterance(buf.len * 1000 / wasapi.TARGET_SAMPLE_RATE, guarded);
            runner.vad.reset();
            runner.utt_guarded = false;
        },
    }
}

fn onHotkeyToggle(user: ?*anyopaque) void {
    const runner: *Runner = @ptrCast(@alignCast(user.?));
    runner.toggleListening();
}

fn onStopHotkey(user: ?*anyopaque) void {
    const runner: *Runner = @ptrCast(@alignCast(user.?));
    if (runner.tts) |t| t.stopSpeaking();
}

fn ipcHandler(msg: protocol.Inbound, user: ?*anyopaque) void {
    const runner: *Runner = @ptrCast(@alignCast(user.?));
    switch (msg) {
        .ping => {
            runner.emitMicReady();
            runner.emitStatus();
            runner.emitHotkeyStatus();
            runner.emitStopHotkeyStatus();
            runner.sendEvent(.pong);
        },
        .set_listening => |s| runner.setListening(s.enabled),
        .set_tts_enabled => |s| runner.setTts(s.enabled),
        .set_tts_voice => |s| if (runner.tts) |t| {
            t.setVoice(s.id) catch {};
        },
        .set_tts_volume => |s| if (runner.tts) |t| t.setVolume(s.volume),
        .set_tts_rate => |s| if (runner.tts) |t| t.setRate(s.rate),
        .speak_text => |s| if (runner.tts) |t| {
            t.speakForce(s.text) catch {};
        } else {
            runner.sendEvent(.{ .log = .{ .level = "warn", .msg = "TTS unavailable: SAPI voice failed to initialise" } });
        },
        .stop_speaking => if (runner.tts) |t| t.stopSpeaking(),
        .reload_grammar, .reload_config => runner.requests.requestReload(),
        .list_audio_devices => runner.requests.requestDeviceList(),
        .set_audio_device => |s| runner.requests.requestDevice(s.id) catch {
            runner.log("error", "set_audio_device: out of memory", .{});
        },
        .list_tts_output_devices => runner.emitTtsOutputDevices(),
        .set_tts_output_device => |s| runner.applyTtsOutputDevice(s.id),
        .set_hotkey => |s| runner.requests.requestHotkey(s.chord) catch {
            runner.log("error", "set_hotkey: out of memory", .{});
        },
        .set_stop_hotkey => |s| runner.requests.requestStopHotkey(s.chord) catch {
            runner.log("error", "set_stop_hotkey: out of memory", .{});
        },
        .trigger_command => |s| {
            // GUI triggers bypass the voice cooldown.
            runner.set_lock.lockShared();
            defer runner.set_lock.unlockShared();
            for (runner.set.commands) |cmd| {
                if (std.mem.eql(u8, cmd.id, s.id)) {
                    runner.fire(cmd);
                    return;
                }
            }
            runner.log("warn", "trigger_command: unknown command id '{s}'", .{s.id});
        },
        .unknown => |t| runner.log("warn", "unknown message type: {s}", .{t}),
    }
}

// ---- --decode-wav: offline latency / accuracy check for both recognizers ----

pub fn decodeWav(
    allocator: std.mem.Allocator,
    out: std.fs.File.Writer,
    model_path: [:0]const u8,
    commands_path: []const u8,
    wav_paths: []const []const u8,
) !void {
    if (!build_options.with_vosk) return Error.VoskDisabled;
    var set = try config.loadFromFile(allocator, commands_path);
    defer set.deinit();
    var grammar = std.ArrayList(u8).init(allocator);
    defer grammar.deinit();
    try codegen.writeVoskJson(grammar.writer(), set.commands);

    var t = std.time.milliTimestamp();
    var model = vosk.Model.load(model_path, true) catch return Error.VoskInitFailed;
    defer model.deinit();
    try out.print("model load {d} ms\n", .{std.time.milliTimestamp() - t});
    t = std.time.milliTimestamp();
    var g_rec = vosk.Recognizer.initGrammar(allocator, model, grammar.items) catch return Error.VoskInitFailed;
    defer g_rec.deinit();
    try out.print("grammar recognizer build {d} ms ({d} phrases)\n", .{ std.time.milliTimestamp() - t, set.phraseCount() });
    t = std.time.milliTimestamp();
    var f_rec = vosk.Recognizer.initFree(allocator, model) catch return Error.VoskInitFailed;
    defer f_rec.deinit();
    try out.print("free-form recognizer build {d} ms\n", .{std.time.milliTimestamp() - t});

    for (wav_paths) |path| {
        const bytes = try std.fs.cwd().readFileAlloc(allocator, path, 64 << 20);
        defer allocator.free(bytes);
        var pcm = try wav.parseI16(allocator, bytes);
        defer pcm.deinit(allocator);
        if (pcm.sample_rate != wasapi.TARGET_SAMPLE_RATE) {
            try out.print("{s}: {d} Hz (need 16000), skipped\n", .{ path, pcm.sample_rate });
            continue;
        }
        const audio_ms = pcm.samples.len * 1000 / wasapi.TARGET_SAMPLE_RATE;
        // Stream 10 ms blocks like the listener, timing only the final flush (post-speech wait).
        {
            g_rec.abort();
            f_rec.abort();
            var feed_g: i128 = 0;
            var feed_f: i128 = 0;
            var off: usize = 0;
            while (off < pcm.samples.len) : (off += 160) {
                const blk = pcm.samples[off..@min(off + 160, pcm.samples.len)];
                const a = std.time.nanoTimestamp();
                g_rec.accept(blk);
                const b = std.time.nanoTimestamp();
                f_rec.accept(blk);
                feed_f += std.time.nanoTimestamp() - b;
                feed_g += b - a;
            }
            const t0 = std.time.nanoTimestamp();
            const g = try g_rec.finish();
            const t1 = std.time.nanoTimestamp();
            const f = try f_rec.finish();
            const t2 = std.time.nanoTimestamp();
            try out.print("{s} [{d} ms audio, STREAMED] flush after end of speech: grammar {d:.1} ms \"{s}\" + free-form {d:.1} ms \"{s}\" (feeding during speech: grammar {d:.0} ms, free-form {d:.0} ms total)\n", .{
                std.fs.path.basename(path),
                audio_ms,
                @as(f64, @floatFromInt(t1 - t0)) / 1e6,
                g.text,
                @as(f64, @floatFromInt(t2 - t1)) / 1e6,
                f.text,
                @as(f64, @floatFromInt(feed_g)) / 1e6,
                @as(f64, @floatFromInt(feed_f)) / 1e6,
            });
        }
        // Batch decode of the whole utterance: first pass is cold, second warm.
        for (0..2) |pass| {
            const t0 = std.time.nanoTimestamp();
            const g = try g_rec.decode(pcm.samples);
            const t1 = std.time.nanoTimestamp();
            const f = try f_rec.decode(pcm.samples);
            const t2 = std.time.nanoTimestamp();
            var scratch: [256]u8 = undefined;
            const is_q = question.startsWithLead(f.text) and dispatch.matchExact(set.commands, f.text) == null;
            const m = dispatch.matchCommand(set.commands, g.text, &scratch);
            try out.print("{s} [{d} ms audio, pass {d}] grammar {d:.1} ms \"{s}\" -> {s} | free-form {d:.1} ms \"{s}\" -> {s}\n", .{
                std.fs.path.basename(path),
                audio_ms,
                pass + 1,
                @as(f64, @floatFromInt(t1 - t0)) / 1e6,
                g.text,
                if (m) |i| set.commands[i].id else "(no match)",
                @as(f64, @floatFromInt(t2 - t1)) / 1e6,
                f.text,
                if (is_q) "QUESTION" else "not a question",
            });
        }
    }
}
