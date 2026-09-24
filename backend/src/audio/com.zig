const std = @import("std");
const windows = std.os.windows;

pub const HRESULT = windows.HRESULT;
pub const S_OK: HRESULT = 0;

pub const GUID = extern struct {
    Data1: u32,
    Data2: u16,
    Data3: u16,
    Data4: [8]u8,
};

pub const COINIT_MULTITHREADED: windows.DWORD = 0x0;
pub const COINIT_APARTMENTTHREADED: windows.DWORD = 0x2;

pub const CLSCTX_INPROC_SERVER: windows.DWORD = 0x1;
pub const CLSCTX_ALL: windows.DWORD = 0x17;

pub extern "ole32" fn CoInitializeEx(pvReserved: ?*anyopaque, dwCoInit: windows.DWORD) callconv(windows.WINAPI) HRESULT;
pub extern "ole32" fn CoUninitialize() callconv(windows.WINAPI) void;
pub extern "ole32" fn CoCreateInstance(
    rclsid: *const GUID,
    pUnkOuter: ?*anyopaque,
    dwClsContext: windows.DWORD,
    riid: *const GUID,
    ppv: *?*anyopaque,
) callconv(windows.WINAPI) HRESULT;
pub extern "ole32" fn CoTaskMemFree(pv: ?*anyopaque) callconv(windows.WINAPI) void;

pub const Error = error{
    CoInitFailed,
    NoDevice,
    NoInterface,
    ActivateFailed,
    InitializeFailed,
    GetServiceFailed,
    StartFailed,
    StopFailed,
    GetBufferFailed,
    ReleaseBufferFailed,
    UnsupportedFormat,
    EnumFailed,
};

pub fn ok(hr: HRESULT) bool {
    return hr >= 0;
}
