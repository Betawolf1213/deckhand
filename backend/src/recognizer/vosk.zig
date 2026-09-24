const std = @import("std");
const recognizer = @import("recognizer.zig");

// Vosk C API bindings (libvosk.dll beside the exe; import lib in vendor/vosk-api/).

pub const VoskModel = opaque {};
pub const VoskRecognizer = opaque {};

extern "vosk" fn vosk_model_new(model_path: [*:0]const u8) callconv(.C) ?*VoskModel;
extern "vosk" fn vosk_model_free(model: *VoskModel) callconv(.C) void;

extern "vosk" fn vosk_recognizer_new(model: *VoskModel, sample_rate: f32) callconv(.C) ?*VoskRecognizer;
extern "vosk" fn vosk_recognizer_new_grm(model: *VoskModel, sample_rate: f32, grammar: [*:0]const u8) callconv(.C) ?*VoskRecognizer;
extern "vosk" fn vosk_recognizer_free(r: *VoskRecognizer) callconv(.C) void;

extern "vosk" fn vosk_recognizer_accept_waveform_s(r: *VoskRecognizer, data: [*]const i16, length: c_int) callconv(.C) c_int;
extern "vosk" fn vosk_recognizer_result(r: *VoskRecognizer) callconv(.C) [*:0]const u8;
extern "vosk" fn vosk_recognizer_partial_result(r: *VoskRecognizer) callconv(.C) [*:0]const u8;
extern "vosk" fn vosk_recognizer_final_result(r: *VoskRecognizer) callconv(.C) [*:0]const u8;
extern "vosk" fn vosk_recognizer_reset(r: *VoskRecognizer) callconv(.C) void;

extern "vosk" fn vosk_set_log_level(level: c_int) callconv(.C) void;

// One acoustic model shared by recognizers; Vosk refcounts it, so freeing our handle early is safe.
pub const Model = struct {
    handle: *VoskModel,

    pub fn load(model_path: [:0]const u8, quiet: bool) recognizer.Error!Model {
        if (quiet) vosk_set_log_level(-1);
        const m = vosk_model_new(model_path.ptr) orelse return recognizer.Error.ModelLoadFailed;
        return .{ .handle = m };
    }

    pub fn deinit(self: *Model) void {
        vosk_model_free(self.handle);
    }
};

pub const SAMPLE_RATE: f32 = 16000.0;

pub const Recognizer = struct {
    allocator: std.mem.Allocator,
    rec: *VoskRecognizer,
    // Copy of the latest result text, since Vosk's JSON lives in library memory.
    text_buf: std.ArrayList(u8),
    // Segments Vosk finalised mid-utterance (endpointer on pauses), joined with the final flush.
    acc: std.ArrayList(u8),

    fn make(allocator: std.mem.Allocator, rr: *VoskRecognizer) Recognizer {
        return .{
            .allocator = allocator,
            .rec = rr,
            .text_buf = std.ArrayList(u8).init(allocator),
            .acc = std.ArrayList(u8).init(allocator),
        };
    }

    /// Constrained recognizer; `grammar_json` is a phrase array (codegen.zig writeVoskJson).
    pub fn initGrammar(allocator: std.mem.Allocator, model: Model, grammar_json: []const u8) recognizer.Error!Recognizer {
        const grammar_z = try allocator.dupeZ(u8, grammar_json);
        defer allocator.free(grammar_z);
        const rr = vosk_recognizer_new_grm(model.handle, SAMPLE_RATE, grammar_z.ptr) orelse return recognizer.Error.InitFailed;
        return make(allocator, rr);
    }

    pub fn initGrammarFile(allocator: std.mem.Allocator, model: Model, grammar_json_path: [:0]const u8) recognizer.Error!Recognizer {
        const grammar = readFile(allocator, grammar_json_path) catch return recognizer.Error.GrammarLoadFailed;
        defer allocator.free(grammar);
        return initGrammar(allocator, model, grammar);
    }

    /// Open-vocabulary recognizer (used for question detection).
    pub fn initFree(allocator: std.mem.Allocator, model: Model) recognizer.Error!Recognizer {
        const rr = vosk_recognizer_new(model.handle, SAMPLE_RATE) orelse return recognizer.Error.InitFailed;
        return make(allocator, rr);
    }

    pub fn deinit(self: *Recognizer) void {
        vosk_recognizer_free(self.rec);
        self.text_buf.deinit();
        self.acc.deinit();
    }

    pub fn reset(self: *Recognizer) void {
        vosk_recognizer_reset(self.rec);
    }

    // ---- streaming API: accept() during speech, finish() at end so only the tail is decoded ----

    /// Feed 16 kHz mono i16 audio of the current utterance.
    pub fn accept(self: *Recognizer, samples: []const i16) void {
        if (samples.len == 0) return;
        if (vosk_recognizer_accept_waveform_s(self.rec, samples.ptr, @intCast(samples.len)) != 0) {
            self.appendSegment(std.mem.span(vosk_recognizer_result(self.rec)));
        }
    }

    /// Flush and return the whole utterance, then reset; text valid until the next call.
    pub fn finish(self: *Recognizer) recognizer.Error!recognizer.Result {
        self.appendSegment(std.mem.span(vosk_recognizer_final_result(self.rec)));
        vosk_recognizer_reset(self.rec);
        self.text_buf.clearRetainingCapacity();
        self.text_buf.appendSlice(self.acc.items) catch {
            self.acc.clearRetainingCapacity();
            return recognizer.Error.OutOfMemory;
        };
        self.acc.clearRetainingCapacity();
        const text = self.text_buf.items;
        return .{ .text = text, .confidence = if (text.len > 0) 0.95 else 0.0, .is_final = true };
    }

    /// Drop the current utterance.
    pub fn abort(self: *Recognizer) void {
        vosk_recognizer_reset(self.rec);
        self.acc.clearRetainingCapacity();
    }

    fn appendSegment(self: *Recognizer, json_source: []const u8) void {
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, json_source, .{}) catch return;
        defer parsed.deinit();
        if (parsed.value != .object) return;
        const v = parsed.value.object.get("text") orelse return;
        if (v != .string or v.string.len == 0) return;
        if (self.acc.items.len > 0) self.acc.append(' ') catch return;
        self.acc.appendSlice(v.string) catch return;
    }

    /// Decode one complete utterance in one go (offline / --decode-wav).
    pub fn decode(self: *Recognizer, samples: []const i16) recognizer.Error!recognizer.Result {
        self.abort();
        self.accept(samples);
        return self.finish();
    }

    // Feed 16 kHz mono i16; no confidence in Vosk's C API, so final=0.95, empty=0.0, partial=0.5.
    pub fn feed(self: *Recognizer, samples: []const i16) recognizer.Error!recognizer.Result {
        const done = vosk_recognizer_accept_waveform_s(self.rec, samples.ptr, @intCast(samples.len));
        if (done != 0) {
            const json_z = std.mem.span(vosk_recognizer_result(self.rec));
            const text = try self.extractText(json_z, "text");
            return .{
                .text = text,
                .confidence = if (text.len > 0) 0.95 else 0.0,
                .is_final = true,
            };
        } else {
            const json_z = std.mem.span(vosk_recognizer_partial_result(self.rec));
            const text = try self.extractText(json_z, "partial");
            return .{
                .text = text,
                .confidence = 0.5,
                .is_final = false,
            };
        }
    }

    pub fn final(self: *Recognizer) recognizer.Error!recognizer.Result {
        const json_z = std.mem.span(vosk_recognizer_final_result(self.rec));
        const text = try self.extractText(json_z, "text");
        return .{
            .text = text,
            .confidence = if (text.len > 0) 0.95 else 0.0,
            .is_final = true,
        };
    }

    fn extractText(self: *Recognizer, json_source: []const u8, key: []const u8) recognizer.Error![]const u8 {
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, json_source, .{}) catch return recognizer.Error.RecognizeFailed;
        defer parsed.deinit();
        self.text_buf.clearRetainingCapacity();
        if (parsed.value != .object) return self.text_buf.items;
        const v = parsed.value.object.get(key) orelse return self.text_buf.items;
        if (v != .string) return self.text_buf.items;
        self.text_buf.appendSlice(v.string) catch return recognizer.Error.OutOfMemory;
        return self.text_buf.items;
    }
};

fn readFile(allocator: std.mem.Allocator, path: [:0]const u8) ![]u8 {
    var f = try std.fs.cwd().openFile(path, .{});
    defer f.close();
    return try f.readToEndAlloc(allocator, 1 * 1024 * 1024);
}
