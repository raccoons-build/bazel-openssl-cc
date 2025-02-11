"""Generate files with perl. These are assumed to be .pl files as src and .s file as output.
"""

def get_binary_invocation_based_on_cpu(is_nix):
    if is_nix:
        return "perl"
    else:
        return "perl.exe"

def run_generation(ctx, src, out, binary_invocation):
    out_as_file = ctx.actions.declare_file(out)
    ctx.actions.run_shell(
        inputs = src.files,
        outputs = [out_as_file],
        command = "{} {} nasm {}".format(binary_invocation, src, out),
        mnemonic = "GenerateAssemblyFromPerlScripts",
        progress_message = "Generating file {} from script {}".format(out, src),
        toolchain =
            "@rules_perl//:current_toolchain",
    )
    return out_as_file

def _perl_genrule_impl(ctx):
    binary_invocation = get_binary_invocation_based_on_cpu(ctx.attr.is_nix)
    out_files = []
    for src, out in ctx.attr.srcs_to_outs.items():
        out_as_file = run_generation(ctx, src, out, binary_invocation)
        out_files.append(out_as_file)
    for src, out in ctx.attr.srcs_to_outs_dupes.items():
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
        # We allow outs to be empty so when we don't generate anything for nix platforms
        # we don't get an error.
        "outs": attr.output_list(allow_empty = True, doc = "List of output files."),
        "srcs_to_outs": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files from their source script."),
        # The dicts of srcs to their outs when they are dupes from the first dict.
        "srcs_to_outs_dupes": attr.label_keyed_string_dict(allow_files = True, doc = "Dict of input to output files where the source is dupe from the first dict."),
    },
)
