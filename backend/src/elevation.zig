const std = @import("std");
const windows = std.os.windows;
const builtin = @import("builtin");

// GetTokenInformation, not IsUserAnAdmin (shell32), which is legacy since Vista.
extern "advapi32" fn OpenProcessToken(
    ProcessHandle: windows.HANDLE,
    DesiredAccess: windows.DWORD,
    TokenHandle: *windows.HANDLE,
) callconv(windows.WINAPI) windows.BOOL;

extern "advapi32" fn GetTokenInformation(
    TokenHandle: windows.HANDLE,
    TokenInformationClass: c_int,
    TokenInformation: ?*anyopaque,
    TokenInformationLength: windows.DWORD,
    ReturnLength: *windows.DWORD,
) callconv(windows.WINAPI) windows.BOOL;

const TOKEN_QUERY: windows.DWORD = 0x0008;
const TokenElevation: c_int = 20;

const TOKEN_ELEVATION = extern struct {
    TokenIsElevated: windows.DWORD,
};

pub const ElevationError = error{
    OpenProcessTokenFailed,
    GetTokenInformationFailed,
    UnsupportedOs,
};

pub fn isElevated() ElevationError!bool {
    if (builtin.os.tag != .windows) return ElevationError.UnsupportedOs;

    var token: windows.HANDLE = undefined;
    if (OpenProcessToken(windows.kernel32.GetCurrentProcess(), TOKEN_QUERY, &token) == 0) {
        return ElevationError.OpenProcessTokenFailed;
    }
    defer windows.CloseHandle(token);

    var info: TOKEN_ELEVATION = .{ .TokenIsElevated = 0 };
    var returned: windows.DWORD = 0;
    if (GetTokenInformation(
        token,
        TokenElevation,
        &info,
        @sizeOf(TOKEN_ELEVATION),
        &returned,
    ) == 0) {
        return ElevationError.GetTokenInformationFailed;
    }

    return info.TokenIsElevated != 0;
}
