const std = @import("std");
const windows = std.os.windows;
const com = @import("../audio/com.zig");
const wasapi = @import("../audio/wasapi.zig");

// WASAPI TTS render (shared, AUTOCONVERTPCM resampling); not thread-safe, sapi5 worker serializes.

pub const Error = com.Error || std.mem.Allocator.Error;

pub const IAudioRenderClient = extern struct {
    lpVtbl: *const VTable,
    pub const VTable = extern struct {
        QueryInterface: *const fn (*IAudioRenderClient, *const com.GUID, *?*anyopaque) callconv(windows.WINAPI) com.HRESULT,
        AddRef: *const fn (*IAudioRenderClient) callconv(windows.WINAPI) u32,
        Release: *const fn (*IAudioRenderClient) callconv(windows.WINAPI) u32,
        GetBuffer: *const fn (*IAudioRenderClient, u32, *[*]u8) callconv(windows.WINAPI) com.HRESULT,
        ReleaseBuffer: *const fn (*IAudioRenderClient, u32, u32) callconv(windows.WINAPI) com.HRESULT,
    };
};

pub const IID_IAudioRenderClient = com.GUID{
    .Data1 = 0xF294ACFC, .Data2 = 0x3146, .Data3 = 0x4483,
    .Data4 = .{ 0xA7, 0xBF, 0xAD, 0xDC, 0xA7, 0xC2, 0x60, 0xE2 },
};

extern "ole32" fn PropVariantClear(pvar: *wasapi.PROPVARIANT) callconv(windows.WINAPI) com.HRESULT;

fn createEnumerator() com.Error!*wasapi.IMMDeviceEnumerator {
    _ = com.CoInitializeEx(null, com.COINIT_MULTITHREADED);
    var pv: ?*anyopaque = null;
    if (!com.ok(com.CoCreateInstance(&wasapi.CLSID_MMDeviceEnumerator, null, com.CLSCTX_ALL, &wasapi.IID_IMMDeviceEnumerator, &pv))) return com.Error.NoInterface;
    return @ptrCast(@alignCast(pv));
}

fn deviceIdInto(dev: *wasapi.IMMDevice, buf: []u8) []const u8 {
    var wid: ?[*:0]u16 = null;
    if (!com.ok(dev.lpVtbl.GetId(dev, &wid)) or wid == null) return buf[0..0];
    defer com.CoTaskMemFree(wid);
    return wasapi.wideToUtf8(buf, wid.?);
}

fn friendlyNameInto(dev: *wasapi.IMMDevice, buf: []u8) []const u8 {
    var store: ?*wasapi.IPropertyStore = null;
    if (!com.ok(dev.lpVtbl.OpenPropertyStore(dev, wasapi.STGM_READ, &store)) or store == null) return buf[0..0];
    defer _ = store.?.lpVtbl.Release(store.?);
    var pv = wasapi.PROPVARIANT{};
    if (!com.ok(store.?.lpVtbl.GetValue(store.?, &wasapi.PKEY_Device_FriendlyName, &pv))) return buf[0..0];
    defer _ = PropVariantClear(&pv);
    if (pv.vt != wasapi.VT_LPWSTR or pv.data.pwszVal == null) return buf[0..0];
    return wasapi.wideToUtf8(buf, pv.data.pwszVal.?);
}

/// Active render endpoints; free with wasapi.freeDeviceList.
pub fn listRenderDevices(allocator: std.mem.Allocator) Error![]wasapi.DeviceInfo {
    const en = try createEnumerator();
    defer _ = en.lpVtbl.Release(en);

    var default_buf: [512]u8 = undefined;
    var default_id: []const u8 = default_buf[0..0];
    var def: *wasapi.IMMDevice = undefined;
    if (com.ok(en.lpVtbl.GetDefaultAudioEndpoint(en, @intFromEnum(wasapi.EDataFlow.eRender), @intFromEnum(wasapi.ERole.eConsole), &def))) {
        default_id = deviceIdInto(def, &default_buf);
        _ = def.lpVtbl.Release(def);
    }

    var coll: ?*wasapi.IMMDeviceCollection = null;
    if (!com.ok(en.lpVtbl.EnumAudioEndpoints(en, @intFromEnum(wasapi.EDataFlow.eRender), wasapi.DEVICE_STATE_ACTIVE, &coll)) or coll == null) return com.Error.EnumFailed;
    defer _ = coll.?.lpVtbl.Release(coll.?);

    var count: u32 = 0;
    if (!com.ok(coll.?.lpVtbl.GetCount(coll.?, &count))) return com.Error.EnumFailed;

    var list = std.ArrayList(wasapi.DeviceInfo).init(allocator);
    errdefer {
        for (list.items) |d| {
            allocator.free(d.id);
            allocator.free(d.name);
        }
        list.deinit();
    }
    var i: u32 = 0;
    while (i < count) : (i += 1) {
        var dev: ?*wasapi.IMMDevice = null;
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

/// Entry in `devices` with endpoint id `id`, or null (also for ""); used to reject unknown ids.
pub fn findDevice(devices: []const wasapi.DeviceInfo, id: []const u8) ?wasapi.DeviceInfo {
    if (id.len == 0) return null;
    for (devices) |d| if (std.mem.eql(u8, d.id, id)) return d;
    return null;
}

/// Blocking mono i16 playback on `device_id` (null/"" = default) until done or `stop_flag` set.
pub fn playPcm(
    samples: []const i16,
    sample_rate: u32,
    device_id: ?[]const u8,
    stop_flag: *const std.atomic.Value(bool),
) Error!void {
    const en = try createEnumerator();
    defer _ = en.lpVtbl.Release(en);

    var device: *wasapi.IMMDevice = undefined;
    if (device_id != null and device_id.?.len > 0) {
        var wbuf: [512:0]u16 = undefined;
        if (device_id.?.len >= wbuf.len) return com.Error.NoDevice;
        const n = std.unicode.utf8ToUtf16Le(&wbuf, device_id.?) catch return com.Error.NoDevice;
        wbuf[n] = 0;
        var dev: ?*wasapi.IMMDevice = null;
        if (!com.ok(en.lpVtbl.GetDevice(en, wbuf[0..n :0].ptr, &dev)) or dev == null) return com.Error.NoDevice;
        device = dev.?;
    } else {
        var dev: *wasapi.IMMDevice = undefined;
        if (!com.ok(en.lpVtbl.GetDefaultAudioEndpoint(
            en,
            @intFromEnum(wasapi.EDataFlow.eRender),
            @intFromEnum(wasapi.ERole.eConsole),
            &dev,
        ))) return com.Error.NoDevice;
        device = dev;
    }
    defer _ = device.lpVtbl.Release(device);

    var client_pv: ?*anyopaque = null;
    if (!com.ok(device.lpVtbl.Activate(
        device,
        &wasapi.IID_IAudioClient,
        com.CLSCTX_ALL,
        null,
        &client_pv,
    ))) return com.Error.ActivateFailed;
    const client: *wasapi.IAudioClient = @ptrCast(@alignCast(client_pv));
    defer _ = client.lpVtbl.Release(client);

    // Source: mono int16 at `sample_rate`; AUTOCONVERTPCM converts to the endpoint mix format.
    const fmt = wasapi.WAVEFORMATEX{
        .wFormatTag = wasapi.WAVE_FORMAT_PCM,
        .nChannels = 1,
        .nSamplesPerSec = sample_rate,
        .nAvgBytesPerSec = sample_rate * 2, // 1 ch * 2 bytes
        .nBlockAlign = 2,
        .wBitsPerSample = 16,
        .cbSize = 0,
    };
    const buf_duration: i64 = wasapi.REFTIMES_PER_SEC; // 1 second buffer

    if (!com.ok(client.lpVtbl.Initialize(
        client,
        wasapi.AUDCLNT_SHAREMODE_SHARED,
        wasapi.AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | wasapi.AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY,
        buf_duration,
        0,
        &fmt,
        null,
    ))) return com.Error.InitializeFailed;

    var render_pv: ?*anyopaque = null;
    if (!com.ok(client.lpVtbl.GetService(client, &IID_IAudioRenderClient, &render_pv)) or render_pv == null) return com.Error.GetServiceFailed;
    const render: *IAudioRenderClient = @ptrCast(@alignCast(render_pv));
    defer _ = render.lpVtbl.Release(render);

    var buffer_frames: u32 = 0;
    if (!com.ok(client.lpVtbl.GetBufferSize(client, &buffer_frames))) return com.Error.InitializeFailed;

    var written: usize = 0;
    // Prime the buffer with silence so Start() doesn't stutter; overwritten as we go.
    if (buffer_frames > 0) {
        var buf: [*]u8 = undefined;
        if (com.ok(render.lpVtbl.GetBuffer(render, buffer_frames, &buf))) {
            const to_write: u32 = @intCast(@min(@as(usize, buffer_frames), samples.len - written));
            copySamples(buf, samples[written .. written + to_write]);
            if (to_write < buffer_frames) {
                // Zero the tail.
                const zero_bytes = @as(usize, buffer_frames - to_write) * 2;
                @memset(buf[to_write * 2 .. to_write * 2 + zero_bytes], 0);
            }
            _ = render.lpVtbl.ReleaseBuffer(render, buffer_frames, 0);
            written += to_write;
        }
    }

    if (!com.ok(client.lpVtbl.Start(client))) return com.Error.StartFailed;
    defer _ = client.lpVtbl.Stop(client);

    // Padding is in mix-format frames, so exact accounting is impossible; poll every 10 ms.
    const poll_ns: u64 = 10 * std.time.ns_per_ms;

    while (written < samples.len) {
        if (stop_flag.load(.acquire)) return;
        std.time.sleep(poll_ns);
        // GetCurrentPadding isn't typed in wasapi.zig, so write at most half the buffer per tick.
        const chunk: u32 = @intCast(@min(@as(usize, buffer_frames / 2), samples.len - written));
        if (chunk == 0) break;
        var buf: [*]u8 = undefined;
        const hr = render.lpVtbl.GetBuffer(render, chunk, &buf);
        if (!com.ok(hr)) {
            // Buffer full or other transient — try again next tick.
            continue;
        }
        copySamples(buf, samples[written .. written + chunk]);
        _ = render.lpVtbl.ReleaseBuffer(render, chunk, 0);
        written += chunk;
    }

    // Wait for the last buffer to drain, polling the stop flag so stopSpeaking() can interrupt.
    const drain_ns: u64 = @as(u64, buffer_frames) * std.time.ns_per_s / sample_rate;
    var slept: u64 = 0;
    while (slept < drain_ns) {
        if (stop_flag.load(.acquire)) return;
        const step: u64 = @min(20 * std.time.ns_per_ms, drain_ns - slept);
        std.time.sleep(step);
        slept += step;
    }
}

fn copySamples(dst: [*]u8, src: []const i16) void {
    // i16 is native-endian = little-endian on Windows x64, as WAVE_FORMAT_PCM expects.
    const bytes = std.mem.sliceAsBytes(src);
    @memcpy(dst[0..bytes.len], bytes);
}

// ---- tests ----

fn slot(comptime T: type, comptime name: []const u8) usize {
    return @offsetOf(T, name) / @sizeOf(usize);
}

test "IAudioRenderClient vtable slots match audioclient.h" {
    const R = IAudioRenderClient.VTable;
    // IUnknown (3) + GetBuffer, ReleaseBuffer
    try std.testing.expectEqual(@as(usize, 3), slot(R, "GetBuffer"));
    try std.testing.expectEqual(@as(usize, 4), slot(R, "ReleaseBuffer"));
    try std.testing.expectEqual(@as(usize, 5), @sizeOf(R) / @sizeOf(usize));
}

test "IID_IAudioRenderClient GUID has correct bytes" {
    try std.testing.expectEqual(@as(u32, 0xF294ACFC), IID_IAudioRenderClient.Data1);
    try std.testing.expectEqual(@as(u16, 0x3146), IID_IAudioRenderClient.Data2);
    try std.testing.expectEqual(@as(u16, 0x4483), IID_IAudioRenderClient.Data3);
    try std.testing.expectEqual(@as(u8, 0xA7), IID_IAudioRenderClient.Data4[0]);
    try std.testing.expectEqual(@as(u8, 0xE2), IID_IAudioRenderClient.Data4[7]);
}

test "copySamples writes int16 LE to byte buffer" {
    var src = [_]i16{ 0, 32767, -32768, 1234 };
    var dst = [_]u8{0} ** 8;
    copySamples(&dst, &src);
    // Native little-endian on Windows x64.
    try std.testing.expectEqual(@as(u8, 0), dst[0]);
    try std.testing.expectEqual(@as(u8, 0), dst[1]);
    try std.testing.expectEqual(@as(u8, 0xFF), dst[2]);
    try std.testing.expectEqual(@as(u8, 0x7F), dst[3]);
    try std.testing.expectEqual(@as(u8, 0x00), dst[4]);
    try std.testing.expectEqual(@as(u8, 0x80), dst[5]);
}

test "findDevice: known id returns its entry, unknown id returns null" {
    var id_a = "{0.0.0}.{aaa}".*;
    var name_a = "LG SMARTGAME+".*;
    var id_b = "{0.0.0}.{bbb}".*;
    var name_b = "Speakers (Focusrite)".*;
    const list = [_]wasapi.DeviceInfo{
        .{ .id = &id_a, .name = &name_a, .is_default = true },
        .{ .id = &id_b, .name = &name_b, .is_default = false },
    };
    try std.testing.expectEqualStrings("Speakers (Focusrite)", findDevice(&list, "{0.0.0}.{bbb}").?.name);
    try std.testing.expect(findDevice(&list, "{bogus-device-id}") == null);
    try std.testing.expect(findDevice(&list, "") == null);
}
