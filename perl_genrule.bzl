"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

def get_binary_invocation_based_on_cpu(is_nix):
    if is_nix:
        return "perl"
    else:
        return "perl.exe"

def is_right_architecture(is_x86, out_file):
    """ Determine whether this file belongs to the current architecture.

    Args:
        is_x86: Whether this is x86 or arm64
        out_file: The name of the output file
    Returns:
        Whether this file matches the architecture
    """
    if is_x86 and "x86" in out_file:
        return True
    if not is_x86 and "arm" in out_file:
        return True
    return False

def run_generation(ctx, src, out, binary_invocation):
    out_as_file = ctx.actions.declare_file(out)
    ctx.actions.run_shell(
        inputs = src.files,
        outputs = [out_as_file],
        command = "{} {} nasm {}".format(binary_invocation, src.name, out),
        mnemonic = "GenerateAssemblyFromPerlScripts",
        progress_message = "Generating file {} from script {}".format(out, src.name),
        toolchain =
            "@rules_perl//:current_toolchain",
    )
    return out_as_file

def _perl_genrule_impl(ctx):
    binary_invocation = get_binary_invocation_based_on_cpu(ctx.attr.is_nix)
    out_files = []
    for src, out in ctx.attr.srcs_to_outs.items():
        if is_right_architecture(ctx.attr.is_x86, out):
            out_as_file = run_generation(ctx, src, out, binary_invocation)
            out_files.append(out_as_file)
    for src, out in ctx.attr.srcs_to_outs_dupes.items():
        if is_right_architecture(ctx.attr.is_x86, out):
            out_as_file = run_generation(ctx, src, out, binary_invocation)
            out_files.append(out_as_file)
    runfiles = ctx.runfiles(files = out_files)

    return [DefaultInfo(files = depset(out_files), runfiles = runfiles)]

perl_genrule = rule(
    implementation = _perl_genrule_impl,
    doc = "Generate files using perl.",
    attrs = {
        # We need to know what os this is running on.
        "is_nix": attr.bool(doc = "Whether this is mac or linux or not."),
        # We need to know what architecture this is running on.
        "is_x86": attr.bool(doc = "Whether this is x86_64 or arm64."),
        "srcs_to_outs": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files from their source script."),
        # The dicts of srcs to their outs when they are dupes from the first dict.
        "srcs_to_outs_dupes": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files where the source is dupe from the first dict."),
    },
)
