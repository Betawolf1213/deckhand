const std = @import("std");
const windows = std.os.windows;
const protocol = @import("protocol.zig");

pub const PIPE_NAME_A: [*:0]const u8 = "\\\\.\\pipe\\deckhand";
pub const PIPE_NAME_W: [*:0]const u16 = L("\\\\.\\pipe\\deckhand");

fn L(comptime s: []const u8) [*:0]const u16 {
    return std.unicode.utf8ToUtf16LeStringLiteral(s);
}

// ---- Win32 pipe API ----

pub const PIPE_ACCESS_DUPLEX: u32 = 0x00000003;
pub const FILE_FLAG_FIRST_PIPE_INSTANCE: u32 = 0x00080000;
pub const PIPE_TYPE_BYTE: u32 = 0x00000000;
pub const PIPE_READMODE_BYTE: u32 = 0x00000000;
pub const PIPE_WAIT: u32 = 0x00000000;
pub const PIPE_REJECT_REMOTE_CLIENTS: u32 = 0x00000008;

pub const ERROR_PIPE_CONNECTED: u32 = 535;
pub const ERROR_BROKEN_PIPE: u32 = 109;
pub const ERROR_NO_DATA: u32 = 232;
pub const ERROR_PIPE_LISTENING: u32 = 536;

extern "kernel32" fn CreateNamedPipeW(
    lpName: [*:0]const u16,
    dwOpenMode: u32,
    dwPipeMode: u32,
    nMaxInstances: u32,
    nOutBufferSize: u32,
    nInBufferSize: u32,
    nDefaultTimeOut: u32,
    lpSecurityAttributes: ?*anyopaque,
) callconv(windows.WINAPI) windows.HANDLE;

extern "kernel32" fn ConnectNamedPipe(
    hNamedPipe: windows.HANDLE,
    lpOverlapped: ?*anyopaque,
) callconv(windows.WINAPI) windows.BOOL;

extern "kernel32" fn DisconnectNamedPipe(hNamedPipe: windows.HANDLE) callconv(windows.WINAPI) windows.BOOL;

extern "kernel32" fn ReadFile(
    hFile: windows.HANDLE,
    lpBuffer: [*]u8,
    nNumberOfBytesToRead: u32,
    lpNumberOfBytesRead: *u32,
    lpOverlapped: ?*anyopaque,
) callconv(windows.WINAPI) windows.BOOL;

extern "kernel32" fn WriteFile(
    hFile: windows.HANDLE,
    lpBuffer: [*]const u8,
    nNumberOfBytesToWrite: u32,
    lpNumberOfBytesWritten: *u32,
    lpOverlapped: ?*anyopaque,
) callconv(windows.WINAPI) windows.BOOL;

extern "kernel32" fn FlushFileBuffers(hFile: windows.HANDLE) callconv(windows.WINAPI) windows.BOOL;

extern "kernel32" fn PeekNamedPipe(
    hNamedPipe: windows.HANDLE,
    lpBuffer: ?*anyopaque,
    nBufferSize: u32,
    lpBytesRead: ?*u32,
    lpTotalBytesAvail: ?*u32,
    lpBytesLeftThisMessage: ?*u32,
) callconv(windows.WINAPI) windows.BOOL;

// ---- Server ----

pub const InboundHandler = *const fn (msg: protocol.Inbound, user: ?*anyopaque) void;

pub const Error = error{
    CreatePipeFailed,
    ThreadSpawnFailed,
} || std.mem.Allocator.Error;

pub const Server = struct {
    allocator: std.mem.Allocator,
    pipe: windows.HANDLE = windows.INVALID_HANDLE_VALUE,
    thread: ?std.Thread = null,
    handler: InboundHandler,
    handler_user: ?*anyopaque,
    outbound_mutex: std.Thread.Mutex = .{},
    outbound_cond: std.Thread.Condition = .{},
    outbound_buf: std.ArrayList(u8),
    connected: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),
    shutting_down: std.atomic.Value(bool) = std.atomic.Value(bool).init(false),

    pub fn init(
        allocator: std.mem.Allocator,
        handler: InboundHandler,
        handler_user: ?*anyopaque,
    ) Server {
        return .{
            .allocator = allocator,
            .handler = handler,
            .handler_user = handler_user,
            .outbound_buf = std.ArrayList(u8).init(allocator),
        };
    }

    pub fn deinit(self: *Server) void {
        self.outbound_buf.deinit();
    }

    pub fn start(self: *Server) Error!void {
        const t = std.Thread.spawn(.{}, acceptLoop, .{self}) catch return Error.ThreadSpawnFailed;
        self.thread = t;
    }

    pub fn stop(self: *Server) void {
        self.shutting_down.store(true, .release);
        // Wake any waiter and close pipe so accept loop unblocks.
        self.outbound_cond.broadcast();
        if (self.pipe != windows.INVALID_HANDLE_VALUE) {
            _ = DisconnectNamedPipe(self.pipe);
            windows.CloseHandle(self.pipe);
            self.pipe = windows.INVALID_HANDLE_VALUE;
        }
        if (self.thread) |t| t.join();
        self.thread = null;
    }

    // Queue as a JSON line (thread-safe); dropped with no client so audio_level can't pile up.
    pub fn send(self: *Server, msg: protocol.Outbound) !void {
        self.outbound_mutex.lock();
        defer self.outbound_mutex.unlock();
        if (!self.connected.load(.acquire)) return;
        try msg.write(self.outbound_buf.writer());
        self.outbound_cond.signal();
    }

    fn acceptLoop(self: *Server) void {
        while (!self.shutting_down.load(.acquire)) {
            const pipe = CreateNamedPipeW(
                PIPE_NAME_W,
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1, // single instance — one GUI at a time
                64 * 1024,
                64 * 1024,
                0,
                null,
            );
            if (pipe == windows.INVALID_HANDLE_VALUE) {
                std.debug.print("CreateNamedPipeW failed: {}\n", .{windows.kernel32.GetLastError()});
                std.time.sleep(1 * std.time.ns_per_s);
                continue;
            }
            self.pipe = pipe;

            const ok = ConnectNamedPipe(pipe, null);
            const err = windows.kernel32.GetLastError();
            if (ok == 0 and @intFromEnum(err) != ERROR_PIPE_CONNECTED) {
                windows.CloseHandle(pipe);
                self.pipe = windows.INVALID_HANDLE_VALUE;
                if (self.shutting_down.load(.acquire)) return;
                std.time.sleep(500 * std.time.ns_per_ms);
                continue;
            }

            {
                self.outbound_mutex.lock();
                defer self.outbound_mutex.unlock();
                self.outbound_buf.clearRetainingCapacity();
                self.connected.store(true, .release);
            }

            // Writer thread drains outbound_buf while reader loop runs here.
            var writer_thread = std.Thread.spawn(.{}, writerLoop, .{self}) catch {
                windows.CloseHandle(pipe);
                self.pipe = windows.INVALID_HANDLE_VALUE;
                continue;
            };

            self.readerLoop();

            self.connected.store(false, .release);
            self.outbound_cond.broadcast(); // wake writer so it can exit
            writer_thread.join();

            _ = DisconnectNamedPipe(pipe);
            windows.CloseHandle(pipe);
            self.pipe = windows.INVALID_HANDLE_VALUE;
        }
    }

    fn readerLoop(self: *Server) void {
        var scratch: [4096]u8 = undefined;
        var line: std.ArrayList(u8) = std.ArrayList(u8).init(self.allocator);
        defer line.deinit();

        while (!self.shutting_down.load(.acquire)) {
            // PeekNamedPipe before ReadFile: a blocking read on this sync handle stalls writes.
            var avail: u32 = 0;
            if (PeekNamedPipe(self.pipe, null, 0, null, &avail, null) == 0) return; // disconnected
            if (avail == 0) {
                std.time.sleep(10 * std.time.ns_per_ms);
                continue;
            }
            const to_read: u32 = @min(avail, @as(u32, scratch.len));
            var got: u32 = 0;
            const ok = ReadFile(self.pipe, &scratch, to_read, &got, null);
            if (ok == 0 or got == 0) return; // client disconnected

            const chunk = scratch[0..got];
            var i: usize = 0;
            while (i < chunk.len) {
                const nl = std.mem.indexOfScalarPos(u8, chunk, i, '\n') orelse {
                    line.appendSlice(chunk[i..]) catch return;
                    break;
                };
                line.appendSlice(chunk[i..nl]) catch return;
                self.dispatchLine(line.items);
                line.clearRetainingCapacity();
                i = nl + 1;
            }
        }
    }

    fn dispatchLine(self: *Server, raw: []const u8) void {
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, raw, .{}) catch {
            self.handler(.{ .unknown = "bad-json" }, self.handler_user);
            return;
        };
        defer parsed.deinit();
        const msg = protocol.Inbound.parse(parsed.value);
        self.handler(msg, self.handler_user);
    }

    fn writerLoop(self: *Server) void {
        var out_scratch: std.ArrayList(u8) = std.ArrayList(u8).init(self.allocator);
        defer out_scratch.deinit();

        while (self.connected.load(.acquire)) {
            self.outbound_mutex.lock();
            while (self.outbound_buf.items.len == 0 and self.connected.load(.acquire) and !self.shutting_down.load(.acquire)) {
                self.outbound_cond.wait(&self.outbound_mutex);
            }
            out_scratch.clearRetainingCapacity();
            out_scratch.appendSlice(self.outbound_buf.items) catch {};
            self.outbound_buf.clearRetainingCapacity();
            self.outbound_mutex.unlock();

            if (out_scratch.items.len == 0) continue;

            var written: u32 = 0;
            const ok = WriteFile(self.pipe, out_scratch.items.ptr, @intCast(out_scratch.items.len), &written, null);
            if (ok == 0) return;
            _ = FlushFileBuffers(self.pipe);
        }
    }
};

test "server construct" {
    var s = Server.init(std.testing.allocator, dummyHandler, null);
    defer s.deinit();
    // We don't start it in tests — CreateNamedPipeW would need Windows.
}

fn dummyHandler(msg: protocol.Inbound, user: ?*anyopaque) void {
    _ = msg;
    _ = user;
}
