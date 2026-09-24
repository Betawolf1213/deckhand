const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{
        .default_target = .{ .os_tag = .windows, .abi = .gnu },
    });
    const optimize = b.standardOptimizeOption(.{});

    const default_elevate = optimize != .Debug;
    const elevate = b.option(bool, "elevate", "Embed requireAdministrator manifest (default: release=true, debug=false)") orelse default_elevate;

    // Vosk auto-detected (scripts/fetch_models.ps1); without it the recognizer is stubbed.
    const vosk_present = fileExists("vendor/vosk-api/libvosk.lib");
    const with_vosk = b.option(bool, "vosk", "Link libvosk (auto-detected from vendor/vosk-api/libvosk.lib)") orelse vosk_present;

    // whisper.cpp auto-detected from vendor/whisper.cpp/whisper.lib; -Dwhisper=false opts out.
    const whisper_present = fileExists("vendor/whisper.cpp/whisper.lib");
    const with_whisper = b.option(bool, "whisper", "Link whisper.cpp (auto-detected from vendor/whisper.cpp/whisper.lib)") orelse whisper_present;

    const build_opts = b.addOptions();
    build_opts.addOption(bool, "with_vosk", with_vosk);
    build_opts.addOption(bool, "with_whisper", with_whisper);

    const exe = b.addExecutable(.{
        .name = "deckhand",
        .root_source_file = b.path("backend/src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe.root_module.addOptions("build_options", build_opts);

    exe.linkLibC();
    if (target.result.os.tag == .windows) {
        exe.linkSystemLibrary("user32");
        exe.linkSystemLibrary("advapi32");
        exe.linkSystemLibrary("ole32");
        exe.linkSystemLibrary("oleaut32");
        exe.linkSystemLibrary("shell32");
        exe.linkSystemLibrary("kernel32");
        exe.linkSystemLibrary("winmm"); // PlaySound for TTS playback

        if (with_vosk) {
            exe.addLibraryPath(b.path("vendor/vosk-api"));
            exe.linkSystemLibrary("libvosk");
        }

        if (with_whisper) {
            exe.addLibraryPath(b.path("vendor/whisper.cpp"));
            exe.linkSystemLibrary("whisper");
        }

        const rc_flags: []const []const u8 = if (elevate)
            &.{ "/D", "ELEVATE=1" }
        else
            &.{};

        exe.addWin32ResourceFile(.{
            .file = b.path("backend/resources/deckhand.rc"),
            .flags = rc_flags,
        });
    }

    b.installArtifact(exe);

    // Install Vosk and its MinGW runtime DLLs beside the executable.
    if (with_vosk) {
        const vosk_dll = b.addInstallBinFile(b.path("vendor/vosk-api/libvosk.dll"), "libvosk.dll");
        b.getInstallStep().dependOn(&vosk_dll.step);
        const libstdcxx_dll = b.addInstallBinFile(b.path("vendor/vosk-api/libstdc++-6.dll"), "libstdc++-6.dll");
        const libgcc_dll = b.addInstallBinFile(b.path("vendor/vosk-api/libgcc_s_seh-1.dll"), "libgcc_s_seh-1.dll");
        const winpthread_dll = b.addInstallBinFile(b.path("vendor/vosk-api/libwinpthread-1.dll"), "libwinpthread-1.dll");
        b.getInstallStep().dependOn(&libstdcxx_dll.step);
        b.getInstallStep().dependOn(&libgcc_dll.step);
        b.getInstallStep().dependOn(&winpthread_dll.step);
    }
    if (with_whisper) {
        const dll = b.addInstallBinFile(b.path("vendor/whisper.cpp/whisper.dll"), "whisper.dll");
        b.getInstallStep().dependOn(&dll.step);
    }

    const run_cmd = b.addRunArtifact(exe);
    run_cmd.step.dependOn(b.getInstallStep());
    if (b.args) |args| run_cmd.addArgs(args);
    const run_step = b.step("run", "Run the backend");
    run_step.dependOn(&run_cmd.step);

    const unit_tests = b.addTest(.{
        .root_source_file = b.path("backend/src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    unit_tests.root_module.addOptions("build_options", build_opts);
    const run_unit_tests = b.addRunArtifact(unit_tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_unit_tests.step);
}

fn fileExists(path: []const u8) bool {
    std.fs.cwd().access(path, .{}) catch return false;
    return true;
}
