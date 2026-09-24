const std = @import("std");
const windows = std.os.windows;
const com = @import("com.zig");

// ---- WASAPI GUIDs and constants ----

pub const CLSID_MMDeviceEnumerator = com.GUID{
    .Data1 = 0xBCDE0395, .Data2 = 0xE52F, .Data3 = 0x467C,
    .Data4 = .{ 0x8E, 0x3D, 0xC4, 0x57, 0x92, 0x91, 0x69, 0x2E },
};

pub const IID_IMMDeviceEnumerator = com.GUID{
    .Data1 = 0xA95664D2, .Data2 = 0x9614, .Data3 = 0x4F35,
    .Data4 = .{ 0xA7, 0x46, 0xDE, 0x8D, 0xB6, 0x36, 0x17, 0xE6 },
};

pub const IID_IAudioClient = com.GUID{
    .Data1 = 0x1CB9AD4C, .Data2 = 0xDBFA, .Data3 = 0x4C32,
    .Data4 = .{ 0xB1, 0x78, 0xC2, 0xF5, 0x68, 0xA7, 0x03, 0xB2 },
};

pub const IID_IAudioCaptureClient = com.GUID{
    .Data1 = 0xC8ADBD64, .Data2 = 0xE71E, .Data3 = 0x48A0,
    .Data4 = .{ 0xA4, 0xDE, 0x18, 0x5C, 0x39, 0x5C, 0xD3, 0x17 },
};

pub const EDataFlow = enum(u32) { eRender = 0, eCapture = 1, eAll = 2 };
pub const ERole = enum(u32) { eConsole = 0, eMultimedia = 1, eCommunications = 2 };

pub const DEVICE_STATE_ACTIVE: u32 = 0x1;
pub const STGM_READ: u32 = 0;
pub const VT_LPWSTR: u16 = 31;

pub const PROPERTYKEY = extern struct { fmtid: com.GUID, pid: u32 };

// PKEY_Device_FriendlyName {a45c254e-df1c-4efd-8020-67d146a850e0}, 14
pub const PKEY_Device_FriendlyName = PROPERTYKEY{
    .fmtid = .{ .Data1 = 0xA45C254E, .Data2 = 0xDF1C, .Data3 = 0x4EFD, .Data4 = .{ 0x80, 0x20, 0x67, 0xD1, 0x46, 0xA8, 0x50, 0xE0 } },
    .pid = 14,
};

// PROPVARIANT: VARTYPE + 3 reserved WORDs, then a 16-byte union (24 bytes on x64).
pub const PROPVARIANT = extern struct {
    vt: u16 = 0,
    reserved1: u16 = 0,
    reserved2: u16 = 0,
    reserved3: u16 = 0,
    data: extern union { pwszVal: ?[*:0]u16, raw: [2]u64 } = .{ .raw = .{ 0, 0 } },
};

extern "ole32" fn PropVariantClear(pvar: *PROPVARIANT) callconv(windows.WINAPI) com.HRESULT;

pub const AUDCLNT_SHAREMODE_SHARED: u32 = 0;

pub const AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM: u32 = 0x80000000;
pub const AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY: u32 = 0x08000000;

pub const AUDCLNT_BUFFERFLAGS_SILENT: u32 = 0x2;

pub const WAVE_FORMAT_PCM: u16 = 1;
pub const WAVE_FORMAT_IEEE_FLOAT: u16 = 3;
pub const WAVE_FORMAT_EXTENSIBLE: u16 = 0xFFFE;

// Reference time is in 100-nanosecond units.
pub const REFTIMES_PER_SEC: i64 = 10_000_000;

pub const WAVEFORMATEX = extern struct {
    wFormatTag: u16,
    nChannels: u16,
    nSamplesPerSec: u32,
    nAvgBytesPerSec: u32,
    nBlockAlign: u16,
    wBitsPerSample: u16,
    cbSize: u16,
};

pub const WAVEFORMATEXTENSIBLE = extern struct {
    Format: WAVEFORMATEX,
    Samples: u16, // union: wValidBitsPerSample / wSamplesPerBlock / wReserved
    dwChannelMask: u32,
    SubFormat: com.GUID,
};

// KSDATAFORMAT_SUBTYPE_IEEE_FLOAT
pub const SUBTYPE_IEEE_FLOAT = com.GUID{
    .Data1 = 0x00000003, .Data2 = 0x0000, .Data3 = 0x0010,
    .Data4 = .{ 0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71 },
};
pub const SUBTYPE_PCM = com.GUID{
    .Data1 = 0x00000001, .Data2 = 0x0000, .Data3 = 0x0010,
    .Data4 = .{ 0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71 },
};

// ---- COM interface vtables (slot order MUST match the C header) ----

pub const IMMDeviceEnumerator = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const fn (*IMMDeviceEnumerator, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        AddRef: *const fn (*IMMDeviceEnumerator) callconv(windows.WINAPI) u32,
        Release: *const fn (*IMMDeviceEnumerator) callconv(windows.WINAPI) u32,
        EnumAudioEndpoints: *const fn (*IMMDeviceEnumerator, u32, windows.DWORD, *?*IMMDeviceCollection) callconv(windows.WINAPI) com.HRESULT,
        GetDefaultAudioEndpoint: *const fn (*IMMDeviceEnumerator, u32, u32, **IMMDevice) callconv(windows.WINAPI) com.HRESULT,
        GetDevice: *const fn (*IMMDeviceEnumerator, [*:0]const u16, *?*IMMDevice) callconv(windows.WINAPI) com.HRESULT,
        RegisterEndpointNotificationCallback: *const anyopaque,
        UnregisterEndpointNotificationCallback: *const anyopaque,
    };
};

pub const IMMDevice = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const fn (*IMMDevice, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        AddRef: *const fn (*IMMDevice) callconv(windows.WINAPI) u32,
        Release: *const fn (*IMMDevice) callconv(windows.WINAPI) u32,
        Activate: *const fn (*IMMDevice, *const com.GUID, windows.DWORD, ?*anyopaque, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        OpenPropertyStore: *const fn (*IMMDevice, windows.DWORD, *?*IPropertyStore) callconv(windows.WINAPI) com.HRESULT,
        GetId: *const fn (*IMMDevice, *?[*:0]u16) callconv(windows.WINAPI) com.HRESULT,
        GetState: *const anyopaque,
    };
};

// mmdeviceapi.h: IUnknown(3) + GetCount, Item.
pub const IMMDeviceCollection = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const anyopaque,
        AddRef: *const anyopaque,
        Release: *const fn (*IMMDeviceCollection) callconv(windows.WINAPI) u32,
        GetCount: *const fn (*IMMDeviceCollection, *u32) callconv(windows.WINAPI) com.HRESULT,
        Item: *const fn (*IMMDeviceCollection, u32, *?*IMMDevice) callconv(windows.WINAPI) com.HRESULT,
    };
};

// propsys.h: IUnknown(3) + GetCount, GetAt, GetValue, SetValue, Commit.
pub const IPropertyStore = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const anyopaque,
        AddRef: *const anyopaque,
        Release: *const fn (*IPropertyStore) callconv(windows.WINAPI) u32,
        GetCount: *const anyopaque,
        GetAt: *const anyopaque,
        GetValue: *const fn (*IPropertyStore, *const PROPERTYKEY, *PROPVARIANT) callconv(windows.WINAPI) com.HRESULT,
        SetValue: *const anyopaque,
        Commit: *const anyopaque,
    };
};

// ---- Endpoint identity helpers ----

/// UTF-16Z -> UTF-8 into `buf`, truncated at a codepoint boundary; unpaired surrogates become '?'.
pub fn wideToUtf8(buf: []u8, wide: [*:0]const u16) []const u8 {
    const w = std.mem.span(wide);
    var n: usize = 0;
    var i: usize = 0;
    while (i < w.len) {
        var cp: u21 = '?';
        const u = w[i];
        if (u >= 0xD800 and u <= 0xDBFF and i + 1 < w.len and w[i + 1] >= 0xDC00 and w[i + 1] <= 0xDFFF) {
            cp = @intCast(0x10000 + ((@as(u32, u) - 0xD800) << 10) + (@as(u32, w[i + 1]) - 0xDC00));
            i += 2;
        } else {
            if (u < 0xD800 or u > 0xDFFF) cp = @intCast(u);
            i += 1;
        }
        var tmp: [4]u8 = undefined;
        const len = std.unicode.utf8Encode(cp, &tmp) catch 1;
        if (n + len > buf.len) break;
        @memcpy(buf[n .. n + len], tmp[0..len]);
        n += len;
    }
    return buf[0..n];
}

fn deviceIdInto(dev: *IMMDevice, buf: []u8) []const u8 {
    var wid: ?[*:0]u16 = null;
    if (!com.ok(dev.lpVtbl.GetId(dev, &wid)) or wid == null) return buf[0..0];
    defer com.CoTaskMemFree(wid);
    return wideToUtf8(buf, wid.?);
}

fn friendlyNameInto(dev: *IMMDevice, buf: []u8) []const u8 {
    var store: ?*IPropertyStore = null;
    if (!com.ok(dev.lpVtbl.OpenPropertyStore(dev, STGM_READ, &store)) or store == null) return buf[0..0];
    defer _ = store.?.lpVtbl.Release(store.?);
    var pv = PROPVARIANT{};
    if (!com.ok(store.?.lpVtbl.GetValue(store.?, &PKEY_Device_FriendlyName, &pv))) return buf[0..0];
    defer _ = PropVariantClear(&pv);
    if (pv.vt != VT_LPWSTR or pv.data.pwszVal == null) return buf[0..0];
    return wideToUtf8(buf, pv.data.pwszVal.?);
}

fn createEnumerator() com.Error!*IMMDeviceEnumerator {
    _ = com.CoInitializeEx(null, com.COINIT_MULTITHREADED);
    var pv: ?*anyopaque = null;
    if (!com.ok(com.CoCreateInstance(&CLSID_MMDeviceEnumerator, null, com.CLSCTX_ALL, &IID_IMMDeviceEnumerator, &pv))) return com.Error.NoInterface;
    return @ptrCast(@alignCast(pv));
}

pub const DeviceInfo = struct { id: []u8, name: []u8, is_default: bool };

/// Active capture endpoints; `is_default` marks the eConsole default. Free with freeDeviceList.
pub fn listCaptureDevices(allocator: std.mem.Allocator) (com.Error || std.mem.Allocator.Error)![]DeviceInfo {
    const en = try createEnumerator();
    defer _ = en.lpVtbl.Release(en);

    var default_buf: [512]u8 = undefined;
    var default_id: []const u8 = default_buf[0..0];
    var def: *IMMDevice = undefined;
    if (com.ok(en.lpVtbl.GetDefaultAudioEndpoint(en, @intFromEnum(EDataFlow.eCapture), @intFromEnum(ERole.eConsole), &def))) {
        default_id = deviceIdInto(def, &default_buf);
        _ = def.lpVtbl.Release(def);
    }

    var coll: ?*IMMDeviceCollection = null;
    if (!com.ok(en.lpVtbl.EnumAudioEndpoints(en, @intFromEnum(EDataFlow.eCapture), DEVICE_STATE_ACTIVE, &coll)) or coll == null) return com.Error.EnumFailed;
    defer _ = coll.?.lpVtbl.Release(coll.?);

    var count: u32 = 0;
    if (!com.ok(coll.?.lpVtbl.GetCount(coll.?, &count))) return com.Error.EnumFailed;

    var list = std.ArrayList(DeviceInfo).init(allocator);
    errdefer {
        for (list.items) |d| {
            allocator.free(d.id);
            allocator.free(d.name);
        }
        list.deinit();
    }
    var i: u32 = 0;
    while (i < count) : (i += 1) {
        var dev: ?*IMMDevice = null;
        if (!com.ok(coll.?.lpVtbl.Item(coll.?, i, &dev)) or dev == null) continue;
        defer _ = dev.?.lpVtbl.Release(dev.?);
        var id_buf: [512]u8 = undefined;
        var name_buf: [256]u8 = undefined;
        const id = deviceIdInto(dev.?, &id_buf);
        if (id.len == 0) continue;
        const name = friendlyNameInto(dev.?, &name_buf);
        const id_copy = try allocator.dupe(u8, id);
        errdefer allocator.free(id_copy);
        const name_copy = try allocator.dupe(u8, name);
        errdefer allocator.free(name_copy);
        try list.append(.{ .id = id_copy, .name = name_copy, .is_default = std.mem.eql(u8, id, default_id) });
    }
    return list.toOwnedSlice();
}

pub fn freeDeviceList(allocator: std.mem.Allocator, list: []DeviceInfo) void {
    for (list) |d| {
        allocator.free(d.id);
        allocator.free(d.name);
    }
    allocator.free(list);
}

pub const IAudioClient = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const fn (*IAudioClient, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        AddRef: *const fn (*IAudioClient) callconv(windows.WINAPI) u32,
        Release: *const fn (*IAudioClient) callconv(windows.WINAPI) u32,
        Initialize: *const fn (*IAudioClient, u32, u32, i64, i64, *const WAVEFORMATEX, ?*const com.GUID) callconv(windows.WINAPI) com.HRESULT,
        GetBufferSize: *const fn (*IAudioClient, *u32) callconv(windows.WINAPI) com.HRESULT,
        GetStreamLatency: *const anyopaque,
        GetCurrentPadding: *const anyopaque,
        IsFormatSupported: *const anyopaque,
        GetMixFormat: *const fn (*IAudioClient, *?*WAVEFORMATEX) callconv(windows.WINAPI) com.HRESULT,
        GetDevicePeriod: *const anyopaque,
        Start: *const fn (*IAudioClient) callconv(windows.WINAPI) com.HRESULT,
        Stop: *const fn (*IAudioClient) callconv(windows.WINAPI) com.HRESULT,
        Reset: *const anyopaque,
        SetEventHandle: *const anyopaque,
        GetService: *const fn (*IAudioClient, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
    };
};

pub const IAudioCaptureClient = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const fn (*IAudioCaptureClient, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        AddRef: *const fn (*IAudioCaptureClient) callconv(windows.WINAPI) u32,
        Release: *const fn (*IAudioCaptureClient) callconv(windows.WINAPI) u32,
        GetBuffer: *const fn (*IAudioCaptureClient, *[*]u8, *u32, *u32, ?*u64, ?*u64) callconv(windows.WINAPI) com.HRESULT,
        ReleaseBuffer: *const fn (*IAudioCaptureClient, u32) callconv(windows.WINAPI) com.HRESULT,
        GetNextPacketSize: *const fn (*IAudioCaptureClient, *u32) callconv(windows.WINAPI) com.HRESULT,
    };
};

// ---- Public capture API ----

pub const CaptureFormat = struct {
    channels: u16,
    sample_rate: u32,
    is_float: bool,
    bits_per_sample: u16,
};

// Fixed target format the recognizer wants: 16 kHz mono int16.
pub const TARGET_SAMPLE_RATE: u32 = 16000;
pub const TARGET_CHANNELS: u16 = 1;

pub const CaptureCallback = *const fn (samples: []const i16, user: ?*anyopaque) void;

pub const Capture = struct {
    enumerator: *IMMDeviceEnumerator = undefined,
    device: *IMMDevice = undefined,
    client: *IAudioClient = undefined,
    capture: *IAudioCaptureClient = undefined,
    format: CaptureFormat = undefined,
    resample_state: ResampleState = .{},
    running: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
    // Identity of the opened endpoint (UTF-8). Read via deviceId()/deviceName().
    id_buf: [512]u8 = undefined,
    id_len: usize = 0,
    name_buf: [256]u8 = undefined,
    name_len: usize = 0,

    pub fn deviceId(self: *const Capture) []const u8 {
        return self.id_buf[0..self.id_len];
    }
    pub fn deviceName(self: *const Capture) []const u8 {
        return self.name_buf[0..self.name_len];
    }

    /// Open a capture endpoint by IMMDevice id; null or "" = default eConsole capture device.
    pub fn open(device_id: ?[]const u8) com.Error!Capture {
        var self: Capture = .{};

        // COM init is idempotent per-thread; caller may have done it already.
        self.enumerator = try createEnumerator();
        errdefer _ = self.enumerator.lpVtbl.Release(self.enumerator);

        if (device_id != null and device_id.?.len > 0) {
            var wbuf: [512:0]u16 = undefined;
            // UTF-16 never needs more code units than UTF-8 has bytes.
            if (device_id.?.len >= wbuf.len) return com.Error.NoDevice;
            const n = std.unicode.utf8ToUtf16Le(&wbuf, device_id.?) catch return com.Error.NoDevice;
            wbuf[n] = 0;
            var dev: ?*IMMDevice = null;
            if (!com.ok(self.enumerator.lpVtbl.GetDevice(self.enumerator, wbuf[0..n :0].ptr, &dev)) or dev == null) return com.Error.NoDevice;
            self.device = dev.?;
        } else {
            var dev: *IMMDevice = undefined;
            if (!com.ok(self.enumerator.lpVtbl.GetDefaultAudioEndpoint(
                self.enumerator,
                @intFromEnum(EDataFlow.eCapture),
                @intFromEnum(ERole.eConsole),
                &dev,
            ))) return com.Error.NoDevice;
            self.device = dev;
        }
        errdefer _ = self.device.lpVtbl.Release(self.device);
        self.id_len = deviceIdInto(self.device, &self.id_buf).len;
        self.name_len = friendlyNameInto(self.device, &self.name_buf).len;

        var client_pv: ?*anyopaque = null;
        if (!com.ok(self.device.lpVtbl.Activate(
            self.device,
            &IID_IAudioClient,
            com.CLSCTX_ALL,
            null,
            &client_pv,
        ))) return com.Error.ActivateFailed;
        self.client = @ptrCast(@alignCast(client_pv));
        errdefer _ = self.client.lpVtbl.Release(self.client);

    var fmt_ptr: ?*WAVEFORMATEX = null;
    if (!com.ok(self.client.lpVtbl.GetMixFormat(self.client, &fmt_ptr))) return com.Error.UnsupportedFormat;
    const fmt = fmt_ptr.?;
    defer com.CoTaskMemFree(fmt);

    self.format = try classifyFormat(fmt);

        // 1 s shared-mode buffer; AUTOCONVERTPCM is belt-and-braces since we use the mix format.
        const buf_duration: i64 = REFTIMES_PER_SEC;
        if (!com.ok(self.client.lpVtbl.Initialize(
            self.client,
            AUDCLNT_SHAREMODE_SHARED,
            AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
            buf_duration,
            0,
            fmt,
            null,
        ))) return com.Error.InitializeFailed;

        var cap_pv: ?*anyopaque = null;
        if (!com.ok(self.client.lpVtbl.GetService(self.client, &IID_IAudioCaptureClient, &cap_pv)) or cap_pv == null) return com.Error.GetServiceFailed;
        self.capture = @ptrCast(@alignCast(cap_pv));

        self.resample_state = ResampleState.init(self.format);
        return self;
    }

    pub fn close(self: *Capture) void {
        _ = self.capture.lpVtbl.Release(self.capture);
        _ = self.client.lpVtbl.Release(self.client);
        _ = self.device.lpVtbl.Release(self.device);
        _ = self.enumerator.lpVtbl.Release(self.enumerator);
    }

    pub fn start(self: *Capture) com.Error!void {
        if (!com.ok(self.client.lpVtbl.Start(self.client))) return com.Error.StartFailed;
        self.running.store(true, .release);
    }

    pub fn stop(self: *Capture) void {
        self.running.store(false, .release);
        _ = self.client.lpVtbl.Stop(self.client);
    }

    // Poll once: delivers 16 kHz mono i16 to `cb`; returns source frames processed (0 = none).
    pub fn poll(self: *Capture, out_buf: []i16, cb: CaptureCallback, user: ?*anyopaque) com.Error!u32 {
        var packet_size: u32 = 0;
        if (!com.ok(self.capture.lpVtbl.GetNextPacketSize(self.capture, &packet_size))) return com.Error.GetBufferFailed;
        if (packet_size == 0) return 0;

        var data: [*]u8 = undefined;
        var frames: u32 = 0;
        var flags: u32 = 0;
        if (!com.ok(self.capture.lpVtbl.GetBuffer(self.capture, &data, &frames, &flags, null, null))) return com.Error.GetBufferFailed;

        const bytes_per_frame: u32 = @as(u32, self.format.bits_per_sample / 8) * self.format.channels;
        const byte_len: u32 = frames * bytes_per_frame;
        const src = data[0..byte_len];

        const written = self.resample_state.convert(src, out_buf);
        if (written > 0) cb(out_buf[0..written], user);

        if (!com.ok(self.capture.lpVtbl.ReleaseBuffer(self.capture, frames))) return com.Error.ReleaseBufferFailed;
        return frames;
    }
};

fn classifyFormat(fmt: *const WAVEFORMATEX) com.Error!CaptureFormat {
    var is_float = false;
    if (fmt.wFormatTag == WAVE_FORMAT_IEEE_FLOAT) {
        is_float = true;
    } else if (fmt.wFormatTag == WAVE_FORMAT_EXTENSIBLE) {
        // WAVEFORMATEX is packed to 18 bytes (Zig pads to 20): SubFormat is at raw[24..40].
        const raw: [*]const u8 = @ptrCast(fmt);
        const sub = raw[24..40];
        if (std.mem.eql(u8, sub, std.mem.asBytes(&SUBTYPE_IEEE_FLOAT))) {
            is_float = true;
        } else if (std.mem.eql(u8, sub, std.mem.asBytes(&SUBTYPE_PCM))) {
            is_float = false;
        } else if (fmt.wBitsPerSample == 32) {
            // Unknown vendor subtype: shared-mode 32-bit mix formats are float.
            is_float = true;
        }
    } else if (fmt.wFormatTag != WAVE_FORMAT_PCM) {
        return com.Error.UnsupportedFormat;
    }
    return .{
        .channels = fmt.nChannels,
        .sample_rate = fmt.nSamplesPerSec,
        .is_float = is_float,
        .bits_per_sample = fmt.wBitsPerSample,
    };
}

// ---- Conversion: mixdown to mono -> linear resample to 16 kHz -> clip to i16 ----

pub const ResampleState = struct {
    src_rate: u32 = 0,
    src_channels: u16 = 1,
    src_is_float: bool = true,
    src_bits: u16 = 32,
    // Fractional accumulator (0..src_rate) tracking output position between source frames.
    phase: f64 = 0,
    last_sample: f32 = 0,

    pub fn init(fmt: CaptureFormat) ResampleState {
        return .{
            .src_rate = fmt.sample_rate,
            .src_channels = fmt.channels,
            .src_is_float = fmt.is_float,
            .src_bits = fmt.bits_per_sample,
        };
    }

    // Consume interleaved source bytes, emit int16 mono @ 16 kHz.
    pub fn convert(self: *ResampleState, src: []const u8, out: []i16) usize {
        const step: f64 = @as(f64, @floatFromInt(self.src_rate)) / @as(f64, @floatFromInt(TARGET_SAMPLE_RATE));
        var written: usize = 0;
        var i: usize = 0;
        const bytes_per_sample: usize = self.src_bits / 8;
        const frame_bytes: usize = bytes_per_sample * self.src_channels;
        const frame_count: usize = src.len / frame_bytes;

        while (i < frame_count and written < out.len) {
            const cur = self.readMono(src, i, bytes_per_sample);

            while (self.phase < 1.0 and written < out.len) {
                const interp = self.last_sample * @as(f32, @floatCast(1.0 - self.phase)) + cur * @as(f32, @floatCast(self.phase));
                out[written] = floatToI16(interp);
                written += 1;
                self.phase += step;
            }
            self.phase -= 1.0;
            self.last_sample = cur;
            i += 1;
        }
        return written;
    }

    fn readMono(self: *ResampleState, src: []const u8, frame_idx: usize, bytes_per_sample: usize) f32 {
        const base = frame_idx * bytes_per_sample * self.src_channels;
        var acc: f32 = 0;
        var ch: usize = 0;
        while (ch < self.src_channels) : (ch += 1) {
            const off = base + ch * bytes_per_sample;
            acc += self.readSample(src, off);
        }
        return acc / @as(f32, @floatFromInt(self.src_channels));
    }

    fn readSample(self: *ResampleState, src: []const u8, off: usize) f32 {
        if (self.src_is_float) {
            var bytes: [4]u8 = undefined;
            @memcpy(&bytes, src[off .. off + 4]);
            return @bitCast(bytes);
        }
        return switch (self.src_bits) {
            16 => blk: {
                var bytes: [2]u8 = undefined;
                @memcpy(&bytes, src[off .. off + 2]);
                const s: i16 = @bitCast(bytes);
                break :blk @as(f32, @floatFromInt(s)) / 32768.0;
            },
            24 => blk: {
                // Sign-extend a little-endian 24-bit sample into i32.
                const s: i32 = (@as(i32, src[off + 2]) << 24 | @as(i32, src[off + 1]) << 16 | @as(i32, src[off]) << 8) >> 8;
                break :blk @as(f32, @floatFromInt(s)) / 8388608.0;
            },
            32 => blk: {
                var bytes: [4]u8 = undefined;
                @memcpy(&bytes, src[off .. off + 4]);
                const s: i32 = @bitCast(bytes);
                break :blk @as(f32, @floatFromInt(s)) / 2147483648.0;
            },
            else => 0,
        };
    }
};

fn floatToI16(x: f32) i16 {
    const clamped: f32 = @max(-1.0, @min(1.0, x));
    return @intFromFloat(clamped * 32767.0);
}

// ---- tests ----

test "resample state init from 48k stereo f32" {
    const st = ResampleState.init(.{
        .channels = 2,
        .sample_rate = 48000,
        .is_float = true,
        .bits_per_sample = 32,
    });
    try std.testing.expectEqual(@as(u32, 48000), st.src_rate);
    try std.testing.expectEqual(@as(u16, 2), st.src_channels);
    try std.testing.expect(st.src_is_float);
}

test "float to i16 clips" {
    try std.testing.expectEqual(@as(i16, 32767), floatToI16(1.5));
    try std.testing.expectEqual(@as(i16, -32767), floatToI16(-1.5));
    try std.testing.expectEqual(@as(i16, 0), floatToI16(0.0));
}

// WAVEFORMATEXTENSIBLE as Windows lays it out (packed 18-byte WAVEFORMATEX, SubFormat at byte 24).
fn testExtensible(bits: u16, sub: com.GUID) [40]u8 {
    var b = [_]u8{0} ** 40;
    std.mem.writeInt(u16, b[0..2], WAVE_FORMAT_EXTENSIBLE, .little);
    std.mem.writeInt(u16, b[2..4], 2, .little); // channels
    std.mem.writeInt(u32, b[4..8], 48000, .little);
    std.mem.writeInt(u16, b[14..16], bits, .little);
    std.mem.writeInt(u16, b[16..18], 22, .little); // cbSize
    std.mem.writeInt(u16, b[18..20], bits, .little); // wValidBitsPerSample
    std.mem.writeInt(u32, b[20..24], 3, .little); // channel mask
    @memcpy(b[24..40], std.mem.asBytes(&sub));
    return b;
}

test "classifyFormat detects extensible float32 mix format" {
    var raw align(4) = testExtensible(32, SUBTYPE_IEEE_FLOAT);
    const f = try classifyFormat(@ptrCast(&raw));
    try std.testing.expect(f.is_float);
    try std.testing.expectEqual(@as(u16, 32), f.bits_per_sample);
    try std.testing.expectEqual(@as(u16, 2), f.channels);
}

test "classifyFormat detects extensible int16 PCM" {
    var raw align(4) = testExtensible(16, SUBTYPE_PCM);
    const f = try classifyFormat(@ptrCast(&raw));
    try std.testing.expect(!f.is_float);
    try std.testing.expectEqual(@as(u16, 16), f.bits_per_sample);
}

test "resampler decodes float32 stereo at the right amplitude" {
    var st = ResampleState.init(.{ .channels = 2, .sample_rate = 48000, .is_float = true, .bits_per_sample = 32 });
    var src: [48 * 2]f32 = undefined;
    for (&src) |*s| s.* = 0.5;
    var out: [64]i16 = undefined;
    const n = st.convert(std.mem.sliceAsBytes(&src), &out);
    try std.testing.expect(n >= 15);
    // After the first interpolated sample, output should sit at ~0.5 full scale.
    try std.testing.expect(@abs(@as(i32, out[n - 1]) - 16383) < 50);
}

fn slot(comptime T: type, comptime name: []const u8) usize {
    return @offsetOf(T, name) / @sizeOf(usize);
}

test "MMDevice API vtable slots match mmdeviceapi.h / propsys.h" {
    const E = IMMDeviceEnumerator.VTable;
    try std.testing.expectEqual(@as(usize, 3), slot(E, "EnumAudioEndpoints"));
    try std.testing.expectEqual(@as(usize, 4), slot(E, "GetDefaultAudioEndpoint"));
    try std.testing.expectEqual(@as(usize, 5), slot(E, "GetDevice"));
    try std.testing.expectEqual(@as(usize, 8), @sizeOf(E) / @sizeOf(usize));

    const D = IMMDevice.VTable;
    try std.testing.expectEqual(@as(usize, 3), slot(D, "Activate"));
    try std.testing.expectEqual(@as(usize, 4), slot(D, "OpenPropertyStore"));
    try std.testing.expectEqual(@as(usize, 5), slot(D, "GetId"));
    try std.testing.expectEqual(@as(usize, 7), @sizeOf(D) / @sizeOf(usize));

    const C = IMMDeviceCollection.VTable;
    try std.testing.expectEqual(@as(usize, 3), slot(C, "GetCount"));
    try std.testing.expectEqual(@as(usize, 4), slot(C, "Item"));
    try std.testing.expectEqual(@as(usize, 5), @sizeOf(C) / @sizeOf(usize));

    const P = IPropertyStore.VTable;
    try std.testing.expectEqual(@as(usize, 5), slot(P, "GetValue"));
    try std.testing.expectEqual(@as(usize, 8), @sizeOf(P) / @sizeOf(usize));
}

test "PROPVARIANT and PROPERTYKEY layouts match the SDK" {
    if (@sizeOf(usize) != 8) return;
    try std.testing.expectEqual(@as(usize, 24), @sizeOf(PROPVARIANT));
    try std.testing.expectEqual(@as(usize, 8), @offsetOf(PROPVARIANT, "data"));
    try std.testing.expectEqual(@as(usize, 20), @sizeOf(PROPERTYKEY));
}

test "wideToUtf8 converts, handles surrogates and truncates safely" {
    const w = std.unicode.utf8ToUtf16LeStringLiteral("Mic \u{e9} \u{1F3A4}");
    var buf: [64]u8 = undefined;
    try std.testing.expectEqualStrings("Mic \u{e9} \u{1F3A4}", wideToUtf8(&buf, w));
    var small: [6]u8 = undefined; // "Mic " + 2-byte e-acute fits exactly
    try std.testing.expectEqualStrings("Mic \u{e9}", wideToUtf8(&small, w));
    var tiny: [5]u8 = undefined; // e-acute does not fit: stop before it
    try std.testing.expectEqualStrings("Mic ", wideToUtf8(&tiny, w));
    const bad = [_:0]u16{ 'a', 0xD800, 'b' };
    try std.testing.expectEqualStrings("a?b", wideToUtf8(&buf, &bad));
}
