const std = @import("std");

// Recognizer interface (Vosk primary, Whisper fallback); input is 16 kHz mono i16 PCM.

pub const EngineTag = enum { vosk, whisper };

pub const Result = struct {
    text: []const u8,
    confidence: f32,
    is_final: bool,
    // Text is engine-owned and valid only until the next call into that engine.
};

pub const Error = error{
    InitFailed,
    ModelLoadFailed,
    GrammarLoadFailed,
    DllMissing,
    RecognizeFailed,
} || std.mem.Allocator.Error;

// Confidence threshold below which we fall through from Vosk to Whisper.
pub const FALLBACK_CONFIDENCE: f32 = 0.65;
