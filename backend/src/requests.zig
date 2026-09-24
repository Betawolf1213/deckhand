const std = @import("std");

// Pipe thread queues, main loop (owner of recognizer/capture/hotkey) applies; latest per kind wins.

pub const Requests = struct {
    allocator: std.mem.Allocator,
    mutex: std.Thread.Mutex = .{},
    pending: Batch = .{},

    pub const Batch = struct {
        reload: bool = false,
        list_devices: bool = false,
        device: ?[]u8 = null, // "" = Windows default
        hotkey: ?[]u8 = null, // "" = disable
        stop_hotkey: ?[]u8 = null, // "" = disable

        pub fn isEmpty(self: *const Batch) bool {
            return !self.reload and !self.list_devices and self.device == null and self.hotkey == null and self.stop_hotkey == null;
        }

        pub fn deinit(self: *Batch, a: std.mem.Allocator) void {
            if (self.device) |d| a.free(d);
            if (self.hotkey) |h| a.free(h);
            if (self.stop_hotkey) |h| a.free(h);
            self.* = .{};
        }
    };

    pub fn init(allocator: std.mem.Allocator) Requests {
        return .{ .allocator = allocator };
    }

    pub fn deinit(self: *Requests) void {
        self.pending.deinit(self.allocator);
    }

    pub fn requestReload(self: *Requests) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.pending.reload = true;
    }

    pub fn requestDeviceList(self: *Requests) void {
        self.mutex.lock();
        defer self.mutex.unlock();
        self.pending.list_devices = true;
    }

    pub fn requestDevice(self: *Requests, id: []const u8) !void {
        const copy = try self.allocator.dupe(u8, id);
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.pending.device) |old| self.allocator.free(old);
        self.pending.device = copy;
    }

    pub fn requestHotkey(self: *Requests, chord: []const u8) !void {
        const copy = try self.allocator.dupe(u8, chord);
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.pending.hotkey) |old| self.allocator.free(old);
        self.pending.hotkey = copy;
    }

    pub fn requestStopHotkey(self: *Requests, chord: []const u8) !void {
        const copy = try self.allocator.dupe(u8, chord);
        self.mutex.lock();
        defer self.mutex.unlock();
        if (self.pending.stop_hotkey) |old| self.allocator.free(old);
        self.pending.stop_hotkey = copy;
    }

    /// Take everything pending; caller must `batch.deinit(allocator)`.
    pub fn take(self: *Requests) Batch {
        self.mutex.lock();
        defer self.mutex.unlock();
        const b = self.pending;
        self.pending = .{};
        return b;
    }
};

test "requests: empty take" {
    var r = Requests.init(std.testing.allocator);
    defer r.deinit();
    var b = r.take();
    defer b.deinit(std.testing.allocator);
    try std.testing.expect(b.isEmpty());
}

test "requests: latest device and hotkey win, flags coalesce" {
    const a = std.testing.allocator;
    var r = Requests.init(a);
    defer r.deinit();
    r.requestReload();
    r.requestReload();
    r.requestDeviceList();
    try r.requestDevice("{old}");
    try r.requestDevice("");
    try r.requestHotkey("f8");
    try r.requestHotkey("alt+f10");
    var b = r.take();
    defer b.deinit(a);
    try std.testing.expect(b.reload and b.list_devices);
    try std.testing.expectEqualStrings("", b.device.?);
    try std.testing.expectEqualStrings("alt+f10", b.hotkey.?);
    var again = r.take();
    defer again.deinit(a);
    try std.testing.expect(again.isEmpty());
}

test "requests: deinit frees untaken strings" {
    var r = Requests.init(std.testing.allocator);
    try r.requestDevice("{x}");
    try r.requestHotkey("f9");
    r.deinit(); // testing allocator reports leaks
}
