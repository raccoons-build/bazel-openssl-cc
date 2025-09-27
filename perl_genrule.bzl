"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

load("@rules_cc//cc:action_names.bzl", "ACTION_NAMES")
load("@rules_cc//cc:defs.bzl", "CcInfo", "cc_common")
load("@rules_cc//cc:find_cc_toolchain.bzl", "find_cc_toolchain", "use_cc_toolchain")

def combine_list_of_lists(list_of_lists):
    final_list = []
    for lst in list_of_lists:
        final_list = final_list + lst
    return final_list

def generate_single_command(binary, assembly_flavor, src, out, ctx):
    """Find the sources and outs and the command for a single src and out.

    Args:
        binary: The binary to run
        assembly_flavor: The assembly flavor to produce
        src: The source to use
        out: The output to produce
        ctx: The bazel rule context
    Returns:
        A list with the command to run, The source files and the out files.
    """
    out_files = []
    src_files = []
    commands = []
    out_file = ctx.actions.declare_file(out)
    src_files = src.files.to_list()

    # We only care about the first source since there should only be
    src_file = src_files[0]
    command = "{} {} {} {}".format(binary, src_file.path, assembly_flavor, out_file.path)
    commands.append(command)
    src_files.append(src_file)
    out_files.append(out_file)
    return commands, src_files, out_files

def generate_commands(binary, assembly_flavor, srcs_to_outs, srcs_to_outs_dupes, ctx, is_windows):
    """Generate commands needed to produces outs from sources.

    Args:
        binary: The binary to run
        assembly_flavor: The type of assembly to produce
        srcs_to_outs: The main sources to outputs dict
        srcs_to_outs_dupes: The secondary sources to outputs dict
        ctx: The bazel rule context
        is_windows: Whether or not the exec platform is windows.
    Returns:
        The commands, the source files and the output files
    """
    commands = []
    out_files = []
    src_files = []
    for src, out in srcs_to_outs.items():
        intermediate_commands, intermediate_src_files, intermediate_out_files = generate_single_command(binary, assembly_flavor, src, out, ctx)
        commands = commands + intermediate_commands
        out_files = out_files + intermediate_out_files
        src_files = src_files + intermediate_src_files
    for src, out in srcs_to_outs_dupes.items():
        intermediate_commands, intermediate_src_files, intermediate_out_files = generate_single_command(binary, assembly_flavor, src, out, ctx)
        commands = commands + intermediate_commands
        out_files = out_files + intermediate_out_files
        src_files = src_files + intermediate_src_files

    if is_windows:
        commands = [c.replace("/", "\\") for c in commands]

    return commands, src_files, out_files

_WINDOWS_TEMPLATE = """\
@ECHO OFF
{}
"""

_UNIX_TEMPLATE = """\
#!/usr/bin/env bash
set -euo pipefail
{}
"""

def _perl_genrule_impl(ctx):
    cc_toolchain = find_cc_toolchain(ctx)

    feature_configuration = cc_common.configure_features(
        ctx = ctx,
        cc_toolchain = cc_toolchain,
        requested_features = ctx.features,
        unsupported_features = ctx.disabled_features,
    )
    env = {
        "CC": cc_common.get_tool_for_action(
            feature_configuration = feature_configuration,
            action_name = ACTION_NAMES.c_compile,
        ),
    }

    perl_interpreter = ctx.attr._perl_toolchain[platform_common.ToolchainInfo].perl_runtime.interpreter
    is_windows = perl_interpreter.basename.endswith((".exe", ".bat", ".ps1"))
    additional_srcs = combine_list_of_lists([src.files.to_list() for src in ctx.attr.additional_srcs])

    commands, srcs_as_files, outs_as_files = generate_commands(
        perl_interpreter.path,
        ctx.attr.assembly_flavor,
        ctx.attr.srcs_to_outs,
        ctx.attr.srcs_to_outs_dupes,
        ctx,
        is_windows,
    )

    action_runner = ctx.actions.declare_file("{}.action_runner.{}".format(ctx.label.name, "bat" if is_windows else "sh"))
    template = _WINDOWS_TEMPLATE if is_windows else _UNIX_TEMPLATE
    ctx.actions.write(
        output = action_runner,
        content = template.format("\n".join(commands)),
        is_executable = True,
    )

    outs_as_files_paths = [out.path for out in outs_as_files]
    srcs_as_files_paths = [src.path for src in srcs_as_files]

    ctx.actions.run(
        inputs = depset(direct = srcs_as_files + additional_srcs),
        outputs = outs_as_files,
        executable = action_runner,
        env = env,
        mnemonic = "OpenSSLGenerateAssemblyFromPerlScripts",
        progress_message = "Generating files {} from scripts {}".format(outs_as_files_paths, srcs_as_files_paths),
        tools = depset(
            direct = [perl_interpreter],
            transitive = [cc_toolchain.all_files, ctx.attr._perl_toolchain[platform_common.ToolchainInfo].perl_runtime.runtime],
        ),
    )

    return [
        DefaultInfo(
            files = depset(outs_as_files),
        ),
        CcInfo(
            compilation_context = cc_common.create_compilation_context(
                direct_private_headers = outs_as_files,
            ),
        ),
    ]

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        "additional_srcs": attr.label_list(
            doc = "List of other input files used by the main input files.",
            allow_files = True,
        ),
        "assembly_flavor": attr.string(
            doc = "What flavor to use for assembly generation.",
        ),
        "srcs_to_outs": attr.label_keyed_string_dict(
            doc = "Dict of input to output files from their source script.",
            allow_files = True,
        ),
        "srcs_to_outs_dupes": attr.label_keyed_string_dict(
            doc = "Dict of input to output files where the source is dupe from the first dict.",
            allow_files = True,
        ),
        "_perl_toolchain": attr.label(
            cfg = "exec",
            default = Label("@rules_perl//perl:current_toolchain"),
        ),
    },
    fragments = ["cpp"],
    toolchains = use_cc_toolchain(),
)
