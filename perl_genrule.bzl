"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

load("@rules_cc//cc:defs.bzl", "CcInfo", "cc_common")

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

def generate_commands(binary, assembly_flavor, srcs_to_outs, srcs_to_outs_dupes, ctx):
    """Generate commands needed to produces outs from sources. 

    Args:
        binary: The binary to run
        assembly_flavor: The type of assembly to produce
        srcs_to_outs: The main sources to outputs dict
        srcs_to_outs_dupes: The secondary sources to outputs dict
        ctx: The bazel rule context
    Returns:
        The commands joined on comma, the source files and the output files
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
    if ctx.attr.is_unix:
        return ",".join([ctx.expand_make_variables(command, "$(PERL)", {"PERL": ctx.attr.perl_toolchain.perl_runtime.interpreter}) for command in commands]), src_files, out_files
    else:
        return ";".join(commands), src_files, out_files

def _perl_genrule_impl(ctx):
    # On Unix we want to use rules_perl version
    binary_invocation = "perl"
    if ctx.attr.is_unix:
        binary_invocation = "$(PERL)"
    additional_srcs = combine_list_of_lists([src.files.to_list() for src in ctx.attr.additional_srcs])

    commands_joined, srcs_as_files, outs_as_files = generate_commands(binary_invocation, ctx.attr.assembly_flavor, ctx.attr.srcs_to_outs, ctx.attr.srcs_to_outs_dupes, ctx)
    outs_as_files_paths = [out.path for out in outs_as_files]
    srcs_as_files_paths = [src.path for src in srcs_as_files]
    perl_generate_file = ctx.file._perl_generate_file
    if ctx.attr.is_unix:
        ctx.actions.run(
            inputs = srcs_as_files + additional_srcs,
            outputs = outs_as_files,
            executable = perl_generate_file,
            arguments = [commands_joined],
            mnemonic = "GenerateAssemblyFromPerlScripts",
            progress_message = "Generating files {} from scripts {}".format(outs_as_files_paths, srcs_as_files_paths),
            toolchain = ctx.attr.perl_toolchain,
        )
    else:
        ctx.actions.run_shell(
            inputs = srcs_as_files + additional_srcs,
            outputs = outs_as_files,
            command = commands_joined,
            mnemonic = "GenerateAssemblyFromPerlScriptsOnWindows",
            progress_message = "Generating files {} from scripts {} on Windows".format(outs_as_files_paths, srcs_as_files_paths),
            use_default_shell_env = True,
        )

    cc_info = CcInfo(
        compilation_context = cc_common.create_compilation_context(direct_private_headers = outs_as_files),
    )
    ret = [DefaultInfo(files = depset(outs_as_files)), cc_info]
    return ret

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        # Additional sources needed by the generation scripts.
        "additional_srcs": attr.label_list(allow_files = True, doc = "List of other input files used by the main input files."),
        # We specify what assemby flavor to use based on os and architecture.
        "assembly_flavor": attr.string(doc = "What flavor to use for assembly generation."),
        # We need to know what os this is running on.
        "is_unix": attr.bool(doc = "Whether this is mac or linux or not."),
        # The dict of srcs to their outs.
        "srcs_to_outs": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files from their source script."),
        # The dicts of srcs to their outs when they are dupes from the first dict.
        "srcs_to_outs_dupes": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files where the source is dupe from the first dict."),
        # Current perl toolchain
        "perl_toolchain": attr.label(doc = "The perl toolchain to use to run the generation scripts."),
        # Script that handles the file generation and existence check. Only used on nix.
        "_perl_generate_file": attr.label(
            allow_single_file = True,
            executable = True,
            cfg = "exec",
            default = "@openssl-generated-overlay//:perl_generate_file.sh",
        ),
    },
    toolchains = [config_common.toolchain_type("@rules_perl//perl:toolchain_type", mandatory = False)],
)
