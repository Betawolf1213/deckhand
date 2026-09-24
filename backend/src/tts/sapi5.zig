const std = @import("std");
const windows = std.os.windows;
const com = @import("../audio/com.zig");
const gain = @import("gain.zig");
const echo_guard = @import("echo_guard.zig");
const wasapi_out = @import("wasapi_out.zig");

// SAPI5 TTS: ISpVoice renders to memory, gain.zig boosts past SAPI's 100%; COM on one MTA worker.

pub const CLSID_SpVoice = com.GUID{
    .Data1 = 0x96749377, .Data2 = 0x3391, .Data3 = 0x11D2,
    .Data4 = .{ 0x9E, 0xE3, 0x00, 0xC0, 0x4F, 0x79, 0x73, 0x96 },
};
pub const IID_ISpVoice = com.GUID{
    .Data1 = 0x6C44DF74, .Data2 = 0x72B9, .Data3 = 0x4992,
    .Data4 = .{ 0xA1, 0xEC, 0xEF, 0x99, 0x6E, 0x04, 0x22, 0xD4 },
};
pub const CLSID_SpStream = com.GUID{
    .Data1 = 0x715D9C59, .Data2 = 0x4442, .Data3 = 0x11D2,
    .Data4 = .{ 0x96, 0x05, 0x00, 0xC0, 0x4F, 0x8E, 0xE6, 0x28 },
};
pub const IID_ISpStream = com.GUID{
    .Data1 = 0x12E3CCA9, .Data2 = 0x7518, .Data3 = 0x44C5,
    .Data4 = .{ 0xA5, 0xE7, 0xBA, 0x5A, 0x79, 0xCB, 0x92, 0x9E },
};
pub const CLSID_SpObjectToken = com.GUID{
    .Data1 = 0xEF411752, .Data2 = 0x3736, .Data3 = 0x4CB4,
    .Data4 = .{ 0x9C, 0x8C, 0x8E, 0xF4, 0xCC, 0xB5, 0x8E, 0xFE },
};
pub const IID_ISpObjectToken = com.GUID{
    .Data1 = 0x14056589, .Data2 = 0xE16C, .Data3 = 0x11D2,
    .Data4 = .{ 0xBB, 0x90, 0x00, 0xC0, 0x4F, 0x8E, 0xE6, 0xC0 },
};
pub const SPDFID_WaveFormatEx = com.GUID{
    .Data1 = 0xC31ADBAE, .Data2 = 0x527F, .Data3 = 0x4FF5,
    .Data4 = .{ 0xA2, 0x30, 0xF6, 0x2B, 0xB6, 0x1F, 0xF7, 0x0C },
};

pub const SPF_DEFAULT: u32 = 0;
pub const SPF_ASYNC: u32 = 1;
pub const SPF_PURGEBEFORESPEAK: u32 = 2;
pub const SPF_IS_XML: u32 = 8;

pub const RENDER_RATE: u32 = 22050;

const SND_SYNC: u32 = 0x0000;
const SND_ASYNC: u32 = 0x0001;
const SND_NODEFAULT: u32 = 0x0002;
const SND_MEMORY: u32 = 0x0004;
const STREAM_SEEK_CUR: u32 = 1;

extern "winmm" fn PlaySoundW(pszSound: ?*const anyopaque, hmod: ?*anyopaque, fdwSound: u32) callconv(windows.WINAPI) windows.BOOL;
extern "ole32" fn CreateStreamOnHGlobal(hGlobal: ?*anyopaque, fDeleteOnRelease: windows.BOOL, ppstm: *?*IStream) callconv(windows.WINAPI) com.HRESULT;
extern "ole32" fn GetHGlobalFromStream(pstm: *IStream, phglobal: *?*anyopaque) callconv(windows.WINAPI) com.HRESULT;
extern "kernel32" fn GlobalLock(hMem: ?*anyopaque) callconv(windows.WINAPI) ?*anyopaque;
extern "kernel32" fn GlobalUnlock(hMem: ?*anyopaque) callconv(windows.WINAPI) windows.BOOL;

// C WAVEFORMATEX is 18 bytes; Zig pads to 20, harmless since SAPI reads only 18 (cbSize = 0).
const WAVEFORMATEX = extern struct {
    wFormatTag: u16,
    nChannels: u16,
    nSamplesPerSec: u32,
    nAvgBytesPerSec: u32,
    nBlockAlign: u16,
    wBitsPerSample: u16,
    cbSize: u16,
};

pub const IStream = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const anyopaque,
        AddRef: *const anyopaque,
        Release: *const fn (*IStream) callconv(windows.WINAPI) u32,
        Read: *const anyopaque,
        Write: *const anyopaque,
        Seek: *const fn (*IStream, i64, u32, ?*u64) callconv(windows.WINAPI) com.HRESULT,
        SetSize: *const anyopaque,
        CopyTo: *const anyopaque,
        Commit: *const anyopaque,
        Revert: *const anyopaque,
        LockRegion: *const anyopaque,
        UnlockRegion: *const anyopaque,
        Stat: *const anyopaque,
        Clone: *const anyopaque,
    };
};

pub const ISpStream = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        // IUnknown
        QueryInterface: *const anyopaque,
        AddRef: *const anyopaque,
        Release: *const fn (*ISpStream) callconv(windows.WINAPI) u32,
        // ISequentialStream + IStream
        Read: *const anyopaque,
        Write: *const anyopaque,
        Seek: *const anyopaque,
        SetSize: *const anyopaque,
        CopyTo: *const anyopaque,
        Commit: *const anyopaque,
        Revert: *const anyopaque,
        LockRegion: *const anyopaque,
        UnlockRegion: *const anyopaque,
        Stat: *const anyopaque,
        Clone: *const anyopaque,
        // ISpStreamFormat
        GetFormat: *const anyopaque,
        // ISpStream
        SetBaseStream: *const fn (*ISpStream, *IStream, *const com.GUID, *const WAVEFORMATEX) callconv(windows.WINAPI) com.HRESULT,
        GetBaseStream: *const anyopaque,
        BindToFile: *const anyopaque,
        Close: *const anyopaque,
    };
};

pub const ISpObjectToken = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        // IUnknown
        QueryInterface: *const anyopaque,
        AddRef: *const anyopaque,
        Release: *const fn (*ISpObjectToken) callconv(windows.WINAPI) u32,
        // ISpDataKey
        SetData: *const anyopaque,
        GetData: *const anyopaque,
        SetStringValue: *const anyopaque,
        GetStringValue: *const anyopaque,
        SetDWORD: *const anyopaque,
        GetDWORD: *const anyopaque,
        OpenKey: *const anyopaque,
        CreateKey: *const anyopaque,
        DeleteKey: *const anyopaque,
        DeleteValue: *const anyopaque,
        EnumKeys: *const anyopaque,
        EnumValues: *const anyopaque,
        // ISpObjectToken
        SetId: *const fn (*ISpObjectToken, ?[*:0]const u16, [*:0]const u16, windows.BOOL) callconv(windows.WINAPI) com.HRESULT,
        GetId: *const anyopaque,
        GetCategory: *const anyopaque,
        CreateInstance: *const anyopaque,
        GetStorageFileName: *const anyopaque,
        RemoveStorageFileName: *const anyopaque,
        Remove: *const anyopaque,
        IsUISupported: *const anyopaque,
        DisplayUI: *const anyopaque,
        MatchesAttributes: *const anyopaque,
    };
};

pub const ISpVoice = extern struct {
    lpVtbl: *const VTable,

    // Vtable order matches ISpVoice as documented in sapi.h.
    pub const VTable = extern struct {
        // IUnknown
        QueryInterface: *const fn (*ISpVoice, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        AddRef: *const fn (*ISpVoice) callconv(windows.WINAPI) u32,
        Release: *const fn (*ISpVoice) callconv(windows.WINAPI) u32,

        // ISpNotifySource
        SetNotifySink: *const anyopaque,
        SetNotifyWindowMessage: *const anyopaque,
        SetNotifyCallbackFunction: *const anyopaque,
        SetNotifyCallbackInterface: *const anyopaque,
        SetNotifyWin32Event: *const anyopaque,
        WaitForNotifyEvent: *const anyopaque,
        GetNotifyEventHandle: *const anyopaque,

        // ISpEventSource
        SetInterest: *const anyopaque,
        GetEvents: *const anyopaque,
        GetInfo: *const anyopaque,

        // ISpVoice inherits ISpEventSource, NOT ISpEventSink: extra slots shift Speak() -> crash.
        SetOutput: *const fn (*ISpVoice, ?*anyopaque, windows.BOOL) callconv(windows.WINAPI) com.HRESULT,
        GetOutputObjectToken: *const anyopaque,
        GetOutputStream: *const anyopaque,
        Pause: *const fn (*ISpVoice) callconv(windows.WINAPI) com.HRESULT,
        Resume: *const fn (*ISpVoice) callconv(windows.WINAPI) com.HRESULT,
        SetVoice: *const fn (*ISpVoice, ?*ISpObjectToken) callconv(windows.WINAPI) com.HRESULT,
        GetVoice: *const anyopaque,
        Speak: *const fn (*ISpVoice, [*:0]const u16, u32, ?*u32) callconv(windows.WINAPI) com.HRESULT,
        SpeakStream: *const anyopaque,
        GetStatus: *const anyopaque,
        Skip: *const anyopaque,
        SetPriority: *const anyopaque,
        GetPriority: *const anyopaque,
        SetAlertBoundary: *const anyopaque,
        GetAlertBoundary: *const anyopaque,
        SetRate: *const fn (*ISpVoice, i32) callconv(windows.WINAPI) com.HRESULT,
        GetRate: *const anyopaque,
        SetVolume: *const fn (*ISpVoice, u16) callconv(windows.WINAPI) com.HRESULT,
        GetVolume: *const anyopaque,
        WaitUntilDone: *const anyopaque,
        SetSyncSpeakTimeout: *const anyopaque,
        GetSyncSpeakTimeout: *const anyopaque,
        SpeakCompleteEvent: *const anyopaque,
        IsUISupported: *const anyopaque,
        DisplayUI: *const anyopaque,
    };
};

pub const Error = error{
    CoCreateFailed,
    SpeakFailed,
    Utf16ConvertFailed,
    ThreadSpawnFailed,
} || std.mem.Allocator.Error;

// Pending TTS work; latest request of each kind wins so stale acks never back up.
pub const Mailbox = struct {
    text: ?[]u8 = null,
    voice: ?[]u8 = null,

    pub fn putText(self: *Mailbox, a: std.mem.Allocator, text: []const u8) !void {
        const copy = try a.dupe(u8, text);
        if (self.text) |old| a.free(old);
        self.text = copy;
    }
    pub fn putVoice(self: *Mailbox, a: std.mem.Allocator, id: []const u8) !void {
        const copy = try a.dupe(u8, id);
        if (self.voice) |old| a.free(old);
        self.voice = copy;
    }
    /// Drop queued speech (stop_speaking); a pending voice change is kept.
    pub fn dropText(self: *Mailbox, a: std.mem.Allocator) void {
        if (self.text) |t| a.free(t);
        self.text = null;
    }
    pub fn isEmpty(self: *const Mailbox) bool {
        return self.text == null and self.voice == null;
    }
    pub const Job = struct { text: ?[]u8, voice: ?[]u8 };
    pub fn take(self: *Mailbox) Job {
        const job = Job{ .text = self.text, .voice = self.voice };
        self.* = .{};
        return job;
    }
    pub fn deinit(self: *Mailbox, a: std.mem.Allocator) void {
        if (self.text) |t| a.free(t);
        if (self.voice) |v| a.free(v);
        self.* = .{};
    }
};

pub const EventFn = *const fn (user: ?*anyopaque, level: []const u8, msg: []const u8) void;

pub const Options = struct {
    // Block the worker until playback ends (`--say`, so the process doesn't exit mid-sentence).
    play_sync: bool = false,
    // WASAPI render (default) vs. legacy PlaySoundW to the Windows default device.
    use_wasapi: bool = true,
    on_event: ?EventFn = null,
    event_user: ?*anyopaque = null,
};

pub const Tts = struct {
    allocator: std.mem.Allocator,
    opts: Options,
    thread: std.Thread = undefined,
    mutex: std.Thread.Mutex = .{},
    cond: std.Thread.Condition = .{},
    mailbox: Mailbox = .{},
    stopping: bool = false,
    busy: bool = false,
    // Bumped by stopSpeaking(); older-generation jobs are discarded. Guarded by `mutex`.
    generation: u64 = 0,
    // 0 = starting, 1 = voice ready, 2 = failed to create SAPI voice.
    init_state: std.atomic.Value(u8) = std.atomic.Value(u8).init(0),

    enabled: std.atomic.Value(bool) = std.atomic.Value(bool).init(true),
    volume_pct: std.atomic.Value(u32) = std.atomic.Value(u32).init(100),
    rate: std.atomic.Value(i32) = std.atomic.Value(i32).init(0),

    // Output device id (UTF-8, "" = default); guarded by `mutex`, worker copies it before playPcm.
    output_device_id: []u8 = &[_]u8{},
    // Set by stopSpeaking, polled by the WASAPI render loop; cleared before each new render.
    output_stop: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),

    // Diagnostics from the most recent utterance / voice change.
    last_samples: std.atomic.Value(u32) = std.atomic.Value(u32).init(0),
    last_peak_in: std.atomic.Value(u32) = std.atomic.Value(u32).init(0),
    last_peak_out: std.atomic.Value(u32) = std.atomic.Value(u32).init(0),
    last_rms_in: std.atomic.Value(u32) = std.atomic.Value(u32).init(0),
    last_rms_out: std.atomic.Value(u32) = std.atomic.Value(u32).init(0),
    last_voice_hr: std.atomic.Value(u32) = std.atomic.Value(u32).init(0),
    // Active while our own speech is queued/playing; the listener ignores the mic.
    guard: echo_guard.EchoGuard = .{},

    pub fn create(allocator: std.mem.Allocator, opts: Options) Error!*Tts {
        const self = try allocator.create(Tts);
        self.* = .{ .allocator = allocator, .opts = opts };
        self.thread = std.Thread.spawn(.{}, workerMain, .{self}) catch {
            allocator.destroy(self);
            return Error.ThreadSpawnFailed;
        };
        // Wait (bounded) for the worker to create the SAPI voice.
        var waited: u32 = 0;
        while (self.init_state.load(.acquire) == 0 and waited < 5000) : (waited += 5) {
            std.time.sleep(5 * std.time.ns_per_ms);
        }
        if (self.init_state.load(.acquire) != 1) {
            self.destroy();
            return Error.CoCreateFailed;
        }
        return self;
    }

    pub fn destroy(self: *Tts) void {
        self.mutex.lock();
        self.stopping = true;
        self.cond.broadcast();
        self.mutex.unlock();
        self.thread.join();
        self.mailbox.deinit(self.allocator);
        if (self.output_device_id.len > 0) self.allocator.free(self.output_device_id);
        self.allocator.destroy(self);
    }

    /// Set WASAPI output device id ("" = Windows default); no-op in --tts-legacy. Thread-safe.
    pub fn setOutputDevice(self: *Tts, id: []const u8) Error!void {
        const copy = try self.allocator.dupe(u8, id);
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.output_device_id.len > 0) self.allocator.free(self.output_device_id);
        self.output_device_id = copy;
    }

    /// Copy the selected output device id into `buf` under the mutex (truncated to buf.len).
    pub fn getOutputDevice(self: *Tts, buf: []u8) []const u8 {
        self.mutex.lock();
        defer self.mutex.unlock();
        const n = @min(buf.len, self.output_device_id.len);
        @memcpy(buf[0..n], self.output_device_id[0..n]);
        return buf[0..n];
    }

    pub fn setEnabled(self: *Tts, on: bool) void {
        self.enabled.store(on, .release);
    }
    pub fn setVolume(self: *Tts, pct: u32) void {
        self.volume_pct.store(@min(pct, gain.MAX_VOLUME_PCT), .release);
    }
    pub fn setRate(self: *Tts, r: i32) void {
        self.rate.store(std.math.clamp(r, -10, 10), .release);
    }

    /// Command acknowledgement: honours the TTS on/off toggle.
    pub fn speak(self: *Tts, text: []const u8) Error!void {
        if (!self.enabled.load(.acquire)) return;
        return self.speakForce(text);
    }

    /// Explicit request (GUI "Test voice", `--say`): ignores the toggle.
    pub fn speakForce(self: *Tts, text: []const u8) Error!void {
        // Mute the mic before the worker even starts, so no echo slips through.
        self.guard.holdPending(std.time.milliTimestamp());
        self.mutex.lock();
        defer self.mutex.unlock();
        try self.mailbox.putText(self.allocator, text);
        self.cond.broadcast();
    }

    /// Stop playback now, drop queued text and release the echo guard. Safe from any thread.
    pub fn stopSpeaking(self: *Tts) void {
        // Set the stop flag OUTSIDE the mutex so a blocked playPcm poll sees it without waiting.
        self.output_stop.store(true, .release);
        self.mutex.lock();
        defer self.mutex.unlock();
        self.mailbox.dropText(self.allocator);
        self.generation +%= 1;
        // PlaySound is process-wide: cancels legacy async playback; harmless with WASAPI.
        _ = PlaySoundW(null, null, 0);
        self.guard.release(std.time.milliTimestamp());
        self.cond.broadcast();
    }

    /// Voice token id (full registry path) or "" for the Windows default.
    pub fn setVoice(self: *Tts, id: []const u8) Error!void {
        self.mutex.lock();
        defer self.mutex.unlock();
        try self.mailbox.putVoice(self.allocator, id);
        self.cond.broadcast();
    }

    /// Wait until all queued work has been processed. Returns false on timeout.
    pub fn waitIdle(self: *Tts, timeout_ms: u64) bool {
        const deadline = std.time.milliTimestamp() + @as(i64, @intCast(timeout_ms));
        self.mutex.lock();
        defer self.mutex.unlock();
        while (self.busy or !self.mailbox.isEmpty()) {
            const now = std.time.milliTimestamp();
            if (now >= deadline) return false;
            self.cond.timedWait(&self.mutex, @as(u64, @intCast(deadline - now)) * std.time.ns_per_ms) catch {};
        }
        return true;
    }

    fn emit(self: *Tts, level: []const u8, comptime fmt: []const u8, args: anytype) void {
        var buf: [256]u8 = undefined;
        const msg = std.fmt.bufPrint(&buf, fmt, args) catch return;
        std.debug.print("TTS: {s}\n", .{msg});
        if (self.opts.on_event) |f| f(self.opts.event_user, level, msg);
    }

    fn workerMain(self: *Tts) void {
        _ = com.CoInitializeEx(null, com.COINIT_MULTITHREADED);
        defer com.CoUninitialize();

        var pv: ?*anyopaque = null;
        if (!com.ok(com.CoCreateInstance(&CLSID_SpVoice, null, com.CLSCTX_ALL, &IID_ISpVoice, &pv))) {
            self.init_state.store(2, .release);
            return;
        }
        const voice: *ISpVoice = @ptrCast(@alignCast(pv.?));
        defer _ = voice.lpVtbl.Release(voice);
        self.init_state.store(1, .release);

        var last_wav: ?[]u8 = null;
        defer {
            _ = PlaySoundW(null, null, 0);
            if (last_wav) |w| self.allocator.free(w);
        }

        while (true) {
            self.mutex.lock();
            while (!self.stopping and self.mailbox.isEmpty()) self.cond.wait(&self.mutex);
            if (self.stopping) {
                self.mutex.unlock();
                break;
            }
            const job = self.mailbox.take();
            const job_gen = self.generation;
            self.busy = true;
            self.mutex.unlock();

            if (job.voice) |id| {
                self.applyVoice(voice, id);
                self.allocator.free(id);
            }
            if (job.text) |text| {
                self.guard.holdPending(std.time.milliTimestamp());
                self.renderAndPlay(voice, text, &last_wav, job_gen);
                self.allocator.free(text);
            }

            self.mutex.lock();
            self.busy = false;
            self.cond.broadcast();
            self.mutex.unlock();
        }
    }

    fn applyVoice(self: *Tts, voice: *ISpVoice, id: []const u8) void {
        if (id.len == 0) {
            const hr = voice.lpVtbl.SetVoice(voice, null);
            self.last_voice_hr.store(@bitCast(hr), .release);
            if (com.ok(hr)) self.emit("info", "voice: Windows default", .{}) else self.emit("warn", "reset voice failed: HRESULT 0x{x:0>8}", .{@as(u32, @bitCast(hr))});
            return;
        }
        const id16 = std.unicode.utf8ToUtf16LeAllocZ(self.allocator, id) catch {
            self.emit("warn", "voice id is not valid UTF-8", .{});
            return;
        };
        defer self.allocator.free(id16);

        var tpv: ?*anyopaque = null;
        var hr = com.CoCreateInstance(&CLSID_SpObjectToken, null, com.CLSCTX_ALL, &IID_ISpObjectToken, &tpv);
        if (!com.ok(hr)) {
            self.last_voice_hr.store(@bitCast(hr), .release);
            self.emit("warn", "create voice token failed: HRESULT 0x{x:0>8}", .{@as(u32, @bitCast(hr))});
            return;
        }
        const token: *ISpObjectToken = @ptrCast(@alignCast(tpv.?));
        defer _ = token.lpVtbl.Release(token);

        hr = token.lpVtbl.SetId(token, null, id16.ptr, 0);
        if (com.ok(hr)) hr = voice.lpVtbl.SetVoice(voice, token);
        self.last_voice_hr.store(@bitCast(hr), .release);
        const short = if (std.mem.lastIndexOfScalar(u8, id, '\\')) |i| id[i + 1 ..] else id;
        if (com.ok(hr)) {
            self.emit("info", "voice set: {s}", .{short});
        } else {
            self.emit("warn", "voice {s} unavailable: HRESULT 0x{x:0>8}", .{ short, @as(u32, @bitCast(hr)) });
        }
    }

    fn renderAndPlay(self: *Tts, voice: *ISpVoice, text: []const u8, last_wav: *?[]u8, job_gen: u64) void {
        const samples = self.render(voice, text) catch |err| {
            self.guard.release(std.time.milliTimestamp());
            self.emit("warn", "speech render failed: {s}", .{@errorName(err)});
            return;
        };
        defer self.allocator.free(samples);

        self.last_samples.store(@intCast(samples.len), .release);
        self.last_peak_in.store(peakAbs(samples), .release);
        self.last_rms_in.store(rmsOf(samples), .release);
        gain.applyVolume(samples, self.volume_pct.load(.acquire));
        self.last_peak_out.store(peakAbs(samples), .release);
        self.last_rms_out.store(rmsOf(samples), .release);

        const wav = gain.buildWav(self.allocator, samples, RENDER_RATE) catch {
            self.guard.release(std.time.milliTimestamp());
            return;
        };
        // Start under the mutex so stopSpeaking() cancels before or stops after, never in between.
        var started = false;
        var wasapi_device_id_owned: ?[]u8 = null;
        {
            self.mutex.lock();
            defer self.mutex.unlock();
            if (self.generation != job_gen) {
                // stop_speaking arrived while rendering: discard.
                self.allocator.free(wav);
                return;
            }
            // Cancel any prior legacy playback + free its buffer; latest ack wins.
            _ = PlaySoundW(null, null, 0);
            if (last_wav.*) |old| self.allocator.free(old);
            last_wav.* = wav;
            const duration_ms: i64 = @intCast(samples.len * 1000 / RENDER_RATE);
            self.guard.playing(std.time.milliTimestamp(), duration_ms);
            // Clear the stop flag under the mutex at render start so stopSpeaking() can't race it.
            self.output_stop.store(false, .release);
            if (self.opts.use_wasapi) {
                // Snapshot the current output device id; playPcm runs outside the mutex.
                wasapi_device_id_owned = self.allocator.dupe(u8, self.output_device_id) catch null;
            } else if (!self.opts.play_sync) {
                started = PlaySoundW(wav.ptr, null, SND_MEMORY | SND_NODEFAULT | SND_ASYNC) != 0;
            }
        }
        if (self.opts.use_wasapi) {
            defer if (wasapi_device_id_owned) |d| self.allocator.free(d);
            const dev_slice: ?[]const u8 = if (wasapi_device_id_owned) |d| d else null;
            wasapi_out.playPcm(samples, RENDER_RATE, dev_slice, &self.output_stop) catch |err| {
                self.emit("warn", "WASAPI playback failed ({s}); use --tts-legacy to fall back to PlaySoundW", .{@errorName(err)});
                self.guard.release(std.time.milliTimestamp());
                return;
            };
            started = true;
        } else if (self.opts.play_sync) {
            started = PlaySoundW(wav.ptr, null, SND_MEMORY | SND_NODEFAULT | SND_SYNC) != 0;
        }
        if (!started) {
            self.guard.release(std.time.milliTimestamp());
            self.emit("warn", "playback did not start", .{});
        }
    }

    // Synthesize `text` to 16-bit mono PCM at RENDER_RATE. Caller frees.
    fn render(self: *Tts, voice: *ISpVoice, text: []const u8) ![]i16 {
        const text16 = std.unicode.utf8ToUtf16LeAllocZ(self.allocator, text) catch return Error.Utf16ConvertFailed;
        defer self.allocator.free(text16);

        var mem: ?*IStream = null;
        if (!com.ok(CreateStreamOnHGlobal(null, 1, &mem))) return error.StreamCreateFailed;
        defer _ = mem.?.lpVtbl.Release(mem.?);

        var spv: ?*anyopaque = null;
        if (!com.ok(com.CoCreateInstance(&CLSID_SpStream, null, com.CLSCTX_ALL, &IID_ISpStream, &spv))) return error.SpStreamCreateFailed;
        const sp: *ISpStream = @ptrCast(@alignCast(spv.?));
        defer _ = sp.lpVtbl.Release(sp);

        const fmt = WAVEFORMATEX{
            .wFormatTag = 1,
            .nChannels = 1,
            .nSamplesPerSec = RENDER_RATE,
            .nAvgBytesPerSec = RENDER_RATE * 2,
            .nBlockAlign = 2,
            .wBitsPerSample = 16,
            .cbSize = 0,
        };
        if (!com.ok(sp.lpVtbl.SetBaseStream(sp, mem.?, &SPDFID_WaveFormatEx, &fmt))) return error.SetBaseStreamFailed;
        if (!com.ok(voice.lpVtbl.SetOutput(voice, sp, 1))) return error.SetOutputFailed;
        defer _ = voice.lpVtbl.SetOutput(voice, null, 1);

        _ = voice.lpVtbl.SetRate(voice, self.rate.load(.acquire));
        _ = voice.lpVtbl.SetVolume(voice, 100); // gain.zig owns loudness
        const hr = voice.lpVtbl.Speak(voice, text16.ptr, SPF_DEFAULT, null);
        if (!com.ok(hr)) {
            std.debug.print("TTS Speak failed: HRESULT 0x{x:0>8}\n", .{@as(u32, @bitCast(hr))});
            return Error.SpeakFailed;
        }

        var written: u64 = 0;
        if (!com.ok(mem.?.lpVtbl.Seek(mem.?, 0, STREAM_SEEK_CUR, &written))) return error.StreamSeekFailed;
        var hglobal: ?*anyopaque = null;
        if (!com.ok(GetHGlobalFromStream(mem.?, &hglobal))) return error.StreamMemoryFailed;
        const base = GlobalLock(hglobal) orelse return error.StreamMemoryFailed;
        defer _ = GlobalUnlock(hglobal);
        const bytes = @as([*]const u8, @ptrCast(base))[0..@intCast(written)];
        const pcm = gain.pcmPayload(bytes);

        const out = try self.allocator.alloc(i16, pcm.len / 2);
        @memcpy(std.mem.sliceAsBytes(out), pcm[0 .. out.len * 2]);
        return out;
    }
};

fn peakAbs(samples: []const i16) u32 {
    var p: u32 = 0;
    for (samples) |s| p = @max(p, @abs(s));
    return p;
}

fn rmsOf(samples: []const i16) u32 {
    if (samples.len == 0) return 0;
    var acc: f64 = 0;
    for (samples) |s| {
        const f: f64 = @floatFromInt(s);
        acc += f * f;
    }
    return @intFromFloat(@sqrt(acc / @as(f64, @floatFromInt(samples.len))));
}

// ---- tests (speech runs via --say; vtable slots pinned: a wrong slot calls the wrong method) ----

test "compile-time vtable well-formed" {
    _ = @sizeOf(ISpVoice);
    _ = @sizeOf(ISpVoice.VTable);
}

fn slot(comptime T: type, comptime name: []const u8) usize {
    return @offsetOf(T, name) / @sizeOf(usize);
}

test "ISpVoice vtable slots match sapi.h" {
    // IUnknown(3) + ISpNotifySource(7) + ISpEventSource(3) = 13, then ISpVoice (no ISpEventSink).
    const V = ISpVoice.VTable;
    try std.testing.expectEqual(@as(usize, 13), slot(V, "SetOutput"));
    try std.testing.expectEqual(@as(usize, 18), slot(V, "SetVoice"));
    try std.testing.expectEqual(@as(usize, 20), slot(V, "Speak"));
    try std.testing.expectEqual(@as(usize, 28), slot(V, "SetRate"));
    try std.testing.expectEqual(@as(usize, 30), slot(V, "SetVolume"));
    try std.testing.expectEqual(@as(usize, 32), slot(V, "WaitUntilDone"));
    try std.testing.expectEqual(@as(usize, 38), @sizeOf(V) / @sizeOf(usize));
}

test "ISpStream, ISpObjectToken and IStream vtable slots match headers" {
    // ISpStream: IUnknown(3) + IStream(11) + ISpStreamFormat(1) -> SetBaseStream at 15.
    try std.testing.expectEqual(@as(usize, 15), slot(ISpStream.VTable, "SetBaseStream"));
    // ISpObjectToken: IUnknown(3) + ISpDataKey(12) -> SetId at 15.
    try std.testing.expectEqual(@as(usize, 15), slot(ISpObjectToken.VTable, "SetId"));
    // IStream: IUnknown(3) + Read, Write -> Seek at 5.
    try std.testing.expectEqual(@as(usize, 5), slot(IStream.VTable, "Seek"));
}

test "mailbox: latest text wins and voice change is kept alongside it" {
    const a = std.testing.allocator;
    var mb = Mailbox{};
    defer mb.deinit(a);
    try mb.putText(a, "gear");
    try mb.putText(a, "boost");
    try mb.putVoice(a, "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\TTS_MS_EN-US_ZIRA_11.0");
    try std.testing.expect(!mb.isEmpty());
    const job = mb.take();
    defer if (job.text) |t| a.free(t);
    defer if (job.voice) |v| a.free(v);
    try std.testing.expectEqualStrings("boost", job.text.?);
    try std.testing.expect(std.mem.endsWith(u8, job.voice.?, "ZIRA_11.0"));
    try std.testing.expect(mb.isEmpty());
}

test "mailbox: empty voice id (Windows default) is a real request" {
    const a = std.testing.allocator;
    var mb = Mailbox{};
    defer mb.deinit(a);
    try mb.putVoice(a, "");
    try std.testing.expect(!mb.isEmpty());
    const job = mb.take();
    defer if (job.voice) |v| a.free(v);
    try std.testing.expectEqual(@as(usize, 0), job.voice.?.len);
    try std.testing.expect(job.text == null);
}

test "mailbox: deinit frees pending requests" {
    const a = std.testing.allocator;
    var mb = Mailbox{};
    try mb.putText(a, "unsent");
    try mb.putVoice(a, "unsent-voice");
    mb.deinit(a); // testing allocator fails the test on leaks
}

test "mailbox: dropText clears queued speech but keeps a voice change" {
    const a = std.testing.allocator;
    var mb = Mailbox{};
    defer mb.deinit(a);
    try mb.putText(a, "a very long answer");
    try mb.putVoice(a, "zira");
    mb.dropText(a);
    try std.testing.expect(mb.text == null);
    try std.testing.expect(!mb.isEmpty());
    mb.dropText(a); // idempotent
    const job = mb.take();
    defer if (job.voice) |v| a.free(v);
    try std.testing.expect(job.text == null);
}
