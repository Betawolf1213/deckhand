const std = @import("std");
const recognizer = @import("recognizer.zig");

// whisper.cpp C API bindings; build.zig links vendor/whisper.cpp/whisper.lib when present.

pub const WhisperContext = opaque {};

pub const SAMPLE_RATE: u32 = 16000;

pub const SamplingStrategy = enum(c_int) {
    greedy = 0,
    beam_search = 1,
};

// ABI-sensitive and large: treated opaquely, filled by whisper_full_default_params.
pub const WhisperFullParams = extern struct {
    // Layout intentionally opaque — do not reach into fields.
    _opaque: [512]u8,
};

pub const WhisperContextParams = extern struct {
    use_gpu: bool,
    flash_attn: bool,
    gpu_device: c_int,
    dtw_token_timestamps: bool,
    dtw_aheads_preset: c_int,
    dtw_n_top: c_int,
    _dtw_aheads_stub: [64]u8,
    dtw_mem_size: usize,
};

extern "whisper" fn whisper_context_default_params() callconv(.C) WhisperContextParams;
extern "whisper" fn whisper_full_default_params(strategy: c_int) callconv(.C) WhisperFullParams;

extern "whisper" fn whisper_init_from_file_with_params(
    path_model: [*:0]const u8,
    params: WhisperContextParams,
) callconv(.C) ?*WhisperContext;

extern "whisper" fn whisper_free(ctx: *WhisperContext) callconv(.C) void;

extern "whisper" fn whisper_full(
    ctx: *WhisperContext,
    params: WhisperFullParams,
    samples: [*]const f32,
    n_samples: c_int,
) callconv(.C) c_int;

extern "whisper" fn whisper_full_n_segments(ctx: *WhisperContext) callconv(.C) c_int;
extern "whisper" fn whisper_full_get_segment_text(ctx: *WhisperContext, i_segment: c_int) callconv(.C) [*:0]const u8;

pub const Engine = struct {
    allocator: std.mem.Allocator,
    ctx: *WhisperContext,
    text_buf: std.ArrayList(u8),
    float_buf: std.ArrayList(f32),

    pub const InitOpts = struct {
        model_path: [:0]const u8,
        use_gpu: bool = false,
    };

    pub fn init(allocator: std.mem.Allocator, opts: InitOpts) recognizer.Error!Engine {
        var params = whisper_context_default_params();
        params.use_gpu = opts.use_gpu;
        const ctx = whisper_init_from_file_with_params(opts.model_path.ptr, params) orelse
            return recognizer.Error.ModelLoadFailed;
        return .{
            .allocator = allocator,
            .ctx = ctx,
            .text_buf = std.ArrayList(u8).init(allocator),
            .float_buf = std.ArrayList(f32).init(allocator),
        };
    }

    pub fn deinit(self: *Engine) void {
        whisper_free(self.ctx);
        self.text_buf.deinit();
        self.float_buf.deinit();
    }

    // One-shot transcription of a whole VAD utterance (<= 30 s), for low-confidence Vosk results.
    pub fn transcribe(self: *Engine, samples: []const i16) recognizer.Error!recognizer.Result {
        try self.float_buf.resize(samples.len);
        for (samples, 0..) |s, i| {
            self.float_buf.items[i] = @as(f32, @floatFromInt(s)) / 32768.0;
        }

        const params = whisper_full_default_params(@intFromEnum(SamplingStrategy.greedy));
        const rc = whisper_full(self.ctx, params, self.float_buf.items.ptr, @intCast(self.float_buf.items.len));
        if (rc != 0) return recognizer.Error.RecognizeFailed;

        self.text_buf.clearRetainingCapacity();
        const n = whisper_full_n_segments(self.ctx);
        var i: c_int = 0;
        while (i < n) : (i += 1) {
            const seg = std.mem.span(whisper_full_get_segment_text(self.ctx, i));
            if (self.text_buf.items.len > 0) try self.text_buf.append(' ');
            try self.text_buf.appendSlice(std.mem.trim(u8, seg, " \t\n"));
        }

        return .{
            .text = self.text_buf.items,
            .confidence = if (self.text_buf.items.len > 0) 0.80 else 0.0,
            .is_final = true,
        };
    }
};
