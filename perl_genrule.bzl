"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

def combine_list_of_lists(list_of_lists):
    final_list = []
    for lst in list_of_lists:
        final_list = final_list + lst
    return final_list

def get_binary_invocation_based_on_cpu(is_nix):
    if is_nix:
        return "perl"
    else:
        return "perl.exe"

def is_right_architecture(is_x86, out_file, src_target):
    """ Determine whether this file belongs to the current architecture.

    Args:
        is_x86: Whether this is x86 or arm64
        out_file: The name of the output file
        src_target: The name of the source target.
    Returns:
        Whether this file matches the architecture
    """

    for src_file in src_target.files.to_list():
        if is_x86 and "x86" in out_file and "x86" in src_file:
            print("Is x86 with out: {} and src: {}".format(out_file, src_file))
            return True
        if not is_x86 and "arm" in out_file and "arm" in src_file:
            print("Is arm64 with out: {} and src: {}".format(out_file, src_file))
            return True
    if is_x86:
        print("Is x86 with arm64 out: {} and src: {}".format(out_file, src_file))
    else:
        print("Is arm64 with x86 out: {} and src: {}".format(out_file, src_file))
    return False

def run_generation(ctx, src, out, binary_invocation, additional_srcs):
    """Run the generation command.

    Args:
        ctx: The context object from bazel.
        src: The source target.
        out: The output target.
        binary_invocation: The binary to run to do generation.
        additional_srcs: The other perl scripts needed in generation.
    Returns:
        The output target as a file. Should only be one.
    """
    out_as_file = ctx.actions.declare_file(out)
    src_files = src.files
    for src_as_file in src_files.to_list():
        ctx.actions.run_shell(
            inputs = [src_as_file] + additional_srcs,
            outputs = [out_as_file],
            command = "{} {} nasm {}".format(binary_invocation, src_as_file.path, out_as_file.path),
            mnemonic = "GenerateAssemblyFromPerlScripts",
            progress_message = "Generating file {} from script {}".format(out_as_file.path, src_as_file.path),
            toolchain =
                "@rules_perl//:current_toolchain",
        )
    return out_as_file

def _perl_genrule_impl(ctx):
    binary_invocation = get_binary_invocation_based_on_cpu(ctx.attr.is_nix)
    out_files = []
    additional_srcs = combine_list_of_lists([src.files.to_list() for src in ctx.attr.additional_srcs])

    for src, out in ctx.attr.srcs_to_outs.items():
        if is_right_architecture(ctx.attr.is_x86, out, src):
            out_as_file = run_generation(ctx, src, out, binary_invocation, additional_srcs)
            out_files.append(out_as_file)
    for src, out in ctx.attr.srcs_to_outs_dupes.items():
        if is_right_architecture(ctx.attr.is_x86, out, src):
            out_as_file = run_generation(ctx, src, out, binary_invocation, additional_srcs)
            out_files.append(out_as_file)
    runfiles = ctx.runfiles(files = out_files)

    return [DefaultInfo(files = depset(out_files), runfiles = runfiles)]

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        # Additional sources needed by the generation scripts.
        "additional_srcs": attr.label_list(allow_files = True, doc = "List of other input files used by the main input files."),
        # We need to know what os this is running on.
        "is_nix": attr.bool(doc = "Whether this is mac or linux or not."),
        # We need to know what architecture this is running on.
        "is_x86": attr.bool(doc = "Whether this is x86_64 or arm64."),
        # The dict of srcs to their outs.
        "srcs_to_outs": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files from their source script."),
        # The dicts of srcs to their outs when they are dupes from the first dict.
        "srcs_to_outs_dupes": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files where the source is dupe from the first dict."),
    },
)
