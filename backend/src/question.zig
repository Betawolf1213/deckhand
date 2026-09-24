const std = @import("std");

// Question detection (docs/IPC.md rule 2): a lead-word utterance goes to the GUI; no command fires.

pub const LEADS = [_][]const u8{ "what", "where", "which", "who", "how", "list", "show", "tell", "find" };

/// True when the first word is a question lead (case-insensitive; "what's" counts, "however" not).
pub fn startsWithLead(text: []const u8) bool {
    const trimmed = std.mem.trimLeft(u8, text, " \t\r\n");
    const end = std.mem.indexOfAny(u8, trimmed, " \t\r\n") orelse trimmed.len;
    var word = trimmed[0..end];
    // "what's" / "who's" / "where'd" -> "what" / "who" / "where"
    if (std.mem.indexOfScalar(u8, word, '\'')) |apos| word = word[0..apos];
    if (word.len == 0) return false;
    for (LEADS) |lead| {
        if (std.ascii.eqlIgnoreCase(word, lead)) return true;
    }
    return false;
}

test "question leads are detected" {
    try std.testing.expect(startsWithLead("what is the price of gold"));
    try std.testing.expect(startsWithLead("where can i sell titanium"));
    try std.testing.expect(startsWithLead("which ship is fastest"));
    try std.testing.expect(startsWithLead("who makes the cutlass"));
    try std.testing.expect(startsWithLead("how far is crusader"));
    try std.testing.expect(startsWithLead("list mining spots"));
    try std.testing.expect(startsWithLead("show me the route"));
    try std.testing.expect(startsWithLead("tell me a joke"));
    try std.testing.expect(startsWithLead("find quantanium"));
    try std.testing.expect(startsWithLead("who"));
}

test "case, leading whitespace and contractions" {
    try std.testing.expect(startsWithLead("  What is that"));
    try std.testing.expect(startsWithLead("WHERE"));
    try std.testing.expect(startsWithLead("what's the best ship"));
    try std.testing.expect(startsWithLead("who's online"));
}

test "non-questions are rejected" {
    try std.testing.expect(!startsWithLead("landing gear"));
    try std.testing.expect(!startsWithLead("however we go"));
    try std.testing.expect(!startsWithLead("showers"));
    try std.testing.expect(!startsWithLead("whatever"));
    try std.testing.expect(!startsWithLead("[unk]"));
    try std.testing.expect(!startsWithLead(""));
    try std.testing.expect(!startsWithLead("   "));
    try std.testing.expect(!startsWithLead("power to weapons what"));
}
